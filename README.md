# Zurich House Hunter

Small Python service that watches Zurich housing search pages and posts new matches into Telegram group chats or DMs.

The current project ships with:

- a working default scraper built around the reachable `alle-immobilien` Zurich house search page
- a generic HTML link-card scraper for additional real-estate sites
- SQLite-based deduplication so the chat only gets new listings
- Telegram Bot API notifications
- Telegram bot mode that auto-registers group chats and DMs from incoming updates
- bootstrap mode to avoid flooding the chat on first run

The implementation is standard-library only, so it runs on the stock Python 3.8 that is already available in this workspace.

## How it works

1. Fetch each configured search URL.
2. Extract listing-like links from the page.
3. Parse rough facts from the card text: price, rooms, size, address, title.
4. Skip listings already seen in the local SQLite database.
5. Optionally fetch new listing pages for better titles and descriptions.
6. Send one Telegram message per new match.

## Setup

1. Create a Telegram bot with `@BotFather`.
2. Add the bot to your group chat.
3. Copy the sample config:

```bash
cp config.example.json config.json
```

4. Export the bot credentials:

```bash
export TELEGRAM_BOT_TOKEN="123456:ABCDEF"
export TELEGRAM_CHAT_ID=""
export TELEGRAM_THREAD_ID=""
```

5. Run a dry pass first:

```bash
python3 hunter.py --config config.json --dry-run run
```

6. Run a real sweep:

```bash
python3 hunter.py --config config.json run
```

7. Run the Telegram bot loop:

```bash
python3 hunter.py --config config.json bot-loop --interval-seconds 900 --poll-timeout-seconds 20
```

`bot-loop` does not need a preconfigured `chat_id`. As soon as the bot is added to a group, or someone sends it `/start` in a DM, it stores that chat ID locally and uses it for future scheduled runs.

## Repeating runs

Cron is the simplest option:

```cron
*/15 * * * * cd /Users/mimo/Desktop/Programming/Utility/zurich-house-hunter && /usr/bin/env TELEGRAM_BOT_TOKEN="..." TELEGRAM_CHAT_ID="..." python3 hunter.py --config config.json run >> hunter.log 2>&1
```

Or keep the process alive:

```bash
python3 hunter.py --config config.json loop --interval-seconds 900
```

Or let the bot both listen for commands and run scheduled scrapes:

```bash
python3 hunter.py --config config.json bot-loop --interval-seconds 900 --poll-timeout-seconds 20
```

## Deploy

The server pattern for this repo now matches your older bots: copy the project to `/usr/bots/zurich-house-hunter` on the server and run it via `systemd`.

Deploy from this machine with:

```bash
bash deploy/deploy_to_server.sh
```

That script:

- syncs the repo to `root@82.165.45.100:/usr/bots/zurich-house-hunter`
- keeps `data/` on the server intact
- copies the systemd unit from [deploy/zurich-house-hunter.service](/Users/mimo/Desktop/Programming/Utility/zurich-house-hunter/deploy/zurich-house-hunter.service)
- enables and restarts `zurich-house-hunter.service`

Notes:

- `config.json` is intentionally gitignored and is still deployed to the server by the script if it exists locally.
- Runtime logs go to `journalctl -u zurich-house-hunter.service -f`.
- The service starts the bot loop, not the one-shot CLI run.

## Group Commands

The bot supports these commands in groups and DMs:

- `/status` or `/filters`
- `/whereami`
- `/set max_price 8000`
- `/set min_rooms 4.5`
- `/set min_area 120`
- `/include chalet`
- `/exclude temporary`
- `/clear max_price`
- `/clear include`
- `/clear all`
- `/run`

## Config notes

- `bootstrap_mark_seen: true` means the first successful run stores current listings without notifying the group.
- `--dry-run` previews matches without writing them into the SQLite state.
- `must_contain_any` and `exclude_if_contains_any` are case-insensitive substring filters.
- `min_rooms`, `max_rooms`, `min_price_chf`, `max_price_chf`, `min_area_sqm`, `max_area_sqm` are optional numeric filters.
- `min_card_score` matters most for the generic scraper. It scores links that look like listing cards by signals such as `CHF`, `rooms`, and `m²`.
- `message_thread_id` is optional and only needed if the bot should post into a specific Telegram topic.
- `telegram.chat_id` is optional for `bot-loop`. Leave it empty to let the bot learn chats from `my_chat_member` and DM/group commands. Keep it set only if you want `run` to target one fixed chat directly.
- The default config disables direct `homegate` and `immoscout24` scraping because they currently return anti-bot challenge pages to scripted clients in this environment. Their listing URLs can still be surfaced through the reachable aggregator source.
- `bot-loop` auto-registers DMs, groups, and supergroups. If `message_thread_id` is set together with `chat_id`, that restriction only applies to that one configured topic.

## Responsible use

- Keep request frequency conservative. The sample config sleeps between requests.
- Respect site terms and robots policies before adding more sources.
- Expect HTML-based scrapers to need occasional selector or filter updates when websites change.

## Verification

The included tests are offline-only:

```bash
python3 -m unittest discover -s tests
```
