"""Telegram presentation for conservative multi-account war and CWL selection."""
from __future__ import annotations

import html
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

SECTIONS = (
    ("main", "✅ Состав", "lineup"),
    ("bench", "🪑 Запас", "reserve"),
    ("inactive", "🕒 48+ ч", "inactive"),
    ("out", "🚫 Не участвуют", "optedOut"),
    ("twinks", "👥 Твинки", "twinks"),
    ("confirm", "❔ Уточнить", "needConfirmation"),
    ("kick", "⚠️ Проверить", "kickCandidates"),
    ("promote", "🎖️ Повысить", "promotionCandidates"),
    ("bonus", "🏅 Бонусы", "bonusCandidates"),
)
CATEGORY = {stage: key for stage, _, key in SECTIONS}
TITLES = {stage: label for stage, label, _ in SECTIONS}


def lineup_keyboard(stage: str = "main", page: int = 0, data: dict | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("⚔️ КВ" + (" ✓" if (data or {}).get("selectionMode") == "war" else ""),
                              callback_data="lineup:war:0"),
         InlineKeyboardButton("🏆 ЛВК" + (" ✓" if (data or {}).get("selectionMode") == "cwl" else ""),
                              callback_data="lineup:cwl:0")],
    ]
    section_pairs = [(SECTIONS[0], SECTIONS[1]), (SECTIONS[2], SECTIONS[3]), (SECTIONS[4], SECTIONS[5])]
    if (data or {}).get("viewerIsCaptain"):
        section_pairs.append((SECTIONS[6], SECTIONS[7]))
    for a, b in section_pairs:
        rows.append([
            InlineKeyboardButton(a[1], callback_data=f"lineup:{a[0]}:0"),
            InlineKeyboardButton(b[1], callback_data=f"lineup:{b[0]}:0"),
        ])
    if (data or {}).get("viewerIsCaptain"):
        rows.append([InlineKeyboardButton("🏅 Кандидаты на бонус", callback_data="lineup:bonus:0")])
    rows.append([InlineKeyboardButton("⚖️ Веса", callback_data="lineup:weights:0")])
    if stage == "details" and data:
        all_players = data.get("recommendedLineup") or []
        for idx in range(page * 6, min((page + 1) * 6, len(all_players))):
            rows.append([InlineKeyboardButton(
                f"{idx + 1}. {str(all_players[idx].get('name', '?'))[:24]}",
                callback_data=f"lineup:player:{idx}",
            )])
        pages = []
        if page:
            pages.append(InlineKeyboardButton("◀", callback_data=f"lineup:details:{page - 1}"))
        if (page + 1) * 6 < len(all_players):
            pages.append(InlineKeyboardButton("▶", callback_data=f"lineup:details:{page + 1}"))
        if pages:
            rows.append(pages)
    rows.extend([
        [InlineKeyboardButton("👤 Данные всех игроков", callback_data="lineup:details:0")],
        [InlineKeyboardButton("🔄 Пересчитать", callback_data="lineup:refresh:0"),
         InlineKeyboardButton("🏠 Штаб", callback_data="menu_home")],
    ])
    return InlineKeyboardMarkup(rows)


def _player_line(player: dict, index: int) -> str:
    hist = player.get("history") or {}
    name = html.escape(str(player.get("name") or "Игрок"))
    score = player.get("selectionScore")
    pref = {"in": "✅", "out": "🚫", "unknown": "❔"}.get(player.get("selectionPreference"), "❔")
    wars = hist.get("wars") or 0
    sample = f"{wars} войн" if wars else "нет истории"
    return f"{index}. {pref} <b>{name}</b> · TH{player.get('townHallLevel') or '?'} · {score if score is not None else '?'} · {sample}"


