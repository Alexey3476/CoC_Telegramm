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

## Version 0.2.1 — единый профиль, КВ/ЛВК и управление кланом

- При /bind бот показывает только **ещё не привязанные** игровые аккаунты из текущего состава клана. У каждого CoC-тега может быть один проверенный владелец Telegram. Доказательство владения — игровой API Token, не совпадение имён.
- /profile и /accounts ведут в один профиль: **ники, ратуши, лига, донат, звания**, статистика аккаунтов, выбор основного, удаление отдельных привязок с подтверждением. /primary #TAG и /unlink #TAG доступны как команды; /unbind confirm удаляет все личные привязки.
- Максимальные права определяются **по любому подтверждённому аккаунту** пользователя в CoC. Если хотя бы один является `leader` или `coLeader`, доступно /staff и /captain, включая /setweight, /lastseen и /adminunlink. Администрирование Telegram-группы не даёт этих прав.
- **Единственный источник согласия на КВ и ЛВК — `warPreference` из CoC**. Красная отметка исключает из рекомендуемого состава в обоих режимах. Отдельный Telegram-переключатель ЛВК удалён из интерфейса.
- Отдельные весовые таблицы: КВ = 20% прокачка относительно TH/лиги, 35% дисциплина, 35% качество атак, 10% звание CoC; ЛВК = 20/35/40/5. Качество атак снижает вес «лёгких» целей и сглаживает малые выборки. Глава или соруководитель может менять веса: `/setweight war quality 40`, `/setweight cwl role 10`; сумма автоматически остаётся 100%.
- **Прокачка** сравнивается только с участниками своего TH: уровень героев, снаряжение, текущая лига. Нельзя судить об обороне, стенах или ловушках, поскольку их уровни не предоставляются публичным CoC API; при отсутствии сверстников индекс нейтральный с пометкой низкой достоверности.
- **Дисциплина:** полностью пропущенный раунд текущей ЛВК исключает из оставшихся её раундов; три подряд назначенные и полностью пропущенные войны → кандидат на рассмотрение кика. Использовать одну из двух атак — недисциплинированно, но это не полностью пропущенная война. Кик не выполняется автоматически.
- Последний вход **не предоставляется CoC API**. Только руководитель может вручную перенести наблюдение из игры: `/lastseen #TAG 3` (дней назад) или `/lastseen #TAG clear`. Подтверждённая ручная отметка 48+ часов создаёт отдельный резерв. Неизвестный вход не считается 0 активностью.
- Разделы КВ/ЛВК: рекомендуемый состав, запас, отказавшиеся, неактивные, твинки, дисквалифицированные до конца текущей ЛВК, кандидаты на повышение, кик и бонусы. Последние три доступны только CoC-руководству; все действия в игре ручные.
- /topplayers открывает **интерактивный список игроков с персональными карточками**, а не только текстовый рейтинг. /donate показывает топ пожертвований текущего сезона; /hall — донат, реальные военные результаты, рейды последнего доступного сезона и кандидатуры на повышение. Очки Игр кланов отсутствуют в официальном публичном API, поэтому не выдумываются.
- /progress позволяет выбрать любого своего твинка и период **7 дней / 30 дней / всё время**. Отдельные SQLite-снимки по каждому CoC-тегу сохраняются в `/data/player_progress.db`. Для сравнения нужны как минимум два разных дня наблюдений.
- Данные продолжают храниться в постоянных SQLite-файлах под `/data`. До обновления рекомендуется создать полную резервную копию аддона в Home Assistant.

## Automated post-war messages (0.2.1)

- The add-on checks persisted completed regular wars and CWL rounds and posts a short group result: stars, destruction and one of five random Russian messages for a win, loss or draw.
- The first successful poll silently marks existing completed wars as seen to avoid flooding the group when upgrading. Subsequent completed wars trigger one notification per group/war; status is stored in the persistent `/data/bindings.db`.
- Only results with a verified clan tag, both star totals and any required damage tie-break can trigger a message. Ended rounds older than 12 hours are ignored.
- Enable or disable greetings with the Home Assistant option `war_results_enabled` (enabled by default). It requires `clan_group_id`, an admin bot that may send messages, and accessible Clash API results.
- Polling runs approximately every 3 minutes, but the backend may take up to 5 minutes to capture a completed war. The bot will not repost already seen results on restart.
- The tracker reserves an announcement before Telegram delivery to prevent duplicate messages. If Telegram fails during delivery, that one announcement can be missed. This is an at-most-once safeguard, not a guarantee of delivery.

## Release 0.2.2 (updates on top of Beerlogger01 0.2.1)

Beerlogger01/main already published version 0.2.1. This post-merge QA release uses version **0.2.2** so that Home Assistant will detect and offer the updated GHCR image, rather than reusing the same add-on version tag. The release retains the multi-account roster and relative strength features, contains the fixed nickname picker (only unbound tags, stale callback protection), safer Telegram UI formatting, and regression tests for promotion coverage and highest CoC leadership role among multiple verified alts. Build and deploy require merging this branch's changes into **Beerlogger01/main**; merging only the staging repository does not publish the production image.


## Версия 0.2.3: ЛВК, рейтинг и голосования

- `/cwl` показывает семь раундов и предварительное место нашего клана в группе. Место считается по доступным в CoC API результатам **всех** кланов: звёзды за атаки + 10 за завершённую победу. При равенстве учитывается суммарное разрушение. Не завершённые и недоступные раунды не выдаются за поражения; итоговая официальная таблица может отличаться.
- `/nextwar cwl` подбирает ровно 15 игроков, усиливая вес уровня ратуши (TH18 > TH15/16 при прочих равных). `/nextwar war 20` (или 15,25,30,35,40,45,50) позволяет задать размер обычной КВ. Если явно не задан, используется размер текущей КВ, иначе 15. В КВ подбор сохраняет распределение ратуш среди доступных игроков.
- `/ranking`, `/ranking war` и `/ranking cwl`: отдельный постраничный список всех членов клана, отсортированный по расчётному индексу. ЛВК и обычная КВ оцениваются по разным шкалам; индекс не является официальным игровым рейтингом.
- Показатели героев, снаряжения, текущей лиги и уровня опыта сравниваются внутри одного TH. Опыт играет вспомогательную роль: уровень опыта **не равен** уровню обороны или укреплений. Публичный CoC API не предоставляет уровни отдельных зданий, стен/защиты и не сообщает онлайн/последний вход игрока.
- `/poll`: лидер или соруководитель CoC создаёт голосование **в личном чате**. Сначала вопрос, затем срок 1/6/24/72 часа, после него по одному вводятся 2–8 вариантов ответов и нажимается «Опубликовать». Публикация идёт в настроенную группу клана; голосуют только пользователи с подтверждённым аккаунтом, который ещё находится в клане. У одного Telegram-пользователя один изменяемый голос, независимо от числа твинков. Через заданный срок бот публикует результаты. Данные голосований в `/data/polls.db`.
- Версия аддона: `0.2.3`. Данные прошлых версий не очищаются. Настроенные вручную веса ЛВК сохраняются, старые стандартные веса автоматически получают новые значения 45/25/25/5.
- Покупка пропусков CoC и подарков Telegram Premium **не реализована**. Это задача исследования, не часть функциональности 0.2.3.

Перед обновлением сделай резервную копию данных аддона. Мерж только в staging не публикует образ продакшен-репозитория Beerlogger01.
