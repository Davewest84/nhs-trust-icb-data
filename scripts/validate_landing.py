"""Deep landing validator.

Goes beyond `check_urls.py` (which only confirms HTTP 200): inspects each landing
page for *evidence that board papers are actually there*. Distinguishes:

  papers_found       — page surfaces dated board-paper PDFs or year archives
  no_papers_visible  — page returns 200 but no board-paper evidence (suspicious;
                       likely the URL points at the wrong sub-page now)
  needs_playwright   — static fetch sees nothing useful but the page looks
                       JS-rendered (we can detect this from a near-empty body)
  broken             — HTTP error / no response

Writes a per-org validation result that the Saturday Claude job uses to decide
what to patch and how to populate the LLM-readable access notes.

Run:
  py scripts/validate_landing.py        # both DBs
  py scripts/validate_landing.py trust  # one only
"""
from __future__ import annotations

import json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

REPO = Path(__file__).resolve().parent.parent
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*",
           "Accept-Language": "en-GB,en;q=0.9"}

# --- evidence detectors ---------------------------------------------------
_M = (r'(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|'
      r'jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)')
DATE_DMY  = re.compile(r'\b\d{1,2}[\s\-]+' + _M + r'[\s\-]+20\d{2}\b', re.I)
DATE_MY   = re.compile(_M + r'[\s\-]+20\d{2}\b', re.I)
DATE_ISO  = re.compile(r'\b20\d{2}-\d{2}-\d{2}\b')
YEAR      = re.compile(r'\b(20\d{2})\b')

def is_pdf_link(href: str, text: str) -> bool:
    h = (href or '').lower(); t = (text or '').lower()
    if h.endswith('.pdf') or '.pdf?' in h: return True
    if '.pdf' in t: return True
    if '/download_file/' in h or '/downloadfile' in h: return True
    if h.endswith('/file') and ('/documents/' in h or '/document/' in h): return True
    return False

def has_date(text: str, href: str) -> bool:
    for pat in (DATE_DMY, DATE_ISO, DATE_MY):
        if pat.search(text or '') or pat.search(href or ''):
            return True
    return False

def evidence_in_page(html: str, base_url: str) -> dict:
    """Return counts of useful signals on the page."""
    soup = BeautifulSoup(html, 'html.parser')
    dated_pdfs = 0
    year_archives = 0
    meeting_subpages = 0
    seen = set()
    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        text = (a.get_text() or '').strip()
        if not href or href.startswith('#') or href.startswith('mailto:'):
            continue
        full = urljoin(base_url, href)
        if full in seen: continue
        seen.add(full)
        pdfy = is_pdf_link(full, text)
        dated = has_date(text, full)
        if pdfy and dated:
            dated_pdfs += 1
        elif not pdfy and dated:
            meeting_subpages += 1
        elif not pdfy and len(text) < 40:
            ym = YEAR.search(text) or YEAR.search(href)
            if ym:
                yr = int(ym.group(0))
                if 2022 <= yr <= 2027:
                    year_archives += 1
    # detect a likely-empty/JS-only body (high header/nav fraction)
    visible_text = soup.get_text(' ', strip=True)
    visible_len = len(visible_text)
    return {
        'dated_pdfs': dated_pdfs,
        'year_archives': year_archives,
        'meeting_subpages': meeting_subpages,
        'visible_text_len': visible_len,
        'mentions_board_papers': bool(re.search(r'board\s+papers?|board\s+meetings?|meeting\s+papers?', visible_text, re.I)),
    }

def classify(ev: dict) -> str:
    if ev['dated_pdfs'] >= 2 or ev['meeting_subpages'] >= 3 or ev['year_archives'] >= 2:
        return 'papers_found'
    if ev['dated_pdfs'] == 1 or ev['meeting_subpages'] in (1, 2) or ev['year_archives'] == 1:
        return 'papers_partial'
    if ev['visible_text_len'] < 800 and not ev['mentions_board_papers']:
        return 'needs_playwright'  # near-empty body, no board-paper text
    return 'no_papers_visible'

# --- main ------------------------------------------------------------------
def validate_one(url: str) -> dict:
    out = {'url': url, 'fetched_at': datetime.now(timezone.utc).isoformat(),
           'status_code': None, 'final_url': None, 'classification': None,
           'evidence': None, 'error': None}
    try:
        r = requests.get(url, headers=HEADERS, timeout=25, allow_redirects=True)
        out['status_code'] = r.status_code
        out['final_url'] = r.url
        if r.status_code >= 400:
            out['classification'] = 'broken'
            out['error'] = f"HTTP {r.status_code}"
            return out
        ev = evidence_in_page(r.text, r.url)
        out['evidence'] = ev
        out['classification'] = classify(ev)
        return out
    except requests.RequestException as e:
        out['classification'] = 'broken'
        out['error'] = f"{type(e).__name__}: {str(e)[:200]}"
        return out

def validate_db(label: str, input_path: Path, output_path: Path, delay: float = 1.5):
    entries = json.loads(input_path.read_text(encoding='utf-8'))
    print(f"[{label}] validating {len(entries)} landing URLs from {input_path.name}")
    results = []
    counts = {'papers_found': 0, 'papers_partial': 0, 'no_papers_visible': 0,
              'needs_playwright': 0, 'broken': 0}
    for i, e in enumerate(entries, 1):
        url = e.get('url')
        if not url:
            continue
        v = validate_one(url)
        cls = v['classification'] or '?'
        counts[cls] = counts.get(cls, 0) + 1
        results.append({'ods_code': e.get('ods_code'), 'name': (e.get('names') or ['?'])[0], **v})
        if cls != 'papers_found':
            print(f"  [{label}][{i:3d}/{len(entries)}] {cls:18}  {e.get('ods_code')}  {url[:100]}")
        elif i % 25 == 0:
            print(f"  [{label}][{i:3d}/{len(entries)}] ...")
        time.sleep(delay)
    report = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'label': label, 'total': len(results),
        'counts': counts, 'results': results,
    }
    output_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"[{label}] DONE: {counts}")
    print(f"[{label}] Report: {output_path}")

def main():
    which = sys.argv[1] if len(sys.argv) > 1 else 'all'
    targets = [
        ('trust', REPO / 'trust_urls.json', REPO / 'trust_urls_validation.json'),
        ('ICB',   REPO / 'icb_urls.json',   REPO / 'icb_urls_validation.json'),
    ]
    for label, inp, outp in targets:
        if which in ('all', label.lower(), label) and inp.exists():
            validate_db(label, inp, outp)

if __name__ == '__main__':
    main()
