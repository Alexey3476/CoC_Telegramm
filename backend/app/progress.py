"""SQLite history for observable player development, without invented upgrade timers."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ("townHallLevel", "expLevel", "bestTrophies", "warStars", "clanCapitalContributions")


def compact_profile(profile: dict) -> dict:
    payload = {key: profile[key] for key in FIELDS if isinstance(profile.get(key), (int, float))}
    for field in ("heroes", "heroEquipment"):
        payload[field] = {
            str(item["name"]): int(item["level"])
            for item in profile.get(field) or []
            if isinstance(item, dict) and item.get("name") and isinstance(item.get("level"), int)
        }
    return payload


def compare(before: dict | None, after: dict) -> dict:
    if before is None:
        return {"historyAvailable": False, "changes": {}}
    changes = {}
    for field in FIELDS:
        old, new = before.get(field), after.get(field)
        if isinstance(old, (int, float)) and isinstance(new, (int, float)) and old != new:
            changes[field] = {"from": old, "to": new, "delta": new - old}
    for field in ("heroes", "heroEquipment"):
        a, b = before.get(field) or {}, after.get(field) or {}
        changed = {name: {"from": a[name], "to": value, "delta": value - a[name]}
                   for name, value in b.items() if name in a and value != a[name]}
        if changed:
            changes[field] = changed
    return {"historyAvailable": True, "changes": changes}


class ProgressStore:
    """One snapshot per player/day, persisted under HA Supervisor /data."""

    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS player_snapshots(
                tag TEXT NOT NULL, day TEXT NOT NULL,
                captured TEXT NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY(tag, day)
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_player_snapshots_tag_day ON player_snapshots(tag,day)")

    def record(self, profile: dict, now: datetime | None = None) -> dict:
        tag = profile.get("tag")
        if not isinstance(tag, str) or not tag.startswith("#"):
            raise ValueError("Verified game tag required")
        now = now or datetime.now(timezone.utc)
        day = now.date().isoformat()
        current = compact_profile(profile)
        with sqlite3.connect(self.path, timeout=10) as conn:
            baseline = conn.execute(
                "SELECT day,data FROM player_snapshots WHERE tag=? AND day<? ORDER BY day DESC LIMIT 1",
                (tag, day),
            ).fetchone()
            conn.execute("""INSERT INTO player_snapshots(tag,day,captured,data) VALUES(?,?,?,?)
            ON CONFLICT(tag,day) DO UPDATE SET captured=excluded.captured,data=excluded.data""",
            (tag, day, now.isoformat(), json.dumps(current)))
        result = compare(json.loads(baseline[1]) if baseline else None, current)
        return {"tag": tag, "name": profile.get("name"), "snapshotDay": day,
                "comparisonDay": baseline[0] if baseline else None, **result}
