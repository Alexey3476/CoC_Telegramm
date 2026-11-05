"""Keyboard and nickname suggestions for CoC player selection."""
from __future__ import annotations

from difflib import SequenceMatcher
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from app.ui import normalize_name


def sorted_roster(members: list[dict], telegram_name: str, telegram_username: str = "") -> list[dict]:
    aliases = [normalize_name(telegram_name), normalize_name(telegram_username)]
    def similarity(member: dict) -> float:
        target = normalize_name(member.get("name", ""))
        return max((SequenceMatcher(None, target, alias).ratio() for alias in aliases if alias and target), default=0)
    return sorted((m for m in members if m.get("tag")), key=lambda m: (-similarity(m), str(m.get("name", "")).casefold()))


def roster_keyboard(members: list[dict], page: int = 0) -> InlineKeyboardMarkup:
    page = max(0, min(page, max(0, (len(members) - 1) // 8)))
    rows = []
    for idx in range(page * 8, min((page + 1) * 8, len(members))):
        member = members[idx]
        rows.append([InlineKeyboardButton(
            f"{str(member.get('name') or '?')[:20]} · TH{member.get('townHallLevel') or '?'}",
            callback_data=f"pick:player:{idx}",
        )])
    nav = []
    if page:
        nav.append(InlineKeyboardButton("◀", callback_data=f"pick:page:{page - 1}"))
    if (page + 1) * 8 < len(members):
        nav.append(InlineKeyboardButton("▶", callback_data=f"pick:page:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("✍️ Ввести тег", callback_data="pick:manual:0")])
    rows.append([InlineKeyboardButton("Отмена", callback_data="bind_cancel")])
    return InlineKeyboardMarkup(rows)
