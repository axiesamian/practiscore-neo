import base64
import re
from datetime import timedelta

import requests
from bs4 import BeautifulSoup
from config import SCRAPER_API_KEY, ZYTE_API_KEY

SCRAPERAPI_ENDPOINT = "http://api.scraperapi.com"
ZYTE_ENDPOINT = "https://api.zyte.com/v1/extract"

CLUB_URL_RE = re.compile(r"^https?://(?:www\.)?practiscore\.com/clubs/([A-Za-z0-9_\-]+)/?$")

# "opens in 5 hours", "opens in 1 week" — PractiScore rounds down to the largest whole unit
COUNTDOWN_RE = re.compile(r"opens\s+in\s+(\d+)\s+(second|minute|hour|day|week|month|year)s?", re.I)
COUNTDOWN_UNITS = {
    "second": timedelta(seconds=1),
    "minute": timedelta(minutes=1),
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
    "year": timedelta(days=365),
}


def normalize_club_url(url: str) -> str | None:
    """Canonical club URL, or None if it isn't a PractiScore club page."""
    m = CLUB_URL_RE.match(url.strip())
    return f"https://practiscore.com/clubs/{m.group(1)}" if m else None


def _fetch(url):
    if ZYTE_API_KEY:
        response = requests.post(
            ZYTE_ENDPOINT,
            auth=(ZYTE_API_KEY, ""),
            json={"url": url, "httpResponseBody": True},
            timeout=60,
        )
        if response.status_code >= 400:
            raise requests.HTTPError(
                f"Zyte API {response.status_code}: {response.text[:300]}"
            )
        data = response.json()
        html = base64.b64decode(data["httpResponseBody"]).decode("utf-8", errors="replace")
        status = data.get("httpResponseStatusCode", 200)
        return html, status
    elif SCRAPER_API_KEY:
        response = requests.get(
            SCRAPERAPI_ENDPOINT,
            params={"api_key": SCRAPER_API_KEY, "url": url},
            timeout=60,
        )
        return response.text, response.status_code
    else:
        response = requests.get(url, timeout=60)
        return response.text, response.status_code


def _extract_club_name(soup, url):
    title_tag = soup.find("title")
    if title_tag:
        text = title_tag.get_text(strip=True)
        if "|" in text:
            return text.split("|")[0].strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return url.rstrip("/").split("/")[-1]


def parse_label(classes: list[str], text: str) -> str:
    """Registration state from a listing label.

    Verified on 2026-09-29: open is `label-success "open"`; not-yet-open and closed
    share `label-default`, told apart only by the text ("opens in …" vs "closed").
    """
    text = " ".join(text.split()).lower()
    if "label-success" in classes:
        return "open"
    if text.startswith("opens in"):
        return "not_yet"
    if text == "closed":
        return "closed"
    return "unknown"


def parse_countdown(text: str):
    """(lower, upper) bound on time until registration opens, or None.

    The label rounds down, so "opens in 5 hours" means somewhere in [5h, 6h).
    """
    m = COUNTDOWN_RE.search(text)
    if not m:
        return None
    unit = COUNTDOWN_UNITS[m.group(2).lower()]
    n = int(m.group(1))
    return n * unit, (n + 1) * unit


def parse_club_page(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    club_name = _extract_club_name(soup, url)
    matches = []
    for item in soup.select("div.clearfix[id^='item_']"):
        match_id = item["id"].replace("item_", "")

        link = item.select_one("div.col-xs-10 strong a")
        if not link:
            continue

        title = link.get_text(strip=True)
        match_url = link.get("href", "")

        small = item.select_one("div.col-xs-10 small")
        divs = small.select("div") if small else []

        date_raw = divs[0].get_text(" ", strip=True) if divs else ""
        date = date_raw.split("·")[0].strip()

        match_type = " ".join(divs[1].get_text(strip=True).split()) if len(divs) > 1 else ""

        status_span = item.select_one("div.pull-right span.label") or item.select_one("span.label")
        label_text = " ".join(status_span.get_text().split()) if status_span else ""
        reg_state = parse_label(status_span.get("class", []) if status_span else [], label_text)

        matches.append({
            "match_id": match_id,
            "title": title,
            "url": match_url,
            "date": date,
            "match_type": match_type,
            "reg_state": reg_state,
            "label_text": label_text,
        })

    return {"name": club_name, "matches": matches}


def scrape_club(url):
    html, status = _fetch(url)
    if status >= 400:
        raise requests.HTTPError(f"HTTP {status} for {url}")
    return parse_club_page(html, url)
