"""Check every URL in trust_urls.json AND icb_urls.json is still live.

Designed to be run on a schedule (cron / Windows Task Scheduler). Produces:
  - trust_urls_report.json — latest run result for trust DB
  - icb_urls_report.json   — latest run result for ICB DB

Neither input file is modified here. The Saturday Claude-orchestrated patch
script reads these reports and patches broken URLs. This conservative design
(check-only, no auto-fix in this script) is deliberate.

Run: py scripts/check_urls.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent

TARGETS = [
    ("trust", REPO / "trust_urls.json", REPO / "trust_urls_report.json"),
    ("ICB",   REPO / "icb_urls.json",   REPO / "icb_urls_report.json"),
]

# Polite delay between requests
DELAY_SECONDS = 2.0

BROKEN_STATUS_CODES = {404, 410, 500, 502, 503}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

try:
    from playwright.sync_api import sync_playwright  # type: ignore
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False


def _check_with_playwright(url: str, timeout: int = 30) -> dict:
    """Last-resort browser check. Fires only when the HTTP path fails."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(user_agent=UA)
            page = ctx.new_page()
            response = page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
            if response is None:
                return {"ok": False, "status": None, "final_url": None,
                        "error": "playwright: no response from navigation"}
            status = response.status
            final_url = page.url
            if status in BROKEN_STATUS_CODES or status in {400, 401}:
                return {"ok": False, "status": status, "final_url": final_url,
                        "error": f"playwright: HTTP {status}"}
            return {"ok": True, "status": status, "final_url": final_url, "error": None}
        finally:
            browser.close()


def check_url(url: str) -> dict:
    """Return {ok, status, final_url, error}.

    Tier 1: requests (HTTP client with browser UA).
    Tier 2: Playwright headless (only if Tier 1 failed and playwright installed).
    """
    http_err = None
    http_status = None
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        if r.status_code < 400 or r.status_code in {401}:
            return {
                "ok": r.status_code < 400,
                "status": r.status_code,
                "final_url": r.url,
                "error": None if r.status_code < 400 else f"HTTP {r.status_code}",
            }
        http_status = r.status_code
        http_err = f"HTTP {r.status_code}"
    except requests.RequestException as e:
        http_err = str(e)
        for code in BROKEN_STATUS_CODES | {400, 401, 403, 429}:
            if str(code) in http_err:
                http_status = code
                break

    # Tier 2 fallback
    if _HAS_PLAYWRIGHT:
        try:
            result = _check_with_playwright(url)
            if result["ok"]:
                result["error"] = "(rescued by playwright fallback)"
                return result
            return {
                "ok": False,
                "status": result.get("status") or http_status,
                "final_url": None,
                "error": f"http: {http_err[:150]}; {result.get('error', '')}"[:300],
            }
        except Exception as pw_err:
            return {
                "ok": False,
                "status": http_status,
                "final_url": None,
                "error": f"http: {http_err[:150]}; playwright: {str(pw_err)[:130]}"[:300],
            }

    return {
        "ok": False,
        "status": http_status,
        "final_url": None,
        "error": http_err[:300] if http_err else "unknown",
    }


def check_db(label: str, input_file: Path, output_file: Path) -> int:
    """Walk one DB. Returns count of broken URLs (0 means all good, -1 missing input)."""
    if not input_file.exists():
        print(f"[{label}] WARN: {input_file} not found — skipping", file=sys.stderr)
        return -1

    entries = json.loads(input_file.read_text(encoding="utf-8"))
    print(f"[{label}] Checking {len(entries)} URLs from {input_file.name}...")

    results = []
    broken = 0
    for i, entry in enumerate(entries, 1):
        url = entry.get("url")
        if not url:
            # Skip entries with empty URL (e.g. brand-new entities without one yet)
            continue
        check = check_url(url)
        if not check["ok"]:
            broken += 1
            status_msg = f"status={check['status']}" if check["status"] else "error"
            print(f"  [{label}][{i:3d}/{len(entries)}] BROKEN ({status_msg}): {entry.get('ods_code')} {url}")
        elif i % 25 == 0:
            print(f"  [{label}][{i:3d}/{len(entries)}] ... {i-broken} ok so far")
        results.append({
            "ods_code": entry.get("ods_code"),
            "name": (entry.get("names") or ["?"])[0],
            "url": url,
            **check,
        })
        time.sleep(DELAY_SECONDS)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label": label,
        "total": len(results),
        "ok": sum(1 for r in results if r["ok"]),
        "broken": broken,
        "results": results,
    }
    output_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[{label}] Done. Total: {report['total']}, OK: {report['ok']}, Broken: {report['broken']}")
    print(f"[{label}] Report: {output_file}")
    print()
    if broken > 0:
        print(f"[{label}] Broken URLs (review and patch {input_file.name} manually):")
        for r in results:
            if not r["ok"]:
                print(f"  {r['ods_code'] or '?':8s} {(r['name'] or '?')[:60]:60s} {r['url']}")
        print()
    return broken


def main() -> int:
    overall_broken = 0
    seen_any = False
    for label, input_file, output_file in TARGETS:
        result = check_db(label, input_file, output_file)
        if result >= 0:
            seen_any = True
            overall_broken += result
    if not seen_any:
        print("ERROR: No input files found.", file=sys.stderr)
        return 1
    print(f"=== Combined: {overall_broken} broken URL(s) across all DBs. ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
