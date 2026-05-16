#!/usr/bin/env python3
"""
NHS Board Papers Analyser — CLI script
Searches for, downloads, and analyses NHS trust board papers using the Claude AI API.

Usage:
    python board_papers.py "Trust Name" --api-key sk-ant-...
    python board_papers.py "Trust Name" --url https://... --api-key sk-ant-...
    python board_papers.py "Trust Name" --pdf ./downloaded.pdf --api-key sk-ant-...

Set ANTHROPIC_API_KEY environment variable to avoid passing --api-key each time.
"""

import os
import io
import sys
import zipfile
import tempfile
import argparse
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
import pypdfium2 as pdfium
import anthropic
from duckduckgo_search import DDGS


# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_MODEL = "claude-opus-4-6"
CHARS_PER_PAGE = 3000
CHAR_LIMIT = 400_000  # ~100k tokens, well within Claude's context window

FALLBACK_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

BOARD_PAPER_URL_KEYWORDS = [
    "board-papers", "board-meeting", "board-meetings", "boardpapers",
    "board/meetings", "trust-board", "board-of-directors",
    "board_papers", "board-pack", "governors/meetings",
]

DOC_EXTENSIONS = (".pdf", ".zip", ".docx", ".doc")
DOC_URL_KEYWORDS = ["download", "document", "/file", "attachment", "board-paper", "agenda"]


# ── Stage 1: Find board papers page ──────────────────────────────────────────

def find_board_papers_url(trust_name: str) -> str | None:
    """Search DuckDuckGo for the trust's board papers index page."""
    queries = [
        f'"{trust_name}" board papers 2025 OR 2026 site:nhs.uk',
        f'"{trust_name}" board meeting papers site:nhs.uk',
        f'"{trust_name}" NHS "board papers" site:nhs.uk',
        f'"{trust_name}" NHS board papers minutes 2026',
    ]

    with DDGS() as ddg:
        for query in queries:
            try:
                results = list(ddg.text(query, max_results=8))
                for r in results:
                    url = r.get("href", "")
                    if any(kw in url.lower() for kw in BOARD_PAPER_URL_KEYWORDS):
                        return url
            except Exception as e:
                print(f"  Search query failed: {e}")

    return None


# ── Stage 2: Fetch index and find document links ──────────────────────────────

