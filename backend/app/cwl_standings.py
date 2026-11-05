"""Calculate observed CWL group rankings from all matches, not only our matches."""
from __future__ import annotations
from typing import Any


def outcome(a: dict, b: dict) -> int:
    """Compare stars and then destruction. Return 1 for win, -1 for loss, 0 for draw."""
    sa, sb = int(a.get("stars") or 0), int(b.get("stars") or 0)
    if sa != sb:
        return 1 if sa > sb else -1
    da, db = float(a.get("destructionPercentage") or 0), float(b.get("destructionPercentage") or 0)
    return (da > db) - (da < db)


def group_standings(group: dict[str, Any], wars: list[dict], clan_tag: str) -> dict:
    """Ten bonus stars per completed win; missing/in-progress data are unscored."""
    clans = {str(c["tag"]): {
        "tag": str(c["tag"]), "name": str(c.get("name") or c["tag"]),
        "stars": 0, "attackStars": 0, "winBonusStars": 0, "destruction": 0.,
        "completedWars": 0, "wins": 0, "losses": 0, "draws": 0,
    } for c in group.get("clans") or [] if c.get("tag")}
    war_tags = {tag for rnd in group.get("rounds") or []
                for tag in rnd.get("warTags") or [] if tag and tag != "#0"}
    available: dict[str, dict] = {}
    for war in wars:
        tag = war.get("_leagueWarTag")
        if tag in war_tags:
            available[tag] = war
    completed = 0
    for war in available.values():
        if war.get("state") != "warEnded":
            continue
        a, b = war.get("clan") or {}, war.get("opponent") or {}
        if a.get("tag") not in clans or b.get("tag") not in clans:
            continue
        if any(side.get("stars") is None or side.get("destructionPercentage") is None
               for side in (a, b)):
            continue
        completed += 1
        result = outcome(a, b)
        for side, result_for_side in ((a, result), (b, -result)):
            record = clans[side["tag"]]
            points = int(side["stars"])
            bonus = 10 if result_for_side > 0 else 0
            record["attackStars"] += points
            record["winBonusStars"] += bonus
            record["stars"] += points + bonus
            record["destruction"] += float(side["destructionPercentage"])
            record["completedWars"] += 1
            record["wins" if result_for_side > 0 else "losses" if result_for_side < 0 else "draws"] += 1
    standings = sorted(clans.values(),
                       key=lambda c: (-c["stars"], -c["destruction"], c["tag"]))
    for idx, c in enumerate(standings):
        previous = next(i for i, x in enumerate(standings)
                        if x["stars"] == c["stars"] and
                        abs(x["destruction"] - c["destruction"]) < 1e-7)
        c["place"] = previous + 1
        c["placeTied"] = any(x is not c and x["stars"] == c["stars"]
                             and abs(x["destruction"] - c["destruction"]) < 1e-7
                             for x in standings)
        c["destruction"] = round(c["destruction"], 2)
    return {
        "clans": standings,
        "myPlace": next((c["place"] for c in standings if c["tag"] == clan_tag), None),
        "myPlaceTied": next((c["placeTied"] for c in standings if c["tag"] == clan_tag), False),
        "expectedWars": len(war_tags), "observedWars": len(available),
        "completedWars": completed,
        "fullyObserved": bool(war_tags) and len(available) == len(war_tags),
        "seasonCompleted": (bool(war_tags) and completed == len(war_tags)
                            and group.get("state") in {"ended", "warEnded"}),
        "scheduledRounds": len(group.get("rounds") or []),
    }
