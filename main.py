import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import (
    BOT_TOKEN, DB_PATH, OWNER_ID, FAILURE_ALERT_THRESHOLD, GUIDE_URL,
    WATCHED_INTERVAL_HOURS, STANDARD_INTERVAL_HOURS, MANUAL_INTERVAL_HOURS,
    SCRAPE_WINDOW_START, SCRAPE_WINDOW_END, SCRAPE_TIMEZONE,
    ZYTE_MONTHLY_CAP, ZYTE_ALERT_PERCENTS,
)
from database import (
    TIERS, LEVELS, init_db, utcnow, parse_ts,
    get_setting, set_setting,
    list_clubs, get_club, add_club, remove_club, update_club,
    get_match, update_match, list_matches,
    get_rules, set_rule, delete_rule,
    due_scheduled_checks, next_scheduled_check, finish_scheduled_checks, expire_scheduled_checks,
)
from monitor import process_scrape, match_has_passed
from notifier import (
    LEVEL_ICONS, event_embed, summary_embed, registration_text,
    scrape_failure_embed, scrape_recovered_embed, usage_embed, usage_alert_embed,
)
from scraper import scrape_club, normalize_club_url
import zyte_usage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

TZ = ZoneInfo(SCRAPE_TIMEZONE)
TICK_MINUTES = 5
# Ticks land a little after a whole interval; without slack a check can slip a full tick later
INTERVAL_SLACK = timedelta(minutes=5)
# A scheduled registration check that keeps failing is retried on each tick for this long
SCHEDULED_RETRY_WINDOW = timedelta(minutes=30)
# How often the scheduler asks the Zyte Stats API for spend
USAGE_CHECK_INTERVAL = timedelta(hours=1)
TIER_INTERVALS = {
    "watched": timedelta(hours=WATCHED_INTERVAL_HOURS),
    "standard": timedelta(hours=STANDARD_INTERVAL_HOURS),
    "manual": timedelta(hours=MANUAL_INTERVAL_HOURS),
}
TIER_DESCRIPTIONS = {
    "watched": f"checked every {WATCHED_INTERVAL_HOURS:g}h",
    "standard": f"checked every {STANDARD_INTERVAL_HOURS:g}h",
    "manual": "checked daily only while a starred match is waiting to open",
    "paused": "not checked",
}
LEVEL_WORDS = {"starred": "⭐ starred", "normal": "normal", "muted": "🔇 muted"}

owner_id: int | None = OWNER_ID
# Scrapes run one at a time, whether started by the scheduler or a command
check_lock = asyncio.Lock()


class OwnerOnlyTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if owner_id and interaction.user.id == owner_id:
            return True
        if interaction.type is discord.InteractionType.application_command:
            await interaction.response.send_message("This is a private bot.", ephemeral=True)
        return False


class NeoBot(commands.Bot):
    async def setup_hook(self):
        global owner_id
        self.add_dynamic_items(LevelButton)

        if not owner_id:
            info = await self.application_info()
            owner_id = info.team.owner_id if info.team else info.owner.id
            log.info(f"Owner auto-detected from the application: {owner_id}")

        synced = await self.tree.sync()
        log.info(f"Slash commands synced (DMs only): {[c.name for c in synced]}")


bot = NeoBot(
    command_prefix=commands.when_mentioned,
    intents=discord.Intents.default(),
    tree_cls=OwnerOnlyTree,
    allowed_contexts=app_commands.AppCommandContext(guild=False, dm_channel=True, private_channel=False),
    allowed_installs=app_commands.AppInstallationType(guild=True, user=False),
)


@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user}")
    if tick.is_running():
        return  # reconnect

    # Commands used to be synced per server; clear those so they don't linger beside the DM ones
    for guild in bot.guilds:
        try:
            if await bot.tree.fetch_commands(guild=guild):
                bot.tree.clear_commands(guild=guild)
                await bot.tree.sync(guild=guild)
                log.info(f"Removed old server commands from {guild.name}")
        except discord.HTTPException as e:
            log.warning(f"Could not clear server commands in {guild.name}: {e}")

    tick.start()


# --- Helpers ---

def fmt(dt: datetime | None, style="f") -> str:
    """Discord timestamp, shown in the reader's own timezone."""
    return discord.utils.format_dt(dt, style) if dt else "never"


def match_sort_key(m):
    try:
        return datetime.strptime(m["date"] or "", "%B %d, %Y")
    except ValueError:
        return datetime.max


def local_today():
    return utcnow().astimezone(TZ).date()


def upcoming(club_url=None) -> list:
    today = local_today()
    rows = [dict(m) for m in list_matches(DB_PATH, club_url) if not match_has_passed(m["date"], today)]
    return sorted(rows, key=match_sort_key)


def has_pending_picks(club_url) -> bool:
    return any(m["level"] == "starred" and m["reg_state"] != "open" for m in upcoming(club_url))


def regular_check_due(club, now) -> bool:
    interval = TIER_INTERVALS.get(club["tier"])
    if interval is None:
        return False
    if club["tier"] == "manual" and not has_pending_picks(club["url"]):
        return False
    last = parse_ts(club["last_checked"])
    return last is None or now - last >= interval - INTERVAL_SLACK


def change_tier(club, tier) -> str:
    """Set a club's tier; leaving paused queues a summary. Returns the reply text."""
    fields = {"tier": tier}
    if club["tier"] == "paused" and tier != "paused":
        fields["summary_pending"] = 1
    update_club(DB_PATH, club["url"], **fields)
    text = f"**{club['name']}** is now **{tier}** — {TIER_DESCRIPTIONS[tier]}."
    if fields.get("summary_pending"):
        text += "\nYou'll get one summary of what changed while it was paused."
    return text


