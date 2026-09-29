import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

from database import (
    init_db, add_club, get_club, get_match, set_rule, update_match, due_scheduled_checks,
)
from monitor import SuspiciousScrape, default_level, process_scrape

CLUB = "https://practiscore.com/clubs/friendly_gun_club"
NOW = datetime(2026, 9, 29, 18, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 29)


def m(match_id, state, label=None, date_="October 24, 2026", mtype="USPSA level I", title=None):
    return {
        "match_id": match_id, "title": title or f"Match {match_id}",
        "url": f"https://practiscore.com/m{match_id}/register", "date": date_,
        "match_type": mtype, "reg_state": state,
        "label_text": label or {"open": "open", "closed": "closed", "not_yet": "opens in 1 week"}.get(state, "full"),
    }


class MonitorTest(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        init_db(self.db)
        add_club(self.db, CLUB, "Friendly Gun Club", "watched")

    def tearDown(self):
        os.remove(self.db)

    def scrape(self, *matches, now=NOW):
        club = get_club(self.db, CLUB)
        return process_scrape(self.db, club, {"name": club["name"], "matches": list(matches)}, now, TODAY)

    def kinds(self, events):
        return [(e.kind, e.match["match_id"]) for e in events]

    def test_fgc_test_sequence(self):
        """The 2026-09-29 test: created, opened early, closed, pushed back, then deleted."""
        events = self.scrape(m("1", "not_yet"))
        self.assertEqual(self.kinds(events), [("new", "1")])
        self.assertEqual(events[0].level, "starred")
        self.assertTrue(events[0].alert)

        self.assertEqual(self.kinds(self.scrape(m("1", "open"))), [("opened", "1")])
        closed = self.scrape(m("1", "closed"))
        self.assertEqual(self.kinds(closed), [("closed", "1")])
        self.assertEqual(closed[0].old["reg_state"], "open")
        self.assertEqual(self.kinds(self.scrape(m("1", "not_yet"))), [])  # closed -> not_yet is quiet
        self.assertEqual(self.kinds(self.scrape(m("1", "open"))), [("reopened", "1")])

        # Deleted: missing once is tolerated, twice is reported
        self.assertEqual(self.kinds(self.scrape(m("2", "not_yet"))), [("new", "2")])
        self.assertEqual(self.kinds(self.scrape(m("2", "not_yet"))), [("removed", "1")])
        self.assertEqual(get_match(self.db, "1")["cancelled"], 1)

    def test_open_to_not_yet_counts_as_closed(self):
        self.scrape(m("1", "open"))
        self.assertEqual(self.kinds(self.scrape(m("1", "not_yet"))), [("closed", "1")])

    def test_relisted_after_removal(self):
        self.scrape(m("1", "not_yet"), m("2", "not_yet"))
        self.scrape(m("2", "not_yet"))
        self.scrape(m("2", "not_yet"))
        self.assertEqual(self.kinds(self.scrape(m("1", "not_yet"), m("2", "not_yet"))), [("relisted", "1")])

    def test_brief_absence_resets(self):
        self.scrape(m("1", "not_yet"), m("2", "not_yet"))
        self.scrape(m("2", "not_yet"))                   # 1 missing once
        self.scrape(m("1", "not_yet"), m("2", "not_yet"))  # back: counter resets
        self.assertEqual(self.kinds(self.scrape(m("2", "not_yet"))), [])

    def test_empty_listing_with_known_matches_is_suspicious(self):
        self.scrape(m("1", "not_yet"), m("2", "not_yet"))
        with self.assertRaises(SuspiciousScrape):
            self.scrape()

    def test_past_matches_are_not_reported_removed(self):
        self.scrape(m("1", "not_yet", date_="September 1, 2026"), m("2", "not_yet"))
        self.scrape(m("2", "not_yet"))
        self.assertEqual(self.kinds(self.scrape(m("2", "not_yet"))), [])

    def test_date_change(self):
        self.scrape(m("1", "not_yet"))
        events = self.scrape(m("1", "not_yet", date_="October 31, 2026"))
        self.assertEqual(self.kinds(events), [("date_changed", "1")])
        self.assertEqual(events[0].old["date"], "October 24, 2026")

    def test_levels_filter_alerts(self):
        self.scrape(m("1", "not_yet"))
        update_match(self.db, "1", touch=False, level="normal")
        events = self.scrape(m("1", "open"))
        self.assertTrue(events[0].alert)          # normal: open is sent
        closed = self.scrape(m("1", "closed"))
        self.assertFalse(closed[0].alert)         # normal: closed is not
        update_match(self.db, "1", touch=False, level="muted")
        self.assertFalse(self.scrape(m("1", "open"))[0].alert)

    def test_unknown_label_always_alerts(self):
        self.scrape(m("1", "open"))
        update_match(self.db, "1", touch=False, level="muted")
        events = self.scrape(m("1", "unknown", label="full"))
        self.assertEqual(self.kinds(events), [("unknown_label", "1")])
        self.assertTrue(events[0].alert)
        self.assertEqual(self.kinds(self.scrape(m("1", "unknown", label="full"))), [])  # not repeated

    def test_rules_and_tier_defaults(self):
        set_rule(self.db, CLUB, "steel", "normal")
        set_rule(self.db, CLUB, "steel challenge: blank", "muted")
        events = self.scrape(m("1", "not_yet", mtype="Steel Challenge: Blank level I"),
                             m("2", "not_yet", mtype="Action Steel level I"),
                             m("3", "not_yet", mtype="USPSA level I"))
        self.assertEqual([e.level for e in events], ["muted", "normal", "starred"])
        self.assertEqual(default_level("manual", m("4", "not_yet"), []), "muted")
        self.assertEqual(default_level("standard", m("4", "not_yet"), []), "normal")

    def test_new_match_already_open(self):
        events = self.scrape(m("1", "open"))
        self.assertEqual(self.kinds(events), [("new", "1")])
        self.assertEqual(get_match(self.db, "1")["registration_notified"], 1)
        self.assertEqual(self.kinds(self.scrape(m("1", "open"))), [])

    def test_hour_countdown_schedules_checks(self):
        self.scrape(m("1", "not_yet", label="opens in 5 hours"))
        runs = sorted(c["run_at"] for c in due_scheduled_checks(self.db, NOW + timedelta(days=1)))
        self.assertEqual(runs, [(NOW + timedelta(hours=5, minutes=30)).isoformat(),
                                (NOW + timedelta(hours=6, minutes=2)).isoformat()])
        self.scrape(m("1", "not_yet", label="opens in 5 hours"))  # same check again: no duplicates
        self.assertEqual(len(due_scheduled_checks(self.db, NOW + timedelta(days=1))), 2)

    def test_week_countdown_and_muted_schedule_nothing(self):
        self.scrape(m("1", "not_yet", label="opens in 1 week"))
        self.scrape(m("2", "not_yet", label="opens in 2 hours"))
        update_match(self.db, "2", touch=False, level="muted")
        before = len(due_scheduled_checks(self.db, NOW + timedelta(days=30)))
        self.scrape(m("1", "not_yet", label="opens in 1 week"), m("2", "not_yet", label="opens in 1 hours"))
        self.assertEqual(len(due_scheduled_checks(self.db, NOW + timedelta(days=30))), before)


if __name__ == "__main__":
    unittest.main()
