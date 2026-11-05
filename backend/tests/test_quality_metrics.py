from app.war_history import summarize_wars


def test_weighted_stars_discount_low_townhall_targets():
    war = {"state": "warEnded", "attacksPerMember": 2,
           "clan": {"tag": "#OUR", "members": [{
               "tag": "#A", "townhallLevel": 18,
               "attacks": [{"stars": 3, "defenderTag": "#LOW"}, {"stars": 2, "defenderTag": "#PEER"}]
           }]},
           "opponent": {"tag": "#THEM", "members": [
               {"tag": "#LOW", "townhallLevel": 15},
               {"tag": "#PEER", "townhallLevel": 18},
           ]}}
    result = summarize_wars([war], "#OUR")["#A"]
    assert result["averageStars"] == 2.5
    assert result["averageWeightedStars"] < result["averageStars"]
    assert 0 < result["qualityPct"] < 100
