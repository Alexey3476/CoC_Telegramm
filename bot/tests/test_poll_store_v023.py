from datetime import datetime, timedelta, timezone

import pytest

from app.polls import PollStore, now_utc


def test_persistent_poll_one_user_one_vote_and_switch(tmp_path):
    db = str(tmp_path / "polls.db")
    s = PollStore(db)
    poll = s.create(1, -1005, "Кого брать?", ["Lex", "Alex"], now_utc() + timedelta(hours=1))
    s.set_message(poll["id"], 42)
    assert s.vote(poll["id"], -1005, 777, 0)["votes"] == [1, 0]
    assert s.vote(poll["id"], -1005, 777, 1)["votes"] == [0, 1]
    restored = PollStore(db)
    assert restored.get(poll["id"])["totalVotes"] == 1
    assert restored.vote(poll["id"], -1005, 888, 0)["votes"] == [1, 1]
    with pytest.raises(ValueError):
        restored.vote(poll["id"], -333, 123, 1)


def test_polls_close_persist_results_and_dont_allow_late_votes(tmp_path):
    s = PollStore(str(tmp_path / "polls.db"))
    poll = s.create(1, 2, "Что менять?", ["Веса", "Состав"],
                    now_utc() + timedelta(hours=1))
    s.set_message(poll["id"], 44)
    with s._connect() as conn:
        conn.execute("UPDATE polls SET ends_at=? WHERE id=?",
                     ((now_utc() - timedelta(seconds=5)).isoformat(), poll["id"]))
    assert [p["id"] for p in s.due()] == [poll["id"]]
    with pytest.raises(ValueError):
        s.vote(poll["id"], 2, 9, 0)
    s.finish(poll["id"])
    assert s.get(poll["id"])["completed"] == 1
    assert not s.due()


def test_reject_duplicate_options_or_missing_voters(tmp_path):
    s = PollStore(str(tmp_path / "polls.db"))
    with pytest.raises(ValueError):
        s.create(1, 2, "Вопрос", ["Да", "да"], now_utc()+timedelta(hours=1))
    with pytest.raises(ValueError):
        s.create(1, 2, "Вопрос", ["Да"], now_utc()+timedelta(hours=1))
    poll = s.create(1, 2, "Вопрос", ["Да", "Нет"], now_utc()+timedelta(hours=1))
    with pytest.raises(ValueError):
        s.vote(poll["id"], 2, 20, 1)
