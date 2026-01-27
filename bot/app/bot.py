import asyncio
import html
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from app.backend_client import fetch_json
from app.settings import settings
from app.storage import (
    fetch_bindings_for_group,
    fetch_cooldowns,
    fetch_group_ids,
    init_db,
    remove_binding,
    update_cooldowns,
    upsert_binding,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


def format_clan(payload: dict[str, Any]) -> str:
    return (
        f"*{payload.get('name', 'Clan')}*\n"
        f"Tag: `{payload.get('tag', 'N/A')}`\n"
        f"Level: {payload.get('clanLevel', 'N/A')}\n"
        f"Members: {payload.get('members', 'N/A')}\n"
        f"War League: {payload.get('warLeague', {}).get('name', 'N/A')}\n"
    )


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
    return (
        f"*Current War*\n"
        f"State: {payload.get('state', 'N/A')}\n"
        f"Team Size: {payload.get('teamSize', 'N/A')}\n"
        f"Start: {payload.get('startTime', 'N/A')}\n"
        f"End: {payload.get('endTime', 'N/A')}\n"
    )


def normalize_player_tag(tag: str) -> str:
    cleaned = tag.strip().upper()
    if not cleaned:
        return ""
    if not cleaned.startswith("#"):
        cleaned = f"#{cleaned}"
    return cleaned


def parse_coc_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def is_group_chat(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and chat.type in {"group", "supergroup"})


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            "Welcome! Use /clan, /player <tag>, or /war to get Clash of Clans info."
        )


async def clan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        try:
            payload = await fetch_json(client, "/clan")
            await update.message.reply_text(format_clan(payload), parse_mode=ParseMode.MARKDOWN)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.warning("Backend error: %s", exc)
            if status == 429:
                message = "Rate limit reached. Please try again later."
            elif status == 400:
                message = "Invalid clan tag configured."
            elif status == 504:
                message = "Backend timed out contacting Clash of Clans."
            else:
                message = "Backend error while fetching clan data."
            await update.message.reply_text(message)
        except httpx.RequestError as exc:
            logger.warning("Backend unreachable: %s", exc)
            await update.message.reply_text("Backend is unreachable. Please try again later.")


