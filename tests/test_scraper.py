import unittest
from datetime import timedelta

from scraper import normalize_club_url, parse_club_page, parse_countdown, parse_label


def listing_item(match_id, label_class, label_text, date="October 24, 2026", mtype="USPSA level I",
                 title="Bot Test Match - Do Not Register"):
    # Shape captured anonymously from the Friendly Gun Club page on 2026-09-29
    return f"""
    <div class="clearfix" id="item_{match_id}">
      <div class="pull-right col-md-2">
        <span class="label {label_class} pull-right"> {label_text} </span>
      </div>
      <div class="col-xs-10">
        <strong><a href="https://practiscore.com/test-{match_id}/register">{title}</a></strong>
        <small><div> {date} · </div><div> {mtype} </div></small>
      </div>
    </div>"""


def club_page(*items, title="Friendly Gun Club | Firearms training for everyone | PractiScore"):
    return f"<html><head><title>{title}</title></head><body>{''.join(items)}</body></html>"


class ParseLabelTest(unittest.TestCase):
    def test_observed_states(self):
        self.assertEqual(parse_label(["label", "label-default", "pull-right"], "opens\n in\n 1 week"), "not_yet")
        self.assertEqual(parse_label(["label", "label-success", "pull-right"], "open"), "open")
        self.assertEqual(parse_label(["label", "label-default", "pull-right"], "closed"), "closed")

    def test_unseen_label_is_unknown(self):
        self.assertEqual(parse_label(["label", "label-warning"], "full"), "unknown")
        self.assertEqual(parse_label([], ""), "unknown")


class CountdownTest(unittest.TestCase):
    def test_rounded_down_bounds(self):
        self.assertEqual(parse_countdown("opens in 5 hours"), (timedelta(hours=5), timedelta(hours=6)))
        self.assertEqual(parse_countdown("opens in 1 week"), (timedelta(weeks=1), timedelta(weeks=2)))
        self.assertEqual(parse_countdown("opens in 30 minutes"), (timedelta(minutes=30), timedelta(minutes=31)))

    def test_not_a_countdown(self):
        self.assertIsNone(parse_countdown("closed"))
        self.assertIsNone(parse_countdown("open"))


class ParseClubPageTest(unittest.TestCase):
    def test_parses_all_fields(self):
        html = club_page(
            listing_item("358850", "label-default", "opens\n in\n 1 week"),
            listing_item("358851", "label-success", "open", date="November 1, 2026", mtype="Steel Challenge: Blank level I"),
            listing_item("358852", "label-default", "closed"),
        )
        result = parse_club_page(html, "https://practiscore.com/clubs/friendly_gun_club")
        self.assertEqual(result["name"], "Friendly Gun Club")
        first, second, third = result["matches"]
        self.assertEqual(first["match_id"], "358850")
        self.assertEqual(first["date"], "October 24, 2026")
        self.assertEqual(first["match_type"], "USPSA level I")
        self.assertEqual(first["reg_state"], "not_yet")
        self.assertEqual(first["label_text"], "opens in 1 week")
        self.assertEqual(second["reg_state"], "open")
        self.assertEqual(second["match_type"], "Steel Challenge: Blank level I")
        self.assertEqual(third["reg_state"], "closed")

    def test_empty_listing(self):
        self.assertEqual(parse_club_page(club_page(), "https://practiscore.com/clubs/x")["matches"], [])


class NormalizeUrlTest(unittest.TestCase):
    def test_accepts_club_pages(self):
        self.assertEqual(normalize_club_url("https://practiscore.com/clubs/tps-uspsa/"),
                         "https://practiscore.com/clubs/tps-uspsa")
        self.assertEqual(normalize_club_url(" http://www.practiscore.com/clubs/friendly_gun_club "),
                         "https://practiscore.com/clubs/friendly_gun_club")

    def test_rejects_other_urls(self):
        self.assertIsNone(normalize_club_url("https://practiscore.com/tps-uspsa-october/register"))
        self.assertIsNone(normalize_club_url("https://example.com/clubs/x"))


if __name__ == "__main__":
    unittest.main()
