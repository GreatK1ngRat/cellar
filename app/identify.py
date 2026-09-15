"""Wine identification: barcode lookup first, Gemini vision + search second.

Both tiers are free at the volume a personal wine log produces. Neither
tier is authoritative -- the result is always shown to the person to
confirm before it gets written to the database.
"""
import base64
import os
from datetime import datetime, timezone

import httpx

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"

WINE_TYPES = ["red", "white", "rose", "sparkling", "dessert", "fortified"]


async def lookup_barcode(barcode: str) -> dict | None:
    """Tier 1: Open Food Facts. Free, unlimited, no API key.

    Coverage is grocery-and-supermarket weighted, so this misses often for
    small producers, restaurant pours, and anything without a barcode at
    all -- that's expected, and the caller falls through to Gemini.
    """
    barcode = barcode.strip()
    if not barcode:
        return None

    url = f"https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
    except httpx.HTTPError:
        return None

    if resp.status_code != 200:
        return None
    payload = resp.json()
    if payload.get("status") != 1:
        return None

    product = payload.get("product", {})
    name = product.get("product_name") or product.get("generic_name")
    if not name:
        return None

    return {
        "name": name,
        "producer": product.get("brands"),
        "image_url": product.get("image_url"),
        "image_source": "openfoodfacts.org",
        "image_checked_at": datetime.now(timezone.utc).isoformat(),
        "matched_via": "barcode",
    }


IDENTIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "legible": {"type": "boolean"},
        "name": {"type": ["string", "null"]},
        "producer": {"type": ["string", "null"]},
        "vintage": {"type": ["string", "null"]},
        "wine_type": {"type": ["string", "null"], "enum": WINE_TYPES + [None]},
        "read_directly": {
            "type": "object",
            "properties": {
                "name": {"type": "boolean"},
                "producer": {"type": "boolean"},
                "vintage": {"type": "boolean"},
            },
        },
        "listing_found": {"type": "boolean"},
        "listing_confidence": {"type": "number"},
        "listing_url": {"type": ["string", "null"]},
        "image_url": {"type": ["string", "null"]},
        "image_source": {"type": ["string", "null"]},
    },
    "required": ["legible", "listing_found", "listing_confidence"],
}

IDENTIFY_PROMPT = """You are reading a photo of a wine label to help catalogue it.

Step 1 -- read only what is printed on the label. Do not infer or guess a
field from general knowledge; if it is not legible, leave it null and set
the matching read_directly flag to false.

Step 2 -- if the label was legible, use web search to find a real product
listing for this exact wine and vintage (a retailer or a site like
Wine-Searcher). Only report listing_found as true if you are genuinely
confident it is the same wine, not just the same producer or a similar
label. Set listing_confidence from 0 to 1. If you find a listing, include
its page URL and, if visible in the search result, a direct product image
URL and the domain it came from.

Respond only with JSON matching the provided schema."""


async def identify_photo(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """Tier 2: Gemini reads the label and searches for a listing.

    One call does both jobs -- vision extraction and grounded web search --
    which keeps this to a single free-tier request per bottle instead of
    two separate paid integrations.
    """
    if not GEMINI_API_KEY:
        return {"legible": False, "listing_found": False, "listing_confidence": 0,
                "error": "GEMINI_API_KEY is not configured"}

    body = {
        "model": GEMINI_MODEL,
        "input": [
            {"type": "text", "text": IDENTIFY_PROMPT},
            {
                "type": "image",
                "data": base64.b64encode(image_bytes).decode("utf-8"),
                "mime_type": mime_type,
            },
        ],
        "tools": [{"type": "google_search"}],
        "response_format": {
            "type": "text",
            "mime_type": "application/json",
            "schema": IDENTIFY_SCHEMA,
        },
    }
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(GEMINI_URL, json=body, headers=headers)
    except httpx.HTTPError:
        return {"legible": False, "listing_found": False, "listing_confidence": 0,
                "error": "Could not reach Gemini"}

    if resp.status_code != 200:
        return {"legible": False, "listing_found": False, "listing_confidence": 0,
                "error": f"Gemini request failed ({resp.status_code})"}

    payload = resp.json()
    output_text = payload.get("output_text", "")
    import json
    try:
        result = json.loads(output_text)
    except (ValueError, TypeError):
        return {"legible": False, "listing_found": False, "listing_confidence": 0,
                "error": "Could not parse Gemini's response"}

    if result.get("image_url"):
        result["image_checked_at"] = None  # verified separately, see verify_image_url
    return result


TEXT_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "listing_found": {"type": "boolean"},
        "listing_confidence": {"type": "number"},
        "image_url": {"type": ["string", "null"]},
        "image_source": {"type": ["string", "null"]},
    },
    "required": ["listing_found", "listing_confidence"],
}


async def identify_text(name: str, producer: str | None, vintage: str | None) -> dict:
    """Re-searches for a listing image from known fields, no photo involved.

    Used by "find a new image" on a wine that already exists -- the identity
    is already trusted, this just tries the search step again in case a
    better or working listing exists now.
    """
    if not GEMINI_API_KEY:
        return {"listing_found": False, "listing_confidence": 0}

    query_bits = " ".join(b for b in [producer, name, vintage] if b)
    prompt = (f'Find a real product listing for the wine "{query_bits}" using web search. '
              "Only report listing_found as true if you are confident it is the same wine. "
              "If found, include a direct product image URL and the domain it came from. "
              "Respond only with JSON matching the provided schema.")

    body = {
        "model": GEMINI_MODEL,
        "input": [{"type": "text", "text": prompt}],
        "tools": [{"type": "google_search"}],
        "response_format": {
            "type": "text",
            "mime_type": "application/json",
            "schema": TEXT_SEARCH_SCHEMA,
        },
    }
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(GEMINI_URL, json=body, headers=headers)
    except httpx.HTTPError:
        return {"listing_found": False, "listing_confidence": 0}
    if resp.status_code != 200:
        return {"listing_found": False, "listing_confidence": 0}

    import json
    try:
        result = json.loads(resp.json().get("output_text", ""))
    except (ValueError, TypeError):
        return {"listing_found": False, "listing_confidence": 0}

    if result.get("image_url") and not await verify_image_url(result["image_url"]):
        result["image_url"] = None
        result["image_source"] = None
    return result


async def verify_image_url(url: str) -> bool:
    """Confirms a candidate image URL actually returns an image before saving it.

    This is what stops a dead or non-image link from ever reaching the
    database -- run it right before save, and again periodically afterward
    to catch links that rot later.
    """
    if not url:
        return False
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            resp = await client.head(url)
            if resp.status_code >= 400 or "image" not in resp.headers.get("content-type", ""):
                resp = await client.get(url)  # some servers don't support HEAD
                if resp.status_code >= 400 or "image" not in resp.headers.get("content-type", ""):
                    return False
        return True
    except httpx.HTTPError:
        return False
