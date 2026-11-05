from app.war_metrics import _league_index, relative_strength


def test_new_ranked_league_tiers_and_experience_are_used():
    assert _league_index("Electro League 32") == 32
    assert _league_index("Electro League 31") == 31
    assert _league_index("Archer League 9") == 9
    players = [
        {"tag":"#LEX","townHallLevel":18,"heroesLevel":350,
         "heroEquipmentScore":100,"expLevel":280,"league":"Electro League 32"},
        {"tag":"#ALEX","townHallLevel":18,"heroesLevel":420,
         "heroEquipmentScore":105,"expLevel":250,"league":"Electro League 31"},
    ]
    result = relative_strength(players)
    assert result["#LEX"]["relativeStrength"] != result["#ALEX"]["relativeStrength"]
    assert result["#LEX"]["strengthCoverage"] == 100


def test_cwl_town_hall_advantage_over_lower_th_with_similar_skill():
    players = [
        {"tag":"#18","townHallLevel":18,"heroesLevel":250,"heroEquipmentScore":100,
         "expLevel":180,"league":"Electro League 31"},
        {"tag":"#16","townHallLevel":16,"heroesLevel":250,"heroEquipmentScore":100,
         "expLevel":180,"league":"Electro League 31"},
    ]
    result = relative_strength(players)
    assert result["#18"]["relativeStrength"] == 50
    assert result["#16"]["relativeStrength"] == 50
    assert result["#18"]["absoluteStrength"] > result["#16"]["absoluteStrength"] + 25