async def dm_owner(embed=None, view=None, content=None) -> bool:
    """DM the owner. Returns True only if the message actually sent."""
    if not owner_id:
        log.error("No owner resolved — cannot send DM")
        return False
    try:
        user = bot.get_user(owner_id) or await bot.fetch_user(owner_id)
        await user.send(content=content, embed=embed, view=view)
        return True
    except discord.HTTPException as e:
        log.error(f"Could not DM owner {owner_id}: {e}")
        return False


# --- Views ---

LEVEL_BUTTONS = {"starred": ("Star", "⭐"), "normal": ("Normal", None), "muted": ("Mute", "🔇")}


class LevelButton(discord.ui.DynamicItem[discord.ui.Button],
                  template=r"lvl:(?P<match_id>\d+):(?P<level>starred|normal|muted)"):
    """Star / Normal / Mute on alert DMs. Survives restarts: the state lives in the custom_id."""

    def __init__(self, match_id: str, level: str, current: str | None = None):
        label, emoji = LEVEL_BUTTONS[level]
        super().__init__(discord.ui.Button(
            label=label, emoji=emoji, custom_id=f"lvl:{match_id}:{level}",
            style=discord.ButtonStyle.primary if level == current else discord.ButtonStyle.secondary,
        ))
        self.match_id = match_id
        self.level = level

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["match_id"], match["level"])

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == owner_id

    async def callback(self, interaction: discord.Interaction):
        row = get_match(DB_PATH, self.match_id)
        if not row:
            await interaction.response.send_message("That match is no longer tracked.", ephemeral=True)
            return
        update_match(DB_PATH, self.match_id, touch=False, level=self.level)
        await interaction.response.send_message(
            f"**{row['title']}** is now {LEVEL_WORDS[self.level]}.", ephemeral=True
        )


def event_view(event) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    url = event.match.get("url")
    if url and event.kind != "removed":
        label = "Register Now" if event.match.get("reg_state") == "open" else "View Match"
        view.add_item(discord.ui.Button(label=label, url=url, style=discord.ButtonStyle.link))
    if event.kind != "removed":
        for level in LEVELS:
            view.add_item(LevelButton(event.match["match_id"], level, current=event.level))
    return view


def _clip(text, limit=100):
    return text if len(text) <= limit else text[: limit - 1] + "…"


class PickView(discord.ui.View):
    """Select which matches to star, after /scan or /addclub."""

    def __init__(self, club, matches):
        super().__init__(timeout=3600)
        self.club = club
        self.matches = matches[:25]
        select = discord.ui.Select(
            placeholder="Choose matches to be alerted about",
            min_values=0,
            max_values=len(self.matches),
            options=[
                discord.SelectOption(
                    label=_clip(m["title"]),
                    value=m["match_id"],
                    description=_clip(f"{m['date'] or 'TBD'} · {registration_text(m)}"),
                    default=m["level"] == "starred",
                )
                for m in self.matches
            ],
        )
        select.callback = self.on_pick
        self.select = select
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == owner_id

    async def on_pick(self, interaction: discord.Interaction):
        chosen = set(self.select.values)
        unstarred_level = "muted" if self.club["tier"] == "manual" else "normal"
        starred = []
        for m in self.matches:
            if m["match_id"] in chosen:
                update_match(DB_PATH, m["match_id"], touch=False, level="starred")
                starred.append(m["title"])
            elif m["level"] == "starred":
                update_match(DB_PATH, m["match_id"], touch=False, level=unstarred_level)
        if starred:
            text = "⭐ Starred: " + ", ".join(f"**{t}**" for t in starred)
            if self.club["tier"] == "manual":
                text += "\nYou'll get a DM when registration opens."
        else:
            text = "No matches starred."
        await interaction.response.send_message(text)


