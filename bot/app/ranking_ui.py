"""Complete clan ranking by independently calculated KV and CWL scores."""
from __future__ import annotations

import html
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def ranking_page(data: dict, page: int = 0, per_page: int = 8) -> str:
    players = sorted(data.get("allPlayers") or data.get("recommendedLineup") or [],
                     key=lambda p: (-float(p.get("selectionScore") or 0),
                                    str(p.get("name") or "").casefold()))
    page = max(0, min(page, (len(players) - 1) // per_page if players else 0))
    mode = data.get("mode", "war")
    title = "ЛВК · абсолютная сила TH" if mode == "cwl" else "КВ · баланс по TH"
    lines = [
        f"🏅 <b>Рейтинг клана · {title}</b>",
        f"Игроков: {len(players)} · стр. {page + 1}/{max(1,(len(players)+per_page-1)//per_page)}",
        "Рейтинг по баллам отбора, не по звёздам за всё время.", "",
    ]
    for i in range(page*per_page, min((page+1)*per_page,len(players))):
        p = players[i]
        n = html.escape(str(p.get("name") or "?")[:35])
        score = p.get("selectionScore")
        points = f"{score:.1f}" if isinstance(score,(float,int)) else "?"
        cons = {"out":"🔴","in":"🟢"}.get(p.get("warPreference"),"❔")
        level = p.get("expLevel")
        exp = f" · ур.{level}" if level else ""
        lines.append(f"{i+1}. {cons} <b>{n}</b> · TH{p.get('townHallLevel','?')}"
                     f" · <b>{points}</b>{exp}")
        league = html.escape(str(p.get("league") or "?")[:28])
        lines.append(f"    {league} · {str(p.get('role') or 'member')}")
    lines += ["", "ℹ️ Красная отметка исключает из состава, но не скрывает игрока в рейтинге.",
              "ЛВК: TH влияет на итог сильнее; КВ: сравнение среди одинаковых TH.",
              "Уровни обороны/стен не доступны через публичный CoC API."]
    return "\n".join(lines)


def ranking_keyboard(data: dict, page: int = 0, per_page: int = 8) -> InlineKeyboardMarkup:
    roster = data.get("allPlayers") or data.get("recommendedLineup") or []
    rows = [
        [InlineKeyboardButton("⚔️ КВ" + (" ✓" if data.get("mode") == "war" else ""),
                              callback_data="rank:mode:war"),
         InlineKeyboardButton("🏆 ЛВК" + (" ✓" if data.get("mode") == "cwl" else ""),
                              callback_data="rank:mode:cwl")],
    ]
    pages = max(1,(len(roster)+per_page-1)//per_page)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀", callback_data=f"rank:page:{page-1}"))
    nav.append(InlineKeyboardButton(f"{min(page+1,pages)}/{pages}",callback_data=f"rank:page:{page}"))
    if page+1 < pages:
        nav.append(InlineKeyboardButton("▶", callback_data=f"rank:page:{page+1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton("👥 Игроки", callback_data="menu_topplayers"),
                 InlineKeyboardButton("🏠 Штаб", callback_data="menu_home")])
    return InlineKeyboardMarkup(rows)
