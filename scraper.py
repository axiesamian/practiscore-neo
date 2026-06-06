import requests
from bs4 import BeautifulSoup
from config import SCRAPER_API_KEY

SCRAPERAPI_ENDPOINT = "http://api.scraperapi.com"


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


def scrape_club(url):
    response = requests.get(
        SCRAPERAPI_ENDPOINT,
        params={"api_key": SCRAPER_API_KEY, "url": url},
        timeout=60,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

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

        status_span = item.select_one("span.label")
        registration_open = bool(
            status_span and "label-success" in status_span.get("class", [])
        )

        matches.append({
            "match_id": match_id,
            "title": title,
            "url": match_url,
            "date": date,
            "match_type": match_type,
            "registration_open": registration_open,
        })

    return {"name": club_name, "matches": matches}


def check_match_cancelled(match_url):
    """Returns True if the match page is gone (404), False if it still loads."""
    base_url = match_url.rstrip("/").rsplit("/", 1)[0]
    try:
        response = requests.get(
            SCRAPERAPI_ENDPOINT,
            params={"api_key": SCRAPER_API_KEY, "url": base_url},
            timeout=60,
        )
        return response.status_code == 404
    except Exception:
        return False
