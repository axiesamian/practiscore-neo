"""Turns a club-page scrape into database updates and alert events. No Discord here."""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from database import (
    get_club_matches, get_rules, insert_match, update_match, add_scheduled_check,
)
from scraper import parse_countdown

# Which match levels each event is DM'd for. Unknown labels always go out: they
# mean PractiScore showed something the parser has never seen.
ALERT_LEVELS = {
    "new": {"starred", "normal"},
    "opened": {"starred", "normal"},
    "reopened": {"starred", "normal"},
    "closed": {"starred"},
    "date_changed": {"starred"},
    "removed": {"starred"},
    "relisted": {"starred"},
    "unknown_label": {"starred", "normal", "muted"},
}

TIER_DEFAULT_LEVEL = {"watched": "starred", "standard": "normal", "manual": "muted", "paused": "normal"}

# A listed match must be missing from this many consecutive checks before it's reported removed
MISSING_CHECKS_BEFORE_REMOVED = 2


class SuspiciousScrape(Exception):
    """The page loaded but its contents don't look like a real listing."""


@dataclass
class Event:
    kind: str
    match: dict
    level: str
    old: dict = field(default_factory=dict)

    @property
    def alert(self) -> bool:
        return self.level in ALERT_LEVELS[self.kind]


def match_has_passed(date_str: str | None, today: date) -> bool:
    """True once a match's date is behind us. Unparseable dates count as not passed."""
    try:
        return datetime.strptime(date_str or "", "%B %d, %Y").date() < today
    except ValueError:
        return False


def default_level(tier: str, match: dict, rules: list) -> str:
    """Level for a newly seen match: the longest matching club rule, else the tier default."""
    haystack = f"{match.get('match_type', '')} {match.get('title', '')}".lower()
    hits = [r for r in rules if r["type_contains"].lower() in haystack]
    if hits:
        return max(hits, key=lambda r: len(r["type_contains"]))["level"]
    return TIER_DEFAULT_LEVEL[tier]


def countdown_check_times(label_text: str, now: datetime) -> list[datetime]:
    """When to look again so an opening announced as "opens in N hours/minutes" is caught promptly.

    The label rounds down, so the opening lies in [lower, upper). One check shortly after the
    earliest possible time, one just after the latest. Day-or-longer countdowns get none: a
    regular check will see the hour countdown first.
    """
    bounds = parse_countdown(label_text)
    if not bounds:
        return []
    lower, upper = bounds
    if upper > timedelta(days=1):
        return []
    if upper <= timedelta(hours=1):
        return [now + upper + timedelta(minutes=1)]
    return [now + lower + timedelta(minutes=30), now + upper + timedelta(minutes=2)]


def _current(row, scraped=None) -> dict:
    """Stored match merged with fresh scraped values, as a plain dict for the notifier."""
    merged = {k: row[k] for k in row.keys()} if row is not None else {}
    if scraped:
        merged.update(scraped)
    return merged


def process_scrape(db_path: str, club, result: dict, now: datetime, today: date) -> list[Event]:
    """Apply one scrape of `club` to the database and return what changed."""
    scraped = result["matches"]
    known = get_club_matches(db_path, club["url"])
    rules = get_rules(db_path, club["url"])

    listed_upcoming = [
        r for r in known.values() if not r["cancelled"] and not match_has_passed(r["date"], today)
    ]
    if not scraped and len(listed_upcoming) >= 2:
        raise SuspiciousScrape(
            f"Listing came back empty but {len(listed_upcoming)} upcoming matches were listed before"
        )

    events = []
    seen = set()
    for m in scraped:
        seen.add(m["match_id"])
        row = known.get(m["match_id"])

        if row is None:
            level = default_level(club["tier"], m, rules)
            insert_match(db_path, club["url"], club["name"], m, level)
            events.append(Event("new", _current(None, m), level))
            if m["reg_state"] == "unknown":
                events.append(Event("unknown_label", _current(None, m), level))
        else:
            level = row["level"] or TIER_DEFAULT_LEVEL[club["tier"]]
            current = _current(row, m)
            fields = {
                "title": m["title"], "match_type": m["match_type"], "url": m["url"],
                "label_text": m["label_text"], "missing_count": 0, "club_name": club["name"],
            }
            if row["cancelled"]:
                fields["cancelled"] = 0
                events.append(Event("relisted", current, level))

            old_state, new_state = row["reg_state"], m["reg_state"]
            if new_state != old_state:
                fields["reg_state"] = new_state
                if new_state == "open":
                    kind = "reopened" if row["registration_notified"] else "opened"
                    fields["registration_notified"] = 1
                    events.append(Event(kind, current, level, {"reg_state": old_state}))
                elif new_state == "unknown":
                    events.append(Event("unknown_label", current, level, {"reg_state": old_state}))
                elif new_state == "closed" or old_state == "open":
                    events.append(Event("closed", current, level, {"reg_state": old_state}))
            elif new_state == "unknown" and m["label_text"] != row["label_text"]:
                events.append(Event("unknown_label", current, level))

            if m["date"] and row["date"] and m["date"] != row["date"]:
                fields["date"] = m["date"]
                events.append(Event("date_changed", current, level, {"date": row["date"]}))

            update_match(db_path, m["match_id"], **fields)

        if m["reg_state"] == "not_yet" and level != "muted":
            for run_at in countdown_check_times(m["label_text"], now):
                add_scheduled_check(db_path, club["url"], m["match_id"], run_at)

    for row in listed_upcoming:
        if row["match_id"] in seen:
            continue
        missing = row["missing_count"] + 1
        if missing >= MISSING_CHECKS_BEFORE_REMOVED:
            update_match(db_path, row["match_id"], touch=False, cancelled=1, missing_count=missing)
            events.append(Event("removed", _current(row), row["level"] or "normal"))
        else:
            update_match(db_path, row["match_id"], touch=False, missing_count=missing)

    return events
