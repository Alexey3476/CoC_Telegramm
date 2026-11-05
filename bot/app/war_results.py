"""One-time announcements of real completed CoC wars.

The Telegram bot and private backend share /data via Home Assistant Supervisor.
War result delivery state is stored in the existing persistent bindings SQLite DB.
"""
from __future__ import annotations

import html
import random
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from app.ui import parse_game_time


PHRASES: dict[str, tuple[str, ...]] = {
    "win": (
        "Отличная командная работа! Так держать, Troublemakers! 💪",
        "Заслуженная победа! Продолжаем в том же духе. 🔥",
        "Каждая звезда была важна. Молодцы, команда! ⭐",
        "Сыграли слаженно и забрали победу. Красавцы! 🏆",
        "Вот так и нужно воевать! Спасибо всем за атаки. 🎉",
    ),
    "loss": (
        "На этот раз соперник оказался сильнее. Разберём ошибки и вернёмся! 💪",
        "Поражение не отменяет хороших атак. В следующей войне постараемся лучше.",
        "Не получилось победить сегодня, зато понятно, над чем работать. ⚔️",
        "Команда, не опускаем руки! Следующую войну проведём сильнее.",
        "Сегодня не наш день. Сделаем выводы и попробуем забрать следующую победу!",
    ),
    "draw": (
        "Равная битва! Молодцы, в следующий раз дожмём до победы. 🤝",
        "Ничья, но борьба была достойной. Так держать, команда!",
        "До победы не хватило совсем немного. Следующую заберём! ⭐",
        "Сыграли на равных. Спасибо за атаки, продолжаем улучшаться!",
        "Соперник оказался достойным. Ничья сегодня, победа в следующий раз! ⚔️",
    ),
}


def war_identity(war: dict[str, Any]) -> str | None:
    """Same ID regardless of which team appears in API clan/opponent fields."""
    own, other = war.get("clan") or {}, war.get("opponent") or {}
    start = war.get("startTime")
    if not start or not own.get("tag") or not other.get("tag"):
        return None
    return "|".join((str(start), *sorted((str(own["tag"]), str(other["tag"])))))


def classify_result(war: dict[str, Any], clan_tag: str) -> str | None:
    if war.get("state") != "warEnded":
        return None
    own, opponent = war.get("clan") or {}, war.get("opponent") or {}
    if opponent.get("tag") == clan_tag:
        own, opponent = opponent, own
    if own.get("tag") != clan_tag:
        return None
    try:
        a, b = int(own["stars"]), int(opponent["stars"])
    except (KeyError, TypeError, ValueError):
        return None
    if a != b:
        return "win" if a > b else "loss"
    if own.get("destructionPercentage") is None or opponent.get("destructionPercentage") is None:
        return None  # Stars alone cannot settle a tie when damage differs.
    try:
        damage = float(own["destructionPercentage"]) - float(opponent["destructionPercentage"])
    except (TypeError, ValueError):
        return None
    if damage > 0.000001:
        return "win"
    if damage < -0.000001:
        return "loss"
    return "draw"


def format_result(war: dict[str, Any], clan_tag: str, *, rng: random.Random | None = None) -> str:
    result = classify_result(war, clan_tag)
    if result is None:
        raise ValueError("War has no verifiable completed result for this clan")
    clan, opponent = war["clan"], war["opponent"]
    if opponent.get("tag") == clan_tag:
        clan, opponent = opponent, clan
    header = {"win": "🏆 Победа!", "loss": "⚔️ Поражение", "draw": "🤝 Ничья"}[result]
    choice = (rng or random).choice(PHRASES[result])
    own_name = html.escape(str(clan.get("name") or "Наш клан"))
    other_name = html.escape(str(opponent.get("name") or "Соперник"))
    our_stars, their_stars = int(clan["stars"]), int(opponent["stars"])
    own_damage = float(clan.get("destructionPercentage") or 0)
    their_damage = float(opponent.get("destructionPercentage") or 0)
    return (
        f"<b>{header}</b>\n"
        f"🏰 {own_name} vs {other_name}\n"
        f"⭐ {our_stars} : {their_stars} · "
        f"💥 {own_damage:.1f}% : {their_damage:.1f}%\n\n"
        f"{html.escape(choice)}"
    )


def recently_finished(war: dict[str, Any], now: datetime | None = None,
                      max_age: timedelta = timedelta(hours=12)) -> bool:
    """Avoid announcing old archived CWL rounds when updating an add-on."""
    now = now or datetime.now(timezone.utc)
    end = parse_game_time(war.get("endTime"))
    if end is None:
        return False
    elapsed = now - end
    return -timedelta(minutes=10) <= elapsed <= max_age


class WarAnnouncementStore:
    """Atomic at-most-once claim. First observation seeds history without spam.

    Reserving a message before Telegram send prevents duplicate congratulations
    after restarts. A rare network failure after the reservation may lose one
    message; exactly-once Telegram delivery is impossible without an API
    idempotency key.
    """

    def __init__(self, db_path: str):
        self.path = db_path
        self._lock = threading.Lock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path, timeout=10) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS war_announcement_state (
                chat_id INTEGER PRIMARY KEY,
                initialized_at TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS war_announcements (
                chat_id INTEGER NOT NULL,
                war_id TEXT NOT NULL,
                reserved_at TEXT NOT NULL,
                PRIMARY KEY(chat_id, war_id)
            )""")

    def claim_new(self, chat_id: int, war_ids: Sequence[str]) -> list[str]:
        """Returns new IDs in order; first check marks all known IDs as seen."""
        ids = list(dict.fromkeys(war_ids))
        with self._lock, sqlite3.connect(self.path, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            first = db.execute(
                "SELECT 1 FROM war_announcement_state WHERE chat_id=?", (chat_id,),
            ).fetchone() is None
            timestamp = datetime.now(timezone.utc).isoformat()
            if first:
                db.execute("INSERT INTO war_announcement_state(chat_id, initialized_at) VALUES(?,?)",
                           (chat_id, timestamp))
            claimed = []
            for war_id in ids:
                inserted = db.execute(
                    "INSERT OR IGNORE INTO war_announcements(chat_id,war_id,reserved_at) VALUES(?,?,?)",
                    (chat_id, war_id, timestamp),
                )
                if inserted.rowcount and not first:
                    claimed.append(war_id)
            db.commit()
        return claimed
