from app.war_metrics import relative_strength, missed_war_streak, missed_current_cwl, promotion_score


def war(time: str, player: str, attacks: list, kind="war"):
    return {"state": "warEnded", "startTime": time, "_warKind": kind,
            "clan": {"tag": "#OURS", "members": [{"tag": player, "attacks": attacks}]},
            "opponent": {"tag": "#OTHER", "members": []}}


def test_relative_th_and_league_not_absolute_th():
    players = [
        {"tag": "#1", "townHallLevel": 16, "heroesLevel": 500, "heroEquipmentScore": 110, "league": "Titan League I"},
        {"tag": "#2", "townHallLevel": 16, "heroesLevel": 260, "heroEquipmentScore": 60, "league": "Crystal League II"},
        {"tag": "#3", "townHallLevel": 18, "heroesLevel": 300, "heroEquipmentScore": 60, "league": "Master League I"},
    ]
    results = relative_strength(players)
    assert results["#1"]["relativeStrength"] > results["#2"]["relativeStrength"]
    assert results["#3"]["relativeStrength"] == 50.0
    assert results["#3"]["strengthCoverage"] == 0
    assert results["#1"]["townHallPeers"] == 2


def test_consecutive_misses_only_when_in_war_and_no_attacks():
    wars = [war("20260103", "#1", []), war("20260102", "#1", []), war("20260101", "#1", [])]
    assert missed_war_streak(wars, "#OURS")["#1"] == 3
    wars[1]["clan"]["members"][0]["attacks"] = [{"stars": 1}]
    assert missed_war_streak(wars, "#OURS")["#1"] == 1
    assert missed_current_cwl(wars, "#OURS") == {"#1"}


def test_no_clan_games_fabrication_or_bonus_from_missing_raid():
    ranking = promotion_score({"history": {"wars": 5, "averageWeightedStars": 2.7, "reliabilityPct": 100},
                               "donations": 90}, 100, 0)
    assert ranking["score"] is not None
    assert ranking["coverage"] == 80
    assert ranking["clanGames"] is None
