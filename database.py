import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

TIERS = ("watched", "standard", "manual", "paused")
LEVELS = ("starred", "normal", "muted")


def get_conn(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: str | None) -> datetime | None:
    """Parse a stored timestamp. SQLite's datetime('now') values are UTC without an offset."""
    if not value:
        return None
    ts = datetime.fromisoformat(value)
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _add_column(conn, table, column, decl):
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        return True
    return False


def init_db(db_path):
    with get_conn(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS clubs (
                url TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                added_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                match_id TEXT PRIMARY KEY,
                club_url TEXT NOT NULL,
                club_name TEXT NOT NULL,
                title TEXT NOT NULL,
                date TEXT,
                match_type TEXT,
                url TEXT,
                announced INTEGER DEFAULT 0,
                registration_notified INTEGER DEFAULT 0,
                first_seen TEXT DEFAULT (datetime('now')),
                last_seen TEXT DEFAULT (datetime('now'))
            )
        """)
        _add_column(conn, "matches", "cancelled", "INTEGER DEFAULT 0")

        # Personal DM rework (2026-09). Existing clubs become watched; existing matches
        # get a registration state from the old one-shot flag and are starred.
        _add_column(conn, "clubs", "tier", "TEXT NOT NULL DEFAULT 'watched'")
        _add_column(conn, "clubs", "last_checked", "TEXT")
        _add_column(conn, "clubs", "summary_pending", "INTEGER NOT NULL DEFAULT 0")
        if _add_column(conn, "matches", "reg_state", "TEXT"):
            conn.execute(
                "UPDATE matches SET reg_state = CASE WHEN registration_notified = 1 THEN 'open' ELSE 'not_yet' END"
            )
        _add_column(conn, "matches", "label_text", "TEXT")
        if _add_column(conn, "matches", "level", "TEXT"):
            conn.execute("UPDATE matches SET level = 'starred'")
        _add_column(conn, "matches", "missing_count", "INTEGER NOT NULL DEFAULT 0")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS club_rules (
                club_url TEXT NOT NULL,
                type_contains TEXT NOT NULL,
                level TEXT NOT NULL,
                PRIMARY KEY (club_url, type_contains)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                club_url TEXT NOT NULL,
                match_id TEXT NOT NULL,
                run_at TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute("DROP TABLE IF EXISTS subscriptions")
        conn.commit()


# --- Settings ---

def get_setting(db_path, key, default=None):
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(db_path, key, value):
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, None if value is None else str(value)),
        )
        conn.commit()


# --- Clubs ---

def list_clubs(db_path) -> list:
    with get_conn(db_path) as conn:
        return conn.execute("SELECT * FROM clubs ORDER BY name").fetchall()


def get_club(db_path, url):
    with get_conn(db_path) as conn:
        return conn.execute("SELECT * FROM clubs WHERE url = ?", (url,)).fetchone()


def add_club(db_path, url, name, tier):
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO clubs (url, name, tier, summary_pending) VALUES (?, ?, ?, 1)",
            (url, name, tier),
        )
        conn.commit()


def remove_club(db_path, url):
    with get_conn(db_path) as conn:
        for table, col in (("scheduled_checks", "club_url"), ("club_rules", "club_url"),
                           ("matches", "club_url"), ("clubs", "url")):
            conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (url,))
        conn.commit()


def update_club(db_path, url, **fields):
    if not fields:
        return
    assignments = ", ".join(f"{k} = ?" for k in fields)
    with get_conn(db_path) as conn:
        conn.execute(f"UPDATE clubs SET {assignments} WHERE url = ?", (*fields.values(), url))
        conn.commit()


# --- Matches ---

def get_club_matches(db_path, club_url) -> dict:
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT * FROM matches WHERE club_url = ?", (club_url,)).fetchall()
    return {r["match_id"]: r for r in rows}


def get_match(db_path, match_id):
    with get_conn(db_path) as conn:
        return conn.execute("SELECT * FROM matches WHERE match_id = ?", (match_id,)).fetchone()


def insert_match(db_path, club_url, club_name, match, level):
    with get_conn(db_path) as conn:
        conn.execute(
            """INSERT INTO matches
               (match_id, club_url, club_name, title, date, match_type, url,
                announced, registration_notified, reg_state, label_text, level)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
            (match["match_id"], club_url, club_name, match["title"], match["date"],
             match["match_type"], match["url"], int(match["reg_state"] == "open"),
             match["reg_state"], match["label_text"], level),
        )
        conn.commit()


