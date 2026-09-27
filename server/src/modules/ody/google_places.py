import os
import time
from concurrent.futures import ThreadPoolExecutor
import requests
from dotenv import load_dotenv

from .odify import find_business_email

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
PLACES_API = "https://maps.googleapis.com/maps/api/place"


def search_without_website(niche: str, location: str, max_results: int = 30) -> list[dict]:
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_PLACES_API_KEY not set in .env")

    query = f"{niche} in {location}"
    all_places: list[dict] = []
    next_token: str | None = None

    # Collect place_ids from textSearch (up to 3 pages = ~60 results)
    for _ in range(3):
        params: dict = {"query": query, "key": GOOGLE_API_KEY}
        if next_token:
            params["pagetoken"] = next_token
            time.sleep(1.5)

        resp = requests.get(f"{PLACES_API}/textsearch/json", params=params)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") not in ("OK", "ZERO_RESULTS"):
            raise RuntimeError(
                f"Places API error: {data.get('status')} — {data.get('error_message', '')}"
            )

        all_places.extend(data.get("results", []))
        next_token = data.get("next_page_token")

        if not next_token or len(all_places) >= max_results * 2:
            break

    # For each place, check if it has a website
    results: list[dict] = []
    for place in all_places:
        if len(results) >= max_results:
            break

        place_id = place.get("place_id")
        if not place_id:
            continue

        try:
            detail_resp = requests.get(
                f"{PLACES_API}/details/json",
                params={
                    "place_id": place_id,
                    "fields": "name,formatted_phone_number,formatted_address,website",
                    "key": GOOGLE_API_KEY,
                },
            )
            detail_resp.raise_for_status()
            detail = detail_resp.json().get("result", {})
        except Exception:
            continue

        if detail.get("website"):
            continue

        results.append({
            "name": detail.get("name", place.get("name", "")),
            "phone": detail.get("formatted_phone_number", ""),
            "address": detail.get("formatted_address", place.get("formatted_address", "")),
            "email": "",
            "website": "",
        })

    # Best-effort email enrichment (businesses here have no website to scrape).
    # Threaded: each lead = 1 DDG query + up to 2 page scrapes.
    def _enrich(lead: dict) -> None:
        try:
            lead["email"] = find_business_email(lead.get("name", ""), location)
        except Exception:
            lead["email"] = ""

    if results:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(_enrich, results))

    return results