class ManageView(discord.ui.View):
    """/manage: a club's matches from the database, with level, tier, scan and remove controls.

    Every action re-reads the database and redraws the same message.
    """

    PAGE_SIZE = 25  # Discord's limit on select options

    def __init__(self, club_url):
        super().__init__(timeout=1800)
        self.club_url = club_url
        self.page = 0
        self.selected: set[str] = set()
        self.confirm_remove = False
        self.message: discord.Message | None = None
        self.club = None
        self.matches = []
        self.note = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == owner_id

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass

    def page_matches(self):
        start = self.page * self.PAGE_SIZE
        return self.matches[start:start + self.PAGE_SIZE]

    def render(self, note=None) -> discord.Embed | None:
        """Reload the club and rebuild the embed and controls. None if the club is gone."""
        self.club = get_club(DB_PATH, self.club_url)
        if not self.club:
            self.clear_items()
            return None
        self.matches = upcoming(self.club_url)
        ids = {m["match_id"] for m in self.matches}
        self.selected &= ids
        pages = max(1, -(-len(self.matches) // self.PAGE_SIZE))
        self.page = min(self.page, pages - 1)

        self.clear_items()
        if self.matches:
            shown = self.page_matches()
            select = discord.ui.Select(
                placeholder="Select matches, then press Star, Normal or Mute",
                min_values=0, max_values=len(shown), row=0,
                options=[
                    discord.SelectOption(
                        label=_clip(m["title"]),
                        value=m["match_id"],
                        emoji=LEVEL_ICONS.get(m["level"] or "normal") or None,
                        description=_clip(f"{m['date'] or 'TBD'} · {registration_text(m)}"),
                        default=m["match_id"] in self.selected,
                    )
                    for m in shown
                ],
            )
            select.callback = self.on_select
            self.select = select
            self.add_item(select)

            for level in LEVELS:
                label, emoji = LEVEL_BUTTONS[level]
                button = discord.ui.Button(label=label, emoji=emoji, row=1, disabled=not self.selected,
                                           style=discord.ButtonStyle.primary)
                button.callback = self.level_callback(level)
                self.add_item(button)
            if pages > 1:
                for step, label in ((-1, "◀ Prev"), (1, "Next ▶")):
                    button = discord.ui.Button(label=label, row=1, style=discord.ButtonStyle.secondary,
                                               disabled=not 0 <= self.page + step < pages)
                    button.callback = self.page_callback(step)
                    self.add_item(button)

        tier = discord.ui.Select(
            row=2,
            options=[discord.SelectOption(label=f"Tier: {t}", value=t, description=TIER_DESCRIPTIONS[t],
                                          default=t == self.club["tier"]) for t in TIERS],
        )
        tier.callback = self.on_tier
        self.tier_select = tier
        self.add_item(tier)

        scan = discord.ui.Button(label="Scan now", emoji="🔄", row=3, style=discord.ButtonStyle.secondary)
        scan.callback = self.on_scan
        self.add_item(scan)
        if self.confirm_remove:
            confirm = discord.ui.Button(label=f"Yes, remove {_clip(self.club['name'], 60)}", emoji="🗑",
                                        row=3, style=discord.ButtonStyle.danger)
            confirm.callback = self.on_remove_confirmed
            cancel = discord.ui.Button(label="Cancel", row=3, style=discord.ButtonStyle.secondary)
            cancel.callback = self.on_remove_cancelled
            self.add_item(confirm)
            self.add_item(cancel)
        else:
            remove = discord.ui.Button(label="Remove club", emoji="🗑", row=3, style=discord.ButtonStyle.danger)
            remove.callback = self.on_remove
            self.add_item(remove)

        last = parse_ts(self.club["last_checked"])
        footer = [f"Last checked {last.astimezone(TZ):%b %d, %I:%M %p %Z}" if last else "Not checked yet",
                  "no requests used until you press Scan now"]
        if pages > 1:
            footer.append(f"page {self.page + 1} of {pages}")
        if self.selected:
            footer.append(f"{len(self.selected)} selected")
        embed = summary_embed(f"Manage {self.club['name']}",
                              f"{self.club['tier']} — {TIER_DESCRIPTIONS[self.club['tier']]}",
                              self.matches, " · ".join(footer))
        if self.confirm_remove:
            note = (f"Remove **{self.club['name']}**? This deletes its {len(self.matches)} upcoming "
                    "matches, rules and scheduled checks. To stop checking but keep everything, "
                    "set the tier to paused instead.")
        self.note = note
        return embed

    async def redraw(self, interaction: discord.Interaction, note=None):
        embed = self.render(note)
        if embed is None:
            await interaction.response.edit_message(content="This club is no longer tracked.",
                                                    embed=None, view=None)
            self.stop()
            return
        await interaction.response.edit_message(content=self.note, embed=embed, view=self)

    async def on_select(self, interaction: discord.Interaction):
        on_page = {m["match_id"] for m in self.page_matches()}
        self.selected = (self.selected - on_page) | set(self.select.values)
        await self.redraw(interaction)

    def level_callback(self, level):
        async def callback(interaction: discord.Interaction):
            titles = [m["title"] for m in self.matches if m["match_id"] in self.selected]
            for match_id in self.selected:
                update_match(DB_PATH, match_id, touch=False, level=level)
            self.selected.clear()
            await self.redraw(interaction, f"Now {LEVEL_WORDS[level]}: "
                                           + ", ".join(f"**{t}**" for t in titles))
        return callback

    def page_callback(self, step):
        async def callback(interaction: discord.Interaction):
            self.page += step
            await self.redraw(interaction)
        return callback

    async def on_tier(self, interaction: discord.Interaction):
        club = get_club(DB_PATH, self.club_url)
        tier = self.tier_select.values[0]
        if not club or tier == club["tier"]:
            await self.redraw(interaction)
            return
        await self.redraw(interaction, change_tier(club, tier))

    async def on_scan(self, interaction: discord.Interaction):
        club = get_club(DB_PATH, self.club_url)
        if not club:
            await self.redraw(interaction)
            return
        await interaction.response.defer()
        events, error = await run_check(club, utcnow())
        if error:
            note = f"Scan failed: {error}"
        else:
            update_club(DB_PATH, self.club_url, summary_pending=0)
            note = f"Scanned just now. {summary_note(events) or 'No changes.'}"
        embed = self.render(note)
        if embed is None:
            await interaction.edit_original_response(content="This club is no longer tracked.",
                                                     embed=None, view=None)
            self.stop()
            return
        await interaction.edit_original_response(content=self.note, embed=embed, view=self)

    async def on_remove(self, interaction: discord.Interaction):
        self.confirm_remove = True
        await self.redraw(interaction)

    async def on_remove_cancelled(self, interaction: discord.Interaction):
        self.confirm_remove = False
        await self.redraw(interaction)

    async def on_remove_confirmed(self, interaction: discord.Interaction):
        name = self.club["name"] if self.club else "the club"
        remove_club(DB_PATH, self.club_url)
        await interaction.response.edit_message(content=f"Stopped tracking **{name}**.", embed=None, view=None)
        self.stop()


# --- Checking ---

async def run_check(club, now, result=None):
    """Scrape one club (unless `result` is given) and apply it. Returns (events, error)."""
    async with check_lock:
        try:
            if result is None:
                result = await asyncio.to_thread(scrape_club, club["url"])
            if result["name"] and result["name"] != club["name"]:
                update_club(DB_PATH, club["url"], name=result["name"])
                club = get_club(DB_PATH, club["url"])
            events = process_scrape(DB_PATH, club, result, now, now.astimezone(TZ).date())
        except Exception as e:
            log.error(f"Check failed for {club['url']}: {e}")
            update_club(DB_PATH, club["url"], last_checked=now.isoformat())
            expire_scheduled_checks(DB_PATH, club["url"], now - SCHEDULED_RETRY_WINDOW)
            return None, str(e) or type(e).__name__

        update_club(DB_PATH, club["url"], last_checked=now.isoformat())
        finish_scheduled_checks(DB_PATH, club["url"], now)
        log.info(f"Checked {club['name']}: {len(result['matches'])} listed, {len(events)} changes")
        return events, None


def summary_note(events) -> str | None:
    counts = {}
    for e in events:
        counts[e.kind] = counts.get(e.kind, 0) + 1
    words = {"new": "new", "opened": "opened", "reopened": "reopened", "closed": "closed",
             "date_changed": "date changed", "removed": "removed", "relisted": "relisted"}
    parts = [f"{n} {words[k]}" for k, n in counts.items() if k in words]
    return ("Changes: " + ", ".join(parts)) if parts else None


async def check_club(club, now) -> str | None:
    """Scheduled check: alerts DM'd one by one, or as a single summary for a new or resumed club."""
    events, error = await run_check(club, now)
    if error:
        return error

    club = get_club(DB_PATH, club["url"])
    if club["summary_pending"]:
        await dm_owner(embed=summary_embed(
            "Catching up", club["name"], upcoming(club["url"]), summary_note(events),
        ))
        update_club(DB_PATH, club["url"], summary_pending=0)
        return None

    for event in events:
        if event.alert:
            await dm_owner(embed=event_embed(event, club["name"]), view=event_view(event))
            log.info(f"Alert: {event.kind} — {event.match['title']}")
    return None


async def record_health(attempted: int, failures: list, now: datetime):
    """Alert the owner once when every check fails repeatedly, once again on recovery."""
    consecutive = int(get_setting(DB_PATH, "consecutive_failures", "0"))
    alert_sent = get_setting(DB_PATH, "failure_alert_sent", "0") == "1"

    if failures and len(failures) == attempted:
        consecutive += 1
        set_setting(DB_PATH, "consecutive_failures", consecutive)
        log.error(f"All {attempted} checks failed (consecutive failed ticks: {consecutive})")
        if consecutive >= FAILURE_ALERT_THRESHOLD and not alert_sent:
            last = parse_ts(get_setting(DB_PATH, "last_success_at"))
            embed = scrape_failure_embed(failures, consecutive, last.astimezone(TZ) if last else None)
            if await dm_owner(embed=embed):
                set_setting(DB_PATH, "failure_alert_sent", "1")
        return

    set_setting(DB_PATH, "last_success_at", now.isoformat())
    if alert_sent:
        await dm_owner(embed=scrape_recovered_embed(consecutive, now.astimezone(TZ)))
    set_setting(DB_PATH, "consecutive_failures", 0)
    set_setting(DB_PATH, "failure_alert_sent", 0)


async def check_spend(now: datetime):
    """DM once per billing period as Zyte spend passes each alert percentage of the cap."""
    last = parse_ts(get_setting(DB_PATH, "usage_checked_at"))
    if last and now - last < USAGE_CHECK_INTERVAL:
        return
    set_setting(DB_PATH, "usage_checked_at", now.isoformat())
    try:
        usage = await asyncio.to_thread(zyte_usage.fetch_usage, now)
    except Exception as e:
        log.warning(f"Zyte usage check failed: {e}")
        return

    period = usage.period_start.date().isoformat()
    sent_period, _, sent_pct = (get_setting(DB_PATH, "usage_alert_sent") or "").partition(":")
    already = int(sent_pct) if sent_period == period and sent_pct else 0
    pct = usage.cost_usd / ZYTE_MONTHLY_CAP * 100
    passed = [p for p in ZYTE_ALERT_PERCENTS if already < p <= pct]
    if not passed:
        return
    threshold = max(passed)
    embed = usage_alert_embed(usage, ZYTE_MONTHLY_CAP, threshold, zyte_usage.projected_cost(usage, now))
    if await dm_owner(embed=embed):
        set_setting(DB_PATH, "usage_alert_sent", f"{period}:{threshold}")
        log.info(f"Zyte spend alert: {pct:.1f}% of cap")


@tasks.loop(minutes=TICK_MINUTES)
async def tick():
    try:
        if zyte_usage.configured():
            await check_spend(utcnow())
        if get_setting(DB_PATH, "scraping_enabled", "1") != "1":
            return
        now = utcnow()
        local = now.astimezone(TZ)
        clubs = {c["url"]: c for c in list_clubs(DB_PATH)}

        due = []
        if SCRAPE_WINDOW_START <= local.hour < SCRAPE_WINDOW_END:
            due = [url for url, c in clubs.items() if regular_check_due(c, now)]
        # Registration-time checks run at any hour
        for check in due_scheduled_checks(DB_PATH, now):
            club = clubs.get(check["club_url"])
            if club and club["tier"] != "paused" and club["url"] not in due:
                due.append(club["url"])
        if not due:
            return

        failures = []
        for url in due:
            error = await check_club(clubs[url], now)
            if error:
                failures.append((clubs[url]["name"], error))
        await record_health(len(due), failures, now)
    except Exception:
        log.exception("Scheduler tick failed")


# --- Autocomplete ---

async def club_autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=_clip(f"{c['name']} ({c['tier']})"), value=c["url"])
        for c in list_clubs(DB_PATH)
        if current.lower() in c["name"].lower()
    ][:25]


