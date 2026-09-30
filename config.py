import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")
ZYTE_API_KEY = os.getenv("ZYTE_API_KEY")
# The only Discord user the bot answers and DMs. Auto-detected from the application owner if unset.
OWNER_ID = int(os.getenv("OWNER_ID")) if os.getenv("OWNER_ID") else None
FAILURE_ALERT_THRESHOLD = int(os.getenv("FAILURE_ALERT_THRESHOLD", "3"))
DB_PATH = os.getenv("DB_PATH", "data/matches.db")
# Usage guide linked from /help; per-command links append #cmd-<name>
GUIDE_URL = os.getenv("GUIDE_URL", "https://civdef.xyz/ps-neo/")

# How often each club tier is checked, in hours
WATCHED_INTERVAL_HOURS = float(os.getenv("WATCHED_INTERVAL_HOURS", "3"))
STANDARD_INTERVAL_HOURS = float(os.getenv("STANDARD_INTERVAL_HOURS", "12"))
MANUAL_INTERVAL_HOURS = float(os.getenv("MANUAL_INTERVAL_HOURS", "24"))

# Regular checks only run inside this window; exact-time registration checks run at any hour
SCRAPE_WINDOW_START = int(os.getenv("SCRAPE_WINDOW_START", "8"))
SCRAPE_WINDOW_END = int(os.getenv("SCRAPE_WINDOW_END", "21"))
SCRAPE_TIMEZONE = os.getenv("SCRAPE_TIMEZONE", "America/New_York")

# Zyte spend reporting (/usage and spend alerts). The dashboard key is not ZYTE_API_KEY:
# it's the API key on app.zyte.com/o/settings; the org ID is the number in app.zyte.com/o/<id>
ZYTE_DASHBOARD_KEY = os.getenv("ZYTE_DASHBOARD_KEY")
ZYTE_ORG_ID = os.getenv("ZYTE_ORG_ID")
ZYTE_BILLING_DAY = int(os.getenv("ZYTE_BILLING_DAY", "7"))
# Pay as you go caps spend at $100/month; hitting it suspends the account until the next period
ZYTE_MONTHLY_CAP = float(os.getenv("ZYTE_MONTHLY_CAP", "100"))
# DM once per billing period as spend passes each of these percentages of the cap
ZYTE_ALERT_PERCENTS = [int(p) for p in os.getenv("ZYTE_ALERT_PERCENTS", "50,80,95").split(",") if p.strip()]