def lineup_message(data: dict, stage: str = "main", page: int = 0) -> str:
    mode = "ЛВК" if data.get("selectionMode") == "cwl" else "КВ"
    groups = data.get("categories") or {}
    all_players = data.get("recommendedLineup") or []
    size = data.get("recommendedSize") or 15
    rows = [
        f"⚔️ <b>Штаб отбора · {mode}</b>",
        f"🏰 {html.escape(str(data.get('clanName') or 'Клан'))} · План: {size} мест",
        f"Подтверждённых: {len(groups.get('lineup', []))} · Свободно: {data.get('reservedSlots', '?')}",
        "",
    ]
    if stage in {"kick", "promote", "bonus"} and not data.get("viewerIsCaptain"):
        return "\n".join(rows + ["Только для руководителей клана."])
    if stage == "weights" or stage == "about":
        weights = data.get("weightTable") or {}
        labels = (("strength", "Сила аккаунта"), ("attendance", "Использование атак"),
                  ("attack", "Качество атак"), ("preference", "Заявка на войну"))
        rows.append("<b>⚖️ Таблица весов:</b>")
        for key, label in labels:
            rows.append(f"• {label}: <b>{weights.get(key, '?')}%</b>")
        rows.extend([
            "",
            "<b>Приоритеты допуска (раньше рейтинга):</b>",
            "1. Отказ от участия → вне состава.",
            "2. Подтверждённое вручную отсутствие 48+ ч → резерв активности.",
            "3. Лимит аккаунтов одного владельца → твинки.",
            "4. Неизвестное согласие → запрос подтверждения.",
            "5. Остальные по рейтингу → основной состав и запас.",
            "",
            "Индекс = средневзвешенная оценка только известных компонентов.",
            "При отсутствии истории вес пересчитывается по доступным показателям, и покрытие снижается.",
            "Допуск в состав зависит от заявки, ручного последнего входа и лимита твинков.",
            "Низкая ратуша сама по себе НЕ основание для исключения.",
            "Все решения остаются за руководителем клана.",
        ])
    elif stage == "player":
        if not 0 <= page < len(all_players):
            return "\n".join(rows + ["Игрок не найден."])
        p = all_players[page]
        hist = p.get("history") or {}
        breakdown = (p.get("scoreBreakdown") or {}).get("components") or {}
        coverage = (p.get("scoreBreakdown") or {}).get("evidenceWeightPct", 0)
        rows.extend([
            f"<b>👤 {html.escape(str(p.get('name') or '?'))}</b> · TH{p.get('townHallLevel') or '?'}",
            f"Тег: <code>{html.escape(str(p.get('tag') or ''))}</code>",
            f"Индекс: <b>{p.get('selectionScore', '?')}</b> · Покрытие: {coverage}%",
            f"Участие: {p.get('selectionPreference', 'unknown')} · CWL: {p.get('cwlPreference', 'unknown')}",
            f"Последний вход (ручной): {html.escape(str(p.get('manualLastSeen') or 'неизвестно'))}" if not data.get("hideManualLastSeen") else "Время входа доступно руководителю",
            f"Сохранённых войн: {hist.get('wars', 0)}",
            f"Использовано атак: {hist.get('attacksUsed', 0)}/{hist.get('attacksPossible', 0)}",
            f"Пропущено атак: {hist.get('missedAttacks', 0)}",
            f"Звёзд в среднем: {hist.get('averageStars') if hist.get('averageStars') is not None else 'нет данных'}",
            "",
            "<b>Компоненты:</b>",
        ])
        names = {"strength": "Сила", "attendance": "Посещаемость войн",
                 "attack": "Качество атак", "preference": "Заявка"}
        for key in ("strength", "attendance", "attack", "preference"):
            v = breakdown.get(key)
            rows.append(f"• {names[key]}: {v if v is not None else 'нет данных'}")
        rows.extend(html.escape(str(x)) for x in p.get("warnings") or [])
        rows.extend(html.escape(str(x)) for x in p.get("kickReasons") or [])
    elif stage == "details":
        rows.append("Нажми имя, чтобы увидеть показатели и источники оценки.")
    else:
        key = CATEGORY.get(stage, "lineup")
        people = groups.get(key) or []
        rows.append(f"<b>{TITLES.get(stage, 'Состав')}</b> · {len(people)} игроков")
        if people:
            for index, p in enumerate(people[:18], 1):
                rows.append(_player_line(p, index))
                reasons = {
                    "kick": "kickReasons", "promote": "promotionReasons", "bonus": "bonusReasons"
                }.get(stage)
                if reasons:
                    for reason in p.get(reasons) or []:
                        rows.append(f"   ↳ {html.escape(str(reason))}")
        else:
            rows.append("Нет игроков в этой категории.")
        if stage == "inactive":
            rows.extend(["", "🕒 Только отметка руководителя о входе в игру. API CoC не передаёт last-online."])
        if stage == "kick":
            rows.extend(["", "⚠️ Только кандидаты для личной проверки, автоматических киков нет."])
        if stage == "bonus":
            rows.extend(["", "🏅 Список основан только на сохранённых боях ЛВК, не на фактически выданных медалях."])
        if stage == "twinks":
            rows.extend(["", "👥 Дополнительные аккаунты одного подтверждённого Telegram-пользователя."])
        if stage == "confirm":
            rows.extend(["", "❔ Эти игроки потенциально подходят, но участие на выбранный тип войны не подтверждено."])
    return "\n".join(rows)[:4000]
