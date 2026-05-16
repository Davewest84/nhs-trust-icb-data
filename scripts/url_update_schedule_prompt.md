# Weekly NHS trust + ICB data refresh — self-contained prompt

Pasted into the Saturday Claude-orchestrated job that maintains the data files
in this repo (`Davewest84/nhs-trust-icb-data`). All four datasets — trust URLs,
ICB URLs, trust contacts, ICB contacts — live as JSON canonicals at the repo
root, with CSV and XLSX derivatives regenerated each run.

---

## Prompt to paste

```
Refresh the NHS trust + ICB data files in this repo.

Working directory: the repository root (this is the canonical home — there is
no separate canonical/mirror split any more).

JSON canonicals at the repo root:
  trust_urls.json       (~207 NHS trusts with board-papers URLs)
  icb_urls.json         (36 post-April-2026 ICBs)
  trust-contacts.json   (~207 trusts with press + FOI emails)
  icb-contacts.json     (36 ICBs with press + FOI emails)

Plus:
  refresh-rotation-state.json — rotation pointer for step 4 (contacts)
  scripts/build_derivatives.py — builds the CSV + XLSX files
  scripts/check_urls.py        — health-check script
  scripts/_run_claude_patch.ps1 — bootstrap (this is what called you)
  scripts/url_update_schedule_prompt.md — this file

Steps:

1. URL health check. Walks both URL JSONs and writes reports:
       py scripts/check_urls.py
   Produces trust_urls_report.json + icb_urls_report.json at the repo root.
   Takes ~9-10 minutes.

2. Read both reports. Collect every entry where ok == false. Track which DB
   each broken entry came from so you patch the right file.

3. For each broken entry (identified by ods_code, with DB tagged):
   a. Web-search the org's current board papers page:
      "{org name} board papers site:{domain-from-original-url}"
      Fall back to: "{org name} board papers 2026"; for ICBs also try
      "{ICB name} board meetings" and "{ICB name} our publications".
   b. Fetch the top candidate URL and verify:
      - Page title contains the trust/ICB name (or an obvious abbreviation)
      - Page links to PDFs labelled "board papers", "board meeting",
        "meeting papers", or month + year pattern
      - URL is on the org's own domain (not a Google cache, news site,
        Wayback Machine, or aggregator)
      - For ICB cluster boards (DLN, LNR, BSOL-BC, CW-HW, STW-SSOT,
        BNSSG-GLO, SW-PEN), joint board pack may live on a partner ICB's
        domain — that's expected.
   c. If the top candidate doesn't verify, try the next one (max 3).
   d. If none verify, leave the URL as-is and note in the commit message.

4. Rotation-based contact refresh (covers BOTH trusts and ICBs). Each weekly
   run touches ~1/10 of orgs deeply. Reads contact pages, refreshes
   trust-contacts.json and icb-contacts.json. Over 10 weeks the full set
   (207 trusts + 36 ICBs = 243 orgs) gets covered.

   State file: `refresh-rotation-state.json` (at repo root). Schema:

       {
         "last_run_date": "YYYY-MM-DD",
         "last_batch_completed": -1
       }

   If the state file doesn't exist, create it with last_batch_completed: -1
   and last_run_date set to today minus 7 days (so this run does batch 0).

   Compute how many batches to do this run:
   - weeks_due     = max(1, round((today - last_run_date).days / 7))
   - batches_to_do = min(weeks_due, 3)   # cap at 3 to bound usage

   Catch-up rule: if behind by more than 1 week, do up to 3 batches and bump
   last_run_date forward by (batches_to_do * 7) days — NOT to today. This
   drifts back to schedule over a few runs without overrunning a single run.

   Batch assignment (deterministic, stable across changes to the org list):
   for each org, batch number =
     int(hashlib.md5(ods_code.encode()).hexdigest(), 16) % 10
   Both trust and ICB orgs share the same buckets — combined ~24 orgs/batch.

   For each batch in
   [(last_batch_completed + 1) % 10 .. (last_batch_completed + batches_to_do) % 10],
   process every org whose batch number matches.

   For each org in the batch, refresh both press and FOI emails. Use a tiered
   fetch — straight-to-Playwright would be wasteful since most NHS contact
   pages are plain HTML:

   a. WebFetch first. Fetch the page in press_source_url, then separately
      foi_source_url. Cheap, fast, handles ~90% of orgs.

   b. Verify the address actually appears in the page. WebFetch returns an
      AI summary, not raw HTML. If Claude reports "press email is X" but X
      doesn't appear in the visible page text (mailto: link or plain text),
      treat it as a miss and escalate.

   c. Fall back to Playwright when WebFetch hits any of:
      - HTTP 403 / Cloudflare "checking your browser" interstitial
      - captcha or bot-protection wall
      - page loads but shows no email where one should exist (Cloudflare's
        cfemail XOR obfuscation hides addresses from non-JS fetchers — known
        cases: Mersey Care, Ashford & St Peter's, Hertfordshire Partnership)
      - WhatDoTheyKnow.com pages (block WebFetch entirely)

   d. Apply the alt-column rules:
      - If the page shows an email matching the existing primary, do nothing.
      - If it matches the existing _alt, do nothing.
      - If it's an entirely new address: move the existing primary into the
        _alt field, put the new one as primary. Update the _source_url.
        Append a note: "primary updated YYYY-MM-DD from [URL]; prior value
        moved to _alt".
      - Never blindly overwrite — the existing primary may be correct and
        the page may show a personal/director's address.
      - NEVER touch `notes` except to add a dated provenance line.

   e. After processing all batches, update the state file:
      - last_batch_completed = (last_batch_completed + batches_to_do) % 10
      - last_run_date = old_last_run_date + batches_to_do * 7 days
        (NOT today — see catch-up rule above)

   Output a per-batch summary: orgs visited, addresses updated, orgs where
   the page couldn't be read (and which method failed).

   The contacts JSON edits go to this repo at the root. They get committed
   alongside the URL changes in step 6 below.

5. Rebuild the CSV + XLSX derivatives from the JSON canonicals:
       py scripts/build_derivatives.py
   Overwrites: trust_urls.csv, trust_urls.xlsx, icb_urls.csv, icb_urls.xlsx,
               trust-contacts.csv, trust-contacts.xlsx,
               icb-contacts.csv, icb-contacts.xlsx

6. Commit everything in one go:
       git add -- trust_urls.json trust_urls.csv trust_urls.xlsx \
                  icb_urls.json icb_urls.csv icb_urls.xlsx \
                  trust-contacts.json trust-contacts.csv trust-contacts.xlsx \
                  icb-contacts.json icb-contacts.csv icb-contacts.xlsx \
                  trust_urls_report.json icb_urls_report.json \
                  refresh-rotation-state.json
       git commit -m "Weekly refresh ($(date +%Y-%m-%d)) — N1 trust URLs fixed, N2 contacts refreshed"

   Commit message should mention which ods_codes were patched in each DB and
   which orgs were visited for contact refresh.

   Push (use GITHUB_TOKEN from env for headless auth):
       source ~/.bashrc 2>/dev/null  # or wherever GITHUB_TOKEN lives
       git push "https://${GITHUB_TOKEN}@github.com/Davewest84/nhs-trust-icb-data.git" main

7. Mirror local Data/Lookup. After the public push has succeeded, sync the
   four JSONs + their CSV companions to the user's workspace lookup folder
   for easy local access:

       LOOKUP="/c/Users/davew/OneDrive - HSJ Information Ltd/Claude code assistant/Data/Lookup"
       for f in trust_urls icb_urls trust-contacts icb-contacts; do
           cp "$f.json" "$LOOKUP/$f.json"
           cp "$f.csv"  "$LOOKUP/$f.csv"
       done

   The XLSX files don't get mirrored to Data/Lookup by default — they're for
   human browsing and live in the public repo. Adjust if Dave wants them too.

Safety rules:
- Only modify files explicitly named in steps 1-7 of this prompt:
  trust_urls.json / .csv / .xlsx, icb_urls.json / .csv / .xlsx,
  trust-contacts.json / .csv / .xlsx, icb-contacts.json / .csv / .xlsx,
  refresh-rotation-state.json, trust_urls_report.json, icb_urls_report.json,
  plus the Data/Lookup copies in step 7. Do not touch any other file in any
  repo.
- If fewer than half of the broken URLs in EITHER DB can be verified,
  something is wrong with the approach — stop and report rather than commit
  a bad batch. (You can still proceed for the DB whose half-failure
  threshold isn't tripped.)
- If you cannot push to GitHub (auth issues, merge conflicts), leave the
  commit local and report. Do not force-push. Do not reset.
- If the health-check script fails to run (dependency missing, network
  down), stop and report — do not attempt a fix.
- Step 7 (local Lookup mirror) is best-effort. If it fails, report but do
  NOT roll back the canonical commit from step 6.
- The ICB DB schema differs slightly from the trust DB — it has additional
  fields (predecessor_codes, merger_date, url_root, cluster_id,
  cluster_meeting_url, notes). Only ever modify the "url" field in URL
  patches; never touch other fields including url_root or
  cluster_meeting_url (those need manual judgement when the next round of
  ICB mergers happens).
- For contact entries, never touch the `notes` field except to append a
  dated provenance line.
```