async def player(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if not context.args:
        await update.message.reply_text("Usage: /player <tag>")
        return
    tag = context.args[0]
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        try:
            payload = await fetch_json(client, f"/player/{tag}")
            await update.message.reply_text(format_player(payload), parse_mode=ParseMode.MARKDOWN)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.warning("Backend error: %s", exc)
            if status == 400:
                message = "Invalid player tag format."
            elif status == 404:
                message = "Player not found."
            elif status == 429:
                message = "Rate limit reached. Please try again later."
            elif status == 504:
                message = "Backend timed out contacting Clash of Clans."
            else:
                message = "Backend error while fetching player data."
            await update.message.reply_text(message)
        except httpx.RequestError as exc:
            logger.warning("Backend unreachable: %s", exc)
            await update.message.reply_text("Backend is unreachable. Please try again later.")


async def war(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        try:
            payload = await fetch_json(client, "/war")
            await update.message.reply_text(format_war(payload), parse_mode=ParseMode.MARKDOWN)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.warning("Backend error: %s", exc)
            if status == 429:
                message = "Rate limit reached. Please try again later."
            elif status == 400:
                message = "Invalid clan tag configured."
            elif status == 504:
                message = "Backend timed out contacting Clash of Clans."
            else:
                message = "Backend error while fetching war data."
            await update.message.reply_text(message)
        except httpx.RequestError as exc:
            logger.warning("Backend unreachable: %s", exc)
            await update.message.reply_text("Backend is unreachable. Please try again later.")


async def bind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if not is_group_chat(update):
        await update.message.reply_text("This command can only be used in group chats.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /bind <player_tag>")
        return
    tag = normalize_player_tag(context.args[0])
    if not tag:
        await update.message.reply_text("Usage: /bind <player_tag>")
        return
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        try:
            await fetch_json(client, f"/player/{tag}")
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.warning("Backend error: %s", exc)
            if status == 400:
                message = "Invalid player tag format."
            elif status == 404:
                message = "Player not found."
            elif status == 429:
                message = "Rate limit reached. Please try again later."
            elif status == 504:
                message = "Backend timed out contacting Clash of Clans."
            else:
                message = "Backend error while validating player."
            await update.message.reply_text(message)
            return
        except httpx.RequestError as exc:
            logger.warning("Backend unreachable: %s", exc)
            await update.message.reply_text("Backend is unreachable. Please try again later.")
            return

    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return
    await upsert_binding(
        telegram_user_id=user.id,
        telegram_username=user.username,
        telegram_full_name=user.full_name,
        coc_player_tag=tag,
        group_id=chat.id,
    )
    await update.message.reply_text(
        f"Bound {tag} to {user.full_name} in this group."
    )


async def unbind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if not is_group_chat(update):
        await update.message.reply_text("This command can only be used in group chats.")
        return
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return
    removed = await remove_binding(user.id, chat.id)
    if removed:
        await update.message.reply_text("Binding removed for this group.")
    else:
        await update.message.reply_text("No binding found for you in this group.")


async def remind_war_attacks(application) -> None:
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        try:
            payload = await fetch_json(client, "/war")
        except httpx.HTTPStatusError as exc:
            logger.warning("Backend error during war reminder: %s", exc)
            return
        except httpx.RequestError as exc:
            logger.warning("Backend unreachable during war reminder: %s", exc)
            return

    state = payload.get("state")
    if state in {"notInWar", "warEnded"}:
        return

    end_time = parse_coc_time(payload.get("endTime"))
    if not end_time:
        logger.warning("War payload missing endTime")
        return
    now = datetime.now(timezone.utc)
    remaining_hours = (end_time - now).total_seconds() / 3600
    if remaining_hours <= 0 or remaining_hours > settings.war_reminder_window_hours:
        return

    members = payload.get("clan", {}).get("members", [])
    zero_attack_tags = []
    for member in members:
        attacks = member.get("attacks") or []
        attack_count = member.get("attackCount")
        if attack_count is None:
            attack_count = len(attacks)
        if attack_count == 0:
            tag = normalize_player_tag(member.get("tag", ""))
            if tag:
                zero_attack_tags.append(tag)

    if not zero_attack_tags:
        return

    group_ids = await fetch_group_ids()
    if not group_ids:
        return

    for group_id in group_ids:
        bindings = await fetch_bindings_for_group(group_id)
        if not bindings:
            continue
        bindings_by_tag = {binding.coc_player_tag: binding for binding in bindings}
        cooldowns = await fetch_cooldowns(group_id)
        now_ts = time.time()
        mentions = []
        reminded_user_ids = []
        for tag in zero_attack_tags:
            binding = bindings_by_tag.get(tag)
            if not binding:
                continue
            last_ts = cooldowns.get(binding.telegram_user_id)
            if last_ts and (
                now_ts - last_ts
                < settings.war_reminder_cooldown_minutes * 60
            ):
                continue
            safe_name = html.escape(binding.telegram_full_name)
            mentions.append(
                f'<a href="tg://user?id={binding.telegram_user_id}">{safe_name}</a>'
            )
            reminded_user_ids.append(binding.telegram_user_id)

        if mentions:
            message = "War reminder: please use your attacks.\n" + " ".join(mentions)
            try:
                await application.bot.send_message(
                    chat_id=group_id,
                    text=message,
                    parse_mode=ParseMode.HTML,
                )
                await update_cooldowns(group_id, reminded_user_ids)
            except Exception as exc:
                logger.warning("Failed to send war reminder: %s", exc)


async def war_reminder_loop(application) -> None:
    while True:
        if settings.war_reminder_enabled:
            try:
                await remind_war_attacks(application)
            except Exception as exc:
                logger.exception("War reminder job failed: %s", exc)
        await asyncio.sleep(settings.war_reminder_interval_minutes * 60)


async def main() -> None:
    await init_db()
    application = ApplicationBuilder().token(settings.telegram_bot_token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("clan", clan))
    application.add_handler(CommandHandler("player", player))
    application.add_handler(CommandHandler("war", war))
    application.add_handler(CommandHandler("bind", bind))
    application.add_handler(CommandHandler("unbind", unbind))

    logger.info("Telegram bot starting")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    reminder_task = asyncio.create_task(war_reminder_loop(application))
    try:
        await asyncio.Event().wait()
    finally:
        reminder_task.cancel()
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        logger.info("Telegram bot shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
