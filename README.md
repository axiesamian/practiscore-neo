# PractiScore Neo

A Discord bot that monitors [PractiScore](https://practiscore.com) club pages and posts notifications when new matches are announced or registration opens.

## Features

- Announces new matches as they appear on club pages
- Sends a follow-up notification when registration opens
- Detects and announces match cancellations
- DM subscriptions — users can opt in to receive alerts in their DMs
- Slash commands: `/help`, `/about`, `/status`, `/clubs`, `/matches`, `/subscribe`, `/unsubscribe`, `/mysubscriptions`
- Configurable scraping window (e.g. daytime only) to reduce API usage

## Prerequisites

- Python 3.11 or higher
- A Discord bot token — [create one here](https://discord.com/developers/applications)
- A scraping service API key if hosting on a cloud/datacenter IP (see [Configuration Reference](#configuration-reference))

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/your-username/practiscore-neo.git
cd practiscore-neo
```

### 2. Create a Discord bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications) and click **New Application**
2. Go to the **Bot** tab → **Reset Token** and copy your `BOT_TOKEN`
3. Go to **OAuth2 → URL Generator**, select the `bot` and `applications.commands` scopes, then the `Send Messages` and `Embed Links` permissions. Use the generated URL to invite the bot to your server.
4. Enable **Developer Mode** in Discord (Settings → Advanced → Developer Mode)
5. Right-click your server icon → **Copy Server ID** — this is your `GUILD_ID`
6. Right-click your announcement channel → **Copy Channel ID** — this is your `CHANNEL_ID`

### 3. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in all values. See the [Configuration Reference](#configuration-reference) below for details.

### 4. Configure clubs

Open `clubs.yaml` and replace the example URLs with the PractiScore club pages you want to track:

```yaml
clubs:
  - https://practiscore.com/clubs/your-club-slug
  - https://practiscore.com/clubs/another-club
```

To find a club's URL: visit [practiscore.com](https://practiscore.com), search for the club, and copy the URL from your browser.

> **Note:** Club names are fetched automatically from PractiScore on the first scrape. Until the first scrape runs, the bot displays the URL slug as a placeholder name in `/clubs` and `/matches`. This resolves on its own within the first scraping window.

### 5. Install dependencies

```bash
python -m venv venv
source venv/bin/activate      # Linux/macOS
venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

### 6. Run the bot

```bash
python main.py
```

The bot will log in, sync slash commands to your server, and begin polling on the configured schedule.

---

## Running as a service (Linux/systemd)

For 24/7 hosting on a Linux server, create a systemd service unit:

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
sudo systemctl enable practiscore-bot
sudo systemctl start practiscore-bot
sudo journalctl -u practiscore-bot -f   # tail logs
```

---

## Configuration reference

All configuration lives in `.env`. Copy `.env.example` to get started.

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_TOKEN` | Yes | — | Discord bot token |
| `GUILD_ID` | Yes | — | Your Discord server ID |
| `CHANNEL_ID` | Yes | — | Channel ID for match announcements |
| `ZYTE_API_KEY` | No | — | Zyte API key — used first if set. [zyte.com](https://www.zyte.com) |
| `SCRAPER_API_KEY` | No | — | ScraperAPI key — used if Zyte key is not set. [scraperapi.com](https://www.scraperapi.com) |
| `POLL_INTERVAL_HOURS` | No | `1` | Minimum hours between scrapes |
| `SCRAPE_WINDOW_START` | No | `8` | Hour (24h) to start scraping each day |
| `SCRAPE_WINDOW_END` | No | `21` | Hour (24h) to stop scraping each day |
| `SCRAPE_TIMEZONE` | No | `America/New_York` | Timezone for the scrape window (IANA name) |

`SCRAPE_TIMEZONE` accepts any [IANA timezone name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones), such as `America/Chicago`, `America/Los_Angeles`, or `Europe/London`.

### Scraping API usage estimate

| Clubs | Interval | Est. requests/month |
|---|---|---|
| 3 | 3 hours | ~450 |
| 5 | 3 hours | ~750 |
| 10 | 3 hours | ~1,500 |

Increase `POLL_INTERVAL_HOURS` to reduce request volume if needed.

---

## Slash commands

| Command | Description |
|---|---|
| `/help` | Lists all commands; `/help [command]` for detailed usage |
| `/about` | About this bot and project |
| `/status` | Shows last scrape time, clubs tracked, and active match count |
| `/clubs` | Lists all tracked clubs |
| `/matches [club]` | Shows upcoming matches; optionally filtered to one club |
| `/subscribe <club>` | Subscribe to DM alerts for a club |
| `/unsubscribe <club>` | Unsubscribe from alerts for a club |
| `/mysubscriptions` | Lists your active subscriptions |

---

## Adding or removing clubs

**To add a club:** add its URL to `clubs.yaml` and restart the bot.

**To remove a club:** remove its URL from `clubs.yaml` and restart the bot. The bot stops scraping it immediately. Existing match records in the database are retained but no longer updated.
