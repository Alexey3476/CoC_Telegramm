"""Telegram presentation: no API calls, deterministic and unit-testable."""
from __future__ import annotations

import html
import re
import unicodedata
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

BERLIN = ZoneInfo("Europe/Berlin")
COC_DATE = re.compile(r"^\d{8}T\d{6}(?:\.\d+)?Z$")


def parse_game_time(raw: str | None) -> datetime | None:
    if not raw:
        return None
    value = str(raw)
    if not COC_DATE.fullmatch(value):
        return None
    try:
        return datetime.strptime(value.split(".")[0], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def game_time(raw: str | None) -> str:
    date = parse_game_time(raw)
    if date is None:
        return "Нет данных"
    return date.astimezone(BERLIN).strftime("%d.%m.%Y, %H:%M")


def remaining_until(raw: str | None, now: datetime | None = None) -> str | None:
    end = parse_game_time(raw)
    if end is None:
        return None
    now = now or datetime.now(timezone.utc)
    seconds = int((end - now).total_seconds())
    if seconds <= 0:
        return "Время истекло"
    hours, minutes = divmod(seconds // 60, 60)
    return f"{hours} ч {minutes:02d} мин" if hours else f"{minutes} мин"


def safe_tag_name(name: str, max_chars: int = 16) -> str:
    """Telegram regular-member tag; remove emoji, control chars and truncate."""
    text = unicodedata.normalize("NFKC", name or "")
    clean = []
    for ch in text:
        code = ord(ch)
        if unicodedata.category(ch) in {"So", "Cs", "Cf", "Cc"} or 0x1F000 <= code <= 0x1FAFF:
            continue
        clean.append(ch)
    return " ".join("".join(clean).split())[:max_chars]


def normalize_name(name: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKC", str(name)).casefold() if ch.isalnum())


def format_war_message(war: dict) -> str:
    labels = {"inWar": "⚔️ Идёт", "preparation": "🛡 Подготовка",
              "warEnded": "🏁 Завершена", "notInWar": "Нет активной войны"}
    state = war.get("state", "unknown")
    clan, other = war.get("clan") or {}, war.get("opponent") or {}
    name = html.escape(str(clan.get("name") or "Наш клан"))
    enemy = html.escape(str(other.get("name") or "Соперник"))
    lines = ["⚔️ <b>Война клана</b>", f"Статус: <b>{labels.get(state, 'Неизвестен')}</b>"]
    if state == "notInWar":
        return "\n".join(lines)
    size = war.get("teamSize")
    if size:
        lines.append(f"Участники: {size} × {size}")
    lines.extend(["", f"🏰 <b>{name}</b>  vs  <b>{enemy}</b>"])
    if state in {"inWar", "warEnded"}:
        lines.append(f"⭐ {clan.get('stars', 0)} : {other.get('stars', 0)}")
        lines.append(f"💥 {float(clan.get('destructionPercentage') or 0):.1f}% : {float(other.get('destructionPercentage') or 0):.1f}%")
        attacks_per = int(war.get("attacksPerMember") or 1)
        total = int(size or 0) * attacks_per
        if total:
            used = sum(len(m.get("attacks") or []) for m in clan.get("members", []))
            lines.append(f"🎯 Наши атаки: {used}/{total} · осталось {max(0, total - used)}")
    if state == "preparation":
        lines.append(f"Начало: {game_time(war.get('startTime'))}")
    else:
        lines.append(f"Начало: {game_time(war.get('startTime'))}")
        lines.append(f"Конец: {game_time(war.get('endTime'))}")
    if state in {"inWar", "preparation"}:
        countdown = remaining_until(war.get("endTime") if state == "inWar" else war.get("startTime"))
        if countdown:
            lines.append(f"⏳ Осталось: {countdown}")
    return "\n".join(lines)


def format_raid_message(data: dict) -> str:
    raid = data.get("currentRaid")
    if not raid:
        return "🏛 <b>Рейды столицы</b>\nСведения о последнем рейде отсутствуют."
    state = raid.get("state")
    state_label = {"ongoing": "⚔️ Идёт", "ended": "🏁 Последний рейд завершён",
                   "notInWar": "Нет активного рейда"}.get(state, str(state or "Неизвестно"))
    lines = ["🏛 <b>Рейды столицы</b>", f"Статус: {html.escape(state_label)}",
             f"Начало: {game_time(raid.get('startTime'))}",
             f"Конец: {game_time(raid.get('endTime'))}"]
    if state == "ongoing":
        countdown = remaining_until(raid.get("endTime"))
        if countdown:
            lines.append(f"⏳ Осталось: {countdown}")
    for key, label in (("capitalTotalLoot", "Добыто золота"), ("raidsCompleted", "Районов разгромлено"),
                       ("totalAttacks", "Атак использовано"), ("defensiveReward", "Награда за защиту")):
        if raid.get(key) is not None:
            lines.append(f"{label}: {raid[key]}")
    members = sorted(raid.get("members") or [], key=lambda x: x.get("capitalResourcesLooted") or 0, reverse=True)
    if members:
        lines.extend(["", "<b>Топ добытчиков:</b>"])
        for m in members[:5]:
            attacks = m.get("attacks", 0)
            lines.append(f"• {html.escape(str(m.get('name', '?')))}: {m.get('capitalResourcesLooted', 0)} золота · {attacks} атак")
    return "\n".join(lines)


def lineup_keyboard(stage: str = "main", page: int = 0, data: dict | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("✅ Состав", callback_data="lineup:main:0"),
         InlineKeyboardButton("🪑 Запас", callback_data="lineup:bench:0")],
        [InlineKeyboardButton("👤 Игроки", callback_data="lineup:details:0"),
         InlineKeyboardButton("ℹ️ Методика", callback_data="lineup:about:0")],
    ]
    if stage == "details" and data:
        members = data.get("recommendedLineup") or []
        offset = page * 6
        for idx in range(offset, min(offset + 6, len(members))):
            member = members[idx]
            label = f"{idx + 1}. {str(member.get('name', '?'))[:20]}"
            rows.append([InlineKeyboardButton(label, callback_data=f"lineup:player:{idx}")])
        navigation = []
        if page:
            navigation.append(InlineKeyboardButton("◀", callback_data=f"lineup:details:{page - 1}"))
        if offset + 6 < len(members):
            navigation.append(InlineKeyboardButton("▶", callback_data=f"lineup:details:{page + 1}"))
        if navigation:
            rows.append(navigation)
    rows.extend([[InlineKeyboardButton("🔄 Обновить", callback_data="lineup:refresh:0")],
                 [InlineKeyboardButton("🏠 Штаб", callback_data="menu_home")]])
    return InlineKeyboardMarkup(rows)


def lineup_message(data: dict, stage: str = "main", page: int = 0) -> str:
    members = data.get("recommendedLineup") or []
    size = max(1, min(25, int(data.get("recommendedSize") or 15)))
    size = min(size, len(members))
    total = int(data.get("observedWarCount") or 0)
    header = f"⚔️ <b>Подбор состава · {html.escape(str(data.get('clanName') or 'Клан'))}</b>\n"
    header += f"Предварительный размер: <b>{size} игроков</b> · История: {total} войн\n"
    if stage == "about":
        return header + (
            "\n<b>Как считается индекс?</b>\n"
            "• Сила аккаунта: ратуша, герои и снаряжение.\n"
            "• Надёжность: использованные атаки и звёзды против соперников разного TH.\n"
            "• При наличии истории: 55% история, 45% сила.\n"
            "• Без истории индекс основан только на силе, не доказывает надёжность.\n\n"
            "⚠️ Это рекомендация, а не прогноз и не автоматический выбор на войну."
        )
    if stage == "player":
        if not 0 <= page < len(members):
            return header + "\nИгрок не найден."
        m = members[page]
        hist = m.get("history") or {}
        pref = {"in": "Хочет участвовать", "out": "Не хочет участвовать"}.get(m.get("warPreference"), "Неизвестно")
        return header + (
            f"\n<b>{html.escape(str(m.get('name') or '?'))}</b> · TH{m.get('townHallLevel') or '?'}\n"
            f"Тег: <code>{html.escape(str(m.get('tag') or ''))}</code>\n"
            f"Индекс: {m.get('warReadiness') or 'н/д'} · {pref}\n"
            f"Завершённых войн: {hist.get('wars', 0)}\n"
            f"Атак использовано: {hist.get('attacksUsed', 0)}/{hist.get('attacksPossible', 0)}\n"
            f"Пропуски: {hist.get('missedAttacks', 'н/д')}\n"
            f"Средние звёзды: {hist.get('averageStars') if hist.get('averageStars') is not None else 'н/д'}\n"
            f"Триплы по равным/сильнее: {hist.get('threeStarsEqualOrHigher', 0)}\n"
            f"Триплы по слабым: {hist.get('threeStarsDownhill', 0)}\n"
            + ("⚠️ Мало наблюдений, оценка предварительна." if hist.get("wars", 0) < 5 else "")
        )
    if stage == "details":
        return header + "\nВыбери игрока для подробной статистики. Данные доступны только за сохранённые войны."
    if stage == "bench":
        subset = list(enumerate(members[size:], size + 1))[:10]
        title = "🪑 <b>Запасные кандидаты</b>"
    else:
        subset = list(enumerate(members[:size], 1))
        title = "✅ <b>Рекомендуемый состав</b>"
    rows = [header, title]
    for idx, m in subset:
        name = html.escape(str(m.get("name") or "?"))
        score = m.get("warReadiness")
        score_label = f"{score:.1f}" if isinstance(score, (int, float)) else "?"
        hist = m.get("history") or {}
        evidence = f"{hist.get('wars')} войн" if hist.get("wars") else "без истории"
        preference = " ⚠️ вне заявок" if m.get("warPreference") == "out" else ""
        rows.append(f"{idx}. <b>{name}</b> · TH{m.get('townHallLevel') or '?'} · {score_label} · {evidence}{preference}")
    if not subset:
        rows.append("Нет доступных игроков.")
    rows.append("\n⚠️ Индексы без истории нельзя сравнивать как подтверждённую надёжность.")
    return "\n".join(rows)[:4000]
