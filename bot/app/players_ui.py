"""CoC clan player directory and season donation board."""
from __future__ import annotations

import html
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def roster_page(roster: list[dict], page: int = 0, per_page: int = 8) -> str:
    page = max(0, min(page, (len(roster) - 1)//per_page if roster else 0))
    lines = [f"👥 <b>Игроки клана · {len(roster)}</b>",
             f"Страница {page + 1}/{max(1, (len(roster) + per_page - 1)//per_page)}", ""]
    for i in range(page * per_page, min((page+1) * per_page, len(roster))):
        m = roster[i]
        role = {"leader":"👑", "coLeader":"🛡️", "admin":"⭐"}.get(m.get("role"), "👤")
        lines.append(f"{i+1}. {role} <b>{html.escape(str(m.get('name') or '?')[:36])}</b> "
                     f"· TH{m.get('townHallLevel') or '?'} · 🎁 {m.get('donations',0)}")
    lines += ["", "Нажми ник ниже для подробной статистики."]
    return "\n".join(lines)


def roster_keyboard(roster: list[dict], page: int = 0, per_page: int = 8) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(str(roster[i].get("name") or "?")[:29],
                                  callback_data=f"players:view:{i}")]
            for i in range(page * per_page, min((page+1)*per_page,len(roster)))]
    nav = []
    if page:
        nav.append(InlineKeyboardButton("◀", callback_data=f"players:page:{page-1}"))
    if (page+1)*per_page < len(roster):
        nav.append(InlineKeyboardButton("▶", callback_data=f"players:page:{page+1}"))
    if nav:
        rows.append(nav)
    rows.extend([
        [InlineKeyboardButton("🎁 Донат", callback_data="players:donate:0"),
         InlineKeyboardButton("🏆 Зал славы", callback_data="players:hall:0")],
        [InlineKeyboardButton("🏠 Штаб", callback_data="menu_home")],
    ])
    return InlineKeyboardMarkup(rows)


def donation_text(members: list[dict]) -> str:
    donors = sorted(members, key=lambda m: (-int(m.get("donations") or 0),
                                            str(m.get("name") or "").lower()))
    lines = ["🎁 <b>Топ доната · текущий сезон</b>", ""]
    for i, m in enumerate(donors[:20],1):
        lines.append(f"{i}. <b>{html.escape(str(m.get('name') or '?')[:32])}</b>"
                     f" · {int(m.get('donations') or 0)} войск")
    lines.append("\nСчётчик сбрасывается каждый сезон. Низкий донат не доказывает неактивность.")
    return "\n".join(lines)


def hall_text(data: dict) -> str:
    lines = ["🏆 <b>Зал славы клана</b>",
             "Раздельные рейтинги по измеряемым данным, не общий балл всех времён.", ""]
    sections = [
        ("🎁 Донат · сезон", "donations", "донат"),
        ("⭐ Качество атак · КВ и ЛВК", "war", "индекс"),
        ("🏛️ Рейды · последний доступный рейд", "raids", "золото"),
        ("📈 На повышение · вклад в клан", "promotion", "индекс"),
    ]
    for title,key,unit in sections:
        lines.append(f"<b>{title}</b>")
        people = data.get(key) or []
        if not people:
            lines.append("История пока недостаточна.")
        for i,m in enumerate(people[:5],1):
            lines.append(f"{i}. {html.escape(str(m.get('name') or '?')[:35])}"
                         f" · {m.get('score','?')} {unit}")
        lines.append("")
    lines.append("🎮 Игры кланов: очки игроков не передаются публичным API, в рейтинг не включены.")
    return "\n".join(lines)


def back_to_roster(page: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀ К игрокам", callback_data=f"players:page:{page}")],
        [InlineKeyboardButton("🎁 Донат", callback_data="players:donate:0"),
         InlineKeyboardButton("🏆 Зал славы", callback_data="players:hall:0")],
        [InlineKeyboardButton("🏠 Штаб", callback_data="menu_home")],
    ])


def ranking_page(data: dict, mode: str = "war", page: int = 0, per_page: int = 10) -> str:
    """All clan players by calculated KV/CWL selection score, not trophy count."""
    players = sorted(
        data.get("allPlayers") or data.get("recommendedLineup") or [],
        key=lambda m: (-float(m.get("selectionScore") or 0),
                       -int(m.get("townHallLevel") or 0), str(m.get("name") or "")),
    )
    pages = max(1, (len(players) + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    lines = [
        f"🏆 <b>Рейтинг игроков · {'ЛВК' if mode == 'cwl' else 'КВ'}</b>",
        f"Игроков: {len(players)} · страница {page + 1}/{pages}",
        "Рейтинг по вычисленному индексу, не по кубкам. Отказ от войны показан отдельно.",
        "",
    ]
    for i in range(page * per_page, min((page + 1) * per_page, len(players))):
        player = players[i]
        name = html.escape(str(player.get("name") or "?")[:27])
        league = html.escape(str(player.get("league") or "?")[:19])
        role = {"leader": "👑", "coLeader": "🛡️", "admin": "⭐"}.get(
            player.get("role"), "")
        inactive = " ⛔" if player.get("eligibility") != "candidate" else ""
        exp = player.get("expLevel")
        exp_label = f" · ур.{exp}" if isinstance(exp, int) else ""
        lines.append(
            f"{i + 1}. {role}<b>{name}</b> · TH{player.get('townHallLevel') or '?'}"
            f"{exp_label} · <b>{float(player.get('selectionScore') or 0):.1f}</b>{inactive}"
        )
        lines.append(f"   🏆 {league}")
    lines.append(
        "\nℹ️ Оборона и постройки недоступны в CoC API. Уровень опыта — "
        "косвенный показатель, а звание — малый бонус, не доказательство силы."
    )
    return "\n".join(lines)[:4000]


def ranking_keyboard(mode: str = "war", page: int = 0, total: int = 0,
                     per_page: int = 10) -> InlineKeyboardMarkup:
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    rows = [[
        InlineKeyboardButton("⚔️ КВ" + (" ✓" if mode == "war" else ""),
                             callback_data="rank:mode:war"),
        InlineKeyboardButton("🏆 ЛВК" + (" ✓" if mode == "cwl" else ""),
                             callback_data="rank:mode:cwl"),
    ]]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀", callback_data=f"rank:page:{page-1}"))
    if page + 1 < pages:
        nav.append(InlineKeyboardButton("▶", callback_data=f"rank:page:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("🔄 Обновить", callback_data=f"rank:mode:{mode}")])
    rows.append([InlineKeyboardButton("🏠 Штаб", callback_data="menu_home")])
    return InlineKeyboardMarkup(rows)
