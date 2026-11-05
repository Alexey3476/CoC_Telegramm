import asyncio
import html
import os
import logging
import re
from urllib.parse import quote
from datetime import datetime, timedelta, timezone, time
from typing import Any

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.backend_client import build_url, fetch_json
from app.bindings_storage import Binding, BindingsStorage
from app.settings import env_snapshot, settings, settings_snapshot, validate_settings

log_level = logging.DEBUG if settings.debug else logging.INFO
logging.basicConfig(level=log_level, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)
logger.debug("Debug mode enabled")

TAG_PATTERN = re.compile(r"^[0289PYLQGRJCUV]+$")
TAG_EXTRACT_PATTERN = re.compile(r"#?[0289PYLQGRJCUV]{4,}")


def format_clan(payload: dict[str, Any]) -> str:
    """Format clan information with capital details."""
    msg = (
        f"*{payload.get('name', 'Clan')}*\n"
        f"🏷️ Tag: `{payload.get('tag', 'N/A')}`\n"
        f"📊 Level: {payload.get('clanLevel', 'N/A')}\n"
        f"👥 Members: {payload.get('members', 'N/A')}\n"
        f"⚔️ War League: {payload.get('warLeague', {}).get('name', 'N/A')}\n"
    )
    
    # Add capital info if available
    capital = payload.get('clanCapital', {})
    if capital:
        capital_name = capital.get('name', 'Capital')
        capital_level = capital.get('capitalHallLevel', 'N/A')
        msg += f"\n🏛️ *Capital:* {capital_name} (Hall Level: {capital_level})\n"
    
    return msg


def format_player(payload: dict[str, Any]) -> str:
    return (
        f"*{payload.get('name', 'Player')}*\n"
        f"Tag: `{payload.get('tag', 'N/A')}`\n"
        f"Town Hall: {payload.get('townHallLevel', 'N/A')}\n"
        f"Trophies: {payload.get('trophies', 'N/A')}\n"
        f"Best Trophies: {payload.get('bestTrophies', 'N/A')}\n"
        f"Clan: {payload.get('clan', {}).get('name', 'No clan')}\n"
    )


def format_war(payload: dict[str, Any]) -> str:
    """Format war information with current status."""
    state = payload.get('state', 'N/A')
    team_size = payload.get('teamSize', 'N/A')
    start_time = payload.get('startTime', 'N/A')
    end_time = payload.get('endTime', 'N/A')
    
    msg = f"⚔️ *Война клана*\n"
    msg += f"*Статус:* {state}\n"
    msg += f"*Размер:* {team_size}v{team_size}\n"
    msg += f"*Начало:* {start_time}\n"
    msg += f"*Конец:* {end_time}\n"
    
    # Add current war status if in war
    if state == "inWar":
        clan_team = payload.get('clan', {})
        opponent = payload.get('opponent', {})
        clan_destruction = clan_team.get('destructionPercentage', 0)
        opponent_destruction = opponent.get('destructionPercentage', 0)
        
        msg += f"\n*Текущий статус войны*\n"
        msg += f"🏛️ *Наш клан:* {clan_team.get('name', 'N/A')} - {clan_destruction:.1f}% разрушено\n"
        msg += f"⚔️ *Враги:* {opponent.get('name', 'N/A')} - {opponent_destruction:.1f}% разрушено\n"
    
    return msg


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
        update.message.text,
    )


def bind_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Привязать", callback_data="bind_start")]]
    )


def bind_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Отмена", callback_data="bind_cancel")]]
    )


