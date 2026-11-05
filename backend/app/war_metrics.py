"""Pure war analysis. No unsupported Clash API fields or automatic moderation."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

LEAGUE_ORDER = {
    "unranked": 0, "bronze": 1, "silver": 2, "gold": 3,
    "crystal": 4, "master": 5, "champion": 6,
    "titan": 7, "legend": 8,
}


def _league_index(name: str) -> float | None:
    """Modern 2026 ranked leagues expose numbered tiers, e.g. Electro League 32.

    Legacy Bronze/Crystal names are supported only as a fallback. Do not
    assume Electro, Archer etc are unranked based on the pre-2026 list.
    """
    lower = (name or "").lower()
    match = re.search(r"\bleague\s+(\d{1,2})\b", lower)
    if match:
        number = int(match.group(1))
        return float(number) if 1 <= number <= 50 else None
    for league, level in LEAGUE_ORDER.items():
        if league in lower:
            tier = re.search(r"\b(iii|ii|iv|i|v)\b", lower)
            bonus = {"iii": .0, "ii": .3, "i": .6}.get(tier.group(1), .3) if tier else .3
            return level + bonus
    return None


def _peer_percentile(value: float | None, cohort: list[float]) -> float | None:
    if value is None or len(cohort) < 2:
        return None
    return round(100 * (sum(v < value for v in cohort) +
                        .5 * sum(v == value for v in cohort)) / len(cohort), 1)


def relative_strength(players: list[dict[str, Any]]) -> dict[str, dict]:
    """Compare same-TH heroes, equipment, ranked league and experience.

    Exp level is only a modest proxy for long-term play, NEVER an inference
    of defensive buildings. The absolute CWL proxy weights Town Hall level.
    """
    cohorts: dict[int, list[dict]] = defaultdict(list)
    for member in players:
        if member.get("tag"):
            cohorts[int(member.get("townHallLevel") or 0)].append(member)
    highest = max(cohorts, default=0)
    out = {}
    for th, members in cohorts.items():
        def cohort_values(field: str) -> list[float]:
            return [float(p[field]) for p in members
                    if isinstance(p.get(field), (int, float))]
        heroes = cohort_values("heroesLevel")
        equipment = cohort_values("heroEquipmentScore")
        experience = cohort_values("expLevel")
        leagues = [_league_index(str(p.get("league") or "")) for p in members]
        ranked = [x for x in leagues if x is not None]
        for player in members:
            def peer(field: str, values: list[float]) -> float | None:
                val = player.get(field)
                return _peer_percentile(float(val), values) if isinstance(val, (int, float)) else None
            pairs = (
                (45, peer("heroesLevel", heroes)),
                (20, peer("heroEquipmentScore", equipment)),
                (15, peer("expLevel", experience)),
                (20, _peer_percentile(_league_index(str(player.get("league") or "")), ranked)),
            )
            known = [(weight, value) for weight, value in pairs if value is not None]
            relative = (round(sum(w * value for w, value in known) / sum(w for w, _ in known), 1)
                        if known else 50.)
            # CWL has no equal-TH matchmaking: a rushed TH18 can be weaker
            # than a maxed TH17, but raw TH still matters considerably.
            # Bounded 18 points per TH step; 20% same-TH relative adjustments.
            hall_proxy = max(10., 100. - 18. * max(0, highest - th))
            absolute = round(.80 * hall_proxy + .20 * relative, 1)
            out[str(player["tag"])] = {
                "relativeStrength": relative,
                "absoluteStrength": absolute,
                "strengthCoverage": sum(w for w, _ in known),
                "townHallPeers": len(members),
                "method": "same-TH cohort: heroes45/equipment20/exp15/league20; "
                          "CWL proxy: hall80/relative20; building defenses unknown",
            }
    return out


def missed_war_streak(wars: list[dict], clan_tag: str) -> dict[str, int]:
    """Consecutive FULLY missed wars among wars actually featuring each player."""
    seen: set[str] = set()
    streaks: dict[str, int] = {}
    for war in sorted(wars, key=lambda x: x.get("startTime") or "", reverse=True):
        if war.get("state") != "warEnded":
            continue
        ours = next((side for side in (war.get("clan") or {}, war.get("opponent") or {})
                     if side.get("tag") == clan_tag), None)
        if not ours:
            continue
        for member in ours.get("members") or []:
            tag = member.get("tag")
            if not tag or tag in seen:
                continue
            if member.get("attacks"):
                seen.add(tag)
            else:
                streaks[tag] = streaks.get(tag, 0) + 1
    return streaks


def missed_current_cwl(wars: list[dict], clan_tag: str) -> set[str]:
    """In the current CWL group, a single FULLY missed round bars later rounds."""
    missed: set[str] = set()
    for war in wars:
        if war.get("state") != "warEnded":
            continue
        ours = next((side for side in (war.get("clan") or {}, war.get("opponent") or {})
                     if side.get("tag") == clan_tag), None)
        if ours:
            missed.update(m["tag"] for m in (ours.get("members") or [])
                          if m.get("tag") and not m.get("attacks"))
    return missed


def promotion_score(player: dict, donation_max: int, raid_max: int) -> dict:
    """40% war, 25% current-season donations, 20% last raid, 15% attendance.

    Ignore entirely missing metrics and show coverage. Never pretend the public
    API exposes per-player Clan Games points.
    """
    # Consistent measurement period: use observed completed attacks from both
    # regular war and CWL. These remain separate for mode-specific lineup scores.
    regular = player.get("history") or {}
    cwl = player.get("cwlHistory") or {}
    observed_wars = int(regular.get("wars") or 0) + int(cwl.get("wars") or 0)
    observed_used = int(regular.get("attacksUsed") or 0) + int(cwl.get("attacksUsed") or 0)
    observed_possible = int(regular.get("attacksPossible") or 0) + int(cwl.get("attacksPossible") or 0)
    parts = []
    for group in (regular, cwl):
        used = int(group.get("attacksUsed") or 0)
        quality = group.get("qualityPct")
        if quality is None and group.get("averageWeightedStars") is not None:
            quality = min(100., float(group["averageWeightedStars"]) / 3 * 100)
        if used and quality is not None:
            parts.append((used, float(quality)))
    quality = (sum(used * value for used, value in parts) / sum(used for used, _ in parts)
               if parts and observed_wars >= 3 else None)
    participation = (100 * observed_used / observed_possible
                     if observed_possible and observed_wars >= 3 else None)
    donations = player.get("donations")
    raids = player.get("raidLoot")
    components = {
        "war": (40, quality),
        "donations": (25, min(100., 100 * donations / donation_max) if donations is not None and donation_max > 0 else None),
        "raids": (20, min(100., 100 * raids / raid_max) if raids is not None and raid_max > 0 else None),
        "discipline": (15, participation),
    }
    known = [(w, float(v)) for w, v in components.values() if v is not None]
    return {
        "score": round(sum(w * v for w, v in known) / sum(w for w, _ in known), 1) if known else None,
        "coverage": sum(w for w, _ in known),
        "donationSeason": donations,
        "latestRaidLoot": raids,
        "clanGames": None,
        "warQuality": round(quality, 1) if quality is not None else None,
        "observedWars": observed_wars,
    }
