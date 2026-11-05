from datetime import datetime, timezone, timedelta

from app.bindings_storage import Binding, BindingsStorage
from app.selection import SelectionPolicy, build_selection


NOW = datetime(2026, 11, 5, 15, tzinfo=timezone.utc)


def one(tag, score=98, pref="in", wars=5, missed=0, reliability=100, avg=2.7, cwl=None):
    return {"tag": tag, "name": tag, "townHallLevel": 18, "combatReadiness": score,
            "warPreference": pref, "history": {"wars": wars, "missedAttacks": missed,
             "reliabilityPct": reliability, "averageStars": avg},
            "cwlHistory": cwl}


def link(db, user, tag, last_seen=None, cwl="unknown"):
    db.upsert_binding(Binding(user, -100, tag, None, "Tester", NOW.isoformat()))
    db.set_cwl_opt_in(-100, user, tag, cwl)
    if last_seen:
        db.set_manual_last_seen(-100, tag, last_seen.isoformat())


def test_twinks_one_slot_per_owner_and_extra_is_separate(tmp_path):
    db = BindingsStorage(str(tmp_path / "db.sqlite"))
    link(db, 1, "#A")
    link(db, 1, "#B")
    link(db, 2, "#C")
    d = build_selection({"recommendedLineup": [one("#A", 90), one("#B", 99),
        one("#C", 80)], "recommendedSize": 3}, db, -100, "war", SelectionPolicy(), NOW)
    assert [x["tag"] for x in d["categories"]["lineup"]] == ["#B", "#C"]
    assert [x["tag"] for x in d["categories"]["twinks"]] == ["#A"]
    assert d["reservedSlots"] == 1


def test_last_seen_unknown_is_not_48_hour_inactivity(tmp_path):
    db = BindingsStorage(str(tmp_path / "d.sqlite"))
    d = build_selection({"recommendedLineup": [one("#A")], "recommendedSize": 1},
                        db, -100, "war", SelectionPolicy(), NOW)
    assert d["categories"]["lineup"][0]["lastSeenSource"] == "unknown"
    assert not d["categories"]["inactive"]


def test_manual_older_than_two_days_goes_to_inactive(tmp_path):
    db = BindingsStorage(str(tmp_path / "d.sqlite"))
    link(db, 1, "#A", NOW - timedelta(days=3))
    d = build_selection({"recommendedLineup": [one("#A")], "recommendedSize": 1},
                        db, -100, "war", SelectionPolicy(), NOW)
    assert [x["tag"] for x in d["categories"]["inactive"]] == ["#A"]


def test_separate_kv_and_cwl_preferences(tmp_path):
    db = BindingsStorage(str(tmp_path / "d.sqlite"))
    link(db, 1, "#A", cwl="out")
    data = {"recommendedLineup": [one("#A", pref="in")], "recommendedSize": 1}
    assert build_selection(data, db, -100, "war", SelectionPolicy(), NOW)["categories"]["lineup"]
    assert build_selection(data, db, -100, "cwl", SelectionPolicy(), NOW)["categories"]["optedOut"]


def test_kick_requires_evidence_and_not_weak_th_only(tmp_path):
    db = BindingsStorage(str(tmp_path / "d.sqlite"))
    players = [one("#A", 25, wars=0, missed=0),
               one("#B", 90, wars=5, missed=5, reliability=40)]
    d = build_selection({"recommendedLineup": players}, db, -100, "war", SelectionPolicy(), NOW)
    assert [x["tag"] for x in d["categories"]["kickCandidates"]] == ["#B"]


def test_promotion_and_cwl_bonus_use_distinct_history(tmp_path):
    db = BindingsStorage(str(tmp_path / "d.sqlite"))
    player = one("#A", cwl={"wars": 4, "reliabilityPct": 100, "averageStars": 2.8})
    d = build_selection({"recommendedLineup": [player]}, db, -100, "war", SelectionPolicy(), NOW)
    assert d["categories"]["promotionCandidates"]
    assert d["categories"]["bonusCandidates"]


def test_unknown_cwl_signup_requires_confirmation(tmp_path):
    db = BindingsStorage(str(tmp_path / "d.sqlite"))
    d = build_selection({"recommendedLineup": [one("#A")], "recommendedSize": 1},
                        db, -100, "cwl", SelectionPolicy(), NOW)
    assert not d["categories"]["lineup"]
    assert d["categories"]["needConfirmation"]


def test_weights_cannot_silently_be_wrong():
    try:
        SelectionPolicy(strength=70, attendance=30, attack=25, preference=10)
        assert False
    except ValueError:
        pass



def test_manual_inactive_no_war_evidence_is_only_review(tmp_path):
    db = BindingsStorage(str(tmp_path / "db.sqlite"))
    link(db, 1, "#A", NOW - timedelta(days=9))
    d = build_selection({"recommendedLineup": [one("#A", wars=0, missed=0)],
                         "recommendedSize": 15, "observedWarCount": 6},
                        db, -100, "war", SelectionPolicy(), NOW)
    assert d["categories"]["inactive"]
    assert d["categories"]["kickCandidates"]
    assert "капитан" in d["categories"]["kickCandidates"][0]["kickReasons"][0]


def test_promotion_skips_already_senior_captain(tmp_path):
    db = BindingsStorage(str(tmp_path / "db.sqlite"))
    player = {**one("#A"), "role": "coLeader"}
    d = build_selection({"recommendedLineup": [player], "recommendedSize": 1},
                        db, -100, "war", SelectionPolicy(), NOW)
    assert not d["categories"]["promotionCandidates"]



def test_relative_last_seen_and_refuse_future():
    from app.selection import reported_last_seen
    assert reported_last_seen("2d", NOW) == (NOW - timedelta(days=2)).isoformat()
    assert reported_last_seen("48h", NOW) == (NOW - timedelta(hours=48)).isoformat()
    assert reported_last_seen("clear", NOW) is None
    try:
        reported_last_seen("2026-11-10 12:00", NOW)
        assert False
    except ValueError:
        pass
