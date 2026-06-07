import base64
import requests
from bs4 import BeautifulSoup
from config import SCRAPER_API_KEY, ZYTE_API_KEY

SCRAPERAPI_ENDPOINT = "http://api.scraperapi.com"
ZYTE_ENDPOINT = "https://api.zyte.com/v1/extract"


def _fetch(url):
    if ZYTE_API_KEY:
        response = requests.post(
            ZYTE_ENDPOINT,
            auth=(ZYTE_API_KEY, ""),
            json={"url": url, "httpResponseBody": True},
            timeout=60,
        )
        response.raise_for_status()
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


def scrape_club(url):
    html, status = _fetch(url)
    if status >= 400:
        raise requests.HTTPError(f"HTTP {status} for {url}")
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
    base_url = match_url.rstrip("/").rsplit("/", 1)[0]
    try:
        _, status = _fetch(base_url)
        return status == 404
    except Exception:
        return False
