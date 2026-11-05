"""Telegram member-tag integration (Bot API 9.5) for linked CoC players."""
from __future__ import annotations

import asyncio
import logging

import httpx
from app.ui import safe_tag_name

logger = logging.getLogger(__name__)


async def assign_game_tag(context, group_id: int, user_id: int, name: str) -> bool:
    """Assign a regular member's nickname; skip administrators and absent users."""
    label = safe_tag_name(name)
    if not label:
        return False
    try:
        member = await context.bot.get_chat_member(chat_id=group_id, user_id=user_id)
        if member.status in {"administrator", "creator", "left", "kicked", "banned"}:
            return False
        if member.status == "restricted" and not getattr(member, "is_member", False):
            return False
        # PTB 21.4 predates Telegram Bot API 9.5; call the official endpoint directly.
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{context.bot.token}/setChatMemberTag",
                json={"chat_id": group_id, "user_id": user_id, "tag": label},
            )
        if response.status_code == 200 and response.json().get("ok") is True:
            return True
        logger.warning("Member tag rejected by Telegram status=%s user_id=%s",
                       response.status_code, user_id)
    except Exception:
        # Never print request/exception URL; Telegram embeds the bot token in it.
        logger.warning("Member tag could not be updated user_id=%s", user_id)
    return False


async def sync_tags_daily(context) -> None:
    """Refresh bound game nicknames once per day and preserve admin custom titles."""
    from app.backend_client import fetch_json
    from urllib.parse import quote
    from app.settings import settings
    storage = context.application.bot_data["storage"]
    group_id = settings.clan_group_id
    if group_id is None:
        return
    bindings = [b for b in storage.get_bindings_for_group(group_id) if b.is_primary]
    semaphore = asyncio.Semaphore(3)
    async def one(binding):
        async with semaphore:
            try:
                async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                    player = await fetch_json(client, f"/player/{quote(binding.coc_player_tag, safe='')}")
                if settings.enforce_clan_membership:
                    if (player.get("clan") or {}).get("tag") != settings.coc_clan_tag:
                        return
                await assign_game_tag(context, group_id, binding.telegram_user_id, player.get("name", ""))
            except Exception:
                logger.warning("Tag refresh unavailable for member=%s", binding.telegram_user_id)
    await asyncio.gather(*(one(binding) for binding in bindings))
