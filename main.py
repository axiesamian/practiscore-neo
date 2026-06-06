import logging
import yaml
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import (
    BOT_TOKEN, CHANNEL_ID, GUILD_ID, POLL_INTERVAL_HOURS, DB_PATH,
    SCRAPE_WINDOW_START, SCRAPE_WINDOW_END, SCRAPE_TIMEZONE,
)
from database import (
    init_db, get_conn,
    seed_clubs, update_club_name,
    add_subscription, remove_subscription,
    get_user_subscriptions, get_club_subscribers,
    get_active_matches_for_club, mark_match_cancelled,
)
from scraper import scrape_club, check_match_cancelled
from notifier import new_match_embed, registration_open_embed, match_cancelled_embed, match_view

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


def load_clubs_config():
    try:
        with open("clubs.yaml") as f:
            data = yaml.safe_load(f)
        urls = (data or {}).get("clubs", [])
        if not urls:
            log.error("clubs.yaml has no clubs defined — add at least one URL.")
        return urls
    except FileNotFoundError:
        log.error("clubs.yaml not found — add your club URLs to clubs.yaml.")
        return []


@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user}")
    guild = discord.Object(id=GUILD_ID)

    bot.tree.copy_global_to(guild=guild)
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()

    try:
        synced = await bot.tree.sync(guild=guild)
        log.info(f"Slash commands synced to guild: {[c.name for c in synced]}")
    except Exception as e:
        log.error(f"Failed to sync slash commands: {e}")

    club_urls = load_clubs_config()
    if club_urls:
        seed_clubs(DB_PATH, club_urls)
    else:
        log.error("No clubs configured — bot will run but won't scrape anything.")

    poll_clubs.start()


ET = ZoneInfo(SCRAPE_TIMEZONE)

last_scraped: datetime | None = None


async def _dm_subscribers(club_url: str, embed: discord.Embed, view: discord.ui.View):
    user_ids = get_club_subscribers(DB_PATH, club_url)
    for user_id in user_ids:
        try:
            user = await bot.fetch_user(user_id)
            await user.send(embed=embed, view=view)
        except Exception as e:
            log.warning(f"Could not DM user {user_id}: {e}")


