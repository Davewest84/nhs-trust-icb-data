# NHS trust + ICB data

Public dataset of English NHS **trust + integrated care board** reference data, refreshed weekly. Use freely.

| Dataset | JSON (canonical) | CSV | XLSX | Entries |
|---|---|---|---|---:|
| Trust board-papers URLs | [`trust_urls.json`](trust_urls.json) | [`trust_urls.csv`](trust_urls.csv) | [`trust_urls.xlsx`](trust_urls.xlsx) | ~207 |
| ICB board-papers URLs | [`icb_urls.json`](icb_urls.json) | [`icb_urls.csv`](icb_urls.csv) | [`icb_urls.xlsx`](icb_urls.xlsx) | 36 |
| Trust press & FOI contacts | [`trust-contacts.json`](trust-contacts.json) | [`trust-contacts.csv`](trust-contacts.csv) | [`trust-contacts.xlsx`](trust-contacts.xlsx) | ~207 |
| ICB press & FOI contacts | [`icb-contacts.json`](icb-contacts.json) | [`icb-contacts.csv`](icb-contacts.csv) | [`icb-contacts.xlsx`](icb-contacts.xlsx) | 36 |

JSON is the authoritative format; CSV and XLSX are regenerated from it each Saturday by [`scripts/build_derivatives.py`](scripts/build_derivatives.py). Don't edit the CSV or XLSX directly — your edits will be lost on the next refresh.

## Direct raw URLs (for tools)

```
https://raw.githubusercontent.com/Davewest84/nhs-trust-icb-data/main/trust_urls.json
https://raw.githubusercontent.com/Davewest84/nhs-trust-icb-data/main/icb_urls.json
https://raw.githubusercontent.com/Davewest84/nhs-trust-icb-data/main/trust-contacts.json
https://raw.githubusercontent.com/Davewest84/nhs-trust-icb-data/main/icb-contacts.json
```

(Old URLs pointing at `Davewest84/nhs-board-papers-reader` still redirect — GitHub auto-redirects all references to the old name.)

## Schemas

### Trust URLs

```json
{
  "ods_code": "RA2",
  "names": ["Royal Surrey County Hospital NHS Foundation Trust", "Royal Surrey County Hospital"],
  "type": "Acute and Acute & Community Trusts",
  "region": "South East",
  "ics": "Surrey Heartlands",
  "correspondent": "Alison",
  "url": "https://www.royalsurrey.nhs.uk/board-papers/"
}
```

In the CSV/XLSX, the `names` array is flattened: first entry → `name`, remainder → `alt_names` (semicolon-separated).

### ICB URLs

```json
{
  "ods_code": "QYG",
  "names": ["Cheshire and Merseyside ICB"],
  "predecessor_codes": [],
  "merger_date": null,
  "region": "North West",
  "correspondent": null,
  "url": "https://www.cheshireandmerseyside.nhs.uk/get-involved/...",
  "url_root": "https://www.cheshireandmerseyside.nhs.uk",
  "cluster_id": null,
  "cluster_meeting_url": null,
  "notes": null
}
```

`predecessor_codes` captures the ICBs that merged into the current entity in April 2026 (where applicable). `cluster_id` / `cluster_meeting_url` are used where multiple ICBs share a joint board.

### Contacts (trust + ICB)

```json
{
  "trust_name": "Airedale NHS Foundation Trust",
  "ods_code": "RCF",
  "press_email": "anhsft.communications@nhs.net",
  "press_email_alt": null,
  "press_source_url": "https://www.airedale-trust.nhs.uk/contact-us/media-enquiries/",
  "foi_email": "anhsft.foi@nhs.net",
  "foi_email_alt": null,
  "foi_source_url": "https://www.airedale-trust.nhs.uk/contact-us/freedom-of-information-requests/",
  "notes": null
}
```

`*_email_alt` columns hold the previous primary email when superseded (so legacy mailing lists keep working). `*_source_url` records where the address was sourced from. `notes` carries dated provenance lines and free-text caveats.

## How the data is maintained

A scheduled task on Dave West's machine runs every Saturday morning. It:

1. Checks every URL in the two URL JSONs for HTTP 200, finds broken ones, web-searches for replacements, verifies, and patches the JSON.
2. Visits ~24 organisations per week (a 10-week rotation across trust + ICB combined) to refresh their press and FOI emails by reading each organisation's own contact pages. Tiered fetch (WebFetch → Playwright when blocked) handles Cloudflare-obfuscated email pages.
3. Regenerates all CSV and XLSX derivatives from the JSON canonicals.
4. Commits and pushes everything back to this repo.

The work is orchestrated by Claude Code running a documented prompt at [`scripts/url_update_schedule_prompt.md`](scripts/url_update_schedule_prompt.md). The whole pipeline is bootstrapped by [`scripts/_run_claude_patch.ps1`](scripts/_run_claude_patch.ps1).

If you spot anything stale or wrong, an issue or message is welcome — usually it'll be fixed in the next weekly run.

## License

Data files are released under **CC0 1.0** (effectively public domain — see [`LICENSE`](LICENSE)). The data is aggregated from publicly-listed information on each organisation's website. Use freely; attribution appreciated but not required.

The Python and PowerShell scripts in this repo are MIT-equivalent unless a more restrictive license is added.

## Archive

The [`archive/`](archive/) folder contains earlier code from when this repo was named `nhs-board-papers-reader` and held a Colab notebook for fetching/analysing trust board papers. The Colab is no longer actively maintained but kept here for anyone who wants the starting point.
