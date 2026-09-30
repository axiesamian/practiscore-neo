import unittest
from datetime import datetime, timezone

from zyte_usage import billing_period, parse_stats, projected_cost


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


class BillingPeriodTest(unittest.TestCase):
    def test_after_rollover_day(self):
        self.assertEqual(billing_period(utc(2026, 9, 29, 15), 7), (utc(2026, 9, 7), utc(2026, 10, 7)))

    def test_before_rollover_day(self):
        self.assertEqual(billing_period(utc(2026, 10, 3), 7), (utc(2026, 9, 7), utc(2026, 10, 7)))

    def test_on_rollover_midnight(self):
        self.assertEqual(billing_period(utc(2026, 10, 7), 7), (utc(2026, 10, 7), utc(2026, 11, 7)))

    def test_year_boundary(self):
        self.assertEqual(billing_period(utc(2027, 1, 2), 7), (utc(2026, 12, 7), utc(2027, 1, 7)))
        self.assertEqual(billing_period(utc(2026, 12, 20), 7), (utc(2026, 12, 7), utc(2027, 1, 7)))


class ParseStatsTest(unittest.TestCase):
    # Shape from https://docs.zyte.com/zyte-api/usage/stats.html with groupby_time=day
    RESPONSE = {
        "page": 1, "page_size": 500, "total_result_count": 2,
        "results": [
            {"day": "2026-09-08T00:00:00Z", "request_count": 10, "cost_microusd_total": "20000.00",
             "status_codes": [{"code": 200, "count": 9}, {"code": None, "count": 1}]},
            {"day": "2026-09-07T00:00:00Z", "request_count": 5, "cost_microusd_total": "10000.00",
             "status_codes": [{"code": 200, "count": 4}, {"code": 520, "count": 1}]},
        ],
    }

    def test_totals_and_days(self):
        usage = parse_stats(self.RESPONSE, utc(2026, 9, 7), utc(2026, 10, 7))
        self.assertEqual(usage.requests, 15)
        self.assertAlmostEqual(usage.cost_usd, 0.03)
        self.assertEqual(usage.status_codes, {200: 13, None: 1, 520: 1})
        self.assertEqual(usage.failed, 2)
        self.assertEqual([d[0] for d in usage.days], [utc(2026, 9, 7), utc(2026, 9, 8)])

    def test_empty(self):
        usage = parse_stats({"results": []}, utc(2026, 9, 7), utc(2026, 10, 7))
        self.assertEqual((usage.requests, usage.cost_usd, usage.failed), (0, 0.0, 0))


class ProjectionTest(unittest.TestCase):
    def test_linear(self):
        usage = parse_stats({"results": [{"request_count": 1, "cost_microusd_total": "3000000"}]},
                            utc(2026, 9, 7), utc(2026, 10, 7))
        self.assertAlmostEqual(projected_cost(usage, utc(2026, 9, 10)), 30.0)

    def test_none_in_first_day(self):
        usage = parse_stats({"results": []}, utc(2026, 9, 7), utc(2026, 10, 7))
        self.assertIsNone(projected_cost(usage, utc(2026, 9, 7, 12)))


if __name__ == "__main__":
    unittest.main()
