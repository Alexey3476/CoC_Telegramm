"""Single private CoC player profile for all verified accounts and alt accounts."""
from __future__ import annotations

import html
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

ROLE_NAMES = {"leader": "Глава", "coLeader": "Соруководитель",
              "admin": "Старейшина", "member": "Участник"}
ROLE_RANKS = {"leader": 4, "coLeader": 3, "admin": 2, "member": 1}


def highest_role(profiles: list[dict]) -> str:
    return max((str(p.get("role") or "member") for p in profiles),
               key=lambda role: ROLE_RANKS.get(role, 0), default="member")


def profile_text(profiles: list[dict], primary_tag: str | None) -> str:
    role = highest_role(profiles)
    lines = ["👤 <b>Мой профиль · CoC</b>",
             f"🛡️ Максимальное звание: <b>{ROLE_NAMES.get(role, 'Участник')}</b>",
             f"🎮 Подтверждено аккаунтов: <b>{len(profiles)}</b>", ""]
    for i, p in enumerate(profiles, 1):
        title = html.escape(str(p.get("name") or p.get("tag") or "?")[:45])
        mark = "⭐" if p.get("tag") == primary_tag else "▫️"
        role_name = ROLE_NAMES.get(p.get("role"), "Участник")
        pref = {"in": "🟢", "out": "🔴"}.get(p.get("warPreference"), "❔")
        league = html.escape(str(p.get("leagueName") or "Неизвестно")[:38])
        lines += [
            f"{mark} <b>{i}. {title}</b> · TH{p.get('townHallLevel') or '?'}",
            f"   Ур. {p.get('expLevel') or '?'} · {role_name} · {league} · КВ/ЛВК: {pref}",
            f"   🏆 {p.get('trophies','?')} · 🎁 Донат {p.get('donations','?')} · "
            f"⭐ Войны {p.get('warStars','?')}",
        ]
    lines += ["", "Выбери ник ниже для подробной статистики, развития или управления привязкой.",
              "Права главы/соруководителя действуют по любому подтверждённому твинку."]
    return "\n".join(lines)


def profile_keyboard(profiles: list[dict]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"🎮 {str(p.get('name') or p.get('tag') or '?')[:26]} · TH{p.get('townHallLevel') or '?'}",
                                  callback_data=f"acct:view:{i}")]
            for i,p in enumerate(profiles[:20])]
    rows.extend([
        [InlineKeyboardButton("📈 Развитие аккаунтов", callback_data="acct:progress:0")],
        [InlineKeyboardButton("➕ Добавить аккаунт", callback_data="bind_start")],
        [InlineKeyboardButton("🏠 Штаб", callback_data="menu_home")],
    ])
    return InlineKeyboardMarkup(rows)


def detail_text(profile: dict, is_primary: bool = False) -> str:
    name = html.escape(str(profile.get("name") or "?")[:55])
    league = html.escape(str(profile.get("leagueName") or "?")[:48])
    role = ROLE_NAMES.get(profile.get("role"), "Участник")
    pref = {"in": "🟢 Участвую", "out": "🔴 Отказался"}.get(profile.get("warPreference"), "❔ Неизвестно")
    heroes = profile.get("heroes") or []
    equipment = profile.get("heroEquipment") or []
    lines = [
        f"👤 <b>{name}</b>{' · ⭐ основной' if is_primary else ''}",
        f"Тег: <code>{html.escape(str(profile.get('tag') or ''))}</code>",
        f"🏰 TH{profile.get('townHallLevel','?')} · 🛡️ {role}",
        f"📊 Уровень опыта: {profile.get('expLevel') or 'нет данных'}",
        f"🏆 {league} · {profile.get('trophies','?')} кубков",
        f"🎮 Участие КВ/ЛВК: {pref}",
        f"🎁 Донат: {profile.get('donations','?')} · Получено: {profile.get('donationsReceived','?')}",
        f"⚔️ Военные звёзды за всё время: {profile.get('warStars','?')}",
        f"📊 Победы атак: {profile.get('attackWins','?')}",
        "",
        "<b>Герои</b>",
    ]
    for hero in heroes[:8]:
        lines.append(f"• {html.escape(str(hero.get('name') or '?')[:35])}: ур. {hero.get('level','?')}")
    if not heroes:
        lines.append("Нет данных")
    lines.append("\n<b>Снаряжение</b>")
    for item in equipment[:8]:
        lines.append(f"• {html.escape(str(item.get('name') or '?')[:35])}: ур. {item.get('level','?')}")
    if not equipment:
        lines.append("Нет данных")
    return "\n".join(lines)[:3700]


