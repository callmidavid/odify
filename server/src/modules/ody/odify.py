import re
import time

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
}

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_REGEX = re.compile(
    r"(?:(?:\+?1)?[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
)


def extract_emails(text):
    return list(set(EMAIL_REGEX.findall(text)))


def extract_phones(text):
    raw = PHONE_REGEX.findall(text)
    cleaned = []
    for p in raw:
        digits = re.sub(r"\D", "", p)
        if len(digits) >= 10:
            cleaned.append(p.strip())
    return list(set(cleaned))


def scrape_page(url, timeout=15):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text(separator=" ", strip=True)
        emails = extract_emails(text)
        phones = extract_phones(text)
        return emails, phones
    except Exception:
        return [], []


def search_duckduckgo(query, max_results=10):
    urls = []
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                urls.append(r["href"])
    except Exception:
        pass
    return urls


def search_duckduckgo_fallback(query, max_results=10):
    urls = []
    try:
        params = {"q": query}
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params=params,
            headers=HEADERS,
            timeout=10,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.select("a.result__a"):
            href = a.get("href", "")
            if href and href.startswith("http"):
                urls.append(href)
                if len(urls) >= max_results:
                    break
    except Exception:
        pass
    return urls


def search_and_scrape(query, max_results=10):
    urls = search_duckduckgo(query, max_results)
    if not urls:
        urls = search_duckduckgo_fallback(query, max_results)

    results = []
    for url in urls:
        emails, phones = scrape_page(url)
        results.append({
            "url": url,
            "emails": emails,
            "phones": phones,
        })
        time.sleep(1)

    return results


JUNK_EMAIL_HINTS = ("noreply", "no-reply", "example.", ".invalid", "test@", "sentry", "lorem")


def pick_best_email(emails: list[str]) -> str:
    """First plausible address, skipping obvious junk/crawler artifacts."""
    for e in emails:
        low = e.lower()
        if len(low) > 80:
            continue
        if any(h in low for h in JUNK_EMAIL_HINTS):
            continue
        if low.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")):
            continue
        return e
    return ""


def find_business_email(name: str, location: str, max_pages: int = 2) -> str:
    """Best-effort email for a business with no website: DDG the name, scrape top hits."""
    if not name:
        return ""
    query = f'"{name}" {location} email contact'
    urls = search_duckduckgo(query, max_results=max_pages)
    if not urls:
        urls = search_duckduckgo_fallback(query, max_results=max_pages)
    for url in urls:
        try:
            emails, _ = scrape_page(url, timeout=8)
        except Exception:
            continue
        best = pick_best_email(emails)
        if best:
            return best
    return ""
