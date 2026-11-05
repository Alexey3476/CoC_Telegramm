# Clash of Clans Telegram Bot (independent Home Assistant add-on)

This add-on does not alter or share settings with the Home Assistant smart-home Telegram bot.

## Installation

1. In Home Assistant **Settings → Apps → Install app → ⋮ → Repositories**, add `https://github.com/Beerlogger01/CoC_Telegramm`.
2. Refresh and select **Clash of Clans Telegram Bot**.
3. Enter `telegram_bot_token` (BotFather), `coc_token` (developer.clashofclans.com), and `coc_clan_tag` (including #).
4. Start the app and inspect its logs.
5. Add the bot as admin of a **private Telegram group** with invite and remove permissions. Use `/chatid` in the group and set `clan_group_id` in the app config.
6. Users bind with `/bind #PLAYER_TAG` in a private chat with the bot. Account verification, when enabled, requires the **player API token from game settings**, not the developer portal token.

## API and network

Clash of Clans developer keys must allow the Raspberry Pi's **public outgoing IP**. This add-on contains its own private API at `127.0.0.1:8000` **inside the container**, with no host ports. Redis and Docker Compose are not needed.

## Persistence

Player associations are stored in `/data/bindings.db` and survive restarts; backups are handled by the Supervisor. All credentials live in add-on configuration, never the Git repository.

## Images and updates

The version in `config.yaml` matches the tag on `ghcr.io/beerlogger01/coc-telegram`. The image must be **published and public** on GHCR before Home Assistant can install it. The GitHub Actions workflow publishes multi-architecture images after code is merged to `main` and tests pass. Pull requests run a build without publishing.

## War analytics

War snapshots are sampled locally every five minutes, including clan war league rounds. The bot only uses captured, completed wars for attack reliability: missing attacks, stars and town hall of attacked bases. Historic player-level attacks are not available from the regular public war log. Until completed snapshots exist, reliability remains **unknown** (not zero). The public API also does not reliably report player last-online time or Clan Games individual progress.

## Version 0.2.0 changes
- Telegram slash command menu and interactive dashboard are synchronized.
- Binding offers nickname suggestions and a paginated roster; game-token verification remains mandatory.
- War and raid dates are rendered in Europe/Berlin time, including DST.
- War lineup selection is paginated and labels incomplete historical evidence.
- Verified regular group members receive CoC nickname tags on join and daily at 09:00 Berlin time. Grant Manage Tags permission. Admin titles are never overwritten.
- Telegram bot token URLs and exception logging are redacted. Revoke any previously exposed token.

## Development snapshots

Daily public player-profile snapshots are saved in `/data/player_progress.db` without credentials. `/progress` compares hero, equipment, Town Hall and documented lifetime counters with the previous saved day. No active upgrade timers are inferred.
