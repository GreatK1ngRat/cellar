"""Wine identification: barcode lookup first, a free vision model second.

Both tiers are free at the volume a personal wine log produces. Neither
tier is authoritative -- the result is always shown to the person to
confirm before it gets written to the database.
"""
import base64
import json
import logging
import os
from datetime import datetime, timezone

import httpx

logger = logging.getLogger("cellar.identify")

# Open Food Facts asks every client to send a descriptive User-Agent and
# blocks requests that look like generic bot traffic -- httpx's default
# ("python-httpx/x.x") is exactly that pattern and gets a 403.
OFF_USER_AGENT = "Cellar/1.0 (self-hosted personal wine log; no contact URL)"

WINE_TYPES = ["red", "white", "rose", "sparkling", "dessert", "fortified"]


async def lookup_barcode(barcode: str) -> dict | None:
    """Tier 1: Open Food Facts. Free, unlimited, no API key.

    Coverage is grocery-and-supermarket weighted, so this misses often for
    small producers, restaurant pours, and anything without a barcode at
    all -- that's expected, and the caller falls through to the photo tier.
    """
    barcode = barcode.strip()
    if not barcode:
        return None

    url = f"https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers={"User-Agent": OFF_USER_AGENT})
    except httpx.HTTPError as e:
        logger.warning("barcode lookup: could not reach Open Food Facts for %s: %s", barcode, e)
        return None

    if resp.status_code != 200:
        logger.info("barcode lookup: Open Food Facts returned %s for %s", resp.status_code, barcode)
        return None
    payload = resp.json()
    if payload.get("status") != 1:
        logger.info("barcode lookup: %s not found in Open Food Facts", barcode)
        return None

    product = payload.get("product", {})
    name = product.get("product_name") or product.get("generic_name")
    if not name:
        logger.info("barcode lookup: %s found but has no usable name field", barcode)
        return None

    logger.info("barcode lookup: %s matched to %r", barcode, name)
    return {
        "name": name,
        "producer": product.get("brands"),
        "image_url": product.get("image_url"),
        "image_source": "openfoodfacts.org",
        "image_checked_at": datetime.now(timezone.utc).isoformat(),
        "matched_via": "barcode",
    }


OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "inclusionai/ling-3.0-flash-vl:free")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Confidence (self-reported by the model) above which a match is shown as
# "the" match rather than routed to a plain no-match screen. No published
# guidance on a good cutoff for this -- starting assumption to tune once
# real results come in.
MATCH_CONFIDENCE_THRESHOLD = 0.6


# This free model does not support forced JSON output (no response_format
# support) -- the prompt has to ask for plain JSON and the parser has to
# tolerate stray text or markdown fences around it rather than assume a
# clean object back.
OPENROUTER_PROMPT = """Read this photo of a wine label.

Respond with ONLY a single JSON object, no markdown code fences, no
explanation before or after it. Use this exact shape:

{"legible": true or false,
 "candidates": [
   {"name": string, "producer": string or null, "vintage": string or null,
    "confidence": a number from 0 to 1}
 ]}

List up to 3 candidates, ordered from most to least confident, for what
this wine might be. Usually there is only one real answer and the rest
would be near-duplicates or guesses at ambiguous text -- only include more
than one if the label genuinely supports more than one reading. Only fill
in producer or vintage if it is actually printed on the label -- use null
rather than guessing. If the photo is too blurry, dark, or cropped to read
at all, set legible to false and candidates to an empty list."""


def _extract_json_object(text: str) -> dict | None:
    """Pulls a JSON object out of a model's plain-text reply.

    Handles the common ways an unconstrained model wraps its JSON: markdown
    code fences, or a sentence before/after the object. Returns None if
    nothing parseable is found rather than raising.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return None


async def identify_photo(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """Tier 2: a free vision-capable model via OpenRouter reads the label
    directly. No fixed label database, no web search -- it reads whatever
    text and imagery is actually in the photo and reports what it found.

    Asks for a ranked list of candidates rather than one guess, so a
    photo with a plausible-but-uncertain reading can still be offered as
    a pickable option instead of being discarded as "no match."

    Like every other tier here, this only identifies the wine -- no
    listing image or URL. See BACKLOG.md for that history.
    """
    if not OPENROUTER_API_KEY:
        logger.warning("identify_photo: called but OPENROUTER_API_KEY is not set")
        return {"legible": False, "listing_found": False, "listing_confidence": 0,
                "error": "OPENROUTER_API_KEY is not configured"}

    b64 = base64.b64encode(image_bytes).decode("utf-8")
    body = {
        "model": OPENROUTER_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": OPENROUTER_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
            ],
        }],
    }
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(OPENROUTER_URL, json=body, headers=headers)
    except httpx.HTTPError as e:
        logger.error("identify_photo: could not reach OpenRouter: %s", e)
        return {"legible": False, "listing_found": False, "listing_confidence": 0,
                "error": "Could not reach OpenRouter"}

    if resp.status_code != 200:
        logger.error("identify_photo: OpenRouter returned %s: %s", resp.status_code, resp.text[:500])
        return {"legible": False, "listing_found": False, "listing_confidence": 0,
                "error": f"OpenRouter request failed ({resp.status_code})"}

    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError):
        logger.error("identify_photo: unexpected OpenRouter response shape: %r", resp.text[:500])
        return {"legible": False, "listing_found": False, "listing_confidence": 0,
                "error": "Could not parse OpenRouter's response"}

    parsed = _extract_json_object(content)
    if parsed is None:
        logger.error("identify_photo: could not extract JSON from OpenRouter's reply: %r", content[:500])
        return {"legible": False, "listing_found": False, "listing_confidence": 0,
                "error": "Could not parse OpenRouter's response"}

    legible = bool(parsed.get("legible"))
    raw_candidates = parsed.get("candidates") or []
    # Filter to usable entries and sort by confidence, defensively -- don't
    # trust the model to order them correctly or to only include named ones.
    candidates = sorted(
        (c for c in raw_candidates if isinstance(c, dict) and c.get("name")),
        key=lambda c: c.get("confidence") or 0,
        reverse=True,
    )

    logger.info("identify_photo: OpenRouter (%s) legible=%s candidates=%d top=%r",
                OPENROUTER_MODEL, legible, len(candidates),
                candidates[0].get("name") if candidates else None)

    if not legible or not candidates:
        return {"legible": legible, "listing_found": False, "listing_confidence": 0, "candidates": []}

    top = candidates[0]
    top_confidence = top.get("confidence") or 0

    return {
        "legible": True,
        "listing_found": top_confidence >= MATCH_CONFIDENCE_THRESHOLD,
        "listing_confidence": top_confidence,
        "name": top.get("name"),
        "producer": top.get("producer"),
        "vintage": top.get("vintage"),
        "wine_type": None,
        "image_url": None,
        "image_source": None,
        "candidates": [
            {"name": c.get("name"), "producer": c.get("producer"),
             "vintage": c.get("vintage"), "confidence": c.get("confidence") or 0}
            for c in candidates[1:4]
        ],
    }


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
                    logger.info("verify_image_url: rejected %s (status=%s, content-type=%s)",
                                url, resp.status_code, resp.headers.get("content-type"))
                    return False
        return True
    except httpx.HTTPError as e:
        logger.info("verify_image_url: could not reach %s: %s", url, e)
        return False