@tasks.loop(hours=1)
async def poll_clubs():
    global last_scraped

    now = datetime.now(ET)
    if now.hour >= SCRAPE_WINDOW_END or now.hour < SCRAPE_WINDOW_START:
        log.info(f"Outside scrape window — skipping tick at {now.strftime('%I:%M %p')} {SCRAPE_TIMEZONE}")
        return

    if last_scraped and (now - last_scraped).total_seconds() < POLL_INTERVAL_HOURS * 3600:
        log.info(f"Too soon since last scrape — next scrape after {last_scraped + timedelta(hours=POLL_INTERVAL_HOURS):%I:%M %p} {SCRAPE_TIMEZONE}")
        return

    last_scraped = now

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        log.error(f"Channel {CHANNEL_ID} not found")
        return

    club_urls = load_clubs_config()
    if not club_urls:
        return

    with get_conn(DB_PATH) as conn:
        placeholders = ",".join("?" * len(club_urls))
        clubs = conn.execute(
            f"SELECT url, name FROM clubs WHERE url IN ({placeholders})",
            club_urls,
        ).fetchall()

    for club in clubs:
        try:
            result = scrape_club(club["url"])
            matches = result["matches"]
            update_club_name(DB_PATH, club["url"], result["name"])
            log.info(f"Scraped {len(matches)} matches for {result['name']}")
        except Exception as e:
            log.error(f"Failed to scrape {club['url']}: {e}")
            continue

        for match in matches:
            with get_conn(DB_PATH) as conn:
                existing = conn.execute(
                    "SELECT announced, registration_notified FROM matches WHERE match_id = ?",
                    (match["match_id"],),
                ).fetchone()

            if not existing:
                reg_notified = 1 if match["registration_open"] else 0
                with get_conn(DB_PATH) as conn:
                    conn.execute(
                        """INSERT INTO matches
                           (match_id, club_url, club_name, title, date, match_type, url, announced, registration_notified)
                           VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                        (match["match_id"], club["url"], result["name"],
                         match["title"], match["date"], match["match_type"], match["url"], reg_notified),
                    )
                    conn.commit()
                embed = new_match_embed(match, result["name"])
                view = match_view(match["url"], "View Match")
                await channel.send(embed=embed, view=view)
                await _dm_subscribers(club["url"], embed, view)
                log.info(f"Announced new match: {match['title']}")

            elif existing["registration_notified"] == 0 and match["registration_open"]:
                with get_conn(DB_PATH) as conn:
                    conn.execute(
                        "UPDATE matches SET registration_notified = 1, last_seen = datetime('now') WHERE match_id = ?",
                        (match["match_id"],),
                    )
                    conn.commit()
                embed = registration_open_embed(match, result["name"])
                view = match_view(match["url"], "Register Now")
                await channel.send(embed=embed, view=view)
                await _dm_subscribers(club["url"], embed, view)
                log.info(f"Registration opened for: {match['title']}")

            else:
                with get_conn(DB_PATH) as conn:
                    conn.execute(
                        "UPDATE matches SET last_seen = datetime('now') WHERE match_id = ?",
                        (match["match_id"],),
                    )
                    conn.commit()

        # Cancellation check — look for announced matches that didn't appear in this scrape
        scraped_ids = {m["match_id"] for m in matches}
        active_db_matches = get_active_matches_for_club(DB_PATH, club["url"])
        for db_match in active_db_matches:
            if db_match["match_id"] not in scraped_ids:
                if check_match_cancelled(db_match["url"]):
                    mark_match_cancelled(DB_PATH, db_match["match_id"])
                    embed = match_cancelled_embed(db_match, result["name"])
                    await channel.send(embed=embed)
                    await _dm_subscribers(club["url"], embed, discord.ui.View())
                    log.info(f"Match cancelled: {db_match['title']}")


# --- Autocomplete helpers ---

async def all_clubs_autocomplete(interaction: discord.Interaction, current: str):
    with get_conn(DB_PATH) as conn:
        clubs = conn.execute("SELECT url, name FROM clubs ORDER BY name").fetchall()
    return [
        app_commands.Choice(name=c["name"], value=c["url"])
        for c in clubs
        if current.lower() in c["name"].lower()
    ]


async def subscribed_clubs_autocomplete(interaction: discord.Interaction, current: str):
    subs = get_user_subscriptions(DB_PATH, interaction.user.id)
    return [
        app_commands.Choice(name=s["name"], value=s["url"])
        for s in subs
        if current.lower() in s["name"].lower()
    ]


# --- Slash commands ---

@bot.tree.command(name="clubs", description="List all tracked clubs")
async def clubs_command(interaction: discord.Interaction):
    with get_conn(DB_PATH) as conn:
        clubs = conn.execute("SELECT name, url FROM clubs ORDER BY name").fetchall()

    if not clubs:
        await interaction.response.send_message("No clubs are being tracked.", ephemeral=True)
        return

    lines = [f"• [{c['name']}]({c['url']})" for c in clubs]
    embed = discord.Embed(
        title="Tracked Clubs",
        description="\n".join(lines),
        color=discord.Color.blue(),
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="matches", description="Show upcoming matches — all clubs, or just one")
@app_commands.describe(club="Filter to a specific club (optional)")
@app_commands.autocomplete(club=all_clubs_autocomplete)
async def matches_command(interaction: discord.Interaction, club: str = None):
    await interaction.response.defer(ephemeral=True)

    with get_conn(DB_PATH) as conn:
        if club:
            clubs = conn.execute("SELECT url, name FROM clubs WHERE url = ?", (club,)).fetchall()
        else:
            clubs = conn.execute("SELECT url, name FROM clubs").fetchall()

    if not clubs:
        await interaction.followup.send("Club not found.", ephemeral=True)
        return

    all_matches = []
    for c in clubs:
        try:
            result = scrape_club(c["url"])
            for m in result["matches"]:
                m["club_name"] = result["name"]
            all_matches.extend(result["matches"])
        except Exception as e:
            log.error(f"Failed to scrape {c['url']}: {e}")

    if not all_matches:
        await interaction.followup.send("No upcoming matches found.", ephemeral=True)
        return

    title = f"Upcoming Matches — {clubs[0]['name']}" if club else "Upcoming Matches"
    embed = discord.Embed(title=title, color=discord.Color.blue())
    for m in all_matches:
        status = "Open" if m["registration_open"] else "Not yet open"
        value = f"📅 {m['date']}\n🏆 {m['match_type']}\n🎯 Registration: {status}\n[Register]({m['url']})"
        embed.add_field(
            name=f"{m['club_name']} — {m['title']}",
            value=value,
            inline=False,
        )

    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="subscribe", description="Subscribe to match alerts for a club")
@app_commands.describe(club="Club to subscribe to")
@app_commands.autocomplete(club=all_clubs_autocomplete)
async def subscribe_command(interaction: discord.Interaction, club: str):
    with get_conn(DB_PATH) as conn:
        club_row = conn.execute("SELECT name FROM clubs WHERE url = ?", (club,)).fetchone()

    if not club_row:
        await interaction.response.send_message("Club not found.", ephemeral=True)
        return

    added = add_subscription(DB_PATH, interaction.user.id, club)
    if added:
        await interaction.response.send_message(
            f"Subscribed to **{club_row['name']}**. You'll get a DM when new matches are posted or registration opens.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            f"You're already subscribed to **{club_row['name']}**.",
            ephemeral=True,
        )


@bot.tree.command(name="unsubscribe", description="Unsubscribe from match alerts for a club")
@app_commands.describe(club="Club to unsubscribe from")
@app_commands.autocomplete(club=subscribed_clubs_autocomplete)
async def unsubscribe_command(interaction: discord.Interaction, club: str):
    with get_conn(DB_PATH) as conn:
        club_row = conn.execute("SELECT name FROM clubs WHERE url = ?", (club,)).fetchone()

    if not club_row:
        await interaction.response.send_message("Club not found.", ephemeral=True)
        return

    removed = remove_subscription(DB_PATH, interaction.user.id, club)
    if removed:
        await interaction.response.send_message(
            f"Unsubscribed from **{club_row['name']}**.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            f"You weren't subscribed to **{club_row['name']}**.",
            ephemeral=True,
        )


@bot.tree.command(name="mysubscriptions", description="See your active club subscriptions")
async def mysubscriptions_command(interaction: discord.Interaction):
    subs = get_user_subscriptions(DB_PATH, interaction.user.id)

    if not subs:
        await interaction.response.send_message(
            "You have no active subscriptions. Use `/subscribe` to get DM alerts for a club.",
            ephemeral=True,
        )
        return

    lines = [f"• [{s['name']}]({s['url']})" for s in subs]
    embed = discord.Embed(
        title="Your Subscriptions",
        description="\n".join(lines),
        color=discord.Color.green(),
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


if __name__ == "__main__":
    init_db(DB_PATH)
    bot.run(BOT_TOKEN)
