"""Build CSV and XLSX derivatives from the four JSON canonicals in this repo.

Canonical files (all live at the repo root):
    trust_urls.json          icb_urls.json
    trust-contacts.json      icb-contacts.json

For each canonical, generates two derivatives next to it:
    <stem>.csv               flattened CSV (arrays joined by ';', nulls -> empty string)
    <stem>.xlsx              same data as a single-sheet Excel file with frozen header

Run from anywhere; finds the repo root by file location.

Usage:
    py scripts/build_derivatives.py            # build into the same folder as the canonicals
    py scripts/build_derivatives.py <out_dir>  # build into a different folder
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
except ImportError:
    print("ERROR: openpyxl not installed. `pip install --user openpyxl`", file=sys.stderr)
    sys.exit(1)

REPO = Path(__file__).resolve().parent.parent
DATASETS = ["trust_urls", "icb_urls", "trust-contacts", "icb-contacts"]


def _flatten(entry: dict) -> dict:
    """Convert one JSON entry to a flat dict for CSV/XLSX.

    Arrays become semicolon-joined strings. Nulls become empty strings.
    For the URL files, the `names` array is split: first goes to `name`,
    rest to `alt_names`.
    """
    out = {}
    for k, v in entry.items():
        if k == "names":
            names = list(v or [])
            out["name"] = names[0] if names else ""
            out["alt_names"] = ";".join(names[1:])
            continue
        if isinstance(v, list):
            out[k] = ";".join(str(x) for x in v)
        elif v is None:
            out[k] = ""
        else:
            out[k] = v
    return out


def _column_union(rows: list[dict]) -> list[str]:
    """Build an ordered union of all keys seen across rows (preserves first-seen order)."""
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    return cols


def _write_csv(rows: list[dict], cols: list[str], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, quoting=csv.QUOTE_MINIMAL, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_xlsx(rows: list[dict], cols: list[str], path: Path, sheet_name: str) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name[:31]  # Excel sheet name 31-char limit

    # Header row
    bold = Font(bold=True)
    for col_idx, col_name in enumerate(cols, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = bold

    # Data rows
    for row_idx, r in enumerate(rows, start=2):
        for col_idx, col_name in enumerate(cols, start=1):
            ws.cell(row=row_idx, column=col_idx, value=r.get(col_name, ""))

    # Freeze the header
    ws.freeze_panes = "A2"

    # Auto-size columns (capped at 60 chars to keep things readable)
    for col_idx, col_name in enumerate(cols, start=1):
        max_len = len(col_name)
        for r in rows:
            v = r.get(col_name, "")
            if v is not None:
                max_len = max(max_len, min(len(str(v)), 60))
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 2, 60)

    wb.save(path)


def build_one(stem: str, src_root: Path, out_root: Path) -> int:
    src = src_root / f"{stem}.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    rows = [_flatten(e) for e in data]
    cols = _column_union(rows)

    out_root.mkdir(parents=True, exist_ok=True)
    _write_csv(rows, cols, out_root / f"{stem}.csv")
    _write_xlsx(rows, cols, out_root / f"{stem}.xlsx", sheet_name=stem)
    return len(data)


def main() -> int:
    out_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else REPO
    print(f"Source canonicals: {REPO}")
    print(f"Output:           {out_root}")
    print()
    for stem in DATASETS:
        n = build_one(stem, REPO, out_root)
        print(f"  {stem}: {n} entries  ->  {stem}.csv + {stem}.xlsx")
    return 0


if __name__ == "__main__":
    sys.exit(main())
