from app.war_metrics import promotion_score
from app.hall import hall_of_fame


def test_cwl_and_regular_attacks_both_contribute_to_promotion():
    player={"history":{"wars":2,"attacksUsed":4,"attacksPossible":4,"qualityPct":90},
            "cwlHistory":{"wars":3,"attacksUsed":3,"attacksPossible":3,"qualityPct":60},
            "donations":50,"raidLoot":100}
    score=promotion_score(player,50,100)
    assert score["observedWars"]==5
    assert round(score["warQuality"],1)==round((4*90+3*60)/7,1)
    assert score["coverage"] == 100


def test_cwl_only_contributions_do_not_disappear_from_clan_hall():
    clan={"tag":"#OUR","memberList":[{"tag":"#A","name":"A","donations":50,"role":"member"}]}
    wars=[]
    for day in range(1,4):
        wars.append({"state":"warEnded","startTime":f"2026110{day}T000000Z",
            "_warKind":"cwl","attacksPerMember":1,
            "clan":{"tag":"#OUR","members":[{"tag":"#A","townhallLevel":17,
                   "attacks":[{"defenderTag":"#B","stars":3}]}]},
            "opponent":{"tag":"#THEM","members":[{"tag":"#B","townhallLevel":17}]}})
    fame=hall_of_fame(clan,wars)
    assert fame["war"][0]["name"]=="A"
    assert fame["promotion"][0]["name"]=="A"
