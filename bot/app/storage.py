from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable

import aiosqlite

from app.settings import settings


@dataclass(slots=True)
class Binding:
    telegram_user_id: int
    telegram_full_name: str
    coc_player_tag: str
    telegram_username: str | None = None


async def init_db() -> None:
    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS bindings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                telegram_username TEXT,
                telegram_full_name TEXT NOT NULL,
                coc_player_tag TEXT NOT NULL,
                group_id INTEGER NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_bindings_user_group
            ON bindings (telegram_user_id, group_id)
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS reminder_cooldowns (
                telegram_user_id INTEGER NOT NULL,
                group_id INTEGER NOT NULL,
                last_reminded_at INTEGER NOT NULL,
                PRIMARY KEY (telegram_user_id, group_id)
            )
            """
        )
        await db.commit()


async def upsert_binding(
    *,
    telegram_user_id: int,
    telegram_username: str | None,
    telegram_full_name: str,
    coc_player_tag: str,
    group_id: int,
) -> None:
    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute(
            """
            INSERT INTO bindings (
                telegram_user_id,
                telegram_username,
                telegram_full_name,
                coc_player_tag,
                group_id,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_user_id, group_id) DO UPDATE SET
                telegram_username = excluded.telegram_username,
                telegram_full_name = excluded.telegram_full_name,
                coc_player_tag = excluded.coc_player_tag,
                created_at = excluded.created_at
            """,
            (
                telegram_user_id,
                telegram_username,
                telegram_full_name,
                coc_player_tag,
                group_id,
            ),
        )
        await db.commit()


async def remove_binding(telegram_user_id: int, group_id: int) -> bool:
    async with aiosqlite.connect(settings.database_path) as db:
        cursor = await db.execute(
            "DELETE FROM bindings WHERE telegram_user_id = ? AND group_id = ?",
            (telegram_user_id, group_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def fetch_group_ids() -> list[int]:
    async with aiosqlite.connect(settings.database_path) as db:
        cursor = await db.execute("SELECT DISTINCT group_id FROM bindings")
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def fetch_bindings_for_group(group_id: int) -> list[Binding]:
    async with aiosqlite.connect(settings.database_path) as db:
        cursor = await db.execute(
            """
            SELECT telegram_user_id, telegram_username, telegram_full_name, coc_player_tag
            FROM bindings
            WHERE group_id = ?
            """,
            (group_id,),
        )
        rows = await cursor.fetchall()
    return [
        Binding(
            telegram_user_id=row[0],
            telegram_username=row[1],
            telegram_full_name=row[2],
            coc_player_tag=row[3],
        )
        for row in rows
    ]


async def fetch_cooldowns(group_id: int) -> dict[int, int]:
    async with aiosqlite.connect(settings.database_path) as db:
        cursor = await db.execute(
            """
            SELECT telegram_user_id, last_reminded_at
            FROM reminder_cooldowns
            WHERE group_id = ?
            """,
            (group_id,),
        )
        rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}


async def update_cooldowns(group_id: int, user_ids: Iterable[int]) -> None:
    now_ts = int(time.time())
    async with aiosqlite.connect(settings.database_path) as db:
        for user_id in user_ids:
            await db.execute(
                """
                INSERT INTO reminder_cooldowns (telegram_user_id, group_id, last_reminded_at)
                VALUES (?, ?, ?)
                ON CONFLICT(telegram_user_id, group_id) DO UPDATE SET
                    last_reminded_at = excluded.last_reminded_at
                """,
                (user_id, group_id, now_ts),
            )
        await db.commit()