def update_match(db_path, match_id, touch=True, **fields):
    """Update a match. `touch` stamps last_seen — pass False when the match wasn't on the page."""
    if touch:
        fields["last_seen"] = utcnow().strftime("%Y-%m-%d %H:%M:%S")
    assignments = ", ".join(f"{k} = ?" for k in fields)
    with get_conn(db_path) as conn:
        conn.execute(f"UPDATE matches SET {assignments} WHERE match_id = ?", (*fields.values(), match_id))
        conn.commit()


def list_matches(db_path, club_url=None) -> list:
    """Listed, non-removed matches, optionally for one club."""
    query = "SELECT * FROM matches WHERE cancelled = 0"
    params = ()
    if club_url:
        query += " AND club_url = ?"
        params = (club_url,)
    with get_conn(db_path) as conn:
        return conn.execute(query, params).fetchall()


# --- Rules ---

def get_rules(db_path, club_url=None) -> list:
    with get_conn(db_path) as conn:
        if club_url:
            return conn.execute(
                "SELECT * FROM club_rules WHERE club_url = ? ORDER BY type_contains", (club_url,)
            ).fetchall()
        return conn.execute("SELECT * FROM club_rules ORDER BY club_url, type_contains").fetchall()


def set_rule(db_path, club_url, type_contains, level):
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO club_rules (club_url, type_contains, level) VALUES (?, ?, ?) "
            "ON CONFLICT(club_url, type_contains) DO UPDATE SET level = excluded.level",
            (club_url, type_contains, level),
        )
        conn.commit()


def delete_rule(db_path, club_url, type_contains) -> bool:
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM club_rules WHERE club_url = ? AND type_contains = ? COLLATE NOCASE",
            (club_url, type_contains),
        )
        conn.commit()
        return cur.rowcount > 0


# --- Scheduled checks ---

def add_scheduled_check(db_path, club_url, match_id, run_at: datetime):
    """Schedule a one-off check. Pending checks within 10 minutes of each other collapse into one,
    and the earliest wins: a later one is replaced, so a tighter countdown is never delayed."""
    with get_conn(db_path) as conn:
        pending = conn.execute(
            "SELECT id, run_at FROM scheduled_checks WHERE match_id = ? AND done = 0", (match_id,)
        ).fetchall()
        nearby = [r for r in pending if abs((parse_ts(r["run_at"]) - run_at).total_seconds()) < 600]
        if any(parse_ts(r["run_at"]) <= run_at for r in nearby):
            return False
        conn.executemany("DELETE FROM scheduled_checks WHERE id = ?", [(r["id"],) for r in nearby])
        conn.execute(
            "INSERT INTO scheduled_checks (club_url, match_id, run_at) VALUES (?, ?, ?)",
            (club_url, match_id, run_at.isoformat()),
        )
        conn.commit()
        return True


def due_scheduled_checks(db_path, now: datetime) -> list:
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT * FROM scheduled_checks WHERE done = 0").fetchall()
    return [r for r in rows if parse_ts(r["run_at"]) <= now]


def next_scheduled_check(db_path):
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT run_at FROM scheduled_checks WHERE done = 0").fetchall()
    times = [parse_ts(r["run_at"]) for r in rows]
    return min(times) if times else None


def expire_scheduled_checks(db_path, club_url, cutoff: datetime):
    """Give up on a club's due checks scheduled before `cutoff` (they kept failing)."""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT id, run_at FROM scheduled_checks WHERE club_url = ? AND done = 0", (club_url,)
        ).fetchall()
        ids = [r["id"] for r in rows if parse_ts(r["run_at"]) < cutoff]
        conn.executemany("UPDATE scheduled_checks SET done = 1 WHERE id = ?", [(i,) for i in ids])
        conn.commit()


def finish_scheduled_checks(db_path, club_url, now: datetime):
    """Mark every due check for a club done — one scrape of the club page answers all of them."""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT id, run_at FROM scheduled_checks WHERE club_url = ? AND done = 0", (club_url,)
        ).fetchall()
        ids = [r["id"] for r in rows if parse_ts(r["run_at"]) <= now]
        conn.executemany("UPDATE scheduled_checks SET done = 1 WHERE id = ?", [(i,) for i in ids])
        conn.execute("DELETE FROM scheduled_checks WHERE done = 1 AND run_at < ?",
                     ((now - timedelta(days=7)).isoformat(),))
        conn.commit()
