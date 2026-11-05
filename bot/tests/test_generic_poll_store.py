"""Generic question/option/duration poll schema and persistent expiration."""
from datetime import datetime, timedelta, timezone
import sqlite3

from app.clan_poll import ClanPollStore


def test_generic_poll_persists_and_summary_claim_is_one_time(tmp_path):
    path = str(tmp_path / "poll.sqlite3")
    store = ClanPollStore(path)
    now = datetime(2026, 11, 5, tzinfo=timezone.utc)
    deadline = (now + timedelta(hours=1)).isoformat()
    store.create("poll123", -1001, 123, [
        {"tag":"option-1", "name":"За"},
        {"tag":"option-2", "name":"Против"},
        {"tag":"option-3", "name":"Воздержусь"},
    ], question="Стоит ли менять расписание?", closes_at=deadline,
        poll_type="generic")
    assert store.get("poll123")["question"] == "Стоит ли менять расписание?"
    assert store.due_summaries(now) == []
    assert len(ClanPollStore(path).due_summaries(now + timedelta(hours=2))) == 1
    assert store.claim_summary("poll123")
    assert not ClanPollStore(path).claim_summary("poll123")
    assert not store.due_summaries(now + timedelta(hours=2))
    store.release_summary("poll123")
    assert len(store.due_summaries(now + timedelta(hours=2))) == 1


def test_existing_deputy_poll_schema_upgrades_without_data_loss(tmp_path):
    path = str(tmp_path / "legacy.sqlite3")
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE clan_polls (poll_id TEXT PRIMARY KEY, chat_id INTEGER, message_id INTEGER, options TEXT, open INTEGER DEFAULT 1)")
        conn.execute("INSERT INTO clan_polls VALUES ('old',-1001,777,'[{\"tag\":\"#A\",\"name\":\"A\"},{\"tag\":\"#B\",\"name\":\"B\"}]',1)")
    store = ClanPollStore(path)
    assert store.get("old")["poll_type"] == "deputy"
    assert store.get("old")["open"]