async def match_autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(
            name=_clip(f"{LEVEL_WORDS[m['level'] or 'normal']} · {m['title']} — {m['date']}"),
            value=m["match_id"],
        )
        for m in upcoming()
        if current.lower() in f"{m['title']} {m['club_name']}".lower()
    ][:25]


TIER_CHOICES = [app_commands.Choice(name=f"{t} — {TIER_DESCRIPTIONS[t]}", value=t) for t in TIERS]


# --- Commands ---

@bot.tree.command(name="scraping", description="Turn all scheduled checks on or off (the bot keeps running)")
@app_commands.describe(state="on or off")
@app_commands.choices(state=[app_commands.Choice(name="on", value="on"),
                             app_commands.Choice(name="off", value="off")])
async def scraping_command(interaction: discord.Interaction, state: app_commands.Choice[str]):
    was_on = get_setting(DB_PATH, "scraping_enabled", "1") == "1"
    turning_on = state.value == "on"
    set_setting(DB_PATH, "scraping_enabled", "1" if turning_on else "0")
    if turning_on and not was_on:
        # Catch up with one summary per club instead of a burst of alerts
        for c in list_clubs(DB_PATH):
            if c["tier"] != "paused":
                update_club(DB_PATH, c["url"], summary_pending=1)
    await interaction.response.send_message(
        "Scraping is **on**. Clubs due a check are checked within 5 minutes."
        if turning_on else
        "Scraping is **off**. Nothing is checked until you run `/scraping on`."
    )