def make_session(index_url: str = "") -> requests.Session:
    """Create a requests session with browser-like defaults."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": FALLBACK_USER_AGENTS[0],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    })
    # Visit the index page first to pick up session cookies
    if index_url:
        try:
            session.get(index_url, timeout=20)
        except Exception:
            pass
    return session


def get_document_links(session: requests.Session, index_url: str) -> list[dict]:
    """Fetch the board papers index page and extract all document links."""
    try:
        resp = session.get(index_url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"  Could not fetch index page: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    links = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True) or href
        href_lower = href.lower()

        is_doc = (
            any(href_lower.endswith(ext) for ext in DOC_EXTENSIONS)
            or any(kw in href_lower for kw in DOC_URL_KEYWORDS)
        )

        if is_doc:
            full_url = href if href.startswith("http") else urljoin(index_url, href)
            if full_url not in seen:
                seen.add(full_url)
                links.append({"text": text[:120], "url": full_url})

    return links


def pick_best_link(links: list[dict]) -> str | None:
    """Heuristically pick the most recent board pack from a list of links."""
    if not links:
        return None

    priority_terms = ["2026", "2025", "january", "february", "march", "april",
                      "november", "october", "board-pack", "combined", "agenda"]

    for link in links:
        combined = (link["text"] + " " + link["url"]).lower()
        if any(t in combined for t in priority_terms):
            return link["url"]

    # Fall back to first PDF
    for link in links:
        if ".pdf" in link["url"].lower():
            return link["url"]

    return links[0]["url"]


# ── Stage 3: Download ─────────────────────────────────────────────────────────

def download_file(session: requests.Session, url: str, referer: str) -> bytes | None:
    """
    Attempt to download a file using multiple User-Agent strings.
    Returns raw bytes on success, None on failure.
    """
    for i, ua in enumerate(FALLBACK_USER_AGENTS):
        headers = {
            "User-Agent": ua,
            "Referer": referer,
            "Accept": "application/pdf,application/zip,application/octet-stream,*/*",
        }
        try:
            resp = session.get(url, headers=headers, timeout=120)
            if resp.status_code == 200 and len(resp.content) > 10_000:
                return resp.content
            print(f"  Attempt {i + 1}: HTTP {resp.status_code}, {len(resp.content):,} bytes")
        except Exception as e:
            print(f"  Attempt {i + 1} failed: {e}")

    return None


def save_and_unpack(data: bytes, save_dir: str) -> list[str]:
    """
    Save downloaded bytes and return a list of PDF file paths.
    Handles both direct PDFs and ZIP archives.
    """
    os.makedirs(save_dir, exist_ok=True)

    # ZIP files begin with magic bytes PK (0x50 0x4B)
    if data[:2] == b"PK":
        print("  File is a ZIP archive — extracting PDFs...")
        pdf_paths = []
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                all_names = zf.namelist()
                print(f"  ZIP contains {len(all_names)} file(s)")
                for name in all_names:
                    if name.lower().endswith(".pdf") and not name.startswith("__MACOSX"):
                        pdf_data = zf.read(name)
                        safe_name = os.path.basename(name) or f"extracted_{len(pdf_paths)}.pdf"
                        out_path = os.path.join(save_dir, safe_name)
                        with open(out_path, "wb") as f:
                            f.write(pdf_data)
                        pdf_paths.append(out_path)
                        print(f"  Extracted: {safe_name} ({len(pdf_data):,} bytes)")
        except zipfile.BadZipFile:
            print("  ZIP extraction failed.")
        return pdf_paths
    else:
        out_path = os.path.join(save_dir, "board_papers.pdf")
        with open(out_path, "wb") as f:
            f.write(data)
        print(f"  Saved: board_papers.pdf ({len(data):,} bytes)")
        return [out_path]


# ── Stage 4: Extract text ─────────────────────────────────────────────────────

def extract_pages(pdf, start: int, end: int) -> str:
    """Extract and concatenate text from a range of PDF pages."""
    parts = []
    for i in range(start, min(end, len(pdf))):
        try:
            text = pdf[i].get_textpage().get_text_range()
            if text.strip():
                parts.append(f"-- Page {i + 1} --\n{text[:CHARS_PER_PAGE]}")
        except Exception:
            pass
    return "\n".join(parts)


def find_section_starts(agenda_text: str, total_pages: int) -> dict[str, int]:
    """
    Parse the agenda text for page references to key sections.
    Returns a dict of section_name -> 0-indexed start page.
    """
    import re
    patterns = {
        "ceo_report":   r"chief executive[^\n]{0,60}?(\d{1,3})\b",
        "finance":      r"finance report[^\n]{0,60}?(\d{1,3})\b",
        "performance":  r"(?:integrated performance|ipr|performance report)[^\n]{0,60}?(\d{1,3})\b",
        "quality":      r"quality[^\n]{0,60}?(\d{1,3})\b",
        "workforce":    r"(?:people committee|workforce)[^\n]{0,60}?(\d{1,3})\b",
    }
    sections = {}
    for name, pattern in patterns.items():
        match = re.search(pattern, agenda_text.lower())
        if match:
            page_num = int(match.group(1))
            if 3 <= page_num <= total_pages:
                sections[name] = page_num - 1  # convert to 0-indexed
    return sections


def extract_targeted_text(pdf_paths: list[str]) -> dict[str, str]:
    """
    Extract targeted sections from one or more PDFs.
    Returns a dict of section_name -> extracted text.
    """
    all_sections: dict[str, str] = {}

    for pdf_path in pdf_paths:
        label = os.path.basename(pdf_path)
        print(f"  Reading: {label}")

        try:
            pdf = pdfium.PdfDocument(pdf_path)
        except Exception as e:
            print(f"  Could not open PDF: {e}")
            continue

        total = len(pdf)
        print(f"  Pages: {total}")

        # Always read the agenda first
        agenda = extract_pages(pdf, 0, min(6, total))
        all_sections[f"{label}__agenda"] = agenda

        # Try to navigate by agenda references
        sections = find_section_starts(agenda, total)

        if sections:
            print(f"  Sections found in agenda: {list(sections.keys())}")
            for section_name, start in sections.items():
                text = extract_pages(pdf, start, min(start + 30, total))
                all_sections[f"{label}__{section_name}"] = text
        else:
            # Fallback: read in thirds
            print("  No agenda page refs found — reading in thirds")
            chunk = max(20, total // 3)
            all_sections[f"{label}__part_1"] = extract_pages(pdf, 0, chunk)
            all_sections[f"{label}__part_2"] = extract_pages(pdf, chunk, chunk * 2)
            all_sections[f"{label}__part_3"] = extract_pages(pdf, chunk * 2, total)

    return all_sections


# ── Stage 5: Analyse with Claude ─────────────────────────────────────────────

def load_prompt(trust_name: str, board_papers_url: str, extracted_text: str) -> str:
    """Load and populate the prompt template."""
    template_path = Path(__file__).parent / "prompt_template.txt"
    if not template_path.exists():
        raise FileNotFoundError(f"prompt_template.txt not found at {template_path}")

    template = template_path.read_text(encoding="utf-8")
    return (
        template
        .replace("{{TRUST_NAME}}", trust_name)
        .replace("{{BOARD_PAPERS_URL}}", board_papers_url)
        .replace("{{EXTRACTED_TEXT}}", extracted_text)
    )


def analyse_with_claude(
    extracted: dict[str, str],
    trust_name: str,
    board_papers_url: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
) -> str:
    """Send extracted text to Claude and return the story leads."""
    client = anthropic.Anthropic(api_key=api_key)

    # Build combined text up to the character limit
    parts = []
    total_chars = 0
    for section, text in extracted.items():
        if not text.strip():
            continue
        header = f"\n\n=== {section.upper().replace('_', ' ')} ===\n"
        if total_chars + len(header) + len(text) > CHAR_LIMIT:
            print(f"  Character limit reached — skipping remaining sections")
            break
        parts.append(header + text)
        total_chars += len(header) + len(text)

    combined_text = "".join(parts)
    print(f"  Sending {total_chars:,} characters to {model}...")

    prompt = load_prompt(trust_name, board_papers_url, combined_text)

    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    usage = message.usage
    print(f"  Tokens: {usage.input_tokens:,} in / {usage.output_tokens:,} out")

    return message.content[0].text


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run(
    trust_name: str,
    api_key: str,
    manual_url: str = "",
    manual_pdf: str = "",
    model: str = DEFAULT_MODEL,
) -> str:
    print(f"\n{'=' * 60}")
    print(f"NHS Board Papers Analyser: {trust_name}")
    print(f"{'=' * 60}\n")

    save_dir = tempfile.mkdtemp(prefix="nhspapers_")

    # Step 1: Find board papers page
    board_papers_url = manual_url
    if not board_papers_url:
        print("Step 1: Searching for board papers page...")
        board_papers_url = find_board_papers_url(trust_name)
        if not board_papers_url:
            print("  Could not find automatically.")
            board_papers_url = input("  Please paste the board papers URL: ").strip()
    else:
        print(f"Step 1: Using provided URL: {board_papers_url}")

    # Step 2: Find PDF links (skip if PDF provided)
    pdf_paths = []
    pdf_url = ""

    if manual_pdf:
        print(f"\nStep 2: Using provided PDF: {manual_pdf}")
        pdf_paths = [manual_pdf]
        pdf_url = manual_pdf
    else:
        session = make_session(board_papers_url)

        print("\nStep 2: Fetching index page and finding document links...")
        links = get_document_links(session, board_papers_url)

        if links:
            print(f"  Found {len(links)} document link(s):")
            for i, link in enumerate(links[:12]):
                print(f"    [{i}] {link['text'][:60]}")
            pdf_url = pick_best_link(links)
            print(f"\n  Auto-selected: {pdf_url}")
            choice = input("  Press Enter to use this, or type a number to choose: ").strip()
            if choice.isdigit() and 0 <= int(choice) < len(links):
                pdf_url = links[int(choice)]["url"]
        else:
            print("  No document links found on index page.")
            pdf_url = input("  Please paste the direct PDF URL: ").strip()

        # Step 3: Download
        print(f"\nStep 3: Downloading...")
        data = download_file(session, pdf_url, board_papers_url)

        if data is None:
            print("""
