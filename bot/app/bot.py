import asyncio
import html
import os
import logging
import re
from urllib.parse import quote
from datetime import datetime, timedelta, timezone, time
from zoneinfo import ZoneInfo
from typing import Any

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, BotCommand
from telegram.constants import ChatType, ParseMode
from telegram import BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.helpers import escape_markdown

from app.backend_client import build_url, fetch_json
from app.bindings_storage import Binding, BindingsStorage
from app.settings import env_snapshot, settings, settings_snapshot, validate_settings
from app.ui import format_war_message, format_raid_message, format_cwl_message
from app.selection_ui import lineup_message, lineup_keyboard
from app.selection import build_selection, policy_from_settings, reported_last_seen
from app.tags import assign_game_tag, sync_tags_daily
from app.binding_ui import sorted_roster, roster_keyboard
from app.accounts_ui import accounts_text, accounts_keyboard, delete_confirmation
from app.captain import is_captain, captain_report_text

log_level = logging.DEBUG if settings.debug else logging.INFO
logging.basicConfig(level=log_level, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)
logger.debug("Debug mode enabled")
# httpx records full Telegram bot tokens in request URLs at INFO level.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
# Scrub Telegram bot tokens from every formatted log line and traceback.
TOKEN_IN_URL = re.compile(r"/bot\d+:[A-Za-z0-9_-]+")


class SecretRedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return TOKEN_IN_URL.sub("/bot[REDACTED]", super().format(record))


for _handler in logging.getLogger().handlers:
    _handler.setFormatter(SecretRedactingFormatter("%(levelname)s %(name)s %(message)s"))


TAG_PATTERN = re.compile(r"^[0289PYLQGRJCUV]+$")
TAG_EXTRACT_PATTERN = re.compile(r"#?[0289PYLQGRJCUV]{4,}")


def safe_markdown(value: object, default: str = "N/A") -> str:
    return escape_markdown(str(value if value is not None else default), version=1)


def format_clan(payload: dict[str, Any]) -> str:
    """Format clan information with capital details."""
    msg = (
        f"*{safe_markdown(payload.get('name', 'Clan'))}*\n"
        f"🏷️ Tag: `{safe_markdown(payload.get('tag'))}`\n"
        f"📊 Level: {safe_markdown(payload.get('clanLevel'))}\n"
        f"👥 Members: {safe_markdown(payload.get('members'))}\n"
        f"⚔️ War League: {safe_markdown(payload.get('warLeague', {}).get('name'))}\n"
    )
    
    # Add capital info if available
    capital = payload.get('clanCapital', {})
    if capital:
        capital_name = safe_markdown(capital.get('name'), "Capital")
        capital_level = safe_markdown(capital.get('capitalHallLevel'))
        msg += f"\n🏛️ *Capital:* {capital_name} (Hall Level: {capital_level})\n"
    
    return msg


def format_player(payload: dict[str, Any]) -> str:
    return (
        f"*{safe_markdown(payload.get('name', 'Player'))}*\n"
        f"Tag: `{safe_markdown(payload.get('tag'))}`\n"
        f"Town Hall: {safe_markdown(payload.get('townHallLevel'))}\n"
        f"Trophies: {safe_markdown(payload.get('trophies'))}\n"
        f"Best Trophies: {safe_markdown(payload.get('bestTrophies'))}\n"
        f"Clan: {safe_markdown(payload.get('clan', {}).get('name'), 'No clan')}\n"
    )


def format_war(payload: dict[str, Any]) -> str:
    """Render a localised war summary."""
    return format_war_message(payload)


def format_activity_report(payload: dict[str, Any]) -> str:
    """Format clan activity report."""
    clan_name = payload.get("clanName", "Clan")
    clan_level = payload.get("clanLevel", "N/A")
    
    members = payload.get("members", {})
    total = members.get("total", 0)
    avg_trophies = members.get("avgTrophies", 0)
    
    war = payload.get("war", {})
    war_state = war.get("state", "notInWar")
    war_stars = war.get("stars", 0)
    attacks_done = war.get("attacksDone", 0)
    attacks_remaining = war.get("attacksRemaining", 0)
    
    activity = payload.get("activity", {})
    most_active = activity.get("mostActive", [])
    least_active = activity.get("leastActive", [])
    
    msg = f"📊 *Отчет об активности клана {clan_name}*\n\n"
    msg += f"🏆 *Уровень клана:* {clan_level}\n"
    msg += f"👥 *Участников:* {total}\n"
    msg += f"⚔️ *Среднее трофеев:* {avg_trophies}\n\n"
    
    msg += f"🎖️ *Статус войны:* {war_state}\n"
    if war_state == "inWar":
        msg += f"⭐ *Звезд набрано:* {war_stars}\n"
        msg += f"🔨 *Атак сделано:* {attacks_done}/{attacks_done + attacks_remaining}\n"
    msg += "\n"
    
    def translate_role(role: str) -> str:
        """Translate role to Russian."""
        role_map = {
            "leader": "Лидер",
            "coLeader": "Co-Лидер",
            "admin": "Администратор",
            "member": "Участник",
        }
        return role_map.get(role, role)
    
    msg += "🟢 *Больше всего пожертвований (не время онлайн):*\n"
    for player in most_active[:5]:
        name = player.get("name", "Unknown")
        role = translate_role(player.get("role", "member"))
        msg += f"  • {name} ({role})\n"
    
    msg += "\n📉 *Меньше всего пожертвований:*\n"
    for player in least_active[:5]:
        name = player.get("name", "Unknown")
        role = translate_role(player.get("role", "member"))
        msg += f"  • {name} ({role})\n"
    
    return msg


class InvalidTagError(ValueError):
    pass


def normalize_tag(tag: str) -> str:
    cleaned = tag.replace(" ", "").strip().upper()
    if not cleaned.startswith("#"):
        cleaned = f"#{cleaned}"
    raw = cleaned.lstrip("#")
    if not raw or not TAG_PATTERN.fullmatch(raw):
        raise InvalidTagError("Invalid tag format")
    logger.info("Normalized tag input=%s normalized=%s", tag, cleaned)
    return cleaned


def encode_tag(tag: str) -> str:
    return quote(tag, safe="")


def format_mention(user_id: int, name: str) -> str:
    safe_name = html.escape(name, quote=True)
    return f'<a href="tg://user?id={user_id}">{safe_name}</a>'


def parse_coc_time(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y%m%dT%H%M%S.%fZ", "%Y%m%dT%H%M%SZ"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def attacks_used(member: dict[str, Any]) -> int:
    attacks = member.get("attacks")
    if isinstance(attacks, list):
        return len(attacks)
    if isinstance(attacks, int):
        return attacks
    return 0


def binding_error_message(status: int) -> str:
    if status == 400:
        return "Invalid player tag format."
    if status == 401:
        return "Backend token invalid. Please update the backend token."
    if status == 403:
        return "Backend IP is not whitelisted for Clash of Clans."
    if status == 404:
        return "Player tag not found."
    if status == 429:
        return "Rate limit reached. Please try again later."
    if status == 504:
        return "Backend timed out contacting Clash of Clans."
    return "Backend error while validating player."


def ensure_group_chat(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}


def ensure_private_chat(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.type == ChatType.PRIVATE


def format_settings_report() -> str:
    lines = [
        "Bot settings snapshot:",
    ]
    for key, value in settings_snapshot().items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


async def log_any_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    logger.info(
        "Command received user_id=%s chat_id=%s text=%s",
        update.effective_user.id if update.effective_user else None,
        update.effective_chat.id if update.effective_chat else None,
        (update.message.text or "").split(" ", 1)[0],
    )


def bind_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Привязать", callback_data="bind_start")]]
    )


def bind_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Отмена", callback_data="bind_cancel")]]
    )


