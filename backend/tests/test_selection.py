from datetime import datetime, timedelta, timezone

import pytest

from app.selection import DEFAULT_WEIGHTS, SelectionStore, score_and_categorize

NOW = datetime(2026,11,5,12,tzinfo=timezone.utc)


def player(tag="#AAA", **extra):
    base = {"tag":tag,"name":tag,"townHallLevel":18,"combatReadiness":90,
            "warPreference":"in",
            "history":{"wars":6,"attacksUsed":10,"attacksPossible":12,
                       "missedAttacks":2,"averageStars":2.5,
                       "threeStarsEqualOrHigher":5}}
    base.update(extra)
    return base


def test_weights_remain_100_and_reject_invalid(tmp_path):
    db=SelectionStore(str(tmp_path/"policy.db"))
    result=db.set_weight("combat",50)
    assert abs(sum(result.values())-100)<0.0001
    assert abs(db.weights()["combat"]-50)<0.0001
    with pytest.raises(ValueError):
        db.set_weight("whatever",10)
    with pytest.raises(ValueError):
        db.set_weight("combat",101)


def test_war_preference_in_game_applies_to_war_and_cwl(tmp_path):
    db=SelectionStore(str(tmp_path/"policy.db"))
    db.set_cwl("#CLAN","#AAA","out")
    prefs=db.get_preferences("#CLAN")
    war=score_and_categorize([player()],DEFAULT_WEIGHTS,prefs,mode="war",now=NOW)
    cwl=score_and_categorize([player()],DEFAULT_WEIGHTS,prefs,mode="cwl",now=NOW)
    assert len(war["categories"]["main"])==1
    assert len(cwl["categories"]["main"])==1
    out=score_and_categorize([dict(player(),warPreference="out")],DEFAULT_WEIGHTS,prefs,mode="cwl",now=NOW)
    assert len(out["categories"]["optout"])==1


def test_manual_last_seen_over_two_days_excluded_not_api_guess(tmp_path):
    db=SelectionStore(str(tmp_path/"policy.db"))
    db.report_last_seen("#CLAN","#AAA",(NOW-timedelta(days=3)).isoformat(),123)
    selection=score_and_categorize([player()],DEFAULT_WEIGHTS,db.get_preferences("#CLAN"),now=NOW)
    assert len(selection["categories"]["inactive"])==1
    assert len(selection["categories"]["main"])==0
    without=score_and_categorize([player()],DEFAULT_WEIGHTS,{},now=NOW)
    assert len(without["categories"]["main"])==1
    assert without["categories"]["main"][0]["lastSeenSource"]=="unavailable"


def test_kick_requires_multiple_signals_and_stays_advisory(tmp_path):
    bad=player(history={"wars":6,"attacksUsed":3,"attacksPossible":12,
              "missedAttacks":9,"averageStars":1,"threeStarsEqualOrHigher":0})
    db=SelectionStore(str(tmp_path/"policy.db"))
    db.report_last_seen("#CLAN","#AAA",(NOW-timedelta(days=8)).isoformat(),123)
    one=score_and_categorize([bad],DEFAULT_WEIGHTS,db.get_preferences("#CLAN"),now=NOW)
    assert len(one["categories"]["kick"])==1
    assert "kick" not in one["categories"]["kick"][0]["eligibility"]
    none=score_and_categorize([bad],DEFAULT_WEIGHTS,{},now=NOW)
    assert not none["categories"]["kick"]
    out=score_and_categorize([dict(bad,warPreference="out")],DEFAULT_WEIGHTS,
                                db.get_preferences("#CLAN"),now=NOW)
    assert not out["categories"]["kick"]


def test_promotion_and_bonus_need_evidence():
    good=player(role="member", donations=100, raidLoot=300,
        history={"wars":7,"attacksUsed":14,"attacksPossible":14,
                 "reliabilityPct":100,"missedAttacks":0,"qualityPct":95,
                 "averageWeightedStars":2.85,"threeStarsEqualOrHigher":6},
        cwlHistory={"wars":5,"missedAttacks":0,"qualityPct":95,"averageStars":2.8})
    data=score_and_categorize([good],DEFAULT_WEIGHTS,{},now=NOW)
    assert len(data["categories"]["promotion"])==1
    assert len(data["categories"]["bonus"])==1
    assert not score_and_categorize([player()],DEFAULT_WEIGHTS,{},now=NOW)["categories"]["bonus"]


def test_prefs_and_manual_activity_persist(tmp_path):
    path=str(tmp_path/"persistent.db")
    db=SelectionStore(path)
    db.set_cwl("#CLAN","#AAA","in")
    db.report_last_seen("#CLAN","#AAA",(NOW-timedelta(days=1)).isoformat(),7)
    other=SelectionStore(path)
    assert "cwlPreference" not in other.get_preferences("#CLAN")["#AAA"]
    assert other.get_preferences("#CLAN")["#AAA"]["lastSeenReporter"]==7
