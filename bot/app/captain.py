"""Leadership access follows verified game ownership plus current CoC roster role."""
from __future__ import annotations

import html

CAPTAIN_ROLES = frozenset({"leader", "coLeader"})


def is_captain(members: list[dict], tag: str) -> bool:
    tag = (tag or "").strip().upper()
    return any(
        str(m.get("tag", "")).upper() == tag and m.get("role") in CAPTAIN_ROLES
        for m in members
    )


def captain_report_text(data: dict) -> str:
    clan = html.escape(str(data.get("clanName") or "Клан"))
    war = data.get("war") or {}
    members = data.get("members") or {}
    rows = [f"📋 <b>Капитанский отчёт · {clan}</b>",
            f"Участников: {members.get('total', '?')}",
            f"Кубков в среднем: {members.get('avgTrophies', '?')}",
            f"Атак сейчас: {war.get('attacksDone', '?')} · осталось {war.get('attacksRemaining', '?')}",
            "", "<b>Пожертвования:</b>"]
    active = (data.get("activity") or {}).get("mostActive") or []
    for idx, player in enumerate(active[:5], 1):
        rows.append(f"{idx}. {html.escape(str(player.get('name') or '?'))}: {player.get('donations', 0)}")
    rows.append("\n⚠️ Отсутствие доната не доказывает, что игрок неактивен.")
    return "\n".join(rows)
