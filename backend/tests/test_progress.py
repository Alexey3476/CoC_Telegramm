from datetime import datetime, timezone

from app.progress import ProgressStore, compact_profile, compare


def test_persistent_progress_day_by_day(tmp_path):
    path = str(tmp_path / "players.db")
    store = ProgressStore(path)
    before = {"tag": "#VU099JCR", "name": "Lex", "townHallLevel": 17,
              "heroes": [{"name": "King", "level": 80}]}
    later = {"tag": "#VU099JCR", "name": "Lex", "townHallLevel": 18,
             "heroes": [{"name": "King", "level": 81}]}
    assert not store.record(before, datetime(2026, 11, 5, tzinfo=timezone.utc))["historyAvailable"]
    result = ProgressStore(path).record(later, datetime(2026, 11, 6, tzinfo=timezone.utc))
    assert result["historyAvailable"]
    assert result["comparisonDay"] == "2026-11-05"
    assert result["changes"]["townHallLevel"]["delta"] == 1
    assert result["changes"]["heroes"]["King"]["delta"] == 1


def test_no_invented_differences_when_fields_missing():
    result = compare({"townHallLevel": 17}, {"heroes": {"King": 81}})
    assert result["changes"] == {}


def test_no_credentials_persisted():
    compact = compact_profile({"tag": "#ABC", "secret": "token", "townHallLevel": 18})
    assert "secret" not in compact
