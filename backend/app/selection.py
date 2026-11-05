"""CoC roster selection rules. All moderation outcomes are advisory only.

War preference comes from Clash API; CWL preference and last-seen values are
captain/owner-reported because official API has no independent CWL opt-in or last-online.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_WEIGHTS = {
    "combat": 30.0,
    "reliability": 25.0,
    "performance": 25.0,
    "participation": 10.0,
    "activity": 10.0,
}
METRICS = tuple(DEFAULT_WEIGHTS)
PREFS = ("in", "out", "unknown")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(value: str | None) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
        return dt.astimezone(timezone.utc) if dt and dt.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


class SelectionStore:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS preferences (
                clan_tag TEXT NOT NULL,
                player_tag TEXT NOT NULL,
                cwl_opt TEXT NOT NULL DEFAULT 'unknown',
                last_seen_manual TEXT NULL,
                last_seen_reporter INTEGER NULL,
                updated TEXT NOT NULL,
                PRIMARY KEY(clan_tag,player_tag)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS weights(
                metric TEXT PRIMARY KEY,
                value REAL NOT NULL CHECK(value >= 0 AND value <= 100)
            )""")
            conn.executemany(
                "INSERT OR IGNORE INTO weights(metric,value) VALUES(?,?)",
                list(DEFAULT_WEIGHTS.items()),
            )

    def weights(self) -> dict[str, float]:
        with sqlite3.connect(self.path) as conn:
            rows = dict(conn.execute("SELECT metric,value FROM weights"))
        return {key: float(rows.get(key, default)) for key, default in DEFAULT_WEIGHTS.items()}

    def set_weight(self, metric: str, percent: float) -> dict[str, float]:
        """Set one weight; rescale remaining metrics to retain exactly 100%."""
        if metric not in DEFAULT_WEIGHTS or not 0 <= percent <= 100:
            raise ValueError("Invalid metric or percentage (0..100)")
        with sqlite3.connect(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            prev = dict(conn.execute("SELECT metric,value FROM weights"))
            others = [m for m in METRICS if m != metric]
            available = 100.0 - float(percent)
            old_total = sum(float(prev.get(m, DEFAULT_WEIGHTS[m])) for m in others)
            values = {metric: round(float(percent), 4)}
            for name in others:
                share = (float(prev.get(name, DEFAULT_WEIGHTS[name])) / old_total
                         if old_total > 0 else 1 / len(others))
                values[name] = round(available * share, 4)
            # Preserve exact sum within float arithmetic by allocating residual to last metric.
            values[others[-1]] = round(100.0 - sum(v for k, v in values.items() if k != others[-1]), 4)
            conn.executemany("UPDATE weights SET value=? WHERE metric=?",
                             [(value, key) for key, value in values.items()])
            conn.commit()
        return values

    def get_preferences(self, clan_tag: str) -> dict[str, dict]:
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                """SELECT player_tag,cwl_opt,last_seen_manual,last_seen_reporter
                   FROM preferences WHERE clan_tag=?""", (clan_tag,)
            ).fetchall()
        return {row[0]: {"cwlPreference": row[1], "lastSeenManual": row[2],
                         "lastSeenReporter": row[3]} for row in rows}

    def set_cwl(self, clan_tag: str, player_tag: str, preference: str) -> None:
        if preference not in PREFS:
            raise ValueError("CWL preference must be in/out/unknown")
        now = utc_now().isoformat()
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """INSERT INTO preferences(clan_tag,player_tag,cwl_opt,updated)
                   VALUES(?,?,?,?)
                   ON CONFLICT(clan_tag,player_tag)
                   DO UPDATE SET cwl_opt=excluded.cwl_opt, updated=excluded.updated""",
                (clan_tag, player_tag, preference, now),
            )

    def report_last_seen(self, clan_tag: str, player_tag: str,
                         value: str | None, reported_by: int) -> None:
        if value is not None and parse_utc(value) is None:
            raise ValueError("Expected offset-aware ISO timestamp")
        now = utc_now().isoformat()
        if parse_utc(value) and parse_utc(value) > utc_now() + timedelta(minutes=1):
            raise ValueError("Future last-seen timestamps not permitted")
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """INSERT INTO preferences(
                    clan_tag,player_tag,cwl_opt,last_seen_manual,last_seen_reporter,updated
                   ) VALUES(?,?,'unknown',?,?,?)
                   ON CONFLICT(clan_tag,player_tag)
                   DO UPDATE SET last_seen_manual=excluded.last_seen_manual,
                                 last_seen_reporter=excluded.last_seen_reporter,
                                 updated=excluded.updated""",
                (clan_tag, player_tag, value, reported_by, now),
            )


