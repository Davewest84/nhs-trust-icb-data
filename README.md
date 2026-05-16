# NHS Board Papers — public data + Analyser

This repo holds two related things:

1. **Public reference data** about English NHS trusts and integrated care boards: board-papers URLs, press / FOI contacts. Refreshed automatically every Saturday. Use freely.
2. **A Colab notebook + Python tool** that uses that data to fetch and analyse trust board papers with Claude.

---

## Public data files

Updated weekly (Saturday 05:00 UK) by a scheduled job. Each dataset is published in **two formats** — JSON (best for scripts and tools) and CSV (best for humans, Excel and quick browsing).

| Dataset | JSON | CSV | Entries | Canonical format |
|---|---|---|---:|---|
| Trust board-papers URLs | [`trust_urls.json`](trust_urls.json) | [`trust_urls.csv`](trust_urls.csv) | ~208 | JSON |
| ICB board-papers URLs | [`icb_urls.json`](icb_urls.json) | [`icb_urls.csv`](icb_urls.csv) | 36 | JSON |
| Trust press & FOI contacts | [`trust-contacts.json`](trust-contacts.json) | [`trust-contacts.csv`](trust-contacts.csv) | ~208 | CSV |
| ICB press & FOI contacts | [`icb-contacts.json`](icb-contacts.json) | [`icb-contacts.csv`](icb-contacts.csv) | 36 | CSV |

Direct raw URLs for programmatic use, e.g.:

```
https://raw.githubusercontent.com/Davewest84/nhs-board-papers-reader/main/trust_urls.json
https://raw.githubusercontent.com/Davewest84/nhs-board-papers-reader/main/icb-contacts.csv
```

### Trust URL schema (`trust_urls.json` / `.csv`)

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

In the CSV version, the `names` array is flattened: first entry becomes `name`, the rest are semicolon-joined in `alt_names`.

### ICB URL schema (`icb_urls.json` / `.csv`)

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

`predecessor_codes` covers ICBs reconstituted after the April 2026 mergers. `cluster_id` / `cluster_meeting_url` apply where multiple ICBs share a single joint board. In the CSV version arrays are semicolon-joined and `null`s become empty strings.

### Contacts schema (`trust-contacts.csv` / `icb-contacts.csv`)

Columns:

| Column | Notes |
|---|---|
| `trust_name` *(trust file)* / `icb_name` *(ICB file)* | Full organisation name |
| `ods_code` *(trust file only — not yet present on ICB file)* | ODS organisation code |
| `press_email` | Current primary press / media email |
| `press_email_alt` | Previous primary or secondary press email (kept when superseded) |
| `press_source_url` | Page on the org's website where the press email was sourced |
| `foi_email` | Current primary FOI email |
| `foi_email_alt` | Previous primary or secondary FOI email |
| `foi_source_url` | Page on the org's website where the FOI email was sourced |
| `notes` | Free-text provenance / caveats (dated when auto-edited) |

The CSV is the canonical version for contacts; the JSON is generated from it by transforming each row into an object and converting empty strings to `null`.

### How the data is maintained

- A weekly scheduled task on Dave West's machine runs every Saturday morning. It:
  - checks every URL in both URL DBs for HTTP 200, finds broken ones, web-searches for replacements, verifies, and patches the JSONs
  - visits ~1/10 of trusts and ICBs each week (10-week rotation) to refresh the press and FOI emails by reading each organisation's own contact pages
  - regenerates all 8 published files from the canonical sources and pushes them here
- The work is orchestrated by Claude Code running a documented prompt. Sources live in the private `Davewest84/hsj-team-tools` repo.
- If you spot anything stale or wrong, an issue or message is welcome — usually it'll be fixed in the next weekly run.

### License

Data files are released under **CC0 1.0** (effectively public domain — see [`LICENSE`](LICENSE)). The data is aggregated from publicly-listed information on each organisation's website. Use freely; attribution appreciated but not required.

The Python code in this repo (the analyser tool below) is provided as-is for reference; treat it as MIT-equivalent unless a more restrictive license is added.

---

## NHS Board Papers Analyser

