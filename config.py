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

# How often each club tier is checked, in hours
WATCHED_INTERVAL_HOURS = float(os.getenv("WATCHED_INTERVAL_HOURS", "3"))
STANDARD_INTERVAL_HOURS = float(os.getenv("STANDARD_INTERVAL_HOURS", "12"))
MANUAL_INTERVAL_HOURS = float(os.getenv("MANUAL_INTERVAL_HOURS", "24"))

# Regular checks only run inside this window; exact-time registration checks run at any hour
SCRAPE_WINDOW_START = int(os.getenv("SCRAPE_WINDOW_START", "8"))
SCRAPE_WINDOW_END = int(os.getenv("SCRAPE_WINDOW_END", "21"))
SCRAPE_TIMEZONE = os.getenv("SCRAPE_TIMEZONE", "America/New_York")