@bot.tree.command(name="addclub", description="Start tracking a PractiScore club by its URL")
@app_commands.describe(url="Club page, like https://practiscore.com/clubs/tps-uspsa", tier="How often to check it")
@app_commands.choices(tier=TIER_CHOICES)
async def addclub_command(interaction: discord.Interaction, url: str, tier: app_commands.Choice[str] = None):
    tier_value = tier.value if tier else "watched"
    club_url = normalize_club_url(url)
    if not club_url:
        await interaction.response.send_message(
            "That isn't a club URL. It should look like `https://practiscore.com/clubs/<club>`."
        )
        return
    if get_club(DB_PATH, club_url):
        await interaction.response.send_message("That club is already tracked. Use `/tier` to change it.")
        return

    await interaction.response.defer(thinking=True)
    try:
        result = await asyncio.to_thread(scrape_club, club_url)
    except Exception as e:
        await interaction.followup.send(f"Couldn't load that club page: {e}")
        return
    if not result["name"] or result["name"].lower() == "page not found":
        await interaction.followup.send("PractiScore says that club page doesn't exist. Check the URL.")
        return

    add_club(DB_PATH, club_url, result["name"], tier_value)
    club = get_club(DB_PATH, club_url)
    # A new club starts with summary_pending set, so if this first read fails the next
    # scheduled check sends one summary rather than an alert per existing match
    _, error = await run_check(club, utcnow(), result)
    if error:
        await interaction.followup.send(f"Added **{result['name']}**, but reading its matches failed: {error}")
        return
    update_club(DB_PATH, club_url, summary_pending=0)

    club = get_club(DB_PATH, club_url)
    matches = upcoming(club_url)
    note = f"Tier: {tier_value} — {TIER_DESCRIPTIONS[tier_value]}."
    await interaction.followup.send(
        embed=summary_embed(f"Now tracking {result['name']}", result["name"], matches, note),
        view=PickView(club, matches) if matches else None,
    )


@bot.tree.command(name="removeclub", description="Stop tracking a club and forget its matches")
@app_commands.describe(club="Club to remove")
@app_commands.autocomplete(club=club_autocomplete)
async def removeclub_command(interaction: discord.Interaction, club: str):
    row = get_club(DB_PATH, club)
    if not row:
        await interaction.response.send_message("Club not found.")
        return
    remove_club(DB_PATH, club)
    await interaction.response.send_message(f"Stopped tracking **{row['name']}**.")


@bot.tree.command(name="tier", description="Change how often a club is checked")
@app_commands.describe(club="Club to change", tier="New tier")
@app_commands.autocomplete(club=club_autocomplete)
@app_commands.choices(tier=TIER_CHOICES)
async def tier_command(interaction: discord.Interaction, club: str, tier: app_commands.Choice[str]):
    row = get_club(DB_PATH, club)
    if not row:
        await interaction.response.send_message("Club not found.")
        return
    await interaction.response.send_message(change_tier(row, tier.value))


@bot.tree.command(name="scan", description="Check a club right now and choose which matches to star")
@app_commands.describe(club="Club to scan")
@app_commands.autocomplete(club=club_autocomplete)
async def scan_command(interaction: discord.Interaction, club: str):
    row = get_club(DB_PATH, club)
    if not row:
        await interaction.response.send_message("Club not found.")
        return
    await interaction.response.defer(thinking=True)
    events, error = await run_check(row, utcnow())
    if error:
        await interaction.followup.send(f"Scan failed: {error}")
        return
    update_club(DB_PATH, club, summary_pending=0)
    row = get_club(DB_PATH, club)
    matches = upcoming(club)
    await interaction.followup.send(
        embed=summary_embed(f"Scan of {row['name']}", row["name"], matches, summary_note(events)),
        view=PickView(row, matches) if matches else None,
    )


