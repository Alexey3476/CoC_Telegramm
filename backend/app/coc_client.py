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
    client: httpx.AsyncClient, redis: TTLCache
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fetch current CWL group and this clan's round wars (bounded concurrency)."""
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
    # CWL normally has at most 28 wars in an eight-clan group.
    semaphore = asyncio.Semaphore(4)

    async def fetch_one(tag: str) -> dict[str, Any] | None:
        async with semaphore:
            try:
                data = await fetch_with_cache(
                    client, redis, f"cwl-war:{tag}",
                    f"{settings.coc_api_base}/clanwarleagues/wars/{encode_tag(tag)}",
                )
                teams = (data.get("clan") or {}, data.get("opponent") or {})
                return data if any(team.get("tag") == clan_tag for team in teams) else None
            except (NotFoundError, RateLimitError, ForbiddenError, RuntimeError, TimeoutError):
                return None

    fetched = await asyncio.gather(*(fetch_one(tag) for tag in tags[:40]))
    return group, [war for war in fetched if war is not None]


async def get_war(client: httpx.AsyncClient, redis: TTLCache) -> dict[str, Any]:
    """Regular current war, or the current CWL war when the regular endpoint is empty."""
    regular = await get_regular_war(client, redis)
    if regular.get("state") in {"preparation", "inWar"}:
        return regular
    _, wars = await get_league_wars(client, redis)
    live = [war for war in wars if war.get("state") in {"preparation", "inWar"}]
    if not live:
        return regular
    return max(
        live,
        key=lambda war: (war.get("state") == "inWar", war.get("startTime") or ""),
    )


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
    clan_tag = normalize_tag(settings.coc_clan_tag)
    
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
    """Get clan raids (capital games) information."""
    clan_tag = normalize_tag(settings.coc_clan_tag)
    cache_key = f"raids:{clan_tag}"
    url = f"{settings.coc_api_base}/clans/{encode_tag(clan_tag)}/capitalraidseasons"
    
    try:
        data = await fetch_with_cache(client, redis, cache_key, url)
        
        # Get current raid if available
        items = data.get("items", [])
        if not items:
            return {"currentRaid": None}
        
        # Most recent raid is first
        current = items[0]
        state = current.get("state", "unknown")
        
        # Parse dates
        start_time = current.get("startTime", "N/A")
        end_time = current.get("endTime", "N/A")
        
        raid_info = {
            "state": state,
            "capitalName": "Capital Raid",
            "startTime": start_time,
            "endTime": end_time,
        }
        
        # If ongoing, include resource details
        if state == "ongoing":
            clan_capital = current.get("clan", {})
            resources = clan_capital.get("resources", [])
            raid_info["clan"] = {"resources": resources}
        
        return {"currentRaid": raid_info}
    except Exception:
        logger.exception("Failed to get clan raids")
        return {"currentRaid": None}

async def get_clan_games(client: httpx.AsyncClient, redis: TTLCache) -> dict[str, Any]:
    """Get clan games information."""
    clan_tag = normalize_tag(settings.coc_clan_tag)
    cache_key = f"games:{clan_tag}"
    url = f"{settings.coc_api_base}/clans/{encode_tag(clan_tag)}"
    
    try:
        data = await fetch_with_cache(client, redis, cache_key, url)
        
        # The official clan payload does not consistently expose Clan Games progress.
        clan_games = data.get("clanGames", {})
        if not clan_games:
            return {"currentGames": None, "unsupported": True}
        
        state = clan_games.get("state", "notInProgress")
        start_time = clan_games.get("startTime", "N/A")
        end_time = clan_games.get("endTime", "N/A")
        
        games_info = {
            "state": state,
            "startTime": start_time,
            "endTime": end_time,
        }
        
        # If in progress, include score details
        if state == "inProgress":
            games_info["score"] = clan_games.get("memberGameInfo", {}).get("totalScore", "N/A")
        
        return {"currentGames": games_info}
    except Exception:
        logger.exception("Failed to get clan games")
        return {"currentGames": None}


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
) -> dict[str, Any]:
    """Evidence-based lineup. Unknown history is missing data, not zero performance."""
    clan_data = await get_clan(client, redis)
    members = clan_data.get("memberList", [])
    clan_tag = normalize_tag(settings.coc_clan_tag)
    history_stats = summarize_wars(history.completed(20), clan_tag) if history else {}
    try:
        war_data = await get_war(client, redis)
        current_state = war_data.get("state", "unknown")
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
            "league": (profile.get("league") or member.get("league") or {}).get("name", "Unknown"),
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
    ranking.sort(
        key=lambda m: (m["warPreference"] != "in", -m["warReadiness"], -(m["townHallLevel"] or 0))
    )
    return {
        "clanName": clan_data.get("name"),
        "clanTag": clan_data.get("tag"),
        "cwlState": cwl_state,
        "currentWarState": current_state,
        "recommendedLineup": ranking,
        "topTen": ranking[:10],
        "historyKnown": bool(history_stats),
        "observedWarCount": len(history.completed(20)) if history else 0,
        "analysisFactors": {
            "lastWarPerformance": "Только сохранённые завершённые войны: пропуски, звёзды и уровень цели. Неизвестное не считается нулём.",
            "combatReadiness": "Ратуша, уровни героев и снаряжения (если профиль доступен).",
            "warReadiness": "55% подтверждённой военной статистики и 45% силы; при отсутствии истории только сила.",
            "sortedBy": "Предпочтение участия, затем расчётный рейтинг",
        },
    }
