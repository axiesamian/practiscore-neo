"""Zyte API spend from the Zyte Stats API (https://docs.zyte.com/zyte-api/usage/stats.html)."""
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from config import ZYTE_DASHBOARD_KEY, ZYTE_ORG_ID, ZYTE_BILLING_DAY

STATS_ENDPOINT = "https://zyte-api-stats.zyte.com/api/stats"


@dataclass
class Usage:
    period_start: datetime
    period_end: datetime
    requests: int = 0
    cost_usd: float = 0.0
    status_codes: dict = field(default_factory=dict)  # code (None = Zyte-side error) -> count
    days: list = field(default_factory=list)          # (day as datetime, requests, cost_usd), oldest first

    @property
    def failed(self) -> int:
        """Requests with no status or a non-2xx one."""
        return sum(n for code, n in self.status_codes.items() if code is None or not 200 <= code < 300)


def configured() -> bool:
    return bool(ZYTE_DASHBOARD_KEY and ZYTE_ORG_ID)


def billing_period(now: datetime, billing_day: int = ZYTE_BILLING_DAY) -> tuple[datetime, datetime]:
    """Start and end of the billing month containing `now`, rolling over at midnight UTC on `billing_day`."""
    now = now.astimezone(timezone.utc)
    start = now.replace(day=billing_day, hour=0, minute=0, second=0, microsecond=0)
    if now < start:
        start = _add_months(start, -1)
    return start, _add_months(start, 1)


def _add_months(dt: datetime, months: int) -> datetime:
    month = dt.month - 1 + months
    return dt.replace(year=dt.year + month // 12, month=month % 12 + 1)


def parse_stats(data: dict, period_start: datetime, period_end: datetime) -> Usage:
    """Sum a Stats API response grouped by day."""
    usage = Usage(period_start, period_end)
    for row in data.get("results", []):
        requests_ = int(row["request_count"])
        cost = float(row["cost_microusd_total"]) / 1_000_000
        usage.requests += requests_
        usage.cost_usd += cost
        for sc in row.get("status_codes") or []:
            usage.status_codes[sc["code"]] = usage.status_codes.get(sc["code"], 0) + sc["count"]
        if row.get("day"):
            day = datetime.fromisoformat(row["day"].replace("Z", "+00:00"))
            usage.days.append((day, requests_, cost))
    usage.days.sort()
    return usage


def projected_cost(usage: Usage, now: datetime) -> float | None:
    """Straight-line projection to the end of the period; None in the first day, when it means little."""
    elapsed = (now - usage.period_start).total_seconds()
    if elapsed < 86400:
        return None
    return usage.cost_usd * (usage.period_end - usage.period_start).total_seconds() / elapsed


def fetch_usage(now: datetime) -> Usage:
    """Spend so far this billing period. Blocking; raises on HTTP errors."""
    start, end = billing_period(now)
    response = requests.get(
        STATS_ENDPOINT,
        auth=(ZYTE_DASHBOARD_KEY, ""),
        params={
            "organization_id": ZYTE_ORG_ID,
            "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_time": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "groupby_time": "day",
        },
        timeout=30,
    )
    if response.status_code >= 400:
        raise requests.HTTPError(f"Zyte Stats API {response.status_code}: {response.text[:300]}")
    return parse_stats(response.json(), start, end)