async def _set_level(interaction: discord.Interaction, match_id: str, level: str):
    row = get_match(DB_PATH, match_id)
    if not row:
        await interaction.response.send_message("Match not found.")
        return
    update_match(DB_PATH, match_id, touch=False, level=level)
    await interaction.response.send_message(f"**{row['title']}** is now {LEVEL_WORDS[level]}.")


@bot.tree.command(name="star", description="Get every alert for a match, including closes and date changes")
@app_commands.describe(match="Match to star")
@app_commands.autocomplete(match=match_autocomplete)
async def star_command(interaction: discord.Interaction, match: str):
    await _set_level(interaction, match, "starred")


@bot.tree.command(name="unstar", description="Back to normal alerts: new match and registration open")
@app_commands.describe(match="Match to unstar")
@app_commands.autocomplete(match=match_autocomplete)
async def unstar_command(interaction: discord.Interaction, match: str):
    await _set_level(interaction, match, "normal")


@bot.tree.command(name="mute", description="No alerts for a match")
@app_commands.describe(match="Match to mute")
@app_commands.autocomplete(match=match_autocomplete)
async def mute_command(interaction: discord.Interaction, match: str):
    await _set_level(interaction, match, "muted")


@bot.tree.command(name="rule", description="Auto-set the level of a club's new matches by type or title")
@app_commands.describe(
    club="Club the rule applies to",
    text="Text to look for in the match type or title, e.g. Steel Challenge",
    level="Level for matching new matches, or remove to delete the rule",
)
@app_commands.autocomplete(club=club_autocomplete)
@app_commands.choices(level=[app_commands.Choice(name=l, value=l) for l in (*LEVELS, "remove")])
async def rule_command(interaction: discord.Interaction, club: str, text: str, level: app_commands.Choice[str]):
    row = get_club(DB_PATH, club)
    if not row:
        await interaction.response.send_message("Club not found.")
        return
    text = text.strip()
    if level.value == "remove":
        done = delete_rule(DB_PATH, club, text)
        msg = f"Removed the rule for “{text}”." if done else f"No rule for “{text}” at {row['name']}."
    else:
        set_rule(DB_PATH, club, text, level.value)
        msg = f"New {row['name']} matches containing “{text}” will be {LEVEL_WORDS[level.value]}."
    rules = get_rules(DB_PATH, club)
    listing = "\n".join(f"• “{r['type_contains']}” → {LEVEL_WORDS[r['level']]}" for r in rules) or "none"
    await interaction.response.send_message(
        f"{msg}\nRules apply to newly posted matches; use `/star` or `/mute` for existing ones.\n\n"
        f"**{row['name']} rules:**\n{listing}"
    )


@bot.tree.command(name="matches", description="Show upcoming matches — all clubs, or just one")
@app_commands.describe(club="Filter to a specific club (optional)")
@app_commands.autocomplete(club=club_autocomplete)
async def matches_command(interaction: discord.Interaction, club: str = None):
    clubs = [get_club(DB_PATH, club)] if club else list_clubs(DB_PATH)
    clubs = [c for c in clubs if c]
    if not clubs:
        await interaction.response.send_message("No clubs are tracked. Add one with `/addclub`.")
        return
    embeds = []
    for c in clubs[:10]:
        last = parse_ts(c["last_checked"])
        note = f"Last checked {last.astimezone(TZ):%b %d, %I:%M %p %Z}" if last else "Not checked yet"
        embeds.append(summary_embed(c["name"], f"{c['tier']} club", upcoming(c["url"]), note))
    await interaction.response.send_message(embeds=embeds)


@bot.tree.command(name="manage", description="Star, unstar or mute a club's matches, change its tier, or remove it")
@app_commands.describe(club="Club to manage")
@app_commands.autocomplete(club=club_autocomplete)
async def manage_command(interaction: discord.Interaction, club: str):
    if not get_club(DB_PATH, club):
        await interaction.response.send_message("Club not found.")
        return
    view = ManageView(club)
    embed = view.render()
    await interaction.response.send_message(embed=embed, view=view)
    view.message = await interaction.original_response()


@bot.tree.command(name="clubs", description="List tracked clubs with their tier and rules")
async def clubs_command(interaction: discord.Interaction):
    clubs = list_clubs(DB_PATH)
    if not clubs:
        await interaction.response.send_message("No clubs are tracked. Add one with `/addclub`.")
        return
    embed = discord.Embed(title="Tracked Clubs", color=discord.Color.blue())
    for c in clubs:
        matches = upcoming(c["url"])
        starred = sum(1 for m in matches if m["level"] == "starred")
        rules = get_rules(DB_PATH, c["url"])
        lines = [
            f"**{c['tier']}** — {TIER_DESCRIPTIONS[c['tier']]}",
            f"Last checked: {fmt(parse_ts(c['last_checked']), 'R')}",
            f"{len(matches)} upcoming · {starred} starred",
            f"[Club page]({c['url']})",
        ]
        if rules:
            lines.append("Rules: " + ", ".join(f"“{r['type_contains']}” → {r['level']}" for r in rules))
        embed.add_field(name=c["name"], value="\n".join(lines), inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="status", description="Scraping on/off, health, and upcoming checks")
