"""Persistent, one-Telegram-person-one-vote clan polls.

Only the Telegram handlers decide who can create or participate. SQLite keeps
votes across add-on restarts and prevents an alt account voting a second time.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class PollStore:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS polls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER NOT NULL,
                group_id INTEGER NOT NULL,
                message_id INTEGER,
                question TEXT NOT NULL,
                options TEXT NOT NULL,
                ends_at TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS poll_votes (
                poll_id INTEGER NOT NULL,
                telegram_id INTEGER NOT NULL,
                choice INTEGER NOT NULL,
                PRIMARY KEY(poll_id, telegram_id),
                FOREIGN KEY(poll_id) REFERENCES polls(id)
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS polls_due ON polls(completed, ends_at)")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _record(conn: sqlite3.Connection, poll_id: int) -> dict | None:
        row = conn.execute("SELECT * FROM polls WHERE id=?", (poll_id,)).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["options"] = json.loads(out["options"])
        out["votes"] = [0] * len(out["options"])
        for choice, count in conn.execute(
            "SELECT choice,COUNT(*) FROM poll_votes WHERE poll_id=? GROUP BY choice",
            (poll_id,),
        ):
            if 0 <= choice < len(out["options"]):
                out["votes"][choice] = count
        out["totalVotes"] = sum(out["votes"])
        return out

    def create(self, creator_id: int, group_id: int, question: str,
               options: list[str], ends_at: datetime) -> dict:
        if (not 1 <= len(question) <= 240 or not 2 <= len(options) <= 8
                or any(not 1 <= len(option) <= 80 for option in options)
                or len(set(option.casefold() for option in options)) != len(options)
                or ends_at.tzinfo is None or ends_at <= now_utc()):
            raise ValueError("Invalid poll question, options or deadline")
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO polls(creator_id,group_id,question,options,ends_at) "
                "VALUES (?,?,?,?,?)",
                (creator_id, group_id, question, json.dumps(options, ensure_ascii=False),
                 ends_at.astimezone(timezone.utc).isoformat()),
            )
            return self._record(conn, cursor.lastrowid)

    def set_message(self, poll_id: int, message_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE polls SET message_id=? WHERE id=? AND completed=0",
                         (message_id, poll_id))

    def get(self, poll_id: int) -> dict | None:
        with self._connect() as conn:
            return self._record(conn, poll_id)

    def vote(self, poll_id: int, group_id: int, telegram_id: int,
             choice: int) -> dict:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            poll = self._record(conn, poll_id)
            if not poll or poll["group_id"] != group_id or poll["message_id"] is None:
                raise ValueError("Unknown poll")
            if poll["completed"] or datetime.fromisoformat(poll["ends_at"]) <= now_utc():
                raise ValueError("Poll is closed")
            if not 0 <= choice < len(poll["options"]):
                raise ValueError("Invalid poll choice")
            conn.execute(
                "INSERT INTO poll_votes(poll_id,telegram_id,choice) VALUES (?,?,?) "
                "ON CONFLICT(poll_id,telegram_id) DO UPDATE SET choice=excluded.choice",
                (poll_id, telegram_id, choice),
            )
            return self._record(conn, poll_id)

    def due(self) -> list[dict]:
        with self._connect() as conn:
            ids = [row[0] for row in conn.execute(
                "SELECT id FROM polls WHERE completed=0 AND message_id IS NOT NULL "
                "AND ends_at<=? ORDER BY ends_at",
                (now_utc().isoformat(),),
            )]
            return [record for i in ids if (record := self._record(conn, i))]

    def finish(self, poll_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE polls SET completed=1 WHERE id=?", (poll_id,))
