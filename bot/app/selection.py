"""Transparent, conservative war lineup analysis with no fabricated last-online data.

The public CoC API does NOT expose a last login timestamp. Any last-seen value
here is a captain's manual observation from the game's interface. A lack of
observed changes is NOT evidence of two days offline.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.bindings_storage import Binding, BindingsStorage

WEIGHT_FIELDS = ("strength", "attendance", "attack", "preference")
SUPPORTED_MODES = ("war", "cwl")


@dataclass(frozen=True)
class SelectionPolicy:
    strength: int = 35
    attendance: int = 30
    attack: int = 25
    preference: int = 10
    inactive_after_hours: int = 48
    max_accounts_per_owner: int = 1
    min_kick_wars: int = 3
    min_kick_missed_attacks: int = 3
    min_promotion_wars: int = 5
    min_cwl_bonus_wars: int = 3

    def __post_init__(self):
        if any(getattr(self, field) < 0 for field in WEIGHT_FIELDS):
            raise ValueError("Weights must be non-negative")
        if sum(getattr(self, field) for field in WEIGHT_FIELDS) != 100:
            raise ValueError("The four score weights must sum to 100")
        if not 1 <= self.max_accounts_per_owner <= 5:
            raise ValueError("Invalid max accounts per owner")
        if self.inactive_after_hours < 24:
            raise ValueError("Inactivity threshold must be >=24 hours")

    def as_dict(self) -> dict:
        return {field: getattr(self, field) for field in WEIGHT_FIELDS}


def policy_from_settings(settings: Any) -> SelectionPolicy:
    return SelectionPolicy(
        strength=settings.score_weight_strength,
        attendance=settings.score_weight_attendance,
        attack=settings.score_weight_attack,
        preference=settings.score_weight_preference,
        inactive_after_hours=settings.inactive_after_hours,
        max_accounts_per_owner=settings.max_accounts_per_owner,
        min_kick_wars=settings.min_kick_wars,
        min_kick_missed_attacks=settings.min_kick_missed_attacks,
        min_promotion_wars=settings.min_promotion_wars,
        min_cwl_bonus_wars=settings.min_cwl_bonus_wars,
    )


def account_activity_hours(binding: Binding | None, now: datetime) -> float | None:
    if not binding or not binding.last_seen_manual:
        return None
    try:
        observed = datetime.fromisoformat(binding.last_seen_manual.replace("Z", "+00:00"))
        if observed.tzinfo is None:
            return None
        return max(0.0, (now - observed.astimezone(timezone.utc)).total_seconds() / 3600)
    except (ValueError, TypeError):
        return None


def _preference(player: dict, binding: Binding | None, mode: str) -> str:
    if mode == "war":
        status = player.get("warPreference")
    else:
        status = binding.cwl_opt_in if binding else None
    return status if status in {"in", "out"} else "unknown"


def _score(player: dict, status: str, policy: SelectionPolicy) -> tuple[float, list[str], dict]:
    evidence = []
    strength = max(0.0, min(100.0, float(player.get("combatReadiness") or 0)))
    history = player.get("history") or {}
    war_count = int(history.get("wars") or 0)
    record = {
        "strength": round(strength, 1),
        "attendance": None,
        "attack": None,
        "preference": 100.0 if status == "in" else 0.0 if status == "out" else None,
    }
    if war_count:
        if isinstance(history.get("reliabilityPct"), (int, float)):
            record["attendance"] = max(0.0, min(100.0, float(history["reliabilityPct"])))
        if isinstance(history.get("averageStars"), (int, float)):
            record["attack"] = max(0.0, min(100.0, float(history["averageStars"]) / 3 * 100))
    if not war_count:
        evidence.append("Нет сохранённых завершённых войн")
    elif war_count < 3:
        evidence.append(f"Только {war_count} наблюдаемых войн")
    if status == "unknown":
        evidence.append("Неизвестна заявка на этот тип войны")
    known = sum(getattr(policy, field) for field in WEIGHT_FIELDS if record[field] is not None)
    score = sum(getattr(policy, field) * (record[field] or 0) for field in WEIGHT_FIELDS
                if record[field] is not None) / known if known else 0.0
    coverage = round(known, 1)
    return round(score, 1), evidence, {"components": record, "evidenceWeightPct": coverage}


def _kick_evidence(player: dict, policy: SelectionPolicy, preference: str, activity: float | None) -> list[str]:
    """Review only. No automatic kick; never call no API change 'not logged in'."""
    history = player.get("history") or {}
    wars = int(history.get("wars") or 0)
    missed = int(history.get("missedAttacks") or 0)
    reliable = history.get("reliabilityPct")
    reasons = []
    if (preference == "in" and wars >= policy.min_kick_wars
            and missed >= policy.min_kick_missed_attacks
            and isinstance(reliable, (int, float)) and reliable < 75):
        reasons.append(f"{missed} пропущенных атак за {wars} наблюдаемых войн при заявке «за»")
    if activity is not None and activity >= 7 * 24 and missed >= 2 and wars >= policy.min_kick_wars:
        reasons.append("Руководитель отметил отсутствие более недели; есть пропущенные атаки")
    # Being lower TH alone is never a kick criterion.
    return reasons


def build_selection(
    data: dict, storage: BindingsStorage, group_id: int, mode: str,
    policy: SelectionPolicy, now: datetime | None = None,
) -> dict:
    if mode not in SUPPORTED_MODES:
        raise ValueError("Unknown selection mode")
    now = now or datetime.now(timezone.utc)
    bindings = {binding.coc_player_tag: binding for binding in storage.get_bindings_for_group(group_id)}
    population = []
    for raw in data.get("recommendedLineup") or []:
        player = dict(raw)
        tag = player.get("tag")
        binding = bindings.get(tag)
        owner = binding.telegram_user_id if binding else None
        status = _preference(player, binding, mode)
        inactive_hours = account_activity_hours(binding, now)
        score, warnings, detail = _score(player, status, policy)
        player.update(
            selectionScore=score, scoreBreakdown=detail,
            selectionMode=mode, selectionPreference=status,
            manualLastSeen=binding.last_seen_manual if binding else None,
            lastSeenSource="manual" if inactive_hours is not None else "unknown",
            manuallyInactiveHours=round(inactive_hours, 1) if inactive_hours is not None else None,
            ownerId=owner, isPrimary=bool(binding.is_primary) if binding else None,
            cwlPreference=binding.cwl_opt_in if binding else "unknown",
            warnings=warnings,
        )
        player["kickReasons"] = _kick_evidence(player, policy, status, inactive_hours)
        population.append(player)
    # Rank only by available data, preserving preference logic in separate buckets.
    population.sort(key=lambda p: (-p["selectionScore"], -(p.get("townHallLevel") or 0), str(p.get("tag"))))
    groups = {key: [] for key in (
        "lineup", "reserve", "inactive", "optedOut", "twinks", "needConfirmation",
        "kickCandidates", "promotionCandidates", "bonusCandidates",
    )}
    counts = {}
    size = max(1, min(50, int(data.get("recommendedSize") or 15)))
    for player in population:
        status, hours, owner = player["selectionPreference"], player["manuallyInactiveHours"], player["ownerId"]
        if player["kickReasons"]:
            groups["kickCandidates"].append(player)
        hist = player.get("history") or {}
        wars = int(hist.get("wars") or 0)
        reliability = hist.get("reliabilityPct")
        average = hist.get("averageStars")
        if (wars >= policy.min_promotion_wars and isinstance(reliability, (int, float))
                and reliability >= 95 and isinstance(average, (int, float)) and average >= 2.4
                and int(hist.get("missedAttacks") or 0) == 0
                and status == "in" and (hours is None or hours < policy.inactive_after_hours)):
            groups["promotionCandidates"].append(player)
        cwl_hist = player.get("cwlHistory") or {}
        if (int(cwl_hist.get("wars") or 0) >= policy.min_cwl_bonus_wars
                and (cwl_hist.get("reliabilityPct") or 0) >= 95
                and (cwl_hist.get("averageStars") or 0) >= 2.4):
            groups["bonusCandidates"].append(player)
        if status == "out":
            groups["optedOut"].append(player)
        elif hours is not None and hours >= policy.inactive_after_hours:
            groups["inactive"].append(player)
        elif owner is not None and counts.get(owner, 0) >= policy.max_accounts_per_owner:
            groups["twinks"].append(player)
        elif len(groups["lineup"]) >= size:
            groups["reserve"].append(player)
        elif status == "unknown":
            groups["needConfirmation"].append(player)
            # No confirmed consent: keep separate until confirmation rather than silently count as a yes.
        else:
            groups["lineup"].append(player)
            if owner is not None:
                counts[owner] = counts.get(owner, 0) + 1
    # Confirmed candidate pool may be smaller than nominal roster size.
    result = dict(data)
    result["recommendedLineup"] = population
    result["categories"] = groups
    result["selectionMode"] = mode
    result["weightTable"] = policy.as_dict()
    result["reservedSlots"] = max(0, size - len(groups["lineup"]))
    result["selectionNotes"] = [
        "Telegram аккаунт может иметь несколько игровых привязок; ограничение на владельца действует только на основной состав.",
        "Время последнего входа недоступно в CoC API; 48 ч проверяются только по ручному подтверждению руководителя.",
        "Кандидаты на кик/повышение/бонусы только на рассмотрение, без автоматических действий.",
        "Бонусы CWL оцениваются только по сохранённым CWL войнам; API не показывает реальное распределение бонусов.",
    ]
    return result