async def status_command(interaction: discord.Interaction):
    enabled = get_setting(DB_PATH, "scraping_enabled", "1") == "1"
    consecutive = int(get_setting(DB_PATH, "consecutive_failures", "0"))
    last_success = parse_ts(get_setting(DB_PATH, "last_success_at"))
    clubs = list_clubs(DB_PATH)

    if consecutive:
        health = f"⚠️ Failing — {consecutive} failed checks in a row"
    elif last_success:
        health = f"✅ OK — last success {fmt(last_success, 'R')}"
    else:
        health = "No completed check yet"

    tiers = {t: sum(1 for c in clubs if c["tier"] == t) for t in TIERS}
    now = utcnow()
    next_regular = None
    for c in clubs:
        interval = TIER_INTERVALS.get(c["tier"])
        last = parse_ts(c["last_checked"])
        if interval and last and (c["tier"] != "manual" or has_pending_picks(c["url"])):
            due = last + interval
            next_regular = min(next_regular or due, due)

    embed = discord.Embed(title="PractiScore Neo — Status", color=discord.Color.blurple())
    embed.add_field(name="Scraping", value="🟢 On" if enabled else "⏸️ Off", inline=True)
    embed.add_field(name="Health", value=health, inline=True)
    embed.add_field(
        name="Clubs", value=" · ".join(f"{n} {t}" for t, n in tiers.items() if n) or "none", inline=False
    )
    embed.add_field(
        name="Next regular check",
        value=(fmt(max(next_regular, now), "R") if next_regular else "at the next tick")
        + f"\nRegular checks run {SCRAPE_WINDOW_START}:00–{SCRAPE_WINDOW_END}:00 {SCRAPE_TIMEZONE}",
        inline=False,
    )
    embed.add_field(
        name="Next registration-time check", value=fmt(next_scheduled_check(DB_PATH), "R"), inline=False
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="usage", description="Zyte API spend this billing period")
async def usage_command(interaction: discord.Interaction):
    if not zyte_usage.configured():
        await interaction.response.send_message(
            "Zyte usage isn't set up. Add `ZYTE_DASHBOARD_KEY` and `ZYTE_ORG_ID` to `.env` and restart."
        )
        return
    await interaction.response.defer()
    now = utcnow()
    try:
        usage = await asyncio.to_thread(zyte_usage.fetch_usage, now)
    except Exception as e:
        await interaction.followup.send(f"Couldn't get usage from Zyte:\n```{str(e)[:500]}```")
        return
    await interaction.followup.send(
        embed=usage_embed(usage, ZYTE_MONTHLY_CAP, zyte_usage.projected_cost(usage, now))
    )


