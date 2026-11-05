from datetime import datetime, timedelta, timezone
import random

from app.war_results import PHRASES, WarAnnouncementStore, classify_result, format_result, recently_finished, war_identity

NOW = datetime(2026, 11, 5, 15, 0, tzinfo=timezone.utc)


def sample(*, state="warEnded", stars=(35, 32), destruction=(90.5, 92.0),
           end_time="20261105T143000.000Z", reverse=False):
    clan = {"tag": "#OURS", "name": "Trouble<&makers", "stars": stars[0], "destructionPercentage": destruction[0]}
    enemy = {"tag": "#ENEMY", "name": "Enemy<>", "stars": stars[1], "destructionPercentage": destruction[1]}
    return {"state": state, "clan": enemy if reverse else clan,
            "opponent": clan if reverse else enemy,
            "startTime": "20261104T143000.000Z", "endTime": end_time}


def test_three_possible_outcomes_and_undecidable():
    assert classify_result(sample(), "#OURS") == "win"
    assert classify_result(sample(stars=(30, 35)), "#OURS") == "loss"
    assert classify_result(sample(stars=(30, 30), destruction=(99.9, 98.8)), "#OURS") == "win"
    assert classify_result(sample(stars=(30, 30), destruction=(98.8, 99.9)), "#OURS") == "loss"
    assert classify_result(sample(stars=(30, 30), destruction=(99.9, 99.9)), "#OURS") == "draw"
    assert classify_result(sample(state="inWar"), "#OURS") is None
    assert classify_result(sample(), "#OTHER") is None
    a = sample(stars=(30, 30))
    a["opponent"].pop("destructionPercentage")
    assert classify_result(a, "#OURS") is None


def test_cwl_orientation_and_stable_identity():
    first = sample()
    swapped = sample(reverse=True)
    assert war_identity(first) == war_identity(swapped)
    assert classify_result(swapped, "#OURS") == "win"
    assert "Trouble&lt;&amp;makers" in format_result(swapped, "#OURS", rng=random.Random(3))
    assert "Enemy&lt;&gt;" in format_result(swapped, "#OURS", rng=random.Random(3))


def test_five_phrases_for_each_outcome():
    assert {kind: len(set(phrases)) for kind, phrases in PHRASES.items()} == {
        "win": 5, "loss": 5, "draw": 5,
    }
    for kind, conditions in (
        ("win", ((35, 32), (98, 80))),
        ("loss", ((30, 32), (80, 90))),
        ("draw", ((30, 30), (90, 90))),
    ):
        war = sample(stars=conditions[0], destruction=conditions[1])
        assert classify_result(war, "#OURS") == kind
        outputs = {format_result(war, "#OURS", rng=random.Random(i)) for i in range(80)}
        assert len(outputs) == 5


def test_recency_filters_old_cwl_wars():
    assert recently_finished(sample(), NOW)
    assert not recently_finished(sample(end_time="20260101T000000.000Z"), NOW)
    assert not recently_finished(sample(end_time="20261106T150000.000Z"), NOW)


def test_claims_baseline_then_one_time_across_restarts(tmp_path):
    path = str(tmp_path / "bindings.db")
    store = WarAnnouncementStore(path)
    assert store.claim_new(-1001, ["old-war"]) == []
    assert store.claim_new(-1001, ["old-war", "new-war", "new-war"]) == ["new-war"]
    assert WarAnnouncementStore(path).claim_new(-1001, ["new-war"]) == []
    assert store.claim_new(-1002, ["other-group-first-war"]) == []
    assert store.claim_new(-1002, ["other-group-first-war", "new-war"]) == ["new-war"]


def test_empty_first_poll_still_initializes(tmp_path):
    s = WarAnnouncementStore(str(tmp_path / "db.sqlite"))
    assert s.claim_new(-100, []) == []
    assert s.claim_new(-100, ["new-result"]) == ["new-result"]
