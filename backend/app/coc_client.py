from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx
from app.cache import TTLCache

from app.cache import get_cached_json, set_cached_json
from app.settings import settings
from app.war_history import WarHistory, summarize_wars
from app.selection import SelectionStore, score_and_categorize
from app.war_metrics import missed_war_streak, missed_current_cwl

logger = logging.getLogger(__name__)

TAG_PATTERN = re.compile(r"^[0289PYLQGRJCUV]+$")


class InvalidTagError(ValueError):
    pass


class NotFoundError(ValueError):
    pass


class UnauthorizedError(ValueError):
    pass


class ForbiddenError(ValueError):
    pass


class RateLimitError(ValueError):
    pass


def normalize_tag(tag: str) -> str:
    cleaned = tag.replace(" ", "").strip().upper()
    if not cleaned.startswith("#"):
        cleaned = f"#{cleaned}"
    raw = cleaned.lstrip("#")
    if not raw or not TAG_PATTERN.fullmatch(raw):
        logger.warning("Invalid tag format input=%s normalized=%s", tag, cleaned)
        raise InvalidTagError("Invalid tag format")
    logger.info("Normalized tag input=%s normalized=%s", tag, cleaned)
    return cleaned


def encode_tag(tag: str) -> str:
    return normalize_tag(tag).replace("#", "%23")


async def fetch_with_cache(
    client: httpx.AsyncClient,
    redis: TTLCache,
    cache_key: str,
    url: str,
) -> dict[str, Any]:
    cached = await get_cached_json(redis, cache_key)
    if cached:
        logger.info("Cache hit key=%s", cache_key)
        return cached

    try:
        logger.info("CoC API request url=%s", url)
        response = await client.get(url)
    except httpx.TimeoutException as exc:
        logger.warning("CoC API timeout", exc_info=exc)
        raise TimeoutError("CoC API timeout") from exc
    except httpx.RequestError as exc:
        logger.warning("CoC API request failed", exc_info=exc)
        raise RuntimeError("CoC API unavailable") from exc

    logger.info("CoC API response status=%s url=%s", response.status_code, url)
    if response.status_code == 401:
        raise UnauthorizedError("Unauthorized token")
    if response.status_code == 403:
        raise ForbiddenError("Forbidden (IP not whitelisted or token invalid)")
    if response.status_code == 429:
        raise RateLimitError("Rate limit exceeded")
    if response.status_code == 404:
        raise NotFoundError("Not found")
    if response.status_code >= 400:
        raise RuntimeError("CoC API error")

    payload = response.json()
    await set_cached_json(redis, cache_key, payload, settings.cache_ttl_seconds)
    return payload


async def get_clan(client: httpx.AsyncClient, redis: TTLCache) -> dict[str, Any]:
    clan_tag = normalize_tag(settings.coc_clan_tag)
    cache_key = f"clan:{clan_tag}"
    url = f"{settings.coc_api_base}/clans/{encode_tag(clan_tag)}"
    return await fetch_with_cache(client, redis, cache_key, url)


async def get_player(client: httpx.AsyncClient, redis: TTLCache, tag: str) -> dict[str, Any]:
    normalized = normalize_tag(tag)
    cache_key = f"player:{normalized}"
    url = f"{settings.coc_api_base}/players/{encode_tag(normalized)}"
    return await fetch_with_cache(client, redis, cache_key, url)


async def get_regular_war(client: httpx.AsyncClient, redis: TTLCache) -> dict[str, Any]:
    clan_tag = normalize_tag(settings.coc_clan_tag)
    url = f"{settings.coc_api_base}/clans/{encode_tag(clan_tag)}/currentwar"
    return await fetch_with_cache(client, redis, f"war:{clan_tag}", url)


