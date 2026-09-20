"""Directory adapter for FairRoute.

The public FCI query always uses a fixed Gainesville-area point. A resident's
temporary origin is never sent to the directory. The deterministic access
engine therefore remains independent from both the UI and directory source.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import pandas as pd


FCI_SEARCH_URL = "https://www.floridaresourcemap.org/api/resource/search"
GAINESVILLE_CENTER = (29.6516, -82.3248)

TAG_CATEGORY = {
    "shelter": "Shelter & housing",
    "health": "Health care",
    "mental health": "Mental health",
    "substance abuse": "Mental health",
    "legal": "Legal & benefits",
    "financial help": "Legal & benefits",
    "food": "Food assistance",
    "basic needs": "Everyday essentials",
    "jobs": "Employment",
    "transportation": "Transportation",
    "education": "Family & learning",
    "family support": "Family & learning",
    "lgbtq+": "Community support",
}


def _categories(tags: list[str]) -> list[str]:
    categories = []
    for tag in tags:
        category = TAG_CATEGORY.get(str(tag).strip().lower())
        if category and category not in categories:
            categories.append(category)
    return categories or ["Other community support"]


def _hours_text(hours: object, hours_string: str = "") -> str:
    if hours_string:
        return hours_string
    if not isinstance(hours, dict):
        return "Confirm current hours before traveling."
    open_days = []
    for day, windows in hours.items():
        if not windows or windows == [["00:00", "00:00"]]:
            continue
        open_days.append(day[:3].title())
    return f"Hours listed for {', '.join(open_days)}; confirm before traveling." if open_days else "Confirm current hours before traveling."


def normalize_fci_resource(record: dict) -> dict | None:
    coordinates = record.get("coords", {}).get("coordinates", [])
    if len(coordinates) != 2:
        return None
    try:
        longitude, latitude = float(coordinates[0]), float(coordinates[1])
    except (TypeError, ValueError):
        return None
    address = record.get("address") or {}
    street = str(address.get("street") or "").strip()
    locality = ", ".join(
        value
        for value in [str(address.get("city") or "").strip(), str(address.get("state") or "").strip(), str(address.get("zipCode") or "").strip()]
        if value
    )
    address_text = ", ".join(value for value in [street, locality] if value) or "Location supplied by the directory"
    categories = _categories(record.get("tags") or [])
    phone = record.get("phone") or {}
    phone_text = "".join(value for value in [str(phone.get("countryCode") or ""), str(phone.get("number") or "")] if value)
    updated = str(record.get("lastValidated") or record.get("timeLastUpdate") or "")[:10]
    return {
        "resource_id": f"fci-{record.get('resourceId') or record.get('_id')}",
        "name": str(record.get("name") or "Unnamed resource").strip(),
        "category": categories[0],
        "categories": "|".join(categories),
        "latitude": latitude,
        "longitude": longitude,
        "address": address_text,
        "step_free": "unknown",
        "accessible_restroom": "unknown",
        "accessibility_notes": "The directory does not currently provide structured physical-access fields. Confirm the features you need.",
        "hours": _hours_text(record.get("hours"), str(record.get("hours_string") or "")),
        "phone": phone_text,
        "website": str(record.get("website") or ""),
        "description": str(record.get("description") or "Community resource listed by Florida Community Innovation."),
        "source_checked": updated,
        "source": "Florida Community Resource Map",
        "source_id": str(record.get("resourceId") or record.get("_id") or ""),
        "location_precision": "street" if street else "city-level / verify location",
        "service_format": "online" if record.get("online") and not street else "physical or hybrid",
    }


def fetch_fci_resources(timeout: float = 8.0) -> tuple[pd.DataFrame, dict]:
    """Fetch the public Gainesville-area catalog without transmitting a user origin."""
    latitude, longitude = GAINESVILLE_CENTER
    query = urllib.parse.urlencode(
        {
            "page": 0,
            "limit": 100,
            "longitude": longitude,
            "latitude": latitude,
            "distance": 25,
            "language": "en",
        }
    )
    request = urllib.request.Request(
        f"{FCI_SEARCH_URL}?{query}",
        headers={"FCI_app": "frm", "User-Agent": "FairRoute civic-tech prototype"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response).get("payload", {})
    normalized_rows = [normalized for record in payload.get("results", []) if (normalized := normalize_fci_resource(record))]
    # City-only coordinates in the upstream directory commonly collapse to a
    # downtown centroid. Treating that point as a literal entrance would create
    # a dangerously confident one-minute trip, so those records remain counted
    # in coverage but are withheld from routing until their location is precise.
    rows = [row for row in normalized_rows if row["location_precision"] == "street"]
    frame = pd.DataFrame(rows)
    return frame, {
        "source": "Florida Community Resource Map public search",
        "reported_total": int(payload.get("totalCount", len(rows))),
        "loaded": len(rows),
        "unroutable_location_count": len(normalized_rows) - len(rows),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "query_scope": "Fixed 25-mile search around central Gainesville",
    }


def combine_with_curated(fci: pd.DataFrame, curated: pd.DataFrame) -> pd.DataFrame:
    curated = curated.copy()
    if "categories" not in curated:
        curated["categories"] = curated["category"]
    curated["source"] = curated.get("source", "FairRoute demonstration data")
    curated["source_id"] = curated.get("source_id", curated["resource_id"])
    curated["location_precision"] = curated.get("location_precision", "street")
    curated["service_format"] = curated.get("service_format", "physical or hybrid")
    if fci.empty:
        return curated.fillna("")
    existing = {str(name).strip().casefold() for name in fci["name"]}
    supplements = curated[~curated["name"].str.strip().str.casefold().isin(existing)]
    return pd.concat([fci, supplements], ignore_index=True).fillna("")
