from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
import logging


@dataclass(frozen=True)
class Binding:
    telegram_user_id: int
    group_id: int
    coc_player_tag: str
    telegram_username: str | None
    telegram_full_name: str
    created_at: str


class BindingsStorage:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._logger = logging.getLogger(__name__)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bindings (
                    telegram_user_id INTEGER NOT NULL,
                    group_id INTEGER NOT NULL,
                    coc_player_tag TEXT NOT NULL,
                    telegram_username TEXT NULL,
                    telegram_full_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(group_id, telegram_user_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bindings_group_tag
                ON bindings(group_id, coc_player_tag)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminder_cooldowns (
                    group_id INTEGER NOT NULL,
                    telegram_user_id INTEGER NOT NULL,
                    last_reminded_at TEXT NOT NULL,
                    PRIMARY KEY(group_id, telegram_user_id)
                )
                """
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS linked_accounts (
                    group_id INTEGER NOT NULL,
                    telegram_user_id INTEGER NOT NULL,
                    coc_player_tag TEXT NOT NULL,
                    telegram_username TEXT NULL,
                    telegram_full_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(group_id, coc_player_tag)
                )"""
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_linked_accounts_user
                   ON linked_accounts(group_id, telegram_user_id)"""
            )
            # Additive migration, never destroy existing primary bindings.
            conn.execute(
                """INSERT OR IGNORE INTO linked_accounts
                   (group_id, telegram_user_id, coc_player_tag,
                    telegram_username, telegram_full_name, created_at)
                   SELECT group_id, telegram_user_id, coc_player_tag,
                          telegram_username, telegram_full_name, created_at
                   FROM bindings"""
            )
            conn.commit()
        self._logger.info("Bindings schema ensured path=%s", self.db_path)

    def upsert_binding(self, binding: Binding) -> None:
        """Safely add an alt, keeping the first verified account as primary."""
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            owner = conn.execute(
                "SELECT telegram_user_id FROM linked_accounts WHERE group_id=? AND coc_player_tag=?",
                (binding.group_id, binding.coc_player_tag),
            ).fetchone()
            if owner is not None and int(owner[0]) != binding.telegram_user_id:
                raise ValueError("Player account is already linked to another Telegram user")
            conn.execute(
                """INSERT INTO linked_accounts
                (group_id,telegram_user_id,coc_player_tag,telegram_username,telegram_full_name,created_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(group_id,coc_player_tag) DO UPDATE SET
                  telegram_username=excluded.telegram_username,
                  telegram_full_name=excluded.telegram_full_name""",
                (binding.group_id,binding.telegram_user_id,binding.coc_player_tag,
                 binding.telegram_username,binding.telegram_full_name,binding.created_at),
            )
            primary = conn.execute(
                "SELECT coc_player_tag FROM bindings WHERE group_id=? AND telegram_user_id=?",
                (binding.group_id,binding.telegram_user_id),
            ).fetchone()
            if primary is None:
                self._write_primary(conn, binding)
            conn.commit()

    @staticmethod
    def _write_primary(conn: sqlite3.Connection, binding: Binding) -> None:
        conn.execute(
            """INSERT INTO bindings
            (telegram_user_id,group_id,coc_player_tag,telegram_username,telegram_full_name,created_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(group_id,telegram_user_id) DO UPDATE SET
              coc_player_tag=excluded.coc_player_tag,
              telegram_username=excluded.telegram_username,
              telegram_full_name=excluded.telegram_full_name,
              created_at=excluded.created_at""",
            (binding.telegram_user_id,binding.group_id,binding.coc_player_tag,
             binding.telegram_username,binding.telegram_full_name,binding.created_at),
        )

    def get_user_accounts(self, group_id: int, user_id: int) -> list[Binding]:
        """Primary tag first, followed by verified alternate accounts."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT a.* FROM linked_accounts a
                LEFT JOIN bindings b ON b.group_id=a.group_id AND b.telegram_user_id=a.telegram_user_id
                WHERE a.group_id=? AND a.telegram_user_id=?
                ORDER BY (a.coc_player_tag=b.coc_player_tag) DESC, a.created_at ASC, a.coc_player_tag""",
                (group_id, user_id),
            ).fetchall()
        return [self._row_to_binding(row) for row in rows]

    def set_primary_account(self, group_id: int, user_id: int, tag: str) -> bool:
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM linked_accounts WHERE group_id=? AND telegram_user_id=? AND coc_player_tag=?",
                (group_id,user_id,tag),
            ).fetchone()
            if row is None:
                return False
            self._write_primary(conn, self._row_to_binding(row))
            conn.commit()
            return True

    def unlink_account(self, group_id: int, tag: str, owner_id: int | None = None) -> bool:
        """Delete one verified tag; optionally require ownership. Promotes an alt."""
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT telegram_user_id FROM linked_accounts WHERE group_id=? AND coc_player_tag=?",
                (group_id,tag),
            ).fetchone()
            if row is None or (owner_id is not None and int(row[0]) != owner_id):
                return False
            user_id = int(row[0])
            conn.execute(
                "DELETE FROM linked_accounts WHERE group_id=? AND coc_player_tag=?", (group_id,tag))
            primary = conn.execute(
                "SELECT coc_player_tag FROM bindings WHERE group_id=? AND telegram_user_id=?",
                (group_id,user_id),
            ).fetchone()
            if primary is not None and primary[0] == tag:
                new = conn.execute(
                    """SELECT * FROM linked_accounts WHERE group_id=? AND telegram_user_id=?
                    ORDER BY created_at ASC,coc_player_tag LIMIT 1""",
                    (group_id,user_id),
                ).fetchone()
                if new is None:
                    conn.execute(
                        "DELETE FROM bindings WHERE group_id=? AND telegram_user_id=?",
                        (group_id,user_id))
                else:
                    self._write_primary(conn,self._row_to_binding(new))
            conn.commit()
            return True

    def delete_binding(self, group_id: int, telegram_user_id: int) -> bool:
        """Remove ALL of a user's verified accounts; /unlink removes just one."""
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            c1 = conn.execute(
                "DELETE FROM linked_accounts WHERE group_id=? AND telegram_user_id=?",
                (group_id,telegram_user_id))
            c2 = conn.execute(
                "DELETE FROM bindings WHERE group_id=? AND telegram_user_id=?",
                (group_id,telegram_user_id))
            conn.commit()
            return c1.rowcount > 0 or c2.rowcount > 0

    def get_binding(self, group_id: int, telegram_user_id: int) -> Binding | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM bindings WHERE group_id = ? AND telegram_user_id = ?",
                (group_id, telegram_user_id),
            ).fetchone()
        binding = self._row_to_binding(row)
        self._logger.info(
            "Binding lookup group_id=%s user_id=%s found=%s",
            group_id,
            telegram_user_id,
            binding is not None,
        )
        return binding

    def get_bindings_for_group(self, group_id: int) -> list[Binding]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM bindings WHERE group_id = ?",
                (group_id,),
            ).fetchall()
        bindings = [binding for row in rows if (binding := self._row_to_binding(row))]
        self._logger.info("Bindings lookup group_id=%s count=%s", group_id, len(bindings))
        return bindings

    def get_bindings_for_tags(self, group_id: int, tags: Iterable[str]) -> list[Binding]:
        tags_list = list(tags)
        if not tags_list:
            return []
        placeholders = ",".join(["?"] * len(tags_list))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM linked_accounts WHERE group_id = ? AND coc_player_tag IN ({placeholders})",
                (group_id, *tags_list),
            ).fetchall()
        bindings = [binding for row in rows if (binding := self._row_to_binding(row))]
        self._logger.info(
            "Bindings lookup group_id=%s tags_count=%s result_count=%s",
            group_id,
            len(tags_list),
            len(bindings),
        )
        return bindings

    def get_user_id_by_tag(self, group_id: int, coc_tag: str) -> int | None:
        """Get telegram user ID by CoC player tag."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT telegram_user_id FROM linked_accounts WHERE group_id = ? AND coc_player_tag = ?",
                (group_id, coc_tag),
            ).fetchone()
        if row:
            self._logger.info("User lookup by tag tag=%s user_id=%s", coc_tag, row[0])
            return row[0]
        self._logger.info("User not found by tag=%s", coc_tag)
        return None

    def get_group_ids(self) -> list[int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT DISTINCT group_id FROM bindings").fetchall()
        group_ids = [row[0] for row in rows]
        self._logger.info("Binding group ids count=%s", len(group_ids))
        return group_ids

    def get_cooldowns(self, group_id: int, user_ids: Iterable[int]) -> dict[int, datetime]:
        user_list = list(user_ids)
        if not user_list:
            return {}
        placeholders = ",".join(["?"] * len(user_list))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT telegram_user_id, last_reminded_at FROM reminder_cooldowns "
                f"WHERE group_id = ? AND telegram_user_id IN ({placeholders})",
                (group_id, *user_list),
            ).fetchall()
        results: dict[int, datetime] = {}
        for row in rows:
            try:
                results[int(row[0])] = datetime.fromisoformat(row[1])
            except (TypeError, ValueError):
                continue
        self._logger.info(
            "Cooldowns lookup group_id=%s user_count=%s result_count=%s",
            group_id,
            len(user_list),
            len(results),
        )
        return results

    def set_cooldowns(self, group_id: int, user_ids: Iterable[int], timestamp: datetime) -> None:
        payload = [(group_id, user_id, timestamp.isoformat()) for user_id in user_ids]
        if not payload:
            return
        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO reminder_cooldowns (group_id, telegram_user_id, last_reminded_at)
                VALUES (?, ?, ?)
                ON CONFLICT(group_id, telegram_user_id) DO UPDATE SET
                    last_reminded_at=excluded.last_reminded_at
                """,
                payload,
            )
            conn.commit()
        self._logger.info(
            "Cooldowns updated group_id=%s user_count=%s",
            group_id,
            len(payload),
        )

    @staticmethod
    def _row_to_binding(row: sqlite3.Row | None) -> Binding | None:
        if row is None:
            return None
        return Binding(
            telegram_user_id=int(row["telegram_user_id"]),
            group_id=int(row["group_id"]),
            coc_player_tag=str(row["coc_player_tag"]),
            telegram_username=row["telegram_username"],
            telegram_full_name=str(row["telegram_full_name"]),
            created_at=str(row["created_at"]),
        )
