# PractiScore Neo

A personal Discord bot that watches [PractiScore](https://practiscore.com) club pages and DMs you when matches are posted and when registration opens. It is built for one person: every command and every alert happens in the bot's DMs, and nobody else can use it.

## Features

- **DM-only, owner-only.** Slash commands work only in the bot's DMs, and only for you.
- **Club tiers** control how often each club is checked:
  | Tier | Checked |
  |---|---|
  | `watched` | every 3 hours during the day |
  | `standard` | every 12 hours |
  | `manual` | only when you `/scan`, then daily while a starred match is waiting to open |
  | `paused` | never |
- **Match levels** control what you're told about each match:
  | Level | Alerts |
  |---|---|
  | ⭐ `starred` | new, registration open, closed again, reopened, date changed, removed |
  | `normal` | new, registration open |
  | 🔇 `muted` | none |
- **Catches early and reverted openings.** Registration that opens ahead of schedule, closes again, or reopens is detected from the club page's registration label.
- **Registration-time checks.** When a club page says a match "opens in N hours", the bot schedules extra checks around that time, at any hour of the night.
- **Rules** set the level of new matches by type or title (for example, mute every "Steel Challenge" match at one club).
- **Buttons on alerts** to star, unstar or mute a match straight from the DM.
- **Summaries instead of floods.** Adding a club, resuming a paused club or turning scraping back on sends one summary, not an alert per match.
- **Failure alerts.** One DM when checks keep failing, one when they recover.

## How it works

The bot scrapes each club's page (`https://practiscore.com/clubs/<club>`). Each listed match has a registration label, which the bot reads as a state:

| Label | State |
|---|---|
| green `open` | open |
| grey `opens in 2 days` | not yet open |
| grey `closed` | closed |
| anything else | unknown (you get a DM so it can be looked at) |

Alerts come from changes in that state between checks. A match missing from the page on two checks in a row, before its date, is reported as removed.

PractiScore is behind Cloudflare, which blocks most cloud and datacenter IPs. On a cloud server you need a scraping API key (Zyte or ScraperAPI). On a home connection you usually don't.

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/axiesamian/practiscore-neo.git
cd practiscore-neo
```

### 2. Create the Discord bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications) and click **New Application**.
2. **Bot** tab → **Reset Token** and copy it as `BOT_TOKEN`. Turn **Public Bot** off so only you can invite it.
3. Discord only lets a bot DM someone it shares a server with. Create a private server with just you in it (or use one you own).
4. **OAuth2 → URL Generator**: select the `bot` and `applications.commands` scopes. No bot permissions are needed. Open the generated URL and add the bot to that server.
5. Open a DM with the bot (click its name in the server's member list → **Message**). The slash commands appear there within a minute or so of the bot starting.

The bot answers only its owner. By default that's the application owner from the Developer Portal. To use a different account, set `OWNER_ID` (Discord Settings → Advanced → Developer Mode, then right-click your name → **Copy User ID**).

### 3. Configure

```bash
cp .env.example .env
```

Fill in `BOT_TOKEN` and a scraping key. Everything else has defaults (see [Configuration](#configuration)).

### 4. Install and run

```bash
python -m venv venv
source venv/bin/activate      # Linux/macOS
venv\Scripts\activate         # Windows

pip install -r requirements.txt
python main.py
```

Then add your first club from the bot's DMs:

```
/addclub url:https://practiscore.com/clubs/your-club tier:watched
```

## Commands

All commands are DM-only.

| Command | What it does |
|---|---|
| `/addclub <url> [tier]` | Track a club by its page URL. Replies with its upcoming matches and a picker to star some |
| `/removeclub <club>` | Stop tracking a club and forget its matches |
| `/tier <club> <tier>` | Change a club's tier. Leaving `paused` sends one summary of what changed |
| `/scan <club>` | Check a club now; summary plus a picker to choose starred matches |
| `/star` · `/unstar` · `/mute <match>` | Set a match's level |
| `/rule <club> <text> <level>` | New matches whose type or title contains `text` get `level`; `remove` deletes the rule |
| `/matches [club]` | Upcoming matches with registration state and level |
| `/clubs` | Tracked clubs with tier, last check, counts and rules |
| `/status` | Scraping on/off, health, next checks |
| `/scraping <on\|off>` | Pause or resume all scheduled checks. The bot stays online |
| `/help [command]` | Command list with tiers and levels, or details and examples for one command |

## Configuration

All configuration lives in `.env`.

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_TOKEN` | Yes | — | Discord bot token |
| `OWNER_ID` | No | application owner | The only user the bot answers and DMs |
| `ZYTE_API_KEY` | No | — | Zyte API key; used first if set. [zyte.com](https://www.zyte.com) |
| `SCRAPER_API_KEY` | No | — | ScraperAPI key; used if no Zyte key. [scraperapi.com](https://www.scraperapi.com) |
| `WATCHED_INTERVAL_HOURS` | No | `3` | Check interval for `watched` clubs |
| `STANDARD_INTERVAL_HOURS` | No | `12` | Check interval for `standard` clubs |
| `MANUAL_INTERVAL_HOURS` | No | `24` | Check interval for `manual` clubs with a starred match waiting to open |
| `SCRAPE_WINDOW_START` | No | `8` | Hour (24h) regular checks start each day |
| `SCRAPE_WINDOW_END` | No | `21` | Hour (24h) regular checks stop each day |
| `SCRAPE_TIMEZONE` | No | `America/New_York` | Timezone for the window ([IANA name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)) |
| `FAILURE_ALERT_THRESHOLD` | No | `3` | Failed checks in a row before the failure DM |
| `DB_PATH` | No | `data/matches.db` | SQLite database path |
| `GUIDE_URL` | No | `https://civdef.xyz/ps-neo/` | Usage guide linked from `/help` |

### Request usage

One request checks one club page, whatever the number of matches on it.

| Setup | Requests/month (approx.) |
|---|---|
| 1 watched club | 150 |
| 3 watched clubs | 450 |
| 3 watched + 5 standard | 750 |

Registration-time checks add about 2 requests per starred or normal match as it approaches opening.

## Running as a service (Linux/systemd)

```ini
# /etc/systemd/system/practiscore-bot.service
[Unit]
Description=PractiScore Neo
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/practiscore-bot
ExecStart=/home/ubuntu/practiscore-bot/venv/bin/python main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now practiscore-bot
sudo journalctl -u practiscore-bot -f   # tail logs
```

## Tests

```bash
python -m unittest discover -s tests -t .
```

## Upgrading from the multi-user version

The database migrates itself on startup. Existing clubs become `watched`, existing matches become `starred`, and subscriptions are dropped. `clubs.yaml`, `CHANNEL_ID`, `GUILD_ID` and `POLL_INTERVAL_HOURS` are no longer read. Clubs are managed with `/addclub` and `/removeclub`. The old server-specific slash commands are removed automatically on first start.
