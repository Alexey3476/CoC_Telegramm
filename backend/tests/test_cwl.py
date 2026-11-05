from app.coc_client import summarize_cwl


def test_cwl_tiebreaker_and_swapped_team_orientation():
    group = {"state": "inWar", "rounds": [{}, {}, {}]}
    clan = {"tag": "#AAA", "name": "Our", "stars": 35, "destructionPercentage": 99.2}
    enemy = {"tag": "#BBB", "name": "Enemy", "stars": 35, "destructionPercentage": 98.0}
    output = summarize_cwl(group, [
        {"startTime": "20261105T120000Z", "state": "warEnded", "clan": enemy, "opponent": clan},
    ], "#AAA")
    assert output["wins"] == 1
    assert output["losses"] == 0
    assert output["rounds"][0]["enemy"] == "Enemy"


def test_cwl_in_progress_is_not_counted_as_win():
    result = summarize_cwl({"state": "inWar", "rounds": [{}]}, [
        {"startTime": "20261105T120000Z", "state": "inWar",
         "clan": {"tag": "#AAA", "stars": 20}, "opponent": {"tag": "#BBB", "stars": 0}},
    ], "#AAA")
    assert result["wins"] == 0
