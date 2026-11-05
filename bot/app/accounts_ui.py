"""Private-account Telegram controls, keeping CoC verification separate."""
from __future__ import annotations

import html
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.bindings_storage import Binding

CWL_LABELS = {"in": "✅ Участвую", "out": "🚫 Не участвую", "unknown": "❔ Не указано"}
WAR_LABELS = {"in": "✅ Да", "out": "🚫 Нет", "unknown": "❔ Нет данных"}


def accounts_text(accounts: list[Binding], war_preferences: dict[str, str] | None = None) -> str:
    war_preferences = war_preferences or {}
    rows = [
        "👥 <b>Мои игровые аккаунты</b>",
        f"Привязано: <b>{len(accounts)}</b>",
        "",
    ]
    for b in accounts:
        main = " ⭐ основной" if b.is_primary else " (твинк)"
        rows.extend([
            f"• <code>{html.escape(b.coc_player_tag)}</code>{main}",
            f"  КВ (из Clash): {WAR_LABELS.get(war_preferences.get(b.coc_player_tag, 'unknown'), '❔ Нет данных')}",
            f"  ЛВК (выбор в боте): {CWL_LABELS.get(b.cwl_opt_in, CWL_LABELS['unknown'])}",
        ])
    if not accounts:
        rows.append("Пока нет привязанных аккаунтов.")
    rows.extend([
        "",
        "КВ: статус читается из профиля CoC, изменить его нужно в игре.",
        "ЛВК: отдельная заявка внутри этого бота. Это не настройка Supercell.",
        "Владение аккаунтом проверяется игровым токеном, не совпадением ников.",
    ])
    return "\n".join(rows)


def accounts_keyboard(accounts: list[Binding]) -> InlineKeyboardMarkup:
    rows = []
    for b in accounts[:15]:
        tag = b.coc_player_tag
        label = ("⭐ " if b.is_primary else "🎮 ") + tag
        rows.append([
            InlineKeyboardButton(label, callback_data=f"acct:primary:{tag}"),
            InlineKeyboardButton(f"ЛВК: {b.cwl_opt_in}", callback_data=f"acct:cwl:{tag}"),
            InlineKeyboardButton("🗑", callback_data=f"acct:delete:{tag}"),
        ])
    rows.append([InlineKeyboardButton("➕ Добавить аккаунт", callback_data="bind_start")])
    rows.append([InlineKeyboardButton("🏠 Штаб", callback_data="menu_home")])
    return InlineKeyboardMarkup(rows)


def delete_confirmation(tag: str, *, admin: bool = False) -> InlineKeyboardMarkup:
    prefix = "admin" if admin else "acct"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Да, удалить привязку", callback_data=f"{prefix}:confirm:{tag}")],
        [InlineKeyboardButton("↩ Отмена", callback_data=f"{prefix}:cancel:0")],
    ])