def detail_keyboard(index: int, is_primary: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📈 Развитие", callback_data=f"acct:progress:{index}")],
    ]
    if not is_primary:
        rows.append([InlineKeyboardButton("⭐ Сделать основным", callback_data=f"acct:primary:{index}")])
    rows += [
        [InlineKeyboardButton("🗑 Удалить привязку", callback_data=f"acct:delete:{index}")],
        [InlineKeyboardButton("◀ Мои аккаунты", callback_data="acct:list:0")],
    ]
    return InlineKeyboardMarkup(rows)


def delete_keyboard(index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Удалить только эту привязку", callback_data=f"acct:confirm:{index}")],
        [InlineKeyboardButton("Отмена", callback_data=f"acct:view:{index}")],
    ])


def progress_keyboard(profiles: list[dict], selected: int, days: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(("✓ " if i == selected else "") +
                                  str(p.get("name") or p.get("tag") or "?")[:22],
                                  callback_data=f"acct:progress:{i}")]
            for i,p in enumerate(profiles[:20])]
    rows.append([
        InlineKeyboardButton("7 дней" + (" ✓" if days == 7 else ""), callback_data="growth:days:7"),
        InlineKeyboardButton("30 дней" + (" ✓" if days == 30 else ""), callback_data="growth:days:30"),
        InlineKeyboardButton("Всё" + (" ✓" if days == 0 else ""), callback_data="growth:days:0"),
    ])
    rows.append([InlineKeyboardButton("◀ Профиль", callback_data=f"acct:view:{selected}"),
                 InlineKeyboardButton("🏠 Штаб", callback_data="menu_home")])
    return InlineKeyboardMarkup(rows)


def progress_text(data: dict, name: str, days: int) -> str:
    period = "вся история" if days == 0 else f"{days} дней"
    lines = [f"📈 <b>Развитие {html.escape(str(name)[:50])}</b>",
             f"Период: {period} · Последний снимок: {data.get('snapshotDay') or '?'}"]
    if not data.get("historyAvailable"):
        lines.append("Пока только один календарный день наблюдений. Сравнение появится после второго.")
    else:
        lines.append(f"Сравнение с {data.get('comparisonDay')}:")
        translations = {"townHallLevel": "Ратуша", "expLevel": "Уровень опыта",
                        "bestTrophies": "Рекорд кубков", "warStars": "Звёзды КВ",
                        "clanCapitalContributions": "Вклад столицы",
                        "attackWins": "Победы атак", "donations": "Донат за сезон"}
        changes = data.get("changes") or {}
        for key,label in translations.items():
            if key in changes:
                item = changes[key]
                if key == "donations" and item["delta"] < 0:
                    lines.append("• Донат: сезонный сброс счётчика, не ухудшение прогресса")
                else:
                    lines.append(f"• {label}: {item['from']} → {item['to']} ({item['delta']:+g})")
        for key,label in (("heroes","Герои"),("heroEquipment","Снаряжение")):
            for hero, change in changes.get(key, {}).items():
                lines.append(f"• {label}: {html.escape(str(hero)[:35])} {change['from']} → {change['to']}")
        if not changes:
            lines.append("Изменений за выбранный период не обнаружено.")
    lines.append(f"\nВ базе снимков: {data.get('snapshotCount', '?')}. "
                 "CoC API не передаёт таймеры улучшений и полноценные уровни зданий.")
    return "\n".join(lines)[:3750]