---

## Why this design

- **One repo, one source of truth.** All four datasets live as JSON canonicals
  in this repo. CSV + XLSX are derivatives, regenerated each run. No separate
  canonical/mirror split to keep in sync.
- **One run, all four datasets.** A single combined check (`check_urls.py`)
  walks both URL JSONs. A single Claude-orchestrated patch handles broken
  entries + contact refresh + derivative rebuild. One weekly commit.
- **Verified URL replacements only.** Candidate page must look like a board
  papers page before replacement. Keeps garbage out.
- **Half-failure circuit breaker.** If Claude can only verify <50% of broken
  URLs in a DB, it aborts that DB.
- **No force-push, no reset.** Destructive git operations are blocked.
- **Rotation, not all-at-once, for contact emails.** ~24 orgs/week
  (combined). Full coverage every ~10 weeks. Catch-up rule absorbs missed
  weeks without overrunning.
- **Tiered fetch for contact pages.** WebFetch first (cheap, ~90% hit rate),
  Playwright only when blocked (Cloudflare, cfemail obfuscation, captcha,
  WhatDoTheyKnow). Avoids paying browser-spin-up cost for every org.
- **XLSX for humans.** Filterable, sortable in Excel. Easier to skim 200+
  rows than the CSV. Generated each Saturday, never edited by hand.