def main_menu_keyboard(user_id: int | None = None, captain: bool = False) -> InlineKeyboardMarkup:
    """One entry point to the full bot; short labels fit on phones."""
    rows = [
        [InlineKeyboardButton("⚔️ Война", callback_data="menu_war"),
         InlineKeyboardButton("📋 Следующий состав", callback_data="menu_nextwar")],
        [InlineKeyboardButton("👥 Игроки", callback_data="menu_topplayers"),
         InlineKeyboardButton("🏆 Лига CWL", callback_data="menu_cwl")],
        [InlineKeyboardButton("🏛️ Столица", callback_data="menu_raids"),
         InlineKeyboardButton("🏰 Клан", callback_data="menu_clan")],
        [InlineKeyboardButton("👤 Профиль", callback_data="menu_profile"),
         InlineKeyboardButton("👥 Мои аккаунты", callback_data="menu_accounts")],
        [InlineKeyboardButton("📈 Развитие", callback_data="menu_progress"),
         InlineKeyboardButton("❓ Справка", callback_data="menu_help")],
    ]
    if captain:
        rows.append([InlineKeyboardButton("📋 Капитанский отчёт", callback_data="menu_captain")])
    return InlineKeyboardMarkup(rows)


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Штаб клана", callback_data="menu_home")]])


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = (
        "❓ <b>Помощь · Troublemakers</b>\n\n"
        "/menu — главное меню с кнопками\n"
        "/war — текущая война и атаки\n"
        "/nextwar — подбор состава и история\n"
        "/cwl — результаты ЛВК\n"
        "/progress — развитие моего аккаунта\n"
        "/captain — отчёт для руководства клана\n"
        "/clan — данные клана\n"
        "/topplayers — рейтинг активности\n"
        "/raids — рейды столицы\n"
        "/profile — мой игровой профиль\n"
        "/bind — привязать ещё один аккаунт\n"
        "/accounts — управление аккаунтами и ЛВК\n"
        "/primary #ТЕГ — выбрать основной аккаунт\n"
        "/cwlopt in|out — заявка на ЛВК для основного\n"
        "/unbind #ТЕГ — удалить свою привязку\n"
        "/unlink #ТЕГ — удалить чужую привязку (руководство)\n"
        "/lastseen #ТЕГ 2d — ручная отметка по экрану игры (руководство)\n"
        "/grouplink — получить приглашение\n"
        "/unbind — отвязать аккаунт\n"
        "/chatid — ID группы (для администратора)\n\n"
        "Личность игрока подтверждается игровым API Token; его нельзя "
        "путать с ключом разработчика."
    )
    await send_or_edit_message(update, lines, parse_mode=ParseMode.HTML, reply_markup=back_keyboard())


async def sync_bot_commands(bot) -> None:
    """Replace stale BotFather /start /stop /help menu commands."""
    base = [BotCommand("menu", "🏠 Штаб клана"),
            BotCommand("war", "⚔️ Текущая война"),
            BotCommand("nextwar", "📋 Следующий состав"),
            BotCommand("cwl", "🏆 Лига CWL"),
            BotCommand("progress", "📈 Прогресс игрока"),
            BotCommand("profile", "👤 Мой профиль"),
            BotCommand("accounts", "👥 Мои аккаунты"),
            BotCommand("clan", "🏰 Информация о клане"),
            BotCommand("help", "❓ Помощь")]
    await bot.set_my_commands(base)
    await bot.set_my_commands(
        base + [BotCommand("bind", "🔐 Привязать ещё аккаунт"),
                BotCommand("grouplink", "🔗 Ссылка в группу")],
        scope=BotCommandScopeAllPrivateChats(),
    )
    await bot.set_my_commands(
        [BotCommand("menu", "🏠 Штаб клана"),
         BotCommand("war", "⚔️ Текущая война"),
         BotCommand("nextwar", "📋 Следующий состав"),
         BotCommand("cwl", "🏆 Результаты CWL"),
         BotCommand("raids", "🏛️ Рейды столицы"),
         BotCommand("help", "❓ Помощь")],
        scope=BotCommandScopeAllGroupChats(),
    )


async def send_or_edit_message(update: Update, text: str, parse_mode: str = ParseMode.MARKDOWN, reply_markup = None):
    """Send message for regular command or edit for callback query."""
    if update.message:
        return await update.message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    elif update.callback_query:
        if reply_markup is None:
            reply_markup = back_keyboard()
        return await update.callback_query.edit_message_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    return None



def extract_tag(text: str) -> str | None:
    """Extract a valid-looking CoC player tag from private text."""
    match = TAG_EXTRACT_PATTERN.search(text.replace(" ", "").upper())
    return match.group(0) if match else None


