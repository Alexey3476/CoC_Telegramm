"""Persistent non-anonymous clan deputy poll, one Telegram identity per choice."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class ClanPollStore:
    def __init__(self, path):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS clan_polls (poll_id TEXT PRIMARY KEY, chat_id INTEGER, message_id INTEGER, options TEXT, open INTEGER DEFAULT 1)")
            db.execute("CREATE TABLE IF NOT EXISTS clan_poll_choices (poll_id TEXT, user_id INTEGER, choice INTEGER, PRIMARY KEY(poll_id,user_id))")
            # Additive migration from existing deputy poll storage.
            columns = {row[1] for row in db.execute("PRAGMA table_info(clan_polls)")}
            for name, definition in (
                ("question", "TEXT"),
                ("closes_at", "TEXT"),
                ("poll_type", "TEXT NOT NULL DEFAULT 'deputy'"),
                ("summary_sent", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE clan_polls ADD COLUMN {name} {definition}")

    def get(self, poll_id):
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT poll_id,chat_id,message_id,options,open,question,closes_at,poll_type,summary_sent FROM clan_polls WHERE poll_id=?", (poll_id,)).fetchone()
        return {"id":row[0],"chat_id":row[1],"message_id":row[2],"options":json.loads(row[3]),"open":bool(row[4]),"question":row[5],"closes_at":row[6],"poll_type":row[7],"summary_sent":bool(row[8])} if row else None

    def latest(self, chat_id):
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT poll_id FROM clan_polls WHERE chat_id=? ORDER BY rowid DESC LIMIT 1", (chat_id,)).fetchone()
        return self.get(row[0]) if row else None

    def create(self, poll_id, chat_id, message_id, options, *, question=None, closes_at=None, poll_type="deputy"):
        if len(options) < 2 or len(options) > 10:
            raise ValueError("2 to 10 options required")
        with sqlite3.connect(self.path) as db:
            db.execute("""INSERT INTO clan_polls
                (poll_id,chat_id,message_id,options,open,question,closes_at,poll_type)
                VALUES(?,?,?,?,1,?,?,?)""",
                (poll_id,chat_id,message_id,json.dumps(options,ensure_ascii=False),
                 question,closes_at,poll_type))

    def record(self, poll_id, user_id, selected, eligible):
        poll = self.get(poll_id)
        if not poll or not poll["open"]:
            return False
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM clan_poll_choices WHERE poll_id=? AND user_id=?", (poll_id,user_id))
            if eligible and len(selected)==1 and 0<=selected[0]<len(poll["options"]):
                db.execute("INSERT INTO clan_poll_choices VALUES(?,?,?)",
                           (poll_id,user_id,selected[0]))
                return True
        return False

    def count(self, poll_id, eligible_ids):
        poll = self.get(poll_id)
        if not poll:
            return []
        results = [{"tag":c["tag"],"name":c["name"],"votes":0} for c in poll["options"]]
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT user_id,choice FROM clan_poll_choices WHERE poll_id=?", (poll_id,)).fetchall()
        for uid,choice in rows:
            if uid in eligible_ids and 0 <= choice < len(results):
                results[choice]["votes"] += 1
        return sorted(results,key=lambda c:(-c["votes"],c["name"]))

    def close(self, poll_id):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE clan_polls SET open=0 WHERE poll_id=?", (poll_id,))

    def due_summaries(self, now: datetime | None = None) -> list[dict]:
        """Expired generic polls that still require one group summary."""
        now = now or datetime.now(timezone.utc)
        with sqlite3.connect(self.path) as db:
            rows = db.execute(
                """SELECT poll_id FROM clan_polls
                WHERE poll_type='generic' AND summary_sent=0 AND closes_at<=?
                ORDER BY closes_at ASC LIMIT 20""",
                (now.isoformat(),),
            ).fetchall()
        return [self.get(row[0]) for row in rows]

    def claim_summary(self, poll_id: str) -> bool:
        """Atomically claim publishing rights to avoid duplicate results."""
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            result = db.execute(
                "UPDATE clan_polls SET summary_sent=1,open=0 WHERE poll_id=? AND summary_sent=0",
                (poll_id,),
            )
            db.commit()
        return result.rowcount == 1

    def release_summary(self, poll_id: str) -> None:
        """Retry an outcome that definitely failed to send."""
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE clan_polls SET summary_sent=0 WHERE poll_id=?", (poll_id,))