Searches for, downloads, and analyses NHS trust board papers using the Claude AI API. Returns story leads structured for NHS specialist journalism.

### Quick start — Google Colab (recommended)

1. Open `Board_Papers_Analyser.ipynb` in [Google Colab](https://colab.research.google.com)
2. Get an Anthropic API key from [console.anthropic.com](https://console.anthropic.com)
3. Edit the configuration cell (Cell 2) with your API key and trust name
4. Run all cells in order

No installation required.

### What it does

1. **Searches** DuckDuckGo for the trust's board papers page
2. **Fetches** the index page and identifies PDF/ZIP download links
3. **Downloads** the most recent board pack using browser-mimicking headers and session cookies
4. **Extracts** text from the PDF using targeted passes (agenda first, then key sections)
5. **Analyses** the text with Claude, returning structured story leads with page references

### If the download fails

Some NHS trust websites block automated downloads even with browser headers. If this happens, the tool will say so clearly and ask you to upload the PDF manually. You can download it yourself from the trust's website and either:
- **In Colab**: upload via the file panel (left sidebar → Files icon)
- **CLI**: use the `--pdf` flag pointing to your downloaded file

### Approximate costs per run

| Pack size | Pages read | Approx. cost (Opus 4.6) | Approx. cost (Sonnet 4.6) |
|---|---|---|---|
| Small (50pp) | ~40pp | ~£0.50 | ~£0.10 |
| Medium (150pp) | ~80pp | ~£1.00 | ~£0.20 |
| Large (250pp) | ~120pp | ~£1.50 | ~£0.30 |

To use Sonnet instead of Opus, change `MODEL` in the configuration cell. Sonnet is faster and much cheaper; quality is slightly lower for complex editorial judgements.

### Known limitations

- **JS-rendered sites**: trusts using JavaScript to render download buttons (e.g. some Civica/Idox CMS sites) will block automated download — use manual upload
- **Login-gated papers**: some trusts require login to access papers — not supported
- **Scanned PDFs**: papers scanned as images rather than text-layer PDFs will extract no useful text
- **Zipped packs**: handled — the tool unpacks ZIPs and processes each PDF inside
- **Multiple individual papers**: the tool will attempt to download the first/most prominent link; you can override by pasting a direct URL

### CLI usage (developers)

```bash
pip install -r requirements.txt

# Basic usage
python board_papers.py "Sussex Community NHS Foundation Trust" --api-key sk-ant-...

# With known URL (skips search)
python board_papers.py "UCLH" --url https://www.uclh.nhs.uk/.../board-meetings --api-key sk-ant-...

# With manually downloaded PDF
python board_papers.py "Norfolk and Waveney" --pdf ./norfolk_jan2026.pdf --api-key sk-ant-...

# Use environment variable for API key
export ANTHROPIC_API_KEY=sk-ant-...
python board_papers.py "Shrewsbury and Telford Hospital NHS Trust"
```

### Adjusting the analysis

The `prompt_template.txt` file controls what Claude looks for and how it frames the output. Edit it to:
- Adjust story strength thresholds
- Add organisation-specific context
- Change output format (e.g. longer summaries vs shorter bullets)
- Focus on specific story categories

Use `{{TRUST_NAME}}`, `{{BOARD_PAPERS_URL}}` and `{{EXTRACTED_TEXT}}` as placeholders — they are replaced at runtime.

---

## Files in this repo

| File | Purpose |
|---|---|
| `trust_urls.json` / `.csv` | Trust board-papers URL database (public data — see above) |
| `icb_urls.json` / `.csv` | ICB board-papers URL database (public data — see above) |
| `trust-contacts.json` / `.csv` | Trust press & FOI contact database (public data — see above) |
| `icb-contacts.json` / `.csv` | ICB press & FOI contact database (public data — see above) |
| `Board_Papers_Analyser.ipynb` | Google Colab notebook — main user interface for the analyser |
| `board_papers.py` | CLI Python script (developer use) |
| `prompt_template.txt` | Analysis prompt sent to Claude — edit to adjust output |
| `requirements.txt` | Python dependencies for the analyser |
| `LICENSE` | CC0 1.0 — applies to the data files; analyser code is MIT-equivalent unless noted |
