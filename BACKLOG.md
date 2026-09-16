# Backlog

Issues found during testing. Resolved items are removed from this file
once fixed rather than kept as a done-list — check git history if you need
the record of something that used to be here.

## Sheet's × close button doesn't close the panel

**Found:** testing the detail sheet — clicking the × in the top-right corner
of an open panel does nothing.

**Investigated, no bug found in the current code.** Traced the click
handler order, `open()`/`closeAll()`, and the CSS stacking (`.close` sits
inside `.sheet` at z-index 50, above the scrim's 40 — correct). Nothing
earlier in the click handler intercepts a click on `[data-close]` before
it's reached. On paper this should already work.

**Next step:** hard-refresh and retest against the current deployed code —
possible the original report was against stale cached JS from before an
earlier sync. If it's still broken after that, it needs a live repro:
does anything happen at all on click, any console error, does it happen on
every sheet or just one of them.

---

## No-match screen offers no alternates — feature request

**Found:** testing a photo scan on a real wine (Tenuta Ulisse Pecorino
Terre d'Abruzzo IGP) — the label read fine but confidence came back below
the threshold, so it dropped straight to "No match" and offered only
"Enter it myself" or "Try again."

**What's wanted instead:** when the photo-identification tier has a
plausible guess that just didn't clear the confidence bar (rather than
finding genuinely nothing), show it as a pickable option — the same
"other possibilities" pattern already used on the *high*-confidence match
screen, just triggered on the low-confidence path too instead of being
discarded outright.

**What this actually requires:**
- `identify_photo()` in `app/identify.py` currently returns a single
  `name` / `producer` / `vintage` / `confidence` guess. The prompt and
  parsing would need to ask the model for a small ranked list of
  candidates instead of one best guess, if the model can produce that
  reliably — worth testing whether asking for multiple candidates hurts
  accuracy on the top guess before committing to this.
- `runPhotoScan()` in `index.html` already renders a dynamic `matchAlts`
  list (built for real candidates once api4ai supplied them) — it would
  need re-populating from whatever OpenRouter's response shape ends up
  being, and it currently gets nothing since a single-guess response has
  no alternates to show.
- Decide a cutoff: below what confidence do we stop showing anything at
  all and fall to a true "no match" (blurry photo, wine genuinely not
  identifiable)?

---

## Multi-user accounts with roles — admin vs. regular users

**Requested:** move from the current single shared password to real user
accounts, plus a role distinction that limits what non-admin users can do.

**Specifics as given:**
- The current login (`APP_PASSWORD`) becomes the administrator account and
  should not change as part of this.
- New user accounts need a username, not just a password.
- Passwords for these accounts must be enforced at a minimum of 10
  characters.
- Non-admin users can create and edit wines, but cannot delete them
  outright — they can only mark a listing for deletion. Only the
  administrator account can actually delete a marked listing.
- Still one shared list, not per-user separate views — every account sees
  the same central set of wines, same as today. The only per-user change
  is that each entry should be tagged with who added it, visible to
  everyone looking at it.

**Why this is a bigger change than anything else on this list:** everything
else here is a fix within the existing single-user design. This is a
different design — the app's whole auth model right now is one shared
password (`APP_PASSWORD`) checked against a session flag, with no concept
of individual users at all. This needs, at minimum:

- A `users` table (username, hashed password, role) — passwords need actual
  hashing (bcrypt or argon2), not stored in any reversible form.
- The existing `APP_PASSWORD` login path preserved as-is for the admin
  account specifically, per the request, while new accounts go through the
  new table.
- Login changed from "type the shared password" to "type a username and
  password," with the session then carrying which user (and which role) is
  logged in, not just a bare `authed: true` flag.
- A minimum-length check (10 chars) enforced server-side on account
  creation, not just in the browser.
- A new state on the `wines` table — something like `marked_for_deletion` —
  distinct from actually being gone. The existing `DELETE /api/wines/{id}`
  endpoint would need to become admin-only; non-admin users would hit a
  different endpoint that only sets the flag.
- Some admin-facing view of marked-for-deletion listings to actually
  action them, which doesn't exist in any form right now.
- An `added_by` column on the `wines` table (the username at the time of
  creation), plus a small tag rendered on each card/detail view showing
  who added it — this is additive to the existing schema and doesn't
  depend on anything else in this entry, so it could ship on its own if
  the rest of the account system takes longer.
- The README currently describes this as "private, single-user" —
  that framing would need updating throughout once this ships, since it's
  no longer accurate.

**Not started.** Worth deciding, before building it, whether every
non-admin action needs its own permission check individually, or whether a
simple two-role system (admin / member) covers everything wanted here —
the request as given only distinguishes those two, so that's the
assumption to build against unless told otherwise.

---

## Photo identification: no listing image, and the confidence threshold is unverified

**Current state, for anyone picking this up:** the chain is barcode (Open
Food Facts) → a free vision model via OpenRouter → manual entry.
`identify_photo()` in `app/identify.py` sends the label photo to
OpenRouter and asks it to read the name, producer, and vintage directly —
there's no fixed label database being matched against, and no web search
involved.

**What this can't do:** find or return a listing image. It only
identifies the wine. Every photo-identified wine saves with no photo
unless a barcode match happened to find one via Open Food Facts. There is
currently no free path to "also find me a picture of the bottle" — that
would need either a paid search API or a different free service turning
up that can genuinely do both identification and image lookup for free.

**Two things worth tuning once there's real usage data:**
- `MATCH_CONFIDENCE_THRESHOLD` in `identify.py` is set to `0.6` with no
  real basis besides being a reasonable-sounding starting point — worth
  adjusting once there's a sense of whether the model's self-reported
  confidence runs high, low, or about right in practice.
- The specific model pinned in `.env.example`
  (`inclusionai/ling-3.0-flash-vl:free`) doesn't support forced JSON
  output, so `_extract_json_object()` has to tolerate markdown fences or
  stray text around the model's reply. Tested against synthetic cases of
  that (clean JSON, fenced JSON, JSON with chatty text around it, no JSON
  at all) — all four handled correctly — but not yet confirmed against a
  real photo and a real model response.

**Worth knowing if this ever needs replacing again:** OpenRouter's free
model catalog rotates — models get deprecated, added, or lose free status
over time. Check openrouter.ai/models for current free, vision-capable
options before assuming the pinned model still exists or is still free.

---