async def handle_handler_exception(
    update: Update | None,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    logger.exception("Unhandled handler error", exc_info=context.error)
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "Unexpected error occurred. Please try again."
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    try:
        logger.debug("Start command from user %s", update.effective_user.id)
        if ensure_private_chat(update):
            storage: BindingsStorage = context.application.bot_data["storage"]
            linked = storage.get_binding(settings.clan_group_id or 0, update.effective_user.id)
            if linked:
                await menu(update, context)
                return
            # Private chat - show bind option
            user_name = update.effective_user.first_name or "Player"
            await update.message.reply_text(
                f"👋 Привет, {user_name}!\n\n"
                f"Я — бот Clash of Clans для нашего клана.\n\n"
                f"🔐 Чтобы присоединиться к группе клана, нужно:\n"
                f"1️⃣ Привязать свой аккаунт\n"
                f"2️⃣ Получить ссылку на группу\n"
                f"3️⃣ Присоединиться\n\n"
                f"Начнём с привязки!",
                reply_markup=bind_keyboard(),
            )
            return
        # Group chat
        await update.message.reply_text(
            f"🎮 Привет! Напиши мне в личку (@{context.bot.username}), чтобы привязать игровой аккаунт."
        )
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to handle /start: %s", e, exc_info=settings.debug)


async def has_captain_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Revalidate role on every privileged action, not just when rendering buttons."""
    if not ensure_private_chat(update) or not update.effective_user:
        return False
    storage: BindingsStorage = context.application.bot_data["storage"]
    owned = storage.get_bindings_for_user(settings.clan_group_id or 0, update.effective_user.id)
    if not owned:
        return False
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            clan_data = await fetch_json(client, "/clan")
        roster = clan_data.get("memberList") or []
        return any(is_captain(roster, account.coc_player_tag) for account in owned)
    except (httpx.RequestError, httpx.HTTPStatusError):
        return False


async def captain_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await has_captain_access(update, context):
        await send_or_edit_message(update, "Этот раздел доступен только лидеру или соруководителю клана.")
        return
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            data = await fetch_json(client, "/activity-report")
        await send_or_edit_message(update, captain_report_text(data), parse_mode=ParseMode.HTML)
    except (httpx.RequestError, httpx.HTTPStatusError):
        await send_or_edit_message(update, "Не удалось собрать отчёт.")


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show a single navigable dashboard in private chats and groups."""
    if not update.effective_user:
        return
    storage: BindingsStorage = context.application.bot_data["storage"]
    binding = storage.get_binding(settings.clan_group_id or 0, update.effective_user.id)
    who = html.escape(binding.coc_player_tag) if binding else "не привязан"
    name = html.escape(settings.coc_clan_tag or "Troublemakers")
    text = f"🏰 <b>Штаб клана</b>\n{name}\n\n👤 Мой аккаунт: <code>{who}</code>\nВыбери раздел:"
    captain = await has_captain_access(update, context) if binding else False
    await send_or_edit_message(update, text, parse_mode=ParseMode.HTML,
                               reply_markup=main_menu_keyboard(captain=captain))


async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle first message in private chat - offer binding."""
    if not update.message or not update.effective_user or not update.message.text:
        return
    
    # Only for private chats
    if not ensure_private_chat(update):
        return
    
    # Skip if user is waiting for tag input (capture_tag will handle it)
    if context.user_data.get("awaiting_tag") or context.user_data.get("awaiting_player_token"):
        return
    
    # Skip if user is already bound
    storage: BindingsStorage = context.application.bot_data["storage"]
    binding = storage.get_binding(settings.clan_group_id or 0, update.effective_user.id)
    if binding:
        # User is bound, offer menu instead
        context.user_data.pop("awaiting_tag", None)  # Clear any waiting state
        await update.message.reply_text(
            f"✅ Вы привязаны как {binding.coc_player_tag}.\nВыбери раздел:",
            reply_markup=main_menu_keyboard(),
        )
        return
    
    # User not bound - offer binding
    if not context.user_data.get("binding_offered"):
        context.user_data["binding_offered"] = True
        user_name = update.effective_user.first_name or "Player"
        await update.message.reply_text(
            f"👋 Привет, {user_name}!\n\n"
            f"Я — бот Clash of Clans для нашего клана.\n\n"
            f"🔐 Чтобы присоединиться к группе клана, нужно сначала привязать свой аккаунт.\n\n"
            f"Нажми 'Привязать' 👇",
            reply_markup=bind_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )


async def clan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clan summary with consistent back-to-dashboard navigation."""
    if not update.message and not update.callback_query:
        return
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            payload = await fetch_json(client, "/clan")
        await send_or_edit_message(update, format_clan(payload), parse_mode=ParseMode.MARKDOWN)
    except httpx.HTTPStatusError as exc:
        logger.warning("Clan API request failed status=%s", exc.response.status_code)
        await send_or_edit_message(update, binding_error_message(exc.response.status_code))
    except httpx.RequestError:
        logger.warning("Clan API unavailable")
        await send_or_edit_message(update, "Сервис данных клана временно недоступен.")


async def player(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show an explicitly supplied tag or the account linked to this Telegram user."""
    if not update.message and not update.callback_query:
        return
    if not update.effective_user:
        return
    storage: BindingsStorage = context.application.bot_data["storage"]
    if context.args and context.args[0].lower() not in ("я", "me"):
        try:
            tag = normalize_tag(context.args[0])
        except InvalidTagError:
            await send_or_edit_message(update, "Неверный формат тега.")
            return
    else:
        bound = storage.get_binding(settings.clan_group_id or 0, update.effective_user.id)
        if not bound:
            await send_or_edit_message(update, "Сначала привяжи игровой аккаунт через /bind.")
            return
        tag = bound.coc_player_tag
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            payload = await fetch_json(client, f"/player/{encode_tag(tag)}")
        await send_or_edit_message(update, format_player(payload), parse_mode=ParseMode.MARKDOWN)
    except httpx.HTTPStatusError as exc:
        logger.warning("Player API request failed status=%s", exc.response.status_code)
        await send_or_edit_message(update, binding_error_message(exc.response.status_code))
    except httpx.RequestError:
        logger.warning("Player API unavailable")
        await send_or_edit_message(update, "Сервис данных игрока временно недоступен.")


async def war(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message and not update.callback_query:
        return
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        try:
            payload = await fetch_json(client, "/war")
            await send_or_edit_message(update, format_war(payload), parse_mode=ParseMode.HTML)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.warning("Backend error: %s", exc)
            if status == 429:
                message = "Rate limit reached. Please try again later."
            elif status == 400:
                message = "Invalid clan tag configured."
            elif status == 401:
                message = "Backend token invalid. Please update the backend token."
            elif status == 403:
                message = "Backend IP is not whitelisted for Clash of Clans."
            elif status == 504:
                message = "Backend timed out contacting Clash of Clans."
            else:
                message = "Backend error while fetching war data."
            await send_or_edit_message(update, message)
        except httpx.RequestError as exc:
            logger.warning("Backend unreachable: %s", exc)
            await send_or_edit_message(update, "Backend is unreachable. Please try again later.")
        except Exception:  # noqa: BLE001
            logger.exception("Unhandled error in /war")
            await send_or_edit_message(update, "Unexpected error occurred. Please try again.")


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        await update.message.reply_text("pong")
    except Exception:  # noqa: BLE001
        logger.exception("Failed to reply to /ping")


async def bind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not ensure_private_chat(update):
        await update.message.reply_text("Привязка доступна только в личном чате.")
        return
    if context.args:
        await process_binding(update, context, " ".join(context.args))
    else:
        await show_player_picker(update, context)


async def show_player_picker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Select from the real clan roster; verification is still mandatory."""
    if not ensure_private_chat(update) or not update.effective_user:
        return
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            clan_data = await fetch_json(client, "/clan")
        members = sorted_roster(
            clan_data.get("memberList") or [],
            update.effective_user.full_name,
            update.effective_user.username or "",
        )
        if not members:
            raise ValueError("empty member list")
        context.user_data["picker_members"] = members
        context.user_data["awaiting_tag"] = False
        await send_or_edit_message(
            update,
            "🔐 <b>Выбери свой аккаунт</b>\n"
            "Это список участников клана. Первый вариант может совпадать с твоим именем Telegram.\n"
            "Выбор ника НЕ является доказательством владения аккаунтом.",
            parse_mode=ParseMode.HTML,
            reply_markup=roster_keyboard(members),
        )
    except (httpx.HTTPStatusError, httpx.RequestError, ValueError):
        logger.warning("Clan roster unavailable for binding picker")
        context.user_data["awaiting_tag"] = True
        await send_or_edit_message(update, "Введи свой тег игрока, например #VU099JCR.",
                                   parse_mode=None, reply_markup=bind_cancel_keyboard())


async def roster_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query or not ensure_private_chat(update):
        return
    await update.callback_query.answer()
    command = update.callback_query.data or ""
    parts = command.split(":")
    if len(parts) != 3:
        return
    kind, index_str = parts[1:]
    idx = int(index_str)
    if kind == "manual":
        context.user_data["awaiting_tag"] = True
        await update.callback_query.edit_message_text(
            "✍️ Введи игровой тег, например #VU099JCR.",
            reply_markup=bind_cancel_keyboard())
        return
    members = context.user_data.get("picker_members") or []
    if not members:
        await update.callback_query.edit_message_text("Список устарел. Введи /bind.")
        return
    if kind == "page":
        await update.callback_query.edit_message_reply_markup(reply_markup=roster_keyboard(members, idx))
        return
    if kind != "player" or not 0 <= idx < len(members):
        return
    member = members[idx]
    await update.callback_query.edit_message_text(
        f"Выбран {member.get('name', '?')} · {member['tag']}. Проверяю аккаунт...")
    await process_binding(update, context, str(member["tag"]))


async def process_binding(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    raw_tag: str,
    verified: bool = False,
) -> None:
    if not update.effective_user or not update.effective_message:
        return
    context.user_data["awaiting_tag"] = False
    logger.info(
        "Bind request received user_id=%s group_id=%s raw_tag=%s",
        update.effective_user.id,
        settings.clan_group_id,
        raw_tag,
    )
    try:
        tag = normalize_tag(raw_tag)
    except InvalidTagError:
        await update.effective_message.reply_text("Invalid player tag format.")
        return
    logger.info(
        "Bind normalized user_id=%s tag=%s",
        update.effective_user.id,
        tag,
    )
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        try:
            path = f"/player/{encode_tag(tag)}"
            response = await client.get(build_url(path))
            logger.info(
                "Bind backend validation user_id=%s status=%s",
                update.effective_user.id,
                response.status_code,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.warning("Backend error validating player: %s", exc)
            if status == 404:
                await update.effective_message.reply_text("Player tag not found.")
            elif status in {401, 403}:
                await update.effective_message.reply_text(
                    "Backend authentication issue. Check API token/IP."
                )
            else:
                await update.effective_message.reply_text(binding_error_message(status))
            return
        except httpx.RequestError as exc:
            logger.warning("Backend unreachable during bind: %s", exc)
            await update.effective_message.reply_text("Backend is unreachable. Please try again later.")
            return
        except Exception:  # noqa: BLE001
            logger.exception("Unhandled error during bind validation")
            await update.effective_message.reply_text("Unexpected error occurred. Please try again.")
            return
    if settings.enforce_clan_membership:
        if not settings.coc_clan_tag:
            logger.error("Clan membership enforcement enabled without COC_CLAN_TAG set")
            await update.effective_message.reply_text(
                "Binding unavailable: clan configuration missing."
            )
            return
        player_clan = payload.get("clan", {}).get("tag")
        try:
            if not player_clan or normalize_tag(player_clan) != normalize_tag(settings.coc_clan_tag):
                await update.effective_message.reply_text("Player is not in this clan.")
                logger.info(
                    "Bind rejected user_id=%s tag=%s clan_tag=%s",
                    update.effective_user.id,
                    tag,
                    player_clan,
                )
                return
        except InvalidTagError:
            await update.effective_message.reply_text("Player is not in this clan.")
            return
    if settings.require_player_verification and not verified:
        context.user_data["pending_coc_tag"] = tag
        context.user_data["awaiting_player_token"] = True
        await update.effective_message.reply_text(
            "🔐 Для проверки владения аккаунтом открой Clash of Clans → "
            "Настройки → Ещё настройки → API Token и пришли токен игрока сюда.\n"
            "Это НЕ ключ разработчика. Сообщение с токеном бот попытается удалить.",
            reply_markup=bind_cancel_keyboard(),
        )
        return

    storage: BindingsStorage = context.application.bot_data["storage"]
    owner_id = storage.get_user_id_by_tag(settings.clan_group_id or 0, tag)
    if owner_id is not None and owner_id != update.effective_user.id:
        await update.effective_message.reply_text(
            "Игровой аккаунт уже привязан к другому пользователю. Обратитесь к администратору."
        )
        return
    now = datetime.now(timezone.utc).isoformat()
    binding = Binding(
        telegram_user_id=update.effective_user.id,
        group_id=settings.clan_group_id or 0,
        coc_player_tag=tag,
        telegram_username=update.effective_user.username,
        telegram_full_name=update.effective_user.full_name,
        created_at=now,
    )
    try:
        storage.upsert_binding(binding)
    except Exception as exc:  # noqa: BLE001
        logger.error("Bind DB write failed user_id=%s error=%s", update.effective_user.id, exc)
        await update.effective_message.reply_text("Internal error while saving binding.")
        return
    logger.info(
        "Bind saved user_id=%s group_id=%s tag=%s",
        update.effective_user.id,
        binding.group_id,
        tag,
    )
    mention = format_mention(update.effective_user.id, update.effective_user.full_name)
    try:
        if settings.clan_group_id is None:
            await update.effective_message.reply_text(
                f"Bound {mention} to {html.escape(tag)} successfully.\n"
                "Clan group is not configured yet. "
                "Ask an admin to set CLAN_GROUP_ID (use /chatid in the group).",
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return
        expire_at = datetime.now(timezone.utc) + timedelta(minutes=settings.invite_ttl_minutes)
        invite = await context.bot.create_chat_invite_link(
            chat_id=settings.clan_group_id,
            expire_date=expire_at,
            member_limit=1,
        )
        logger.info(
            "Invite created user_id=%s chat_id=%s expire_at=%s",
            update.effective_user.id,
            settings.clan_group_id,
            expire_at.isoformat(),
        )
        await update.effective_message.reply_text(
            f"Bound {mention} to {html.escape(tag)} successfully.\n"
            f"Here is your invite link (valid for {settings.invite_ttl_minutes} minutes):\n"
            f"{invite.invite_link}",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Invite creation failed user_id=%s error=%s", update.effective_user.id, exc)
        await update.effective_message.reply_text(
            f"Bound {mention} to {html.escape(tag)} successfully.",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


async def accounts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Private, multi-account overview. CoC war preference is read-only."""
    if not ensure_private_chat(update) or not update.effective_user:
        return
    storage: BindingsStorage = context.application.bot_data["storage"]
    owned = storage.get_bindings_for_user(settings.clan_group_id or 0, update.effective_user.id)
    prefs = {}
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        for binding in owned[:15]:
            try:
                player_data = await fetch_json(client, f"/player/{encode_tag(binding.coc_player_tag)}")
                prefs[binding.coc_player_tag] = player_data.get("warPreference") or "unknown"
            except (httpx.RequestError, httpx.HTTPStatusError):
                prefs[binding.coc_player_tag] = "unknown"
    await send_or_edit_message(update, accounts_text(owned, prefs),
                               parse_mode=ParseMode.HTML, reply_markup=accounts_keyboard(owned))


async def account_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query or not ensure_private_chat(update) or not update.effective_user:
        return
    await update.callback_query.answer()
    _, action, tag = (update.callback_query.data or "").split(":", 2)
    storage: BindingsStorage = context.application.bot_data["storage"]
    group_id, actor = settings.clan_group_id or 0, update.effective_user.id
    owned = storage.get_bindings_for_user(group_id, actor)
    selected = next((binding for binding in owned if binding.coc_player_tag == tag), None)
    if action == "cancel":
        await accounts(update, context)
        return
    if not selected:
        await update.callback_query.edit_message_text("Аккаунт не принадлежит тебе.")
        return
    if action == "primary":
        storage.set_primary(group_id, actor, tag)
    elif action == "cwl":
        next_state = {"unknown": "in", "in": "out", "out": "unknown"}[selected.cwl_opt_in]
        storage.set_cwl_opt_in(group_id, actor, tag, next_state)
    elif action == "delete":
        await update.callback_query.edit_message_text(
            f"Удалить игровую привязку {tag}? В Telegram-группе участник останется.",
            reply_markup=delete_confirmation(tag),
        )
        return
    elif action == "confirm":
        storage.delete_player_binding(group_id, tag, requester_id=actor)
    await accounts(update, context)


async def primary_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not ensure_private_chat(update) or not update.effective_user:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Используй /primary #ТЕГ")
        return
    try:
        tag = normalize_tag(context.args[0])
    except InvalidTagError:
        await update.message.reply_text("Некорректный тег.")
        return
    storage: BindingsStorage = context.application.bot_data["storage"]
    if storage.set_primary(settings.clan_group_id or 0, update.effective_user.id, tag):
        await update.message.reply_text(f"⭐ {tag} теперь основной аккаунт.")
    else:
        await update.message.reply_text("Этот тег не привязан к тебе.")


async def cwl_opt_in(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Local bot declaration for CWL; cannot alter in-game Supercell preferences."""
    if not update.message or not ensure_private_chat(update) or not update.effective_user:
        return
    if not context.args or context.args[-1].lower() not in {"in", "out", "unknown"}:
        await update.message.reply_text("Используй /cwlopt in|out или /cwlopt #ТЕГ in|out|unknown")
        return
    status = context.args[-1].lower()
    storage: BindingsStorage = context.application.bot_data["storage"]
    owner = update.effective_user.id
    tag = None
    if len(context.args) == 1:
        account = storage.get_binding(settings.clan_group_id or 0, owner)
        tag = account.coc_player_tag if account else None
    elif len(context.args) == 2:
        try:
            tag = normalize_tag(context.args[0])
        except InvalidTagError:
            pass
    if not tag:
        await update.message.reply_text("Тег не найден. Сначала /bind.")
        return
    if storage.set_cwl_opt_in(settings.clan_group_id or 0, owner, tag, status):
        await update.message.reply_text(f"🏆 Заявка на ЛВК для {tag}: {status}.")
    else:
        await update.message.reply_text("Нельзя менять заявку для чужого аккаунта.")


async def unlink_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Captain-only deletion, with a second explicit confirmation callback."""
    if not update.message or not ensure_private_chat(update):
        return
    if not await has_captain_access(update, context):
        await update.message.reply_text("Только для лидера или соруководителя.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("Используй /unlink #ТЕГ")
        return
    try:
        tag = normalize_tag(context.args[0])
    except InvalidTagError:
        await update.message.reply_text("Неверный игровой тег.")
        return
    await update.message.reply_text(
        f"Удалить привязку {tag} из базы? Участник останется в Telegram-группе.",
        reply_markup=delete_confirmation(tag, admin=True),
    )


async def unlink_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query:
        return
    await update.callback_query.answer()
    _, action, tag = (update.callback_query.data or "").split(":", 2)
    if action == "cancel":
        await update.callback_query.edit_message_text("Удаление отменено.")
        return
    if not await has_captain_access(update, context):
        await update.callback_query.edit_message_text("Нет прав руководителя клана.")
        return
    storage: BindingsStorage = context.application.bot_data["storage"]
    deleted = storage.delete_player_binding(
        settings.clan_group_id or 0, tag,
        requester_id=update.effective_user.id, administrator=True,
    )
    await update.callback_query.edit_message_text(
        f"{'Привязка удалена' if deleted else 'Привязка не найдена'}: {tag}."
    )


async def manual_last_seen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Captain's human observation of CoC online status, not API-provided lastSeen."""
    if not update.message or not ensure_private_chat(update):
        return
    if not await has_captain_access(update, context):
        await update.message.reply_text("Только руководитель клана может отмечать последнее посещение.")
        return
    args = context.args or []
    if len(args) not in {2, 3}:
        await update.message.reply_text(
            "Используй /lastseen #ТЕГ YYYY-MM-DD HH:MM (Берлин) или /lastseen #ТЕГ clear"
        )
        return
    try:
        tag = normalize_tag(args[0])
        observed = reported_last_seen(" ".join(args[1:]))
    except (ValueError, InvalidTagError):
        await update.message.reply_text(
            "Неверная дата. Варианты: /lastseen #ТЕГ 2d, /lastseen #ТЕГ 48h, "
            "/lastseen #ТЕГ YYYY-MM-DD HH:MM, /lastseen #ТЕГ clear"
        )
        return
    storage: BindingsStorage = context.application.bot_data["storage"]
    saved = storage.set_manual_last_seen(settings.clan_group_id or 0, tag, observed)
    await update.message.reply_text(
        f"{'Ручная отметка сохранена' if saved else 'Игрок не привязан'}: {tag}. "
        "Это наблюдение из игры, НЕ данные CoC API."
    )


async def unbind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not ensure_private_chat(update) or not update.effective_user:
        return
    storage: BindingsStorage = context.application.bot_data["storage"]
    owned = storage.get_bindings_for_user(settings.clan_group_id or 0, update.effective_user.id)
    if not owned:
        await update.message.reply_text("Нет привязанных аккаунтов.")
        return
    if not context.args:
        await accounts(update, context)
        return
    try:
        tag = normalize_tag(context.args[0])
    except InvalidTagError:
        await update.message.reply_text("Неверный игровой тег.")
        return
    if tag not in {b.coc_player_tag for b in owned}:
        await update.message.reply_text("Ты не владеешь этой привязкой.")
        return
    await update.message.reply_text(
        f"Удалить свой аккаунт {tag} из базы привязок?",
        reply_markup=delete_confirmation(tag),
    )


async def mytag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    try:
        if not ensure_private_chat(update):
            await update.message.reply_text("Please use /mytag in a private chat with the bot.")
            return
        storage: BindingsStorage = context.application.bot_data["storage"]
        binding = storage.get_binding(settings.clan_group_id or 0, update.effective_user.id)
        if not binding:
            await update.message.reply_text("No tag bound for your account.")
            return
        await update.message.reply_text(
            f"Your bound tag is {html.escape(binding.coc_player_tag)}",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to handle /mytag")
        await update.message.reply_text("Unexpected error occurred. Please try again.")


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query:
        return
    await update.callback_query.answer()
    action = update.callback_query.data
    handlers = {
        "menu_home": menu,
        "menu_topplayers": top_players,
        "menu_clan": clan,
        "menu_raids": clan_raids,
        "menu_games": clan_games,
        "menu_war": war,
        "menu_nextwar": next_war_analysis,
        "menu_cwl": cwl,
        "menu_progress": progress,
        "menu_accounts": accounts,
        "menu_captain": captain_report,
        "menu_player": player,
        "menu_profile": player,
        "menu_help": help_command,
    }
    if action in handlers:
        context.args = []
        await handlers[action](update, context)
    elif action == "menu_report":
        await update.callback_query.edit_message_text("Отчёт доступен только капитану.")
    else:
        await update.callback_query.edit_message_text(
            "Неизвестный раздел.", reply_markup=back_keyboard())


async def bind_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query:
        return
    await update.callback_query.answer()
    if not ensure_private_chat(update):
        await update.callback_query.edit_message_text("Привязка доступна в личном чате бота.")
        return
    await show_player_picker(update, context)


async def bind_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query:
        return
    try:
        await update.callback_query.answer()
        context.user_data.pop("awaiting_tag", None)
        context.user_data.pop("awaiting_player_token", None)
        context.user_data.pop("pending_coc_tag", None)
        context.user_data.pop("picker_members", None)
        await update.callback_query.edit_message_text("Привязка отменена.")
    except Exception:  # noqa: BLE001
        logger.exception("Failed to handle bind_cancel callback")


async def private_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ensure a private message is processed only once."""
    if context.user_data.get("awaiting_tag") or context.user_data.get("awaiting_player_token"):
        await capture_tag(update, context)
    else:
        await handle_private_message(update, context)


async def capture_tag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not ensure_private_chat(update):
        return
    if context.user_data.get("awaiting_player_token"):
        await verify_player_ownership(update, context)
        return
    if not context.user_data.get("awaiting_tag"):
        return
    try:
        raw_input = update.message.text or ""
        extracted = extract_tag(raw_input)
        if not extracted:
            await update.message.reply_text(
                "Invalid player tag format. Example: #2PRGP0L22",
                reply_markup=bind_cancel_keyboard(),
            )
            return
        # Only clear awaiting_tag after successful processing
        await process_binding(update, context, extracted)
        context.user_data["binding_offered"] = False
    except Exception:  # noqa: BLE001
        logger.exception("Failed to capture tag message")
        # Don't clear awaiting_tag - let user try again
        await update.message.reply_text(
            "Unexpected error occurred. Please try again.",
            reply_markup=bind_cancel_keyboard(),
        )


async def verify_player_ownership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Verify an in-game player token and never persist it."""
    if not update.message or not update.effective_chat:
        return
    tag = context.user_data.get("pending_coc_tag")
    if not tag:
        context.user_data.pop("awaiting_player_token", None)
        await update.message.reply_text("Сессия привязки истекла. Отправьте /bind.")
        return
    player_token = (update.message.text or "").strip()
    try:
        await update.message.delete()
    except Exception:
        pass
    if not player_token or len(player_token) > 256:
        await context.bot.send_message(update.effective_chat.id, "Неверный формат токена.")
        return
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.post(
                build_url(f"/verify-player/{encode_tag(tag)}"),
                json={"token": player_token},
            )
            response.raise_for_status()
            valid = response.json().get("verified") is True
    except httpx.HTTPStatusError as exc:
        logger.warning("Player verification failed: HTTP %s", exc.response.status_code)
        await context.bot.send_message(update.effective_chat.id, "Ошибка проверки игрока. Повторите позже.")
        return
    except httpx.RequestError:
        logger.warning("Player verification service unreachable")
        await context.bot.send_message(update.effective_chat.id, "Сервис проверки временно недоступен.")
        return
    finally:
        player_token = None
    if not valid:
        await context.bot.send_message(
            update.effective_chat.id, "❌ Токен не подходит выбранному игроку. Попробуйте ещё раз."
        )
        return
    context.user_data.pop("awaiting_player_token", None)
    context.user_data.pop("pending_coc_tag", None)
    await process_binding(update, context, tag, verified=True)


async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    if ensure_group_chat(update):
        await update.message.reply_text(
            f"Chat ID: `{update.effective_chat.id}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await update.message.reply_text(
        "Please run /chatid in the target group chat to obtain its ID."
    )


async def grouplink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send group invite link to bound members (if they lost it)."""
    if not update.message or not update.effective_user:
        return
    if not ensure_private_chat(update):
        return
    
    try:
        # Check if user is bound
        storage: BindingsStorage = context.application.bot_data["storage"]
        binding = storage.get_binding(settings.clan_group_id or 0, update.effective_user.id)
        
        if not binding:
            await update.message.reply_text(
                "❌ Вы не привязаны к боту. Используйте /bind чтобы привязаться."
            )
            return
        
        if settings.clan_group_id is None:
            await update.message.reply_text(
                "⚠️ Группа клана ещё не настроена. Свяжитесь с администратором."
            )
            return
        
        # Generate new invite link
        expire_at = datetime.now(timezone.utc) + timedelta(minutes=settings.invite_ttl_minutes)
        invite = await context.bot.create_chat_invite_link(
            chat_id=settings.clan_group_id,
            expire_date=expire_at,
            member_limit=1,
        )
        
        logger.info(
            "Group link sent user_id=%s tag=%s expire_at=%s",
            update.effective_user.id,
            binding.coc_player_tag,
            expire_at.isoformat(),
        )
        
        await update.message.reply_text(
            f"✅ Ссылка для присоединения к группе клана:\n"
            f"{invite.invite_link}\n\n"
            f"⏱️ Ссылка действительна {settings.invite_ttl_minutes} минут",
            disable_web_page_preview=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to send group link: %s", exc)
        await update.message.reply_text(
            "❌ Ошибка при создании ссылки. Попробуйте позже."
        )


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Open the verified linked account without duplicating formatters."""
    if not ensure_private_chat(update):
        return
    context.args = []
    await player(update, context)


async def settings_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if not ensure_private_chat(update):
        await update.message.reply_text("Please use /settings in a private chat with the bot.")
        return
    await update.message.reply_text("⚙️ Настройки: привязка через /bind, изменение через /unbind.\n"
                                   "Параметры сервера хранятся в Home Assistant и не показываются участникам.")


async def verify_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Verify that new members are bound to the bot before joining clan group."""
    if not update.message or not update.message.new_chat_members:
        return
    if update.effective_chat is None:
        return
    if settings.clan_group_id is None or update.effective_chat.id != settings.clan_group_id:
        return
    storage: BindingsStorage = context.application.bot_data["storage"]
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        binding = storage.get_binding(settings.clan_group_id, member.id)
        if not binding:
            try:
                # Send warning message with bind button
                mention = format_mention(member.id, member.full_name)
                await update.message.reply_text(
                    f"⚠️ {mention} попытался присоединиться, но не привязан к боту!\n\n"
                    f"Чтобы присоединиться к группе клана, нужно:\n"
                    f"1. Написать боту @{context.bot.username} в личные сообщения\n"
                    f"2. Нажать кнопку 'Привязать' и ввести свой тег\n\n"
                    f"После привязки вы сможете присоединиться к группе.",
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                # Remove from group (ban then unban to kick)
                await context.bot.ban_chat_member(update.effective_chat.id, member.id)
                await context.bot.unban_chat_member(update.effective_chat.id, member.id)
                logger.info(
                    "Unbound member removed user_id=%s chat_id=%s",
                    member.id,
                    update.effective_chat.id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to remove unbound member user_id=%s error=%s",
                    member.id,
                    exc,
                )
            continue
        
        # Member is bound - welcome them with CoC info
        mention = format_mention(member.id, member.full_name)
        player_tag = html.escape(binding.coc_player_tag)
        
        # Try to fetch player info for nickname
        coc_name = None
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                path = f"/player/{quote(binding.coc_player_tag)}"
                response = await client.get(build_url(path))
                if response.status_code == 200:
                    player_data = response.json()
                    coc_name = player_data.get("name", "")
        except Exception:  # noqa: BLE001
            pass  # Fallback if API fails
        
        if coc_name:
            await assign_game_tag(context, update.effective_chat.id, member.id, coc_name)

        # Welcome without pinning every new member or requiring pin permissions.
        if coc_name:
            message = (
                f"✅ {mention}\n"
                f"🎮 <b>Ник в игре:</b> {html.escape(coc_name)}\n"
                f"🏷️ <b>Тег:</b> {player_tag}\n"
                "Добро пожаловать в клан! 🎉"
            )
        else:
            message = f"✅ {mention} присоединился как {player_tag}"
        try:
            await update.message.reply_text(
                message, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
            )
        except Exception:
            logger.warning("Could not send welcome message for member user_id=%s", member.id)


async def weekly_activity_report_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send weekly activity report every Sunday to Lex."""
    # Check if it's Sunday (weekday() = 6)
    now = datetime.now(timezone.utc)
    if now.weekday() != 6:  # Sunday
        return
    
    # Get Lex's user ID from database using their CoC tag
    if not settings.lex_coc_tag:
        logger.warning("LEX_COC_TAG not configured for weekly activity report")
        return
    
    storage: BindingsStorage = context.application.bot_data["storage"]
    lex_user_id = storage.get_user_id_by_tag(settings.clan_group_id or 0, settings.lex_coc_tag)
    if not lex_user_id:
        logger.warning("Lex not found in bindings by tag=%s", settings.lex_coc_tag)
        return
    
    await send_activity_report_to_user(context, lex_user_id)


async def send_activity_report_to_user(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Send activity report to specific user."""
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        try:
            payload = await fetch_json(client, "/activity-report")
            message = format_activity_report(payload)
            await context.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            logger.info("Activity report sent to user %s", user_id)
        except httpx.HTTPStatusError as exc:
            logger.warning("Backend error fetching activity report: %s", exc)
        except httpx.RequestError as exc:
            logger.warning("Backend unreachable for activity report: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to send activity report: %s", exc)


async def war_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not settings.war_reminder_enabled:
        return
    storage: BindingsStorage = context.application.bot_data["storage"]
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        try:
            payload = await fetch_json(client, "/war")
        except httpx.HTTPStatusError as exc:
            logger.warning("Backend error fetching war data: %s", exc)
            return
        except httpx.RequestError as exc:
            logger.warning("Backend unreachable for war reminder: %s", exc)
            return
    if payload.get("state") != "inWar":
        return
    end_time = parse_coc_time(payload.get("endTime"))
    if end_time is None:
        logger.warning("Could not parse war end time")
        return
    now = datetime.now(timezone.utc)
    time_to_end = end_time - now
    if time_to_end <= timedelta(0):
        return
    if time_to_end > timedelta(hours=settings.war_reminder_window_hours):
        return
    clan_members = payload.get("clan", {}).get("members", [])
    tags_missing_attacks: set[str] = set()
    members_by_tag: dict[str, dict] = {}
    for member in clan_members:
        attacks_allowed = int(payload.get("attacksPerMember") or 1)
        if attacks_used(member) >= attacks_allowed or not member.get("tag"):
            continue
        try:
            tag = normalize_tag(member["tag"])
            tags_missing_attacks.add(tag)
            members_by_tag[tag] = member
        except InvalidTagError:
            logger.warning("Skipping invalid member tag in war payload")
    if not tags_missing_attacks:
        return
    for group_id in storage.get_group_ids():
        bindings = storage.get_bindings_for_tags(group_id, tags_missing_attacks)
        if not bindings:
            continue
        user_ids = [binding.telegram_user_id for binding in bindings]
        cooldowns = storage.get_cooldowns(group_id, user_ids)
        mentions: list[str] = []
        reminded_user_ids: list[int] = []
        
        # Multiple CoC accounts per user: send ONE Telegram mention with all missed attacks.
        grouped: dict[int, list[str]] = {}
        names_by_user: dict[int, str] = {}
        for binding in bindings:
            tag = binding.coc_player_tag
            name = str(members_by_tag.get(tag, {}).get("name") or tag)
            grouped.setdefault(binding.telegram_user_id, []).append(html.escape(name))
            names_by_user[binding.telegram_user_id] = binding.telegram_full_name
        for user_id, names in grouped.items():
            last_reminded = cooldowns.get(user_id)
            if last_reminded and now - last_reminded < timedelta(hours=1):
                continue
            mention = format_mention(user_id, names_by_user[user_id])
            mentions.append(f"{mention} ({', '.join(names)})")
            reminded_user_ids.append(user_id)

        if not mentions:
            continue
        message = (
            "⚔️ Напоминание: "
            + ", ".join(mentions)
            + " — остались неиспользованные атаки."
        )
        try:
            await context.bot.send_message(
                chat_id=group_id,
                text=message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to send reminder to group %s: %s", group_id, exc)
            continue
        storage.set_cooldowns(group_id, reminded_user_ids, now)


async def top_players(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show most and least active clan members."""
    if not update.message and not update.callback_query:
        return
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        try:
            payload = await fetch_json(client, "/activity")
            
            most_active = payload.get("mostActive", [])
            least_active = payload.get("leastActive", [])
            
            msg = "🏆 *Активность клана*\n\n"
            
            # Most active
            msg += "⭐ *Больше всего доната / атак (не время онлайн):*\n"
            for i, player in enumerate(most_active, 1):
                name = player.get("name", "Unknown")
                donations = player.get("donations", 0)
                attacks = player.get("warAttacks", 0)
                th = player.get("townHallLevel", "?")
                msg += f"{i}. {name} (TH{th})\n"
                msg += f"   💰 {donations} доната | ⚔️ {attacks} атак\n"
            
            msg += "\n"
            
            # Least active
            msg += "📉 *Меньше всего доната / атак (не время онлайн):*\n"
            for i, player in enumerate(least_active, 1):
                name = player.get("name", "Unknown")
                donations = player.get("donations", 0)
                attacks = player.get("warAttacks", 0)
                th = player.get("townHallLevel", "?")
                msg += f"{i}. {name} (TH{th})\n"
                msg += f"   💰 {donations} доната | ⚔️ {attacks} атак\n"
            
            await send_or_edit_message(update, msg)
        except httpx.HTTPStatusError as exc:
            logger.warning("Backend error: %s", exc)
            await send_or_edit_message(update, "Failed to fetch player activity. Try again later.")
        except httpx.RequestError as exc:
            logger.warning("Backend unreachable: %s", exc)
            await send_or_edit_message(update, "Backend is unreachable.")
        except Exception:  # noqa: BLE001
            logger.exception("Unhandled error in /top-players")
            await send_or_edit_message(update, "Unexpected error occurred.")


async def clan_raids(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message and not update.callback_query:
        return
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            payload = await fetch_json(client, "/raids")
        await send_or_edit_message(update, format_raid_message(payload), parse_mode=ParseMode.HTML)
    except (httpx.HTTPStatusError, httpx.RequestError):
        logger.exception("Raid API unavailable")
        await send_or_edit_message(update, "🏛️ Не удалось получить данные о рейдах.")


async def clan_games(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show clan games (Clan Games) status."""
    if not update.message and not update.callback_query:
        return
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        try:
            payload = await fetch_json(client, "/games")
            
            # If no data or no games info, send message
            if not payload or "currentGames" not in payload:
                message = "ℹ️ Информация об играх кланов недоступна."
                await send_or_edit_message(update, message)
                return
            
            current_games = payload.get("currentGames")
            if not current_games:
                message = ("ℹ️ Clash of Clans API не предоставляет данные об Играх кланов."
                           if payload.get("unsupported") else "ℹ️ Информация об играх недоступна.")
                await send_or_edit_message(update, message)
                return
            
            # Format games info
            state = current_games.get("state", "unknown")
            start_time = current_games.get("startTime", "N/A")
            end_time = current_games.get("endTime", "N/A")
            
            if state == "inProgress":
                # Show current score
                score = current_games.get("score", "N/A")
                
                msg = "🎮 *Игры кланов*\n\n"
                msg += "*Статус:* Идут в данный момент 🏁\n"
                msg += f"*Начало:* {start_time}\n"
                msg += f"*Конец:* {end_time}\n"
                msg += f"*Очки:* {score}\n"
            else:
                # Show status when not in progress
                msg = "🎮 *Игры кланов*\n\n"
                msg += "*Статус:* Не проводятся\n"
                msg += f"*Начало:* {start_time}\n"
                msg += f"*Конец:* {end_time}\n"
            
            await send_or_edit_message(update, msg)
        except httpx.HTTPStatusError as exc:
            logger.warning("Backend error: %s", exc)
            await send_or_edit_message(update, "ℹ️ Информация об играх недоступна.")
        except httpx.RequestError as exc:
            logger.warning("Backend unreachable: %s", exc)
            await send_or_edit_message(update, "Backend is unreachable.")
        except Exception:  # noqa: BLE001
            logger.exception("Unhandled error in /clan-raids")
            await send_or_edit_message(update, "Unexpected error occurred.")


async def ai_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with AI-generated text when bot is mentioned or replied-to using Groq API or fallback."""
    if not update.message or not update.message.text or ensure_private_chat(update):
        return

    text = update.message.text
    
    # Detect if bot is mentioned
    bot_username = None
    try:
        bot_username = (context.bot.username or "").lower()
        logger.debug(f"ai_reply_handler: bot username = {bot_username}")
    except Exception as e:
        logger.debug(f"ai_reply_handler: failed to get bot username: {e}")
        bot_username = os.getenv("BOT_USERNAME", "").lower()

    mentioned = False
    if bot_username and f"@{bot_username}" in (text or "").lower():
        mentioned = True
        logger.info("ai_reply_handler: bot mentioned directly in text")
    
    # Check if replying to bot's message
    if not mentioned and update.message.reply_to_message:
        try:
            replied_to_bot = (
                update.message.reply_to_message.from_user and
                update.message.reply_to_message.from_user.id == context.bot.id
            )
            if replied_to_bot:
                mentioned = True
                logger.info("ai_reply_handler: replying to bot message")
        except Exception as e:
            logger.debug(f"ai_reply_handler: error checking reply: {e}")

    if not mentioned:
        logger.debug("ai_reply_handler: bot not mentioned, returning")
        return

    logger.info("AI reply requested in chat %s", update.effective_chat.id if update.effective_chat else "?")
    
    # Try Groq API (free, fast)
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        logger.info("ai_reply_handler: attempting Groq API")
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
            
            # Use the fastest free model available
            response = client.chat.completions.create(
                model="mixtral-8x7b-32768",  # Free tier model
                messages=[
                    {"role": "system", "content": "You are a helpful Telegram bot assistant. Respond concisely in the same language as the user."},
                    {"role": "user", "content": text}
                ],
                max_tokens=256,
                temperature=0.7,
            )
            
            reply = response.choices[0].message.content.strip()
            if reply:
                logger.info(f"ai_reply_handler: Groq reply: {reply[:100]}")
                await update.message.reply_text(reply)
                return
        except Exception as exc:
            logger.warning(f"ai_reply_handler: Groq failed: {exc}")

    # Try OpenAI if key is set
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        logger.info("ai_reply_handler: attempting OpenAI")
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                headers = {"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"}
                body = {
                    "model": "gpt-3.5-turbo",
                    "messages": [
                        {"role": "system", "content": "You are a helpful Telegram bot assistant. Respond concisely."},
                        {"role": "user", "content": text}
                    ],
                    "max_tokens": 256,
                }
                resp = await client.post("https://api.openai.com/v1/chat/completions", json=body, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                reply = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                if reply:
                    logger.info(f"ai_reply_handler: OpenAI reply: {reply[:100]}")
                    await update.message.reply_text(reply)
                    return
        except Exception as exc:
            logger.warning(f"ai_reply_handler: OpenAI failed: {exc}")

    # Fallback
    logger.warning("ai_reply_handler: using fallback reply")
    safe_reply = f"Я упомянут! Вы написали: {text[:400]}"
    await update.message.reply_text(safe_reply)


async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Observed development between real daily CoC profile snapshots."""
    if not update.effective_user:
        return
    storage: BindingsStorage = context.application.bot_data["storage"]
    binding = storage.get_binding(settings.clan_group_id or 0, update.effective_user.id)
    if not binding:
        await send_or_edit_message(update, "Сначала привяжи аккаунт через /bind.")
        return
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            data = await fetch_json(client, f"/progress/{encode_tag(binding.coc_player_tag)}")
        lines = ["📈 <b>Развитие аккаунта</b>",
                 html.escape(str(data.get("name") or binding.coc_player_tag)),
                 f"Снимок: {data.get('snapshotDay')}"]
        if not data.get("historyAvailable"):
            lines.append("\nПервый снимок сохранён. Сравнение появится после следующего дня.")
        else:
            lines.append(f"Сравнение с: {data.get('comparisonDay')}")
            changes = data.get("changes") or {}
            names = {"townHallLevel": "Ратуша", "expLevel": "Опыт",
                     "bestTrophies": "Рекорд кубков", "warStars": "Военные звёзды",
                     "clanCapitalContributions": "Вклад в столицу"}
            for key, label in names.items():
                if key in changes:
                    delta = changes[key]
                    lines.append(f"• {label}: {delta['from']} → {delta['to']}")
            for field, label in (("heroes", "Герои"), ("heroEquipment", "Снаряжение")):
                for item, delta in changes.get(field, {}).items():
                    lines.append(f"• {label}: {html.escape(item)} {delta['from']} → {delta['to']}")
            if not changes:
                lines.append("Изменений относительно предыдущего дня не найдено.")
        lines.append("\nℹ️ Только изменения, подтверждённые API; не таймеры улучшений.")
        await send_or_edit_message(update, "\n".join(lines)[:4000], parse_mode=ParseMode.HTML)
    except (httpx.RequestError, httpx.HTTPStatusError):
        logger.warning("Player progress unavailable")
        await send_or_edit_message(update, "Не удалось получить историю развития.")


async def cwl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message and not update.callback_query:
        return
    try:
        async with httpx.AsyncClient(timeout=max(45, settings.request_timeout_seconds)) as client:
            payload = await fetch_json(client, "/cwl")
        await send_or_edit_message(update, format_cwl_message(payload), parse_mode=ParseMode.HTML)
    except (httpx.HTTPStatusError, httpx.RequestError):
        logger.warning("CWL service unavailable")
        await send_or_edit_message(update, "🏆 Сведения о CWL пока недоступны.")


async def next_war_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Rebuild war/CWL recommendations with weights, owner limits and evidence labels."""
    if not update.effective_user:
        return
    msg = await send_or_edit_message(update, "⏳ Анализирую КВ/ЛВК и привязанные аккаунты...", parse_mode=None)
    try:
        async with httpx.AsyncClient(timeout=max(45, settings.request_timeout_seconds)) as client:
            response = await client.get(build_url("/next-war"))
            response.raise_for_status()
            raw = response.json()
        storage: BindingsStorage = context.application.bot_data["storage"]
        mode = context.user_data.get("selection_mode", "war")
        result = build_selection(
            raw, storage, settings.clan_group_id or 0, mode,
            policy_from_settings(settings),
        )
        result["viewerIsCaptain"] = await has_captain_access(update, context)
        context.user_data["lineup_snapshot"] = result
        await msg.edit_text(lineup_message(result), parse_mode=ParseMode.HTML,
                            reply_markup=lineup_keyboard(data=result))
    except (httpx.HTTPStatusError, httpx.RequestError):
        logger.exception("War planning API unavailable")
        await msg.edit_text("Данные клана временно недоступны.", reply_markup=back_keyboard())
    except Exception:
        logger.exception("Lineup calculations failed")
        await msg.edit_text("Не удалось рассчитать состав. Проверь журнал аддона.", reply_markup=back_keyboard())


async def lineup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query:
        return
    await update.callback_query.answer()
    _, stage, page_raw = (update.callback_query.data or "").split(":", 2)
    if stage in {"war", "cwl"}:
        context.user_data["selection_mode"] = stage
        await next_war_analysis(update, context)
        return
    if stage == "refresh":
        await next_war_analysis(update, context)
        return
    snapshot = context.user_data.get("lineup_snapshot")
    if not snapshot:
        await update.callback_query.edit_message_text(
            "Расчёт устарел. Загрузи данные заново.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Загрузить состав", callback_data="menu_nextwar")],
            ]))
        return
    # Never reveal sensitive management watchlists based solely on a crafted callback.
    if stage in {"kick", "promote", "bonus"}:
        if not await has_captain_access(update, context):
            await update.callback_query.edit_message_text(
                "Это закрытый раздел руководства клана.", reply_markup=back_keyboard())
            return
    page = max(0, min(50, int(page_raw)))
    if stage == "player" and not snapshot.get("viewerIsCaptain"):
        # Player details are available, but manually-entered last login is captain-only.
        snapshot = dict(snapshot)
        snapshot["hideManualLastSeen"] = True
    await update.callback_query.edit_message_text(
        lineup_message(snapshot, stage, page), parse_mode=ParseMode.HTML,
        reply_markup=lineup_keyboard(stage, page, snapshot))


async def main() -> None:
    """Main async function to start the bot."""
    logger.info("Bot environment snapshot: %s", env_snapshot())
    logger.info("Bot settings snapshot: %s", settings_snapshot())
    missing = validate_settings()
    if missing:
        logger.error("Settings validation failed:\n- %s", "\n- ".join(missing))
        logger.error(
            "Fix the missing/invalid environment variables and restart the bot."
        )
        raise SystemExit(1)
    if settings.clan_group_id is None:
        logger.warning(
            "CLAN_GROUP_ID is not set. Invite links and member verification are disabled. "
            "Add the bot to the clan group and run /chatid to obtain the ID."
        )
    logger.info("Environment validation passed")

    from telegram.request import HTTPXRequest
    request = HTTPXRequest(read_timeout=settings.request_timeout_seconds)
    application = ApplicationBuilder().token(settings.telegram_bot_token).request(request).build()

    application.bot_data["storage"] = BindingsStorage(settings.bindings_db_path)

    application.add_handler(MessageHandler(filters.COMMAND, log_any_command), group=-1)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("clan", clan))
    application.add_handler(CommandHandler("topplayers", top_players))
    application.add_handler(CommandHandler("player", player))
    application.add_handler(CommandHandler("war", war))
    application.add_handler(CommandHandler("nextwar", next_war_analysis))
    application.add_handler(CommandHandler("cwl", cwl))
    application.add_handler(CommandHandler("progress", progress))
    application.add_handler(CommandHandler("captain", captain_report))
    application.add_handler(CommandHandler("raids", clan_raids))
    application.add_handler(CommandHandler("games", clan_games))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("bind", bind))
    application.add_handler(CommandHandler("unbind", unbind))
    application.add_handler(CommandHandler("accounts", accounts))
    application.add_handler(CommandHandler("primary", primary_account))
    application.add_handler(CommandHandler("cwlopt", cwl_opt_in))
    application.add_handler(CommandHandler("unlink", unlink_admin))
    application.add_handler(CommandHandler("lastseen", manual_last_seen))
    application.add_handler(CommandHandler("mytag", mytag))
    application.add_handler(CommandHandler("chatid", chatid))
    application.add_handler(CommandHandler("grouplink", grouplink))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("settings", settings_info))
    application.add_handler(CallbackQueryHandler(bind_start, pattern="^bind_start$"))
    application.add_handler(CallbackQueryHandler(bind_cancel, pattern="^bind_cancel$"))
    application.add_handler(CallbackQueryHandler(account_callback, pattern=r"^acct:(primary|cwl|delete|confirm|cancel):"))
    application.add_handler(CallbackQueryHandler(unlink_admin_callback, pattern=r"^admin:(confirm|cancel):"))
    application.add_handler(CallbackQueryHandler(roster_callback, pattern=r"^pick:(manual|page|player):[0-9]+$"))
    application.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu_"))
    application.add_handler(CallbackQueryHandler(lineup_callback, pattern=r"^lineup:(main|bench|inactive|out|twinks|confirm|kick|promote|bonus|weights|details|about|player|refresh|war|cwl):[0-9]+$"))
    
    # One router avoids two handlers replying to a successful token message.
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, private_text_router),
        group=0,
    )

    # AI mention handler: replies when the bot is mentioned or replied-to (group=2 to run last)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS, ai_reply_handler),
        group=2,
    )
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, verify_new_members))
    application.add_error_handler(handle_handler_exception)

    if settings.clan_group_id is not None:
        application.job_queue.run_daily(
            sync_tags_daily,
            time=time(hour=9, minute=0, tzinfo=ZoneInfo("Europe/Berlin")),
            name="clan-game-nickname-sync",
        )

    if settings.war_reminder_enabled:
        application.job_queue.run_repeating(
            war_reminder_job,
            interval=timedelta(minutes=settings.war_reminder_interval_minutes),
            first=timedelta(minutes=1),
            name="war-reminder",
        )

    logger.info("Telegram bot starting")
    await application.initialize()
    try:
        await sync_bot_commands(application.bot)
    except Exception:
        logger.exception("Could not sync Telegram command menu")
    await application.start()
    await application.updater.start_polling()
    
    # Register weekly activity report after polling starts
    if settings.lex_coc_tag:
        application.job_queue.run_daily(
            weekly_activity_report_job,
            time=time(hour=10, minute=0, tzinfo=timezone.utc),
            days=(6,),  # 6 = Sunday
            name="weekly-activity-report",
        )

    try:
        await asyncio.Event().wait()
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        logger.info("Telegram bot shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