Sorry this site blocks automated downloads - if you like you can manually
upload a board paper PDF to the file panel on the left, and I will process it.
""")
            manual_path = input("  Path to downloaded PDF (or Enter to exit): ").strip()
            if not manual_path:
                sys.exit(0)
            pdf_paths = [manual_path]
        else:
            pdf_paths = save_and_unpack(data, save_dir)

    if not pdf_paths:
        print("No PDFs to process.")
        sys.exit(1)

    # Step 4: Extract text
    print(f"\nStep 4: Extracting text from {len(pdf_paths)} PDF(s)...")
    extracted = extract_targeted_text(pdf_paths)
    print(f"  Extracted {len(extracted)} section(s)")

    # Step 5: Analyse
    print("\nStep 5: Analysing with Claude...")
    results = analyse_with_claude(extracted, trust_name, board_papers_url, api_key, model)

    # Output
    print(f"\n{'=' * 60}")
    print("STORY LEADS")
    print(f"{'=' * 60}\n")
    print(results)

    output_path = Path(save_dir) / f"{trust_name.replace(' ', '_')}_leads.md"
    output_path.write_text(results, encoding="utf-8")
    print(f"\n(Saved to: {output_path})")

    return results


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Analyse NHS board papers with Claude AI"
    )
    parser.add_argument("trust_name", help="Name of the NHS trust or ICB")
    parser.add_argument("--api-key", help="Anthropic API key (or set ANTHROPIC_API_KEY)")
    parser.add_argument("--url", default="", help="Board papers index URL (skips search)")
    parser.add_argument("--pdf", default="", help="Path to local PDF (skips download)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Claude model to use (default: {DEFAULT_MODEL})")

    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("Error: No API key. Use --api-key or set ANTHROPIC_API_KEY.")
        sys.exit(1)

    run(args.trust_name, api_key, manual_url=args.url, manual_pdf=args.pdf, model=args.model)