def main_menu_keyboard(user_id: int | None = None) -> InlineKeyboardMarkup:
    """Compact main menu with callbacks supported by the bot."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👥 Топ игроков", callback_data="menu_topplayers"),
            InlineKeyboardButton("🏛️ Рейды", callback_data="menu_raids"),
        ],
        [
            InlineKeyboardButton("🎮 Игры кланов", callback_data="menu_games"),
            InlineKeyboardButton("🏘️ Клан", callback_data="menu_clan"),
        ],
        [
            InlineKeyboardButton("📊 Война", callback_data="menu_war"),
            InlineKeyboardButton("⚔️ Следующая война", callback_data="menu_nextwar"),
        ],
        [
            InlineKeyboardButton("👤 Игрок", callback_data="menu_player"),
            InlineKeyboardButton("⚙️ Привязка", callback_data="bind_start"),
        ],
    ])


async def send_or_edit_message(update: Update, text: str, parse_mode: str = ParseMode.MARKDOWN, reply_markup = None):
    """Send message for regular command or edit for callback query."""
    if update.message:
        return await update.message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    elif update.callback_query:
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
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        # Group chat
        await update.message.reply_text(
            "🎮 Привет! Напиши мне в личку (@bot_username) чтобы привязать аккаунт и присоединиться к группе!"
        )
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to handle /start: %s", e, exc_info=settings.debug)


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show main menu with all bot functions."""
    if not update.message:
        return
    try:
        storage: BindingsStorage = context.application.bot_data["storage"]
        binding = storage.get_binding(settings.clan_group_id or 0, update.effective_user.id)
        
        # Check if this is Lex
        is_lex = binding and settings.lex_coc_tag and binding.coc_player_tag == settings.lex_coc_tag
        
        # Create base keyboard
        keyboard = [
            [
                InlineKeyboardButton("👥 Топ игроков", callback_data="menu_topplayers"),
                InlineKeyboardButton("🏛️ Рейды", callback_data="menu_raids"),
            ],
            [
                InlineKeyboardButton("🎮 Игры кланов", callback_data="menu_games"),
                InlineKeyboardButton("🏘️ Информация о клане", callback_data="menu_clan"),
            ],
            [
                InlineKeyboardButton("📊 Война", callback_data="menu_war"),
                InlineKeyboardButton("⚔️ Следующая война", callback_data="menu_nextwar"),
            ],
            [
                InlineKeyboardButton("👤 Информация об игроке", callback_data="menu_player"),
                InlineKeyboardButton("⚙️ Привязка", callback_data="bind_start"),
            ],
        ]
        
        # Add report button for Lex
        if is_lex:
            keyboard.append([
                InlineKeyboardButton("📋 Отчет об активности", callback_data="menu_report"),
            ])
        
        await update.message.reply_text(
            "🎮 *Меню бота*\n\n"
            "Выберите функцию:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to handle /menu: %s", e, exc_info=settings.debug)


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
            f"✅ Вы привязаны как {html.escape(binding.coc_player_tag)}\n\n"
            f"Что дальше?",
            reply_markup=main_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
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
    if not update.message and not update.callback_query:
        return
    
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        try:
            payload = await fetch_json(client, "/clan")
            message = format_clan(payload)
            if update.callback_query:
                await update.callback_query.edit_message_text(message, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
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
                message = "Backend error while fetching clan data."
            if update.callback_query:
                await update.callback_query.edit_message_text(message)
            else:
                await update.message.reply_text(message)
        except httpx.RequestError as exc:
            logger.warning("Backend unreachable: %s", exc)
            message = "Backend is unreachable. Please try again later."
            if update.callback_query:
                await update.callback_query.edit_message_text(message)
            else:
                await update.message.reply_text(message)
        except Exception:  # noqa: BLE001
            logger.exception("Unhandled error in /clan")
            message = "Unexpected error occurred. Please try again."
            if update.callback_query:
                await update.callback_query.edit_message_text(message)
            else:
                await update.message.reply_text(message)


async def player(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message and not update.callback_query:
        return
    
    storage: BindingsStorage = context.application.bot_data["storage"]
    
    # Determine the tag to fetch
    tag = None
    if context.args and context.args[0].lower() not in ("я", "me"):
        # User provided a tag as argument
        try:
            tag = normalize_tag(context.args[0])
        except InvalidTagError:
            message = "Неверный формат тега игрока."
            if update.callback_query:
                await update.callback_query.edit_message_text(message)
            else:
                await update.message.reply_text(message)
            return
    else:
        # User didn't provide tag or said "я" - use their binding
        binding = storage.get_binding(settings.clan_group_id or 0, update.effective_user.id)
        if not binding:
            message = "Пожалуйста напишите ник игрока или напишите 'я'"
            if update.callback_query:
                await update.callback_query.edit_message_text(message)
            else:
                await update.message.reply_text(message)
            return
        tag = binding.coc_player_tag
    
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        try:
            payload = await fetch_json(client, f"/player/{encode_tag(tag)}")
            message = format_player(payload)
            if update.callback_query:
                await update.callback_query.edit_message_text(message, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.warning("Backend error: %s", exc)
            if status == 400:
                message = "Неверный формат тега игрока."
            elif status == 404:
                message = "Игрок не найден."
            elif status == 401:
                message = "Токен бэкенда недействителен."
            elif status == 403:
                message = "IP бэкенда не в списке разрешенных для Clash of Clans."
            elif status == 429:
                message = "Лимит запросов. Попробуйте позже."
            elif status == 504:
                message = "Бэкенд не смог соединиться с Clash of Clans."
            else:
                message = "Ошибка при получении данных игрока."
            if update.callback_query:
                await update.callback_query.edit_message_text(message)
            else:
                await update.message.reply_text(message)
        except httpx.RequestError as exc:
            logger.warning("Backend unreachable: %s", exc)
            message = "Бэкенд недоступен. Попробуйте позже."
            if update.callback_query:
                await update.callback_query.edit_message_text(message)
            else:
                await update.message.reply_text(message)
        except Exception:  # noqa: BLE001
            logger.exception("Unhandled error in /player")
            message = "Неожиданная ошибка. Попробуйте позже."
            if update.callback_query:
                await update.callback_query.edit_message_text(message)
            else:
                await update.message.reply_text(message)


async def war(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message and not update.callback_query:
        return
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        try:
            payload = await fetch_json(client, "/war")
            await send_or_edit_message(update, format_war(payload))
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


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        menu_text = (
            "📋 *Menu*\n\n"
            "🏰 */clan* - Get clan information\n"
            "👤 */player* <tag> - Get player information\n"
            "⚔️ */war* - Get current war info\n"
            "🔗 */bind* <tag> - Bind your player tag\n"
            "🔓 */unbind* - Unbind your player tag\n"
            "🏷️ */mytag* - Show your bound tag\n"
            "🔔 */ping* - Check bot status\n"
            "⚙️ */settings* - Show bot settings\n"
        )
        await update.message.reply_text(menu_text, parse_mode=ParseMode.MARKDOWN)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to reply to /menu")


async def bind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    try:
        if not ensure_private_chat(update):
            await update.message.reply_text("Please use /bind in a private chat with the bot.")
            return
        if not context.args:
            await update.message.reply_text(
                "Send your player tag (e.g. #2PRGP0L22).",
                reply_markup=bind_cancel_keyboard(),
            )
            context.user_data["awaiting_tag"] = True
            return
        raw_tag = " ".join(context.args)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to handle /bind")
        await update.message.reply_text("Unexpected error occurred. Please try again.")
        return
    await process_binding(update, context, raw_tag)


async def process_binding(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    raw_tag: str,
    verified: bool = False,
) -> None:
    if not update.effective_user or not update.message:
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
        await update.message.reply_text("Invalid player tag format.")
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
                await update.message.reply_text("Player tag not found.")
            elif status in {401, 403}:
                await update.message.reply_text(
                    "Backend authentication issue. Check API token/IP."
                )
            else:
                await update.message.reply_text(binding_error_message(status))
            return
        except httpx.RequestError as exc:
            logger.warning("Backend unreachable during bind: %s", exc)
            await update.message.reply_text("Backend is unreachable. Please try again later.")
            return
        except Exception:  # noqa: BLE001
            logger.exception("Unhandled error during bind validation")
            await update.message.reply_text("Unexpected error occurred. Please try again.")
            return
    if settings.enforce_clan_membership:
        if not settings.coc_clan_tag:
            logger.error("Clan membership enforcement enabled without COC_CLAN_TAG set")
            await update.message.reply_text(
                "Binding unavailable: clan configuration missing."
            )
            return
        player_clan = payload.get("clan", {}).get("tag")
        try:
            if not player_clan or normalize_tag(player_clan) != normalize_tag(settings.coc_clan_tag):
                await update.message.reply_text("Player is not in this clan.")
                logger.info(
                    "Bind rejected user_id=%s tag=%s clan_tag=%s",
                    update.effective_user.id,
                    tag,
                    player_clan,
                )
                return
        except InvalidTagError:
            await update.message.reply_text("Player is not in this clan.")
            return
    if settings.require_player_verification and not verified:
        context.user_data["pending_coc_tag"] = tag
        context.user_data["awaiting_player_token"] = True
        await update.message.reply_text(
            "🔐 Для проверки владения аккаунтом открой Clash of Clans → "
            "Настройки → Ещё настройки → API Token и пришли токен игрока сюда.\n"
            "Это НЕ ключ разработчика. Сообщение с токеном бот попытается удалить.",
            reply_markup=bind_cancel_keyboard(),
        )
        return

    storage: BindingsStorage = context.application.bot_data["storage"]
    owner_id = storage.get_user_id_by_tag(settings.clan_group_id or 0, tag)
    if owner_id is not None and owner_id != update.effective_user.id:
        await update.message.reply_text(
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
        await update.message.reply_text("Internal error while saving binding.")
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
            await update.message.reply_text(
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
        await update.message.reply_text(
            f"Bound {mention} to {html.escape(tag)} successfully.\n"
            f"Here is your invite link (valid for {settings.invite_ttl_minutes} minutes):\n"
            f"{invite.invite_link}",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Invite creation failed user_id=%s error=%s", update.effective_user.id, exc)
        await update.message.reply_text(
            f"Bound {mention} to {html.escape(tag)} successfully.",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


async def unbind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    try:
        if not ensure_private_chat(update):
            await update.message.reply_text("Please use /unbind in a private chat with the bot.")
            return
        storage: BindingsStorage = context.application.bot_data["storage"]
        removed = storage.delete_binding(settings.clan_group_id or 0, update.effective_user.id)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to handle /unbind")
        await update.message.reply_text("Unexpected error occurred. Please try again.")
        return
    if removed:
        mention = format_mention(update.effective_user.id, update.effective_user.full_name)
        message = f"Removed binding for {mention}."
    else:
        message = "No binding found for your account."
    await update.message.reply_text(
        message,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
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
    """Handle menu button callbacks."""
    if not update.callback_query:
        return
    
    callback_data = update.callback_query.data
    
    try:
        await update.callback_query.answer()
        
        # Route to appropriate handler
        if callback_data == "menu_topplayers":
            context.args = []
            await top_players(update, context)
        elif callback_data == "menu_clan":
            await clan(update, context)
        elif callback_data == "menu_raids":
            await clan_raids(update, context)
        elif callback_data == "menu_games":
            await clan_games(update, context)
        elif callback_data == "menu_war":
            await war(update, context)
        elif callback_data == "menu_nextwar":
            await next_war_analysis(update, context)
        elif callback_data == "menu_player":
            # Show player info using the callback_query (will use binding if no args)
            context.args = []  # Clear args to trigger binding lookup
            await player(update, context)
        elif callback_data == "menu_report":
            storage: BindingsStorage = context.application.bot_data["storage"]
            binding = storage.get_binding(settings.clan_group_id or 0, update.effective_user.id)
            if not (binding and settings.lex_coc_tag and binding.coc_player_tag == settings.lex_coc_tag):
                await update.callback_query.edit_message_text("Нет доступа к отчёту.")
                return
            await update.callback_query.edit_message_text("📋 Отчёт отправляется...")
            await send_activity_report_to_user(context, update.effective_user.id)
        else:
            await update.callback_query.edit_message_text("Неизвестная команда")
    except Exception as e:
        logger.error("Menu callback error: %s", e, exc_info=settings.debug)


async def bind_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query or not update.effective_user:
        return
    try:
        await update.callback_query.answer()
        if not ensure_private_chat(update):
            await update.callback_query.edit_message_text(
                "Please use /bind in a private chat with the bot."
            )
            return
        context.user_data["awaiting_tag"] = True
        await update.callback_query.edit_message_text(
            "Send your player tag (e.g. #2PRGP0L22).",
            reply_markup=bind_cancel_keyboard(),
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to handle bind_start callback")


async def bind_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query:
        return
    try:
        await update.callback_query.answer()
        context.user_data.pop("awaiting_tag", None)
        context.user_data.pop("awaiting_player_token", None)
        context.user_data.pop("pending_coc_tag", None)
        await update.callback_query.edit_message_text("Binding cancelled.")
    except Exception:  # noqa: BLE001
        logger.exception("Failed to handle bind_cancel callback")


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
        # Clear only after successful binding
        context.user_data["awaiting_tag"] = False
        context.user_data["binding_offered"] = False  # Reset so menu shows next time
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
    """Show user's full CoC profile from binding."""
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
        
        # Fetch player info from API
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            try:
                path = f"/player/{quote(binding.coc_player_tag)}"
                response = await client.get(build_url(path))
                response.raise_for_status()
                player_data = response.json()
            except httpx.HTTPStatusError:
                await update.message.reply_text(
                    "❌ Ошибка при получении профиля. Попробуйте позже."
                )
                return
        
        # Format player profile
        name = player_data.get("name", "Unknown")
        tag = html.escape(player_data.get("tag", "N/A"))
        th_level = player_data.get("townHallLevel", "?")
        exp_level = player_data.get("expLevel", "?")
        trophies = player_data.get("trophies", 0)
        best_trophies = player_data.get("bestTrophies", 0)
        troops = player_data.get("troops", [])
        spells = player_data.get("spells", [])
        
        profile_text = (
            f"👤 *Твой Профиль*\n\n"
            f"🎮 *Имя:* {html.escape(name)}\n"
            f"🏷️ *Тег:* {tag}\n"
            f"🏛️ *Town Hall:* {th_level}\n"
            f"⭐ *Уровень опыта:* {exp_level}\n"
            f"🏆 *Трофеи:* {trophies} (макс: {best_trophies})\n"
        )
        
        if troops:
            profile_text += f"\n🪖 *Войска:* {len(troops)} видов\n"
        if spells:
            profile_text += f"✨ *Заклинания:* {len(spells)} видов\n"
        
        # Get clan info
        clan = player_data.get("clan", {})
        if clan:
            clan_name = clan.get("name", "Unknown")
            clan_tag = clan.get("tag", "N/A")
            profile_text += f"\n🏰 *Клан:* {html.escape(clan_name)}\n"
            profile_text += f"🏷️ *Тег клана:* {html.escape(clan_tag)}\n"
        
        await update.message.reply_text(
            profile_text,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to show profile: %s", exc)
        await update.message.reply_text(
            "❌ Ошибка при отображении профиля. Попробуйте позже."
        )



async def settings_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if not ensure_private_chat(update):
        await update.message.reply_text("Please use /settings in a private chat with the bot.")
        return
    await update.message.reply_text(format_settings_report())


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
        
        # Create welcome message
        if coc_name:
            message = (
                f"✅ {mention}\n"
                f"🎮 *CoC Ник:* {html.escape(coc_name)}\n"
                f"🏷️ *Тег:* {player_tag}\n"
                f"Добро пожаловать в клан! 🎉"
            )
        else:
            message = f"✅ {mention} присоединился как {player_tag}"
        
        try:
            reply_msg = await update.message.reply_text(
                message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            # Pin the welcome message for a few seconds
            try:
                await context.bot.pin_chat_message(
                    chat_id=update.effective_chat.id,
                    message_id=reply_msg.message_id,
                    disable_notification=True,
                )
                # Unpin after 30 seconds
                async def unpin_later():
                    await asyncio.sleep(30)
                    try:
                        await context.bot.unpin_chat_message(
                            chat_id=update.effective_chat.id,
                            message_id=reply_msg.message_id,
                        )
                    except Exception:  # noqa: BLE001
                        pass
                
                # Run unpin in background
                asyncio.create_task(unpin_later())
            except Exception:  # noqa: BLE001
                pass  # Pinning not critical
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to announce member user_id=%s error=%s", member.id, exc)


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
        if attacks_used(member) >= payload.get("attacksPerMember", 2) or not member.get("tag"):
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
        
        # Attempt to rename users and collect mentions
        for binding in bindings:
            last_reminded = cooldowns.get(binding.telegram_user_id)
            if last_reminded and now - last_reminded < timedelta(hours=1):
                continue
            
            coc_player_name = None
            if binding.coc_player_tag in members_by_tag:
                coc_player_name = members_by_tag[binding.coc_player_tag].get("name")
            
            if coc_player_name:
                # Try to rename user in chat with CoC nickname
                try:
                    await context.bot.get_chat_member(chat_id=group_id, user_id=binding.telegram_user_id)
                    await context.bot.set_chat_member_custom_title(
                        chat_id=group_id,
                        user_id=binding.telegram_user_id,
                        custom_title=coc_player_name[:16],  # Telegram limit is 16 chars
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Could not set custom title for user %s: %s", binding.telegram_user_id, exc)
                # Mention with CoC nickname in parentheses
                mention = format_mention(binding.telegram_user_id, binding.telegram_full_name)
                mentions.append(f"{mention} ({coc_player_name})")
            else:
                # Fallback to regular mention
                mentions.append(format_mention(binding.telegram_user_id, binding.telegram_full_name))
            
            reminded_user_ids.append(binding.telegram_user_id)
            # Add micro pause between mentions to avoid flooding
            await asyncio.sleep(0.1)
        
        if not mentions:
            continue
        message = (
            "War reminder: "
            + ", ".join(mentions)
            + " you still have attacks remaining."
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


async def log_any_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message and update.message.text:
        logger.info("Command received: %s from user %s", update.message.text, update.effective_user.id)


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
    """Show clan raids (capital raids) status."""
    if not update.message and not update.callback_query:
        return
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        try:
            payload = await fetch_json(client, "/raids")
            
            # If no data or no raids info, send message
            if not payload or "currentRaid" not in payload:
                message = "ℹ️ Информация о рейдах столицы недоступна."
                await send_or_edit_message(update, message)
                return
            
            current_raid = payload.get("currentRaid")
            if not current_raid:
                message = "ℹ️ Рейды столицы не проводятся в данный момент."
                await send_or_edit_message(update, message)
                return
            
            # Format raid info
            state = current_raid.get("state", "unknown")
            start_time = current_raid.get("startTime", "N/A")
            end_time = current_raid.get("endTime", "N/A")
            
            if state == "ongoing":
                # Show current resources
                clan_capital = current_raid.get("clan", {})
                resources = clan_capital.get("resources", [])
                
                msg = f"🏛️ *Рейды столицы*\n\n"
                msg += f"*Статус:* Идут в данный момент ⚔️\n"
                msg += f"*Начало:* {start_time}\n"
                msg += f"*Конец:* {end_time}\n"
                
                if resources:
                    msg += f"\n*Ресурсы клана:*\n"
                    for resource in resources:
                        resource_name = resource.get("name", "Resource")
                        amount = resource.get("amount", 0)
                        msg += f"• {resource_name}: {amount}\n"
            else:
                # Show status when not in progress
                msg = f"🏛️ *Рейды столицы*\n\n"
                msg += f"*Статус:* Не проводятся\n"
                msg += f"*Начало:* {start_time}\n"
                msg += f"*Конец:* {end_time}\n"
            
            await send_or_edit_message(update, msg)
        except httpx.HTTPStatusError as exc:
            logger.warning("Backend error: %s", exc)
            await send_or_edit_message(update, "ℹ️ Информация о рейдах недоступна.")
        except httpx.RequestError as exc:
            logger.warning("Backend unreachable: %s", exc)
            await send_or_edit_message(update, "Backend is unreachable.")
        except Exception:  # noqa: BLE001
            logger.exception("Unhandled error in /clan-raids")
            await send_or_edit_message(update, "Unexpected error occurred.")


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
                
                msg = f"🎮 *Игры кланов*\n\n"
                msg += f"*Статус:* Идут в данный момент 🏁\n"
                msg += f"*Начало:* {start_time}\n"
                msg += f"*Конец:* {end_time}\n"
                msg += f"*Очки:* {score}\n"
            else:
                # Show status when not in progress
                msg = f"🎮 *Игры кланов*\n\n"
                msg += f"*Статус:* Не проводятся\n"
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
        logger.info(f"ai_reply_handler: bot mentioned directly in text")
    
    # Check if replying to bot's message
    if not mentioned and update.message.reply_to_message:
        try:
            replied_to_bot = (
                update.message.reply_to_message.from_user and
                update.message.reply_to_message.from_user.id == context.bot.id
            )
            if replied_to_bot:
                mentioned = True
                logger.info(f"ai_reply_handler: replying to bot message")
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


async def next_war_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Rank players transparently by observed war attendance and known battle strength."""
    if not update.callback_query and not update.message:
        return
    msg = await send_or_edit_message(update, "⏳ Собираю состав и историю войн...", parse_mode=None)
    try:
        async with httpx.AsyncClient(timeout=max(45, settings.request_timeout_seconds)) as client:
            response = await client.get(build_url("/next-war"))
            response.raise_for_status()
            data = response.json()
        rows = [
            "⚔️ Рекомендации на следующую войну",
            str(data.get("clanName") or "Клан"),
            f"Статус: {data.get('currentWarState', 'unknown')}; CWL: {data.get('cwlState', 'unknown')}",
            f"История: {data.get('observedWarCount', 0)} завершённых войн в локальной базе",
        ]
        if not data.get("historyKnown"):
            rows.append("⚠️ Реальных прошлых атак ещё нет. Сейчас оценка только по силе, НЕ по надёжности.")
        rows.append("")
        for index, player_data in enumerate(data.get("topTen", []), start=1):
            name = str(player_data.get("name") or "Unknown")
            th = player_data.get("townHallLevel") or "?"
            score = player_data.get("warReadiness")
            history = player_data.get("history")
            pref = player_data.get("warPreference")
            rows.append(f"{index}. {name} | TH{th} | индекс {score} | заявка: {pref}")
            if history:
                reliability = history.get("reliabilityPct")
                missed = history.get("missedAttacks")
                average = history.get("averageStars")
                triples = history.get("threeStarsEqualOrHigher", 0)
                downhits = history.get("threeStarsDownhill", 0)
                rows.append(
                    f"   Войн {history.get('wars')}, использовано {reliability}% атак, "
                    f"пропусков {missed}, ⭐/атаку {average if average is not None else 'н/д'}"
                )
                rows.append(f"   Триплы по равным/сильнее: {triples}; по слабее: {downhits}")
            else:
                rows.append("   Данных об атаках пока нет")
        rows.extend([
            "",
            "Методика: учитываются пропуски, уровень цели и сила аккаунта.",
            "Это подсказка для капитана, а не гарантированный прогноз результата.",
        ])
        await msg.edit_text("\n".join(rows)[:3950], parse_mode=None)
    except (httpx.HTTPStatusError, httpx.RequestError):
        logger.exception("Next-war analysis API error")
        await msg.edit_text("Анализ пока недоступен. Проверьте подключение к CoC API.")
    except Exception:
        logger.exception("Next-war analysis failed")
        await msg.edit_text("Ошибка анализа. Подробности в логах аддона.")


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
    application.add_handler(CommandHandler("clan", clan))
    application.add_handler(CommandHandler("topplayers", top_players))
    application.add_handler(CommandHandler("player", player))
    application.add_handler(CommandHandler("war", war))
    application.add_handler(CommandHandler("nextwar", next_war_analysis))
    application.add_handler(CommandHandler("raids", clan_raids))
    application.add_handler(CommandHandler("games", clan_games))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("bind", bind))
    application.add_handler(CommandHandler("unbind", unbind))
    application.add_handler(CommandHandler("mytag", mytag))
    application.add_handler(CommandHandler("chatid", chatid))
    application.add_handler(CommandHandler("grouplink", grouplink))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("settings", settings_info))
    application.add_handler(CallbackQueryHandler(bind_start, pattern="^bind_start$"))
    application.add_handler(CallbackQueryHandler(bind_cancel, pattern="^bind_cancel$"))
    application.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu_"))
    
    # Tag capture handler - must be first (highest priority) to handle tag input during binding
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, capture_tag),
        group=0,
    )
    
    # Private message handler - offer binding to new users (group=1 to run after tag capture)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_private_message),
        group=1,
    )
    
    # AI mention handler: replies when the bot is mentioned or replied-to (group=2 to run last)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, ai_reply_handler),
        group=2,
    )
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, verify_new_members))
    application.add_error_handler(handle_handler_exception)

    if settings.war_reminder_enabled:
        application.job_queue.run_repeating(
            war_reminder_job,
            interval=timedelta(minutes=settings.war_reminder_interval_minutes),
            first=timedelta(minutes=1),
            name="war-reminder",
        )

    logger.info("Telegram bot starting")
    await application.initialize()
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