def score_and_categorize(ranking: list[dict], weights: dict[str, float],
                         prefs: dict[str, dict], mode: str = "war",
                         now: datetime | None = None, size: int = 15) -> dict:
    """Fully deterministic. No last-online inference. No automated moderation."""
    if mode not in {"war", "cwl"}:
        raise ValueError("mode must be war or cwl")
    now = now or utc_now()
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    groups = {"main": [], "bench": [], "inactive": [], "optout": [], "needs_review": [],
              "kick": [], "promotion": [], "bonus": []}
    full = []
    for original in ranking:
        m = dict(original)
        tag = m.get("tag")
        meta = prefs.get(tag) or {}
        hist = m.get("history") or {}
        wars = int(hist.get("wars") or 0)
        used = int(hist.get("attacksUsed") or 0)
        possible = int(hist.get("attacksPossible") or 0)
        misses = int(hist.get("missedAttacks") or 0)
        combat = max(0., min(100., float(m.get("combatReadiness") or 0)))
        reliability = (100.0 * used / possible if possible else None)
        stars = hist.get("averageStars")
        performance = (min(100., max(0., float(stars) * 100 / 3))
                       if stars is not None and used else None)
        api_preference = m.get("warPreference", "unknown")
        cwl_preference = meta.get("cwlPreference", "unknown")
        # Only game-level preference is used for regular wars. Telegram self-service
        # opt-in for CWL is deliberately independent of the official war switch.
        mode_preference = api_preference if mode == "war" else cwl_preference
        participation = 100. if mode_preference == "in" else 0. if mode_preference == "out" else None
        manual_last_seen = parse_utc(meta.get("lastSeenManual"))
        hours_idle = max(0, (now - manual_last_seen).total_seconds() / 3600) if manual_last_seen else None
        activity = 0. if hours_idle is not None and hours_idle > 48 else 100. if hours_idle is not None else None
        signals = {"combat": combat, "reliability": reliability, "performance": performance,
                   "participation": participation, "activity": activity}
        supplied = {k: v for k, v in signals.items() if v is not None}
        denominator = sum(weights.get(k, 0) for k in supplied)
        score = round(sum(weights[k] * value for k, value in supplied.items()) / denominator, 1) if denominator else None
        m.update({"selectionScore": score, "scoreComponents": signals, "scoreWeights": dict(weights),
                  "cwlPreference": cwl_preference, "lastSeenManual": meta.get("lastSeenManual"),
                  "lastSeenHoursAgo": round(hours_idle, 1) if hours_idle is not None else None,
                  "lastSeenSource": "reported_by_leadership" if manual_last_seen else "unavailable",
                  "confidence": "high" if wars >= 5 and hours_idle is not None else
                                "medium" if wars >= 3 else "low",
                  "eligibility": "candidate", "reasons": []})
        if mode_preference == "out":
            m["eligibility"] = "optout"
            m["reasons"].append("Отказ от участия в игре" if mode == "war" else "Отказ от CWL в Telegram")
        elif hours_idle is not None and hours_idle > 48:
            m["eligibility"] = "inactive"
            m["reasons"].append("По ручной отметке капитана не заходил более 48 часов")
        elif mode == "cwl" and cwl_preference == "unknown":
            m["eligibility"] = "needs_review"
            m["reasons"].append("Не указано согласие на CWL в Telegram")
        elif mode == "war" and api_preference not in {"in", "out"}:
            m["eligibility"] = "needs_review"
            m["reasons"].append("Неизвестен статус участия в КВ")
        if hours_idle is None:
            m["reasons"].append("Последний вход неизвестен: публичный API его не сообщает")
        if wars < 3:
            m["reasons"].append("Мало исторических войн для надёжной оценки")
        # Moderation suggestions require multiple independent signals; never kick
        # someone merely for a low TH, explicit opt-out or 2 days without activity.
        missed_ratio = misses / possible if possible else 0
        if (api_preference == "in" and wars >= 4 and misses >= 3
                and missed_ratio >= 0.4 and (hours_idle is not None and hours_idle >= 7 * 24)):
            groups["kick"].append(m)
            m["reasons"].append("Для рассмотрения руководством: пропуски атак и подтверждённая длительная неактивность")
        if (wars >= 5 and reliability is not None and reliability >= 95 and
                performance is not None and performance >= 75 and
                int(hist.get("threeStarsEqualOrHigher") or 0) >= 3):
            groups["promotion"].append(m)
        cwl_wars = int(m.get("cwlWars") or 0)
        cwl_stars = m.get("cwlAverageStars")
        if (cwl_wars >= 3 and m.get("cwlMissedAttacks", 1) == 0 and
                cwl_stars is not None and float(cwl_stars) >= 2.5):
            groups["bonus"].append(m)
        full.append(m)
    eligible = sorted((m for m in full if m["eligibility"] == "candidate"),
                      key=lambda m: (-(m["selectionScore"] if m["selectionScore"] is not None else -1),
                                     -int(m.get("townHallLevel") or 0),str(m.get("name") or "")))
    groups["main"] = eligible[:max(0, size)]
    groups["bench"] = eligible[max(0, size):]
    for m in full:
        if m["eligibility"] in {"inactive","optout","needs_review"}:
            groups[m["eligibility"]].append(m)
    # Weakest evidence-backed cases first; do not sort by base TH alone.
    groups["kick"].sort(key=lambda m: (m["selectionScore"] if m["selectionScore"] is not None else 101))
    groups["promotion"].sort(key=lambda m: -(m["selectionScore"] or 0))
    groups["bonus"].sort(key=lambda m: -(m["cwlAverageStars"] or 0))
    return {"mode": mode, "weights": weights, "categories": groups,
            "recommendedLineup": groups["main"] + groups["bench"] +
                                 groups["inactive"] + groups["optout"] + groups["needs_review"],
            "recommendedSize": min(size, len(groups["main"])), "allPlayers": full,
            "selectionNote": "Время входа вручную из игры; отсутствие изменений API ≠ отсутствие в сети. Рекомендации не выполняют кик."}
