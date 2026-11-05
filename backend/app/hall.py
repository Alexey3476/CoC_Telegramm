"""Current observable clan contribution rankings; no unexposed Clan Games points."""
from __future__ import annotations

from app.war_history import summarize_wars
from app.war_metrics import promotion_score


def hall_of_fame(clan: dict, wars: list[dict], raid: dict | None = None) -> dict:
    clan_tag = clan.get("tag")
    regular = [w for w in wars if w.get("_warKind") == "war" or
               (not w.get("_warKind") and w.get("attacksPerMember") == 2)]
    history = summarize_wars(regular, clan_tag)
    cwl_history = summarize_wars([w for w in wars if w.get("_warKind") == "cwl"], clan_tag)
    members = clan.get("memberList") or []
    raid_members = (raid or {}).get("members") or []
    raids = {m["tag"]: int(m.get("capitalResourcesLooted") or 0)
             for m in raid_members if m.get("tag")}
    donation_max = max((int(m.get("donations") or 0) for m in members),default=0)
    raid_max = max(raids.values(),default=0)
    sorted_donations = sorted(members,key=lambda m: (-int(m.get("donations") or 0),
                                                     str(m.get("name") or "")))
    war_ranks = []
    contributions = []
    for member in members:
        tag = member.get("tag")
        stats = history.get(tag) or {}
        cwl_stats = cwl_history.get(tag) or {}
        combined = {**member,"history":stats,"cwlHistory":cwl_stats}
        merit = promotion_score({**combined,"raidLoot":raids.get(tag)},donation_max,raid_max)
        total_wars = int(stats.get("wars") or 0) + int(cwl_stats.get("wars") or 0)
        if total_wars >= 3 and merit["warQuality"] is not None:
            war_ranks.append({"name":member.get("name"),"tag":tag,
                              "score":merit["warQuality"],"wars":total_wars})
        payload = {**combined,"raidLoot":raids.get(tag)}
        merit = promotion_score(payload,donation_max,raid_max)
        if (merit["score"] is not None and merit["coverage"] >= 50 and
                member.get("role") not in {"coLeader","leader"}):
            contributions.append({"name":member.get("name"),"tag":tag,
                                  "score":merit["score"],"coverage":merit["coverage"]})
    war_ranks.sort(key=lambda m: (-m["score"],-m["wars"],str(m["name"])))
    contributions.sort(key=lambda m: (-m["score"],str(m["name"])))
    sorted_raids = sorted(
        ({"name":next((m.get("name") for m in members if m.get("tag")==tag),tag),
          "tag":tag,"score":amount} for tag,amount in raids.items()),
        key=lambda m:(-m["score"],str(m["name"])),
    )
    return {
        "donations":[{"name":m.get("name"),"tag":m.get("tag"),
                      "score":int(m.get("donations") or 0)} for m in sorted_donations[:5]],
        "war":war_ranks[:5],"raids":sorted_raids[:5],
        "promotion":contributions[:5], "clanGamesAvailable":False,
        "observedRegularWars":len(regular),
    }
