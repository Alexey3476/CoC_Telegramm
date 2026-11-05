from app.coc_client import summarize_cwl


def side(tag, name, stars, damage):
    return {"tag": tag, "name": name, "stars": stars,
            "destructionPercentage": damage}


def test_seven_round_slots_and_preliminary_group_place_include_other_clans():
    own = side("#AAA", "Наш клан", 30, 90)
    other = side("#BBB", "Вторые", 28, 85)
    third = side("#CCC", "Третьи", 39, 95)
    fourth = side("#DDD", "Четвёртые", 25, 75)
    group = {
        "state": "inWar",
        "clans": [own, other, third, fourth],
        "rounds": [
            {"warTags": ["#W1", "#W2"]},
            *({"warTags": []} for _ in range(6)),
        ],
    }
    wars = [
        {"_warTag": "#W1", "state": "warEnded", "clan": other,
         "opponent": own, "startTime": "20261101T080000Z"},
        {"_warTag": "#W2", "state": "warEnded", "clan": third,
         "opponent": fourth, "startTime": "20261101T080000Z"},
    ]
    result = summarize_cwl(group, wars, "#AAA")
    assert result["scheduledRounds"] == 7
    assert len(result["rounds"]) == 7
    assert result["rounds"][0]["enemy"] == "Вторые"
    assert result["rounds"][1]["stars"] is None
    assert result["predictedPlace"] == 2
    standings = {m["tag"]: m for m in result["standings"]}
    assert standings["#AAA"]["totalStars"] == 40
    assert standings["#CCC"]["totalStars"] == 49
    assert standings["#BBB"]["totalStars"] == 28
    assert result["ourTotalStars"] == 40
    assert result["observedRounds"] == 1


def test_unfinished_round_does_not_receive_win_bonus():
    group = {"state": "inWar", "rounds": [{"warTags": ["#W"]}]}
    wars = [{"_warTag": "#W", "state": "inWar", "startTime": "20261105T120000Z",
             "clan": side("#A", "A", 20, 60),
             "opponent": side("#B", "B", 10, 30)}]
    result = summarize_cwl(group, wars, "#A")
    assert result["wins"] == 0
    assert result["ourTotalStars"] == 20
    assert result["rounds"][0]["result"] == "pending"
    assert result["standingsProvisional"] is True


def test_equal_stars_sorted_by_destruction():
    group = {"state": "inWar", "rounds": [{"warTags": ["#1", "#2"]}]}
    wars = [{"_warTag": "#1", "state": "inWar", "clan": side("#A", "A", 30, 95),
             "opponent": side("#B", "B", 30, 90)},
            {"_warTag": "#2", "state": "inWar", "clan": side("#C", "C", 30, 80),
             "opponent": side("#D", "D", 30, 70)}]
    result = summarize_cwl(group, wars, "#A")
    assert result["standings"][0]["tag"] == "#A"
    assert result["standings"][1]["tag"] == "#B"
