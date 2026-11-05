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

## Version 0.2.1 — alternate accounts and leadership selection

- /bind verifies additional CoC player tags using their in-game API tokens. A Telegram user can own multiple linked tags; one primary tag is preserved from 0.2.0.
- /accounts lists verified game tags, /primary #TAG switches the primary, /unlink #TAG removes one link, /unbind confirm removes all. /adminunlink #TAG lets a verified leader/co-leader delete one binding, NOT kick the player or group member.
- /cwlopt in|out|unknown [#TAG] records player CWL preference separately from CoC profile warPreference. Only owner of a verified tag can submit this.
- /weights displays the five selection metrics (combat, reliability, performance, participation, manually reported activity). /setweight metric percent is for leaders/co-leaders, automatically normalizing totals to 100.
- /lastseen #TAG days lets verified leadership manually report the in-game last seen indicator, while /lastseen #TAG clear removes it. Official public Clash API has NO exact last online field. No API changes do NOT prove the player is offline.
- /nextwar war or /nextwar cwl: main squad, bench, manual >48h inactive reserve, opt-outs and unknown preferences. Opted-out accounts are never auto-selected.
- Kick candidates are leader-only review suggestions requiring missed attacks and at least seven days manually confirmed inactivity. Promotions require consistent archived performance. CWL bonuses require actual CWL history; no invented records.
- No automatic kicks, promotions or bonuses. Missing activity/attack history is displayed as unknown, not zero. Selection weights are kept in /data/selection.db, alternate links migrate additively in /data/bindings.db.
- Back up the Home Assistant add-on data before updating.

## Automated post-war messages (0.2.1)

- The add-on checks persisted completed regular wars and CWL rounds and posts a short group result: stars, destruction and one of five random Russian messages for a win, loss or draw.
- The first successful poll silently marks existing completed wars as seen to avoid flooding the group when upgrading. Subsequent completed wars trigger one notification per group/war; status is stored in the persistent `/data/bindings.db`.
- Only results with a verified clan tag, both star totals and any required damage tie-break can trigger a message. Ended rounds older than 12 hours are ignored.
- Enable or disable greetings with the Home Assistant option `war_results_enabled` (enabled by default). It requires `clan_group_id`, an admin bot that may send messages, and accessible Clash API results.
- Polling runs approximately every 3 minutes, but the backend may take up to 5 minutes to capture a completed war. The bot will not repost already seen results on restart.
- The tracker reserves an announcement before Telegram delivery to prevent duplicate messages. If Telegram fails during delivery, that one announcement can be missed. This is an at-most-once safeguard, not a guarantee of delivery.
