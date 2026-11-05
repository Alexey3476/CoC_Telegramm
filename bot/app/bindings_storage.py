"""Persistent CoC account ownership: multiple verified accounts per Telegram user.

Migration from 0.2.0 preserves all existing bindings and reminder cooldowns.
Player tags remain globally unique within a clan group, so a twink cannot be
claimed by two different Telegram users.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

VALID_CWL = frozenset({"in", "out", "unknown"})


@dataclass(frozen=True)
class Binding:
    telegram_user_id: int
    group_id: int
    coc_player_tag: str
    telegram_username: str | None
    telegram_full_name: str
    created_at: str
    is_primary: bool = False
    cwl_opt_in: str = "unknown"
    last_seen_manual: str | None = None


class BindingsStorage:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._logger = logging.getLogger(__name__)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            present = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='bindings'"
            ).fetchone()
            if present:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(bindings)")}
                if "is_primary" not in columns:
                    conn.execute("ALTER TABLE bindings RENAME TO bindings_v020")
                    self._create_bindings(conn)
                    conn.execute(
                        """INSERT OR IGNORE INTO bindings
                        (group_id, coc_player_tag, telegram_user_id, telegram_username,
                        telegram_full_name, created_at, is_primary, cwl_opt_in)
                        SELECT group_id, coc_player_tag, telegram_user_id,
                        telegram_username, telegram_full_name, created_at, 1, 'unknown'
                        FROM bindings_v020 ORDER BY created_at"""
                    )
                    conn.execute("DROP TABLE bindings_v020")
            else:
                self._create_bindings(conn)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_bindings_user ON bindings(group_id,telegram_user_id)"
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS reminder_cooldowns (
                    group_id INTEGER NOT NULL,
                    telegram_user_id INTEGER NOT NULL,
                    last_reminded_at TEXT NOT NULL,
                    PRIMARY KEY(group_id, telegram_user_id)
                )"""
            )
            conn.commit()
        self._logger.info("Account schema v0.2.1 ready")

    @staticmethod
    def _create_bindings(conn: sqlite3.Connection) -> None:
        conn.execute(
            """CREATE TABLE bindings (
                group_id INTEGER NOT NULL,
                coc_player_tag TEXT NOT NULL,
                telegram_user_id INTEGER NOT NULL,
                telegram_username TEXT,
                telegram_full_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_primary INTEGER NOT NULL DEFAULT 0,
                cwl_opt_in TEXT NOT NULL DEFAULT 'unknown'
                    CHECK(cwl_opt_in IN ('in','out','unknown')),
                last_seen_manual TEXT,
                PRIMARY KEY (group_id, coc_player_tag)
            )"""
        )

    def upsert_binding(self, binding: Binding) -> None:
        """Atomic verified tag ownership check and additive account binding."""
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            owner = conn.execute(
                "SELECT telegram_user_id FROM bindings WHERE group_id=? AND coc_player_tag=?",
                (binding.group_id, binding.coc_player_tag),
            ).fetchone()
            if owner and int(owner[0]) != binding.telegram_user_id:
                raise ValueError("Player account is already linked to another Telegram user")
            count = conn.execute(
                "SELECT COUNT(*) FROM bindings WHERE group_id=? AND telegram_user_id=?",
                (binding.group_id, binding.telegram_user_id),
            ).fetchone()[0]
            if owner:
                conn.execute(
                    """UPDATE bindings SET telegram_username=?,telegram_full_name=?
                    WHERE group_id=? AND coc_player_tag=?""",
                    (binding.telegram_username, binding.telegram_full_name,
                     binding.group_id, binding.coc_player_tag),
                )
            else:
                conn.execute(
                    """INSERT INTO bindings
                    (group_id,coc_player_tag,telegram_user_id,telegram_username,
                    telegram_full_name,created_at,is_primary,cwl_opt_in,last_seen_manual)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (binding.group_id, binding.coc_player_tag, binding.telegram_user_id,
                     binding.telegram_username, binding.telegram_full_name,
                     binding.created_at, int(count == 0),
                     binding.cwl_opt_in if binding.cwl_opt_in in VALID_CWL else "unknown",
                     binding.last_seen_manual),
                )
            conn.commit()
        self._logger.info("Verified player binding added user_id=%s", binding.telegram_user_id)

    def get_binding(self, group_id: int, telegram_user_id: int) -> Binding | None:
        """Backward-compatible primary account lookup."""
        accounts = self.get_bindings_for_user(group_id, telegram_user_id)
        return accounts[0] if accounts else None

    def get_bindings_for_user(self, group_id: int, telegram_user_id: int) -> list[Binding]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM bindings WHERE group_id=? AND telegram_user_id=?
                ORDER BY is_primary DESC,created_at ASC,coc_player_tag""",
                (group_id, telegram_user_id),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get_bindings_for_group(self, group_id: int) -> list[Binding]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM bindings WHERE group_id=? ORDER BY telegram_user_id,is_primary DESC",
                (group_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get_bindings_for_tags(self, group_id: int, tags: Iterable[str]) -> list[Binding]:
        tags_list = list(dict.fromkeys(tags))
        if not tags_list:
            return []
        placeholders = ",".join("?" for _ in tags_list)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM bindings WHERE group_id=? AND coc_player_tag IN ({placeholders})",
                (group_id, *tags_list),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get_user_id_by_tag(self, group_id: int, coc_tag: str) -> int | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT telegram_user_id FROM bindings WHERE group_id=? AND coc_player_tag=?",
                (group_id, coc_tag),
            ).fetchone()
        return int(row[0]) if row else None

    def delete_binding(self, group_id: int, telegram_user_id: int) -> bool:
        """Legacy method. Removes all accounts for this user ONLY."""
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM bindings WHERE group_id=? AND telegram_user_id=?",
                (group_id, telegram_user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_player_binding(
        self, group_id: int, tag: str, *, requester_id: int, administrator: bool = False,
    ) -> bool:
        """Delete exactly one account with explicit ownership/admin authorization."""
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT telegram_user_id,is_primary FROM bindings WHERE group_id=? AND coc_player_tag=?",
                (group_id, tag),
            ).fetchone()
            if row is None:
                return False
            owner, was_primary = int(row[0]), bool(row[1])
            if owner != requester_id and not administrator:
                raise PermissionError("Not the account owner")
            conn.execute(
                "DELETE FROM bindings WHERE group_id=? AND coc_player_tag=?",
                (group_id, tag),
            )
            if was_primary:
                next_account = conn.execute(
                    """SELECT coc_player_tag FROM bindings WHERE group_id=? AND telegram_user_id=?
                    ORDER BY created_at,coc_player_tag LIMIT 1""",
                    (group_id, owner),
                ).fetchone()
                if next_account:
                    conn.execute(
                        "UPDATE bindings SET is_primary=1 WHERE group_id=? AND coc_player_tag=?",
                        (group_id, next_account[0]),
                    )
            conn.commit()
        return True

    def set_primary(self, group_id: int, telegram_user_id: int, tag: str) -> bool:
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """SELECT 1 FROM bindings WHERE group_id=? AND telegram_user_id=?
                AND coc_player_tag=?""", (group_id, telegram_user_id, tag),
            ).fetchone()
            if not existing:
                return False
            conn.execute(
                "UPDATE bindings SET is_primary=0 WHERE group_id=? AND telegram_user_id=?",
                (group_id, telegram_user_id),
            )
            conn.execute(
                "UPDATE bindings SET is_primary=1 WHERE group_id=? AND coc_player_tag=?",
                (group_id, tag),
            )
            conn.commit()
            return True

    def set_cwl_opt_in(self, group_id: int, telegram_user_id: int, tag: str, status: str) -> bool:
        if status not in VALID_CWL:
            raise ValueError("Invalid CWL opt-in state")
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """UPDATE bindings SET cwl_opt_in=? WHERE group_id=?
                AND telegram_user_id=? AND coc_player_tag=?""",
                (status, group_id, telegram_user_id, tag),
            )
            conn.commit()
            return cursor.rowcount > 0

    def set_manual_last_seen(self, group_id: int, tag: str, timestamp: str | None) -> bool:
        """For a leader's in-game observation only; caller enforces captain rights."""
        if timestamp is not None:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE bindings SET last_seen_manual=? WHERE group_id=? AND coc_player_tag=?",
                (timestamp, group_id, tag),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_group_ids(self) -> list[int]:
        with self._connect() as conn:
            return [row[0] for row in conn.execute("SELECT DISTINCT group_id FROM bindings")]

    def get_cooldowns(self, group_id: int, user_ids: Iterable[int]) -> dict[int, datetime]:
        users = list(dict.fromkeys(user_ids))
        if not users:
            return {}
        placeholders = ",".join("?" for _ in users)
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT telegram_user_id,last_reminded_at FROM reminder_cooldowns
                WHERE group_id=? AND telegram_user_id IN ({placeholders})""",
                (group_id, *users),
            ).fetchall()
        records = {}
        for row in rows:
            try:
                records[int(row[0])] = datetime.fromisoformat(row[1])
            except (TypeError, ValueError):
                pass
        return records

    def set_cooldowns(self, group_id: int, user_ids: Iterable[int], timestamp: datetime) -> None:
        payload = [(group_id, user, timestamp.isoformat()) for user in set(user_ids)]
        if not payload:
            return
        with self._lock, self._connect() as conn:
            conn.executemany(
                """INSERT INTO reminder_cooldowns(group_id,telegram_user_id,last_reminded_at)
                VALUES (?,?,?) ON CONFLICT(group_id,telegram_user_id) DO UPDATE
                SET last_reminded_at=excluded.last_reminded_at""", payload,
            )
            conn.commit()

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Binding:
        return Binding(
            telegram_user_id=int(row["telegram_user_id"]),
            group_id=int(row["group_id"]),
            coc_player_tag=str(row["coc_player_tag"]),
            telegram_username=row["telegram_username"],
            telegram_full_name=str(row["telegram_full_name"]),
            created_at=str(row["created_at"]),
            is_primary=bool(row["is_primary"]),
            cwl_opt_in=str(row["cwl_opt_in"]),
            last_seen_manual=row["last_seen_manual"],
        )

    _row_to_binding = _from_row
