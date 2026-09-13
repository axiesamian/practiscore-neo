import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
GUILD_ID = int(os.getenv("GUILD_ID"))
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")
ZYTE_API_KEY = os.getenv("ZYTE_API_KEY")
OWNER_ID = int(os.getenv("OWNER_ID")) if os.getenv("OWNER_ID") else None
FAILURE_ALERT_THRESHOLD = int(os.getenv("FAILURE_ALERT_THRESHOLD", "3"))
POLL_INTERVAL_HOURS = int(os.getenv("POLL_INTERVAL_HOURS", "1"))
DB_PATH = os.getenv("DB_PATH", "data/matches.db")
SCRAPE_WINDOW_START = int(os.getenv("SCRAPE_WINDOW_START", "8"))
SCRAPE_WINDOW_END = int(os.getenv("SCRAPE_WINDOW_END", "21"))
SCRAPE_TIMEZONE = os.getenv("SCRAPE_TIMEZONE", "America/New_York")
