from app.cwl_standings import group_standings


def war(tag, a="#A", b="#B", s=(35, 32), d=(90, 85), state="warEnded"):
    return {"_leagueWarTag": tag, "state": state,
            "clan": {"tag": a, "stars": s[0], "destructionPercentage": d[0]},
            "opponent": {"tag": b, "stars": s[1], "destructionPercentage": d[1]}}


def group():
    return {"clans": [{"tag": tag, "name": tag} for tag in ("#A","#B","#C","#D")],
            "rounds": [{"warTags": ["#W1","#W2"]},
                       {"warTags": ["#W3","#0"]},
                       {"warTags": ["#0","#0"]}]}


def test_all_clans_ranked_with_win_bonus_and_tiebreaker():
    board = group_standings(group(),
                            [war("#W1"), war("#W2","#C","#D",(40,30)),
                             war("#W3","#B","#D",(38,20))], "#A")
    assert board["myPlace"] == 4
    assert board["clans"][0]["tag"] == "#B"
    assert board["clans"][0]["stars"] == 80
    assert board["expectedWars"] == 3 and board["completedWars"] == 3
    assert board["seasonCompleted"]


def test_pending_or_missing_matches_not_treated_as_losses():
    board = group_standings(group(),
                            [war("#W1",s=(20,20),d=(90,80)),
                             war("#W2","#C","#D",(35,34),state="inWar")], "#A")
    assert board["myPlace"] == 1
    assert board["clans"][0]["stars"] == 30
    assert board["observedWars"] == 2 and board["completedWars"] == 1
    assert not board["fullyObserved"] and not board["seasonCompleted"]


def test_exact_draw_shared_position_not_invented():
    g = {"clans": [{"tag":"#A"},{"tag":"#B"}],
         "rounds": [{"warTags":["#W1"]}]}
    board = group_standings(g,[war("#W1",s=(30,30),d=(100,100))],"#A")
    assert board["myPlace"] == 1 and board["myPlaceTied"]
    assert [c["stars"] for c in board["clans"]] == [30,30]
