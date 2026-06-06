import sqlite3
from pathlib import Path


def get_conn(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


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
        try:
            conn.execute("ALTER TABLE matches ADD COLUMN cancelled INTEGER DEFAULT 0")
        except Exception:
            pass  # column already exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER NOT NULL,
                club_url TEXT NOT NULL,
                PRIMARY KEY (user_id, club_url)
            )
        """)
        conn.commit()


def seed_clubs(db_path, urls: list):
    with get_conn(db_path) as conn:
        for url in urls:
            slug = url.rstrip("/").split("/")[-1]
            conn.execute(
                "INSERT OR IGNORE INTO clubs (url, name) VALUES (?, ?)",
                (url, slug),
            )
        conn.commit()


def update_club_name(db_path, url: str, name: str):
    with get_conn(db_path) as conn:
        conn.execute("UPDATE clubs SET name = ? WHERE url = ?", (name, url))
        conn.commit()


def get_active_matches_for_club(db_path, club_url: str) -> list:
    """Returns announced, non-cancelled matches for a club."""
    with get_conn(db_path) as conn:
        return conn.execute(
            """SELECT match_id, title, date, match_type, url
               FROM matches
               WHERE club_url = ? AND announced = 1 AND cancelled = 0""",
            (club_url,),
        ).fetchall()


def mark_match_cancelled(db_path, match_id: str):
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE matches SET cancelled = 1, last_seen = datetime('now') WHERE match_id = ?",
            (match_id,),
        )
        conn.commit()


def add_subscription(db_path, user_id: int, club_url: str) -> bool:
    """Returns True if newly subscribed, False if already subscribed."""
    with get_conn(db_path) as conn:
        existing = conn.execute(
            "SELECT 1 FROM subscriptions WHERE user_id = ? AND club_url = ?",
            (user_id, club_url),
        ).fetchone()
        if existing:
            return False
        conn.execute(
            "INSERT INTO subscriptions (user_id, club_url) VALUES (?, ?)",
            (user_id, club_url),
        )
        conn.commit()
        return True


def remove_subscription(db_path, user_id: int, club_url: str) -> bool:
    """Returns True if removed, False if wasn't subscribed."""
    with get_conn(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM subscriptions WHERE user_id = ? AND club_url = ?",
            (user_id, club_url),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_user_subscriptions(db_path, user_id: int) -> list:
    """Returns list of (url, name) rows for clubs the user is subscribed to."""
    with get_conn(db_path) as conn:
        return conn.execute(
            """SELECT c.url, c.name FROM subscriptions s
               JOIN clubs c ON c.url = s.club_url
               WHERE s.user_id = ?
               ORDER BY c.name""",
            (user_id,),
        ).fetchall()


def get_club_subscribers(db_path, club_url: str) -> list[int]:
    """Returns list of user_ids subscribed to the given club."""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT user_id FROM subscriptions WHERE club_url = ?",
            (club_url,),
        ).fetchall()
        return [r["user_id"] for r in rows]
