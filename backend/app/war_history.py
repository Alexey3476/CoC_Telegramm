"""Persist CoC war snapshots and calculate per-player attack records."""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class WarHistory:
    def __init__(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS wars (
                id TEXT PRIMARY KEY,
                started TEXT NOT NULL,
                state TEXT NOT NULL,
                captured TEXT NOT NULL,
                payload TEXT NOT NULL
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS wars_state_start ON wars(state, started)")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def save(self, war: dict[str, Any]) -> bool:
        state = war.get("state")
        if state not in {"preparation", "inWar", "warEnded"}:
            return False
        clan = war.get("clan") or {}
        enemy = war.get("opponent") or {}
        started = war.get("startTime") or war.get("endTime")
        if not started or not clan.get("tag") or not enemy.get("tag"):
            return False
        identifier = "|".join((str(started), *sorted((clan["tag"], enemy["tag"]))))
        captured = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO wars (id, started, state, captured, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                state=excluded.state, captured=excluded.captured, payload=excluded.payload""",
                (identifier, str(started), state, captured, json.dumps(war)),
            )
        return True

    def completed(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM wars WHERE state = 'warEnded' ORDER BY started DESC LIMIT ?",
                (max(1, min(100, limit)),),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]


def summarize_wars(wars: list[dict[str, Any]], clan_tag: str) -> dict[str, dict[str, Any]]:
    """Use completed wars only; discount easy down-hits, count missed attacks."""
    results: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "wars": 0, "attacksUsed": 0, "attacksPossible": 0, "missedAttacks": 0,
        "stars": 0, "skillWeightedStars": 0.0,
        "threeStarsEqualOrHigher": 0, "threeStarsDownhill": 0, "threeStarsUnknownTarget": 0,
    })
    for war in wars:
        if war.get("state") != "warEnded":
            continue
        sides = [war.get("clan") or {}, war.get("opponent") or {}]
        matching = [i for i, side in enumerate(sides) if side.get("tag") == clan_tag]
        if not matching:
            continue
        our = sides[matching[0]]
        enemy = sides[1 - matching[0]]
        enemy_town_halls = {
            p["tag"]: p.get("townhallLevel", p.get("townHallLevel", 0))
            for p in enemy.get("members", []) if p.get("tag")
        }
        allowed = int(war.get("attacksPerMember") or 1)
        for member in our.get("members", []):
            tag = member.get("tag")
            if not tag:
                continue
            record = results[tag]
            attacks = member.get("attacks") or []
            if not isinstance(attacks, list):
                attacks = []
            used = min(len(attacks), allowed)
            record["wars"] += 1
            record["attacksUsed"] += used
            record["attacksPossible"] += allowed
            record["missedAttacks"] += max(0, allowed - used)
            attacker_th = int(member.get("townhallLevel", member.get("townHallLevel", 0)))
            for attack in attacks[:allowed]:
                stars = min(3, max(0, int(attack.get("stars", 0))))
                record["stars"] += stars
                defender_th = enemy_town_halls.get(attack.get("defenderTag"))
                downhit = bool(defender_th and attacker_th and defender_th < attacker_th)
                known = defender_th is not None and attacker_th > 0 and defender_th > 0
                record["skillWeightedStars"] += stars * (0.7 if downhit else 1.0 if known else 0.85)
                if stars == 3:
                    key = ("threeStarsUnknownTarget" if not known else
                           "threeStarsDownhill" if downhit else "threeStarsEqualOrHigher")
                    record[key] += 1
    for record in results.values():
        possible, used = record["attacksPossible"], record["attacksUsed"]
        record["reliabilityPct"] = round(100 * used / possible, 1) if possible else None
        record["averageStars"] = round(record["stars"] / used, 2) if used else None
        record["warReadiness"] = round(
            65 * used / possible + 35 * record["skillWeightedStars"] / (3 * used), 1
        ) if used and possible else (0.0 if possible else None)
    return dict(results)



def completed_for_clan(wars: list[dict[str, Any]], clan_tag: str) -> list[dict[str, Any]]:
    """Only completed wars involving our clan, always our side in 'clan'."""
    valid = []
    for war in wars:
        if war.get("state") != "warEnded":
            continue
        home, away = war.get("clan") or {}, war.get("opponent") or {}
        if home.get("tag") == clan_tag:
            valid.append(war)
        elif away.get("tag") == clan_tag:
            valid.append({**war, "clan": away, "opponent": home})
    return valid