async def get_league_wars(
    client: httpx.AsyncClient, redis: TTLCache, own_only: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fetch current CWL wars; other clans are required for group standings."""
    clan_tag = normalize_tag(settings.coc_clan_tag)
    url = f"{settings.coc_api_base}/clans/{encode_tag(clan_tag)}/currentwar/leaguegroup"
    try:
        group = await fetch_with_cache(client, redis, f"cwl:{clan_tag}", url)
    except (NotFoundError, ForbiddenError):
        return {"state": "notInWar"}, []
    tags: list[str] = []
    for round_data in group.get("rounds", []):
        for tag in round_data.get("warTags", []):
            if tag and tag != "#0" and tag not in tags:
                tags.append(tag)
    semaphore = asyncio.Semaphore(4)

    async def fetch_one(tag: str) -> dict[str, Any] | None:
        async with semaphore:
            try:
                data = await fetch_with_cache(
                    client, redis, f"cwl-war:{tag}",
                    f"{settings.coc_api_base}/clanwarleagues/wars/{encode_tag(tag)}",
                )
                sides = (data.get("clan") or {}, data.get("opponent") or {})
                if own_only and not any(side.get("tag") == clan_tag for side in sides):
                    return None
                return {**data, "_warTag": tag}
            except (NotFoundError, RateLimitError, ForbiddenError, RuntimeError, TimeoutError):
                return None

    fetched = await asyncio.gather(*(fetch_one(tag) for tag in tags[:40]))
    return group, [war for war in fetched if war is not None]


def _cwl_result(own: dict, enemy: dict, state: str) -> str:
    if state != "warEnded":
        return "pending"
    own_stars, enemy_stars = int(own.get("stars") or 0), int(enemy.get("stars") or 0)
    own_damage = float(own.get("destructionPercentage") or 0)
    enemy_damage = float(enemy.get("destructionPercentage") or 0)
    if own_stars > enemy_stars or (own_stars == enemy_stars and own_damage > enemy_damage):
        return "win"
    if own_stars == enemy_stars and own_damage == enemy_damage:
        return "draw"
    return "loss"


def summarize_cwl(group: dict[str, Any], wars: list[dict[str, Any]], clan_tag: str) -> dict[str, Any]:
    """Provisional group table: stars plus 10 for a completed win, then destruction.

    Missing wars and future rounds are never treated as losses or as zero-star
    results. This calculation is not an official season-end placement.
    """
    group_rounds = group.get("rounds") or []
    war_by_tag = {war["_warTag"]: war for war in wars if war.get("_warTag")}
    positions = {}
    for number, round_data in enumerate(group_rounds, start=1):
        for tag in round_data.get("warTags", []):
            if tag and tag != "#0":
                positions[tag] = number

    seen_wars: set[tuple] = set()
    unique_wars = []
    for war in wars:
        sides = (war.get("clan") or {}, war.get("opponent") or {})
        identity = war.get("_warTag") or (war.get("startTime"), tuple(sorted(
            str(side.get("tag") or "") for side in sides)))
        if identity in seen_wars:
            continue
        seen_wars.add(identity)
        unique_wars.append(war)

    group_members: dict[str, dict] = {
        clan["tag"]: {"tag": clan["tag"], "name": clan.get("name") or clan["tag"],
                      "stars": 0, "bonusStars": 0, "destruction": 0.0, "wins": 0, "warsObserved": 0}
        for clan in (group.get("clans") or []) if clan.get("tag")
    }
    observed = []
    for war in unique_wars:
        left, right = war.get("clan") or {}, war.get("opponent") or {}
        if not left.get("tag") or not right.get("tag"):
            continue
        for side, opponent in ((left, right), (right, left)):
            tag = side["tag"]
            entry = group_members.setdefault(tag, {
                "tag": tag, "name": side.get("name") or tag, "stars": 0,
                "bonusStars": 0, "destruction": 0.0, "wins": 0, "warsObserved": 0,
            })
            entry["stars"] += int(side.get("stars") or 0)
            entry["destruction"] += float(side.get("destructionPercentage") or 0)
            entry["warsObserved"] += 1
            if _cwl_result(side, opponent, war.get("state") or "") == "win":
                entry["wins"] += 1
                entry["bonusStars"] += 10
        if left["tag"] == clan_tag or right["tag"] == clan_tag:
            own, enemy = (left, right) if left["tag"] == clan_tag else (right, left)
            observed.append({
                "round": positions.get(war.get("_warTag")),
                "enemy": enemy.get("name") or "Соперник",
                "result": _cwl_result(own, enemy, war.get("state") or ""),
                "stars": int(own.get("stars") or 0),
                "enemyStars": int(enemy.get("stars") or 0),
                "startTime": war.get("startTime"),
            })

    # Put our games in their real round order even if an intermediate API war
    # tag has not been published. Older tests/snapshots have no _warTag.
    observed.sort(key=lambda w: (w.get("round") or 99, w.get("startTime") or ""))
    rounds = []
    expected_rounds = max(7, len(group_rounds)) if group.get("state") != "notInWar" else len(group_rounds)
    by_round = {r["round"]: r for r in observed if r.get("round") is not None}
    for number in range(1, expected_rounds + 1):
        found = by_round.get(number)
        if found is None:
            without_number = next((r for r in observed if r.get("round") is None
                                   and r not in rounds), None)
            found = without_number
        rounds.append({"round": number, **(found or {
            "enemy": None, "result": "upcoming", "stars": None, "enemyStars": None,
            "startTime": None,
        })})
    for entry in group_members.values():
        entry["totalStars"] = entry["stars"] + entry["bonusStars"]
        entry["destruction"] = round(entry["destruction"], 2)
    standings = sorted(group_members.values(), key=lambda c: (
        -c["totalStars"], -c["destruction"], str(c["name"]).casefold()))
    for i, member in enumerate(standings, start=1):
        member["place"] = i
    ours = next((item for item in standings if item["tag"] == clan_tag), None)
    finished = sum(w.get("state") == "warEnded" for w in unique_wars)
    return {
        "state": group.get("state") or "notInWar",
        "scheduledRounds": expected_rounds,
        "observedRounds": len(observed),
        "wins": sum(x["result"] == "win" for x in observed),
        "draws": sum(x["result"] == "draw" for x in observed),
        "losses": sum(x["result"] == "loss" for x in observed),
        "rounds": rounds,
        "standings": standings,
        "predictedPlace": ours["place"] if ours else None,
        "ourTotalStars": ours["totalStars"] if ours else None,
        "completedWarCount": finished,
        "observedWarCount": len(unique_wars),
        "standingsProvisional": group.get("state") != "ended"
                                or finished != len(unique_wars),
    }


async def get_cwl_summary(client: httpx.AsyncClient, redis: TTLCache) -> dict[str, Any]:
    group, wars = await get_league_wars(client, redis, own_only=False)
    return summarize_cwl(group, wars, normalize_tag(settings.coc_clan_tag))


def orient_war_for_clan(war: dict[str, Any], clan_tag: str) -> dict[str, Any]:
    """Keep our side under 'clan', even when CWL represents us as opponent."""
    home = war.get("clan") or {}
    away = war.get("opponent") or {}
    if home.get("tag") != clan_tag and away.get("tag") == clan_tag:
        return {**war, "clan": away, "opponent": home}
    return war


async def get_war(client: httpx.AsyncClient, redis: TTLCache) -> dict[str, Any]:
    """Regular current war, or the current CWL war when the regular endpoint is empty."""
    regular = await get_regular_war(client, redis)
    if regular.get("state") in {"preparation", "inWar"}:
        return regular
    _, wars = await get_league_wars(client, redis)
    live = [war for war in wars if war.get("state") in {"preparation", "inWar"}]
    if not live:
        return regular
    selected = max(
        live,
        key=lambda war: (war.get("state") == "inWar", war.get("startTime") or ""),
    )
    return orient_war_for_clan(selected, normalize_tag(settings.coc_clan_tag))


async def get_clan_members(client: httpx.AsyncClient, redis: TTLCache, limit: int = 50) -> dict[str, Any]:
    """Get clan members, sorted by trophies."""
    clan_data = await get_clan(client, redis)
    members = clan_data.get("memberList", [])
    # Sort by trophies descending
    sorted_members = sorted(members, key=lambda m: m.get("trophies", 0), reverse=True)
    return {
        "clanName": clan_data.get("name"),
        "clanTag": clan_data.get("tag"),
        "members": sorted_members[:limit]
    }


async def get_clan_activity_report(client: httpx.AsyncClient, redis: TTLCache) -> dict[str, Any]:
    """Get comprehensive clan activity report."""
    # Get clan data
    clan_data = await get_clan(client, redis)
    members = clan_data.get("memberList", [])
    
    # Get war data
    war_data = await get_war(client, redis)
    war_state = war_data.get("state", "notInWar")
    
    # Calculate stats
    total_members = len(members)
    total_trophies = sum(m.get("trophies", 0) for m in members)
    avg_trophies = total_trophies // total_members if total_members > 0 else 0
    
    # Get war stars if in war
    war_stars = 0
    if war_state == "inWar":
        war_members = war_data.get("clan", {}).get("members", [])
        war_stars = sum(m.get("stars", 0) for m in war_members)
    
    # The public API has no lastSeen field; only rank measured donations.
    members_by_activity = sorted(
        members,
        key=lambda m: int(m.get("donations", 0)),
        reverse=True,
    )
    
    # Most and least active
    most_active = members_by_activity[:5] if members_by_activity else []
    least_active = members_by_activity[-5:] if len(members_by_activity) > 5 else []
    
    # War attacks info
    war_attacks_done = 0
    war_attacks_remaining = 0
    if war_state == "inWar":
        war_members = war_data.get("clan", {}).get("members", [])
        per_member = int(war_data.get("attacksPerMember") or 1)
        war_attacks_done = sum(len(m.get("attacks") or []) for m in war_members)
        war_attacks_remaining = sum(max(0, per_member - len(m.get("attacks") or [])) for m in war_members)
    
    return {
        "clanName": clan_data.get("name"),
        "clanTag": clan_data.get("tag"),
        "clanLevel": clan_data.get("clanLevel"),
        "members": {
            "total": total_members,
            "totalTrophies": total_trophies,
            "avgTrophies": avg_trophies,
        },
        "war": {
            "state": war_state,
            "stars": war_stars,
            "attacksDone": war_attacks_done,
            "attacksRemaining": war_attacks_remaining,
            "enemyName": war_data.get("opponent", {}).get("name") if war_state == "inWar" else None,
        },
        "activity": {
            "mostActive": [
                {
                    "name": m.get("name"),
                    "tag": m.get("tag"),
                    "role": m.get("role"),
                    "donations": m.get("donations", 0),
                    "trophies": m.get("trophies"),
                }
                for m in most_active
            ],
            "leastActive": [
                {
                    "name": m.get("name"),
                    "tag": m.get("tag"),
                    "role": m.get("role"),
                    "donations": m.get("donations", 0),
                    "trophies": m.get("trophies"),
                }
                for m in least_active
            ],
        }
    }

async def get_clan_raids(client: httpx.AsyncClient, redis: TTLCache) -> dict[str, Any]:
    """Return the latest real raid season, including completed results."""
    clan_tag = normalize_tag(settings.coc_clan_tag)
    data = await fetch_with_cache(
        client, redis, f"raids:{clan_tag}",
        f"{settings.coc_api_base}/clans/{encode_tag(clan_tag)}/capitalraidseasons",
    )
    items = data.get("items") or []
    if not items:
        return {"currentRaid": None}
    latest = items[0]
    fields = ("state", "startTime", "endTime", "capitalTotalLoot", "raidsCompleted",
              "totalAttacks", "offensiveReward", "defensiveReward", "members")
    return {"currentRaid": {key: latest[key] for key in fields if key in latest}}


async def get_clan_games(client: httpx.AsyncClient, redis: TTLCache) -> dict[str, Any]:
    """Report that Clan Games progress is not exposed by the public API."""
    clan_tag = normalize_tag(settings.coc_clan_tag)
    cache_key = f"games:{clan_tag}"
    url = f"{settings.coc_api_base}/clans/{encode_tag(clan_tag)}"
    
    data = await fetch_with_cache(client, redis, cache_key, url)
    if not data.get("clanGames"):
        return {
            "currentGames": None,
            "unsupported": True,
            "message": "Clan Games progress is not available in the public API.",
        }
    return {"currentGames": data["clanGames"], "unsupported": False}


async def get_player_activity(client: httpx.AsyncClient, redis: TTLCache) -> dict[str, Any]:
    """Get clan members activity statistics."""
    clan_data = await get_clan(client, redis)
    members = clan_data.get("memberList", [])
    war_data = await get_war(client, redis)
    war_state = war_data.get("state", "notInWar")
    war_members = war_data.get("clan", {}).get("members", []) if war_state == "inWar" else []
    
    # Create activity scores for each member
    member_activity = []
    
    for member in members:
        tag = member.get("tag")
        name = member.get("name", "Unknown")
        
        # Donation score
        donations = member.get("donations", 0)
        
        # CoC API does not report last online time.
        last_seen = None
        
        # War attacks
        war_attacks = 0
        if war_state == "inWar":
            war_member = next((m for m in war_members if m.get("tag") == tag), None)
            if war_member and war_member.get("attacks"):
                war_attacks = len(war_member.get("attacks", []))
        
        # Combined activity score (higher = more active)
        activity_score = donations + (war_attacks * 10)
        
        member_activity.append({
            "name": name,
            "tag": tag,
            "donations": donations,
            "lastSeen": last_seen,
            "warAttacks": war_attacks,
            "activityScore": activity_score,
            "townHallLevel": member.get("townHallLevel", 0),
            "trophies": member.get("trophies", 0),
        })
    
    # Sort by activity score
    most_active = sorted(member_activity, key=lambda x: x["activityScore"], reverse=True)[:10]
    least_active = sorted(member_activity, key=lambda x: x["activityScore"])[:10]
    
    return {
        "mostActive": most_active,
        "leastActive": least_active,
    }


async def get_next_war_analysis(
    client: httpx.AsyncClient,
    redis: TTLCache,
    history: WarHistory | None = None,
    policy: SelectionStore | None = None,
    mode: str = "war",
) -> dict[str, Any]:
    """Evidence-based lineup. Unknown history is missing data, not zero performance."""
    clan_data = await get_clan(client, redis)
    members = clan_data.get("memberList", [])
    clan_tag = normalize_tag(settings.coc_clan_tag)
    archived = history.completed(100) if history else []
    # Old snapshots without explicit kind are accepted only for ordinary war
    # when they expose the standard two-attack limit. Future snapshots have
    # unambiguous _warKind from the collector.
    regular_archive = [w for w in archived if w.get("_warKind") == "war"
                       or (not w.get("_warKind") and w.get("attacksPerMember") == 2)]
    cwl_archive = [w for w in archived if w.get("_warKind") == "cwl"]
    history_stats = summarize_wars(regular_archive, clan_tag)
    cwl_history = summarize_wars(cwl_archive, clan_tag)
    missed_streaks = missed_war_streak(archived, clan_tag)
    current_cwl_missed = set()
    try:
        active_group, active_wars = await get_league_wars(client, redis)
        if active_group.get("state") in {"inWar", "preparation"}:
            current_cwl_missed = missed_current_cwl(active_wars, clan_tag)
    except (NotFoundError, ForbiddenError, RateLimitError, RuntimeError, TimeoutError):
        pass
    raids = {}
    try:
        latest_raids = await get_clan_raids(client, redis)
        current_raid = latest_raids.get("currentRaid") or {}
        raids = {m.get("tag"): int(m.get("capitalResourcesLooted") or 0)
                 for m in current_raid.get("members") or [] if m.get("tag")}
    except (NotFoundError, ForbiddenError, RateLimitError, RuntimeError, TimeoutError):
        pass
    suggested_size = 15
    try:
        war_data = await get_war(client, redis)
        current_state = war_data.get("state", "unknown")
        suggested_size = max(5, min(50, int(war_data.get("teamSize") or 15)))
    except (NotFoundError, ForbiddenError, RateLimitError, RuntimeError, TimeoutError):
        current_state = "unavailable"
    try:
        cwl_url = f"{settings.coc_api_base}/clans/{encode_tag(clan_tag)}/currentwar/leaguegroup"
        cwl_data = await fetch_with_cache(client, redis, f"cwl:{clan_tag}", cwl_url)
        cwl_state = cwl_data.get("state", "unknown")
    except (NotFoundError, ForbiddenError, RateLimitError, RuntimeError, TimeoutError):
        cwl_state = "unavailable"

    semaphore = asyncio.Semaphore(5)

    async def get_full_player(member: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            try:
                return await get_player(client, redis, member["tag"])
            except (NotFoundError, ForbiddenError, RateLimitError, RuntimeError, TimeoutError):
                logger.warning("Full player details unavailable for %s", member.get("tag"))
                return {}

    profiles = await asyncio.gather(*(get_full_player(member) for member in members))
    ranking = []
    for member, profile in zip(members, profiles):
        tag = member.get("tag")
        if not tag:
            continue
        town_hall = int(profile.get("townHallLevel") or member.get("townHallLevel") or 0)
        heroes_level = sum(int(hero.get("level", 0)) for hero in profile.get("heroes", []))
        equipped = [e for e in profile.get("heroEquipment", []) if e.get("level")]
        equipment_level = sum(int(item.get("level", 0)) for item in equipped)
        preference = profile.get("warPreference", "unknown")
        previous = history_stats.get(tag)
        cwl_previous = cwl_history.get(tag)
        # TH matters for matchmaking, but is not evidence of reliability.
        combat_score = round(
            min(60, town_hall * 3.3)
            + min(25, heroes_level / 20)
            + min(15, equipment_level / 20), 1
        )
        readiness = combat_score
        if previous and previous.get("warReadiness") is not None:
            readiness = round(0.45 * combat_score + 0.55 * previous["warReadiness"], 1)
        ranking.append({
            "name": member.get("name") or "Unknown",
            "tag": tag,
            "townHallLevel": town_hall,
            "trophies": member.get("trophies", 0),
            "expLevel": profile.get("expLevel"),
            "warStars": profile.get("warStars"),
            "donations": member.get("donations", 0),
            "warPreference": preference,
            "role": profile.get("role") or member.get("role") or "member",
            "raidLoot": raids.get(tag),
            "missedWarsInARow": missed_streaks.get(tag, 0),
            "missedThisCWL": tag in current_cwl_missed,
            "cwlHistory": cwl_previous or {},
            "league": ((profile.get("leagueTier") or profile.get("league")
                        or member.get("leagueTier") or member.get("league") or {}).get("name", "Unknown")),
            "heroesLevel": heroes_level if profile else None,
            "heroEquipmentScore": equipment_level if profile else None,
            "heroEquipmentCount": len(equipped) if profile else None,
            "history": previous,
            "historyKnown": previous is not None,
            "observedWars": previous["wars"] if previous else 0,
            "missedAttacks": previous["missedAttacks"] if previous else None,
            "reliabilityPct": previous["reliabilityPct"] if previous else None,
            "averageStars": previous["averageStars"] if previous else None,
            "combatReadiness": combat_score,
            "warReadiness": readiness,
        })
    for member in ranking:
        ch = member.get("cwlHistory") or {}
        member["cwlWars"] = ch.get("wars", 0)
        member["cwlAverageStars"] = ch.get("averageStars")
        member["cwlMissedAttacks"] = ch.get("missedAttacks")
    if policy:
        selected = score_and_categorize(
            ranking, policy.weights(mode), policy.get_preferences(clan_tag),
            mode=mode, size=suggested_size,
        )
    else:
        ranking.sort(key=lambda m: (m["warPreference"] != "in", -m["warReadiness"],
                                   -(m["townHallLevel"] or 0)))
        selected = {"recommendedLineup": ranking, "recommendedSize": suggested_size}
    return {
        **selected,
        "clanName": clan_data.get("name"),
        "clanTag": clan_data.get("tag"),
        "cwlState": cwl_state,
        "currentWarState": current_state,
        "topTen": selected["recommendedLineup"][:10],
        "historyKnown": bool(history_stats),
        "observedWarCount": len(archived),
        "analysisFactors": {
            "lastWarPerformance": "Только сохранённые завершённые войны: пропуски, звёзды и уровень цели. Неизвестное не считается нулём.",
            "combatReadiness": "Сравнение уровней героев, снаряжения и лиги только среди участников с той же ратушей; без сверстников оценка нейтральная.",
            "warReadiness": "Сравнивай вклад компонентов в таблице весов. Пропуски и уровень цели учитываются только при наличии истории.",
            "sortedBy": "Категория доступности, затем взвешенный балл по имеющимся сигналам",
        },
    }
