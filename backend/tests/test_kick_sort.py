from datetime import datetime, timedelta, timezone

from app.selection import DEFAULT_WEIGHTS, score_and_categorize


def test_kick_review_sorted_lowest_war_score_first():
    now = datetime(2026,11,5,tzinfo=timezone.utc)
    pref = lambda: {"cwlPreference":"unknown",
                   "lastSeenManual":(now-timedelta(days=9)).isoformat()}
    history={"wars":6,"attacksUsed":2,"attacksPossible":12,"missedAttacks":10,
             "averageStars":1.0,"threeStarsEqualOrHigher":0}
    first={"tag":"#A","name":"High","townHallLevel":18,"combatReadiness":80,
           "warPreference":"in","history":history}
    second={"tag":"#B","name":"Low","townHallLevel":13,"combatReadiness":40,
            "warPreference":"in","history":history}
    result=score_and_categorize([first,second],DEFAULT_WEIGHTS,
                                {"#A":pref(),"#B":pref()},now=now)
    assert len(result["categories"]["kick"]) == 2
    # Different TH alone must not influence the review ordering.
    assert result["categories"]["kick"][0]["selectionScore"] == result["categories"]["kick"][1]["selectionScore"]
    assert result["categories"]["main"] == []