COMMAND_HELP = {
    "scraping": {
        "summary": "Turn all scheduled checks on or off",
        "description": "Pauses or resumes every scheduled check, including registration-time checks. "
                       "The bot stays online and commands keep working. Turning it back on sends one "
                       "catch-up summary per club instead of an alert for everything that changed. "
                       "The setting survives restarts.",
        "usage": "`/scraping state:<on|off>`",
        "examples": ["`/scraping state:off`", "`/scraping state:on`"],
    },
    "addclub": {
        "summary": "Track a club by URL, with a tier",
        "description": "Loads the club page once (1 request) to confirm it exists and get its name, then "
                       "replies with its upcoming matches and a picker to star some. New matches default to "
                       "starred for watched clubs, normal for standard, muted for manual.",
        "usage": "`/addclub url:<club page URL> [tier:<watched|standard|manual|paused>]` (default watched)",
        "examples": ["`/addclub url:https://practiscore.com/clubs/tps-uspsa`",
                     "`/addclub url:https://practiscore.com/clubs/some-club tier:manual`"],
    },
    "removeclub": {
        "summary": "Stop tracking a club",
        "description": "Deletes the club with its matches, rules and scheduled checks. To stop checking "
                       "it but keep everything, use `/tier` with `paused` instead.",
        "usage": "`/removeclub club:<club>`",
        "examples": ["`/removeclub club:Friendly Gun Club`"],
    },
    "tier": {
        "summary": "Change how often a club is checked",
        "description": "\n".join(f"**{t}** — {TIER_DESCRIPTIONS[t]}" for t in TIERS)
                       + "\n\nLeaving paused sends one summary of what changed while it was paused.",
        "usage": "`/tier club:<club> tier:<watched|standard|manual|paused>`",
        "examples": ["`/tier club:Gainesville Practical Shooters tier:standard`",
                     "`/tier club:Friendly Gun Club tier:paused`"],
    },
    "scan": {
        "summary": "Check a club now and pick matches to star",
        "description": "Checks the club immediately (1 request), whatever its tier, and replies with its "
                       "upcoming matches plus a picker. Selected matches become starred; unselected starred "
                       "matches go back to normal (muted for manual clubs). For a manual club, starring is "
                       "how you ask to be told when registration opens.",
        "usage": "`/scan club:<club>`",
        "examples": ["`/scan club:TPS USPSA`"],
    },
    "star": {
        "summary": "Get every alert for a match",
        "description": "Starred matches alert on: new, registration open, closed again, reopened, date "
                       "changed, removed from the listing. Same as the ⭐ Star button on alerts.",
        "usage": "`/star match:<match>`",
        "examples": ["`/star match:TPS USPSA October`"],
    },
    "unstar": {
        "summary": "Back to normal alerts for a match",
        "description": "Normal matches alert only when posted and when registration opens.",
        "usage": "`/unstar match:<match>`",
        "examples": ["`/unstar match:Guardian Steel Training Event`"],
    },
    "mute": {
        "summary": "No alerts for a match",
        "description": "The match is still tracked and shown in `/matches`, but nothing is DM'd about it "
                       "(except an unrecognized registration label).",
        "usage": "`/mute match:<match>`",
        "examples": ["`/mute match:TPS PCSL Carbine`"],
    },
    "rule": {
        "summary": "Auto-set levels for a club's new matches",
        "description": "When a club posts a new match whose type or title contains the text (case doesn't "
                       "matter), it gets that level instead of the tier default. If several rules match, "
                       "the longest text wins. Rules only affect matches posted after they're made; use "
                       "`/star` or `/mute` for existing ones. Pick `remove` to delete a rule. The reply "
                       "lists the club's rules.",
        "usage": "`/rule club:<club> text:<text> level:<starred|normal|muted|remove>`",
        "examples": ["`/rule club:TPS USPSA text:Steel Challenge level:normal`",
                     "`/rule club:TPS USPSA text:PCSL level:muted`",
                     "`/rule club:TPS USPSA text:PCSL level:remove`"],
    },
    "matches": {
        "summary": "Upcoming matches, all clubs or one",
        "description": "Reads the database, so it costs no requests. Shows each match's date, registration "
                       "state and level (⭐ starred, 🔇 muted). Data is as of each club's last check.",
        "usage": "`/matches [club:<club>]`",
        "examples": ["`/matches`", "`/matches club:TPS USPSA`"],
    },
    "manage": {
        "summary": "Change a club's match levels, tier, or remove it",
        "description": "Shows the club's upcoming matches from the database (no requests). Select any "
                       "number of matches, then press ⭐ Star, Normal or 🔇 Mute; the list redraws so you "
                       "can do several batches. The same message changes the tier, runs a scan (the only "
                       "control that costs a request) and removes the club after you confirm. The controls "
                       "stop working after 30 minutes; run `/manage` again for fresh ones.",
        "usage": "`/manage club:<club>`",
        "examples": ["`/manage club:TPS USPSA`"],
    },
    "clubs": {
        "summary": "Tracked clubs, tiers and rules",
        "description": "Each club's tier, last check, upcoming and starred counts, rules and page link.",
        "usage": "`/clubs`",
        "examples": [],
    },
    "status": {
        "summary": "Scraping on/off, health, next checks",
        "description": "Whether scraping is on, whether recent checks succeeded, clubs per tier, the next "
                       "regular check (runs "
                       f"{SCRAPE_WINDOW_START}:00–{SCRAPE_WINDOW_END}:00 {SCRAPE_TIMEZONE}), and the next "
                       "check timed to a registration opening (runs at any hour).",
        "usage": "`/status`",
        "examples": [],
    },
    "usage": {
        "summary": "Zyte spend this billing period",
        "description": f"Asks the Zyte Stats API (not a scraping request, so it's free) for spend since the "
                       f"billing period started: dollars against the ${ZYTE_MONTHLY_CAP:.0f} monthly cap, "
                       "request count and cost per 1,000, failed requests, a projection to the reset date, "
                       "and the last 7 days. The bot also DMs you once per period as spend passes "
                       + ", ".join(f"{p}%" for p in ZYTE_ALERT_PERCENTS) + " of the cap.",
        "usage": "`/usage`",
        "examples": [],
    },
    "help": {
        "summary": "This list, or details for one command",
        "description": "Without a command, lists every command plus how tiers and levels work.",
        "usage": "`/help [command:<command>]`",
        "examples": ["`/help`", "`/help command:rule`"],
    },
}


# Commands that share another command's entry in the guide
GUIDE_ANCHORS = {"unstar": "star", "mute": "star"}


def guide_view(anchor="", label="Full guide") -> discord.ui.View:
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label=label, emoji="📖", url=GUIDE_URL + anchor,
                                    style=discord.ButtonStyle.link))
    return view


async def help_autocomplete(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=name, value=name) for name in COMMAND_HELP
            if current.lower() in name][:25]


@bot.tree.command(name="help", description="List commands, or get details for one")
@app_commands.describe(command="Command to explain (optional)")
@app_commands.autocomplete(command=help_autocomplete)
async def help_command(interaction: discord.Interaction, command: str = None):
    if command:
        info = COMMAND_HELP.get(command.strip().lstrip("/").lower())
        if not info:
            await interaction.response.send_message(
                f"Unknown command `{command}`. Run `/help` for the list."
            )
            return
        name = command.strip().lstrip("/").lower()
        embed = discord.Embed(title=f"/{name}", description=info["description"], color=discord.Color.blue())
        embed.add_field(name="Usage", value=info["usage"], inline=False)
        if info["examples"]:
            embed.add_field(name="Examples", value="\n".join(info["examples"]), inline=False)
        await interaction.response.send_message(
            embed=embed, view=guide_view(f"#cmd-{GUIDE_ANCHORS.get(name, name)}", f"/{name} in the guide")
        )
        return

    embed = discord.Embed(
        title="PractiScore Neo — Commands",
        description="\n".join(f"`/{name}` — {info['summary']}" for name, info in COMMAND_HELP.items())
                    + "\n\nRun `/help command:<name>` for details and examples.",
        color=discord.Color.blue(),
    )
    embed.add_field(
        name="Tiers (how often a club is checked)",
        value="\n".join(f"**{t}** — {TIER_DESCRIPTIONS[t]}" for t in TIERS),
        inline=False,
    )
    embed.add_field(
        name="Levels (what you're told about a match)",
        value="⭐ **starred** — everything: new, open, closed again, reopened, date changed, removed\n"
              "**normal** — new match and registration open\n"
              "🔇 **muted** — nothing",
        inline=False,
    )
    await interaction.response.send_message(embed=embed, view=guide_view())


if __name__ == "__main__":
    init_db(DB_PATH)
    bot.run(BOT_TOKEN)
