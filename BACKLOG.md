# Backlog

Issues found during testing. Resolved items are removed from this file
once fixed rather than kept as a done-list — check git history if you need
the record of something that used to be here.

## Photo identification: no listing image, and the confidence threshold is unverified

**Current state, for anyone picking this up:** the chain is barcode (Open
Food Facts) → a free vision model via OpenRouter → manual entry.
`identify_photo()` in `app/identify.py` sends the label photo to
OpenRouter and asks it for a ranked list of candidate readings (name,
producer, vintage, confidence) — there's no fixed label database being
matched against, and no web search involved.

**What this can't do:** find or return a listing image. It only
identifies the wine. Every photo-identified wine saves with no photo
unless a barcode match happened to find one via Open Food Facts. There is
currently no free path to "also find me a picture of the bottle" — that
would need either a paid search API or a different free service turning
up that can genuinely do both identification and image lookup for free.

**Two things worth tuning once there's real usage data -- not code to
write, just parameters to adjust once evidence exists:**
- `MATCH_CONFIDENCE_THRESHOLD` in `identify.py` is set to `0.6` with no
  real basis besides being a reasonable-sounding starting point — worth
  adjusting once there's a sense of whether the model's self-reported
  confidence runs high, low, or about right in practice.
- The specific model pinned in `.env.example`
  (`inclusionai/ling-3.0-flash-vl:free`) doesn't support forced JSON
  output, so `_extract_json_object()` has to tolerate markdown fences or
  stray text around the model's reply. Verified against synthetic cases
  and a full simulated end-to-end scan (jsdom), but not yet confirmed
  against a real photo and a real model response in production.

**Worth knowing if this ever needs replacing again:** OpenRouter's free
model catalog rotates — models get deprecated, added, or lose free status
over time. Check openrouter.ai/models for current free, vision-capable
options before assuming the pinned model still exists or is still free.

---
