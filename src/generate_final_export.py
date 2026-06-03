#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Export konecneho seznamu postupujicich po ukonceni nominaci.

Vstup:  results-for-excel.csv (spust nejprve make excel)
Vystup: final-postupujici.csv, .tsv, .txt, .html

CSV lze otevrit v Excelu. HTML v prohlizeci: Tisk -> Ulozit jako PDF.

Spusteni:
    python3 src/generate_final_export.py
    make final-export
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import List

from config import (
    EXCEL_CSV,
    FINAL_EXPORT_CSV,
    FINAL_EXPORT_HTML,
    FINAL_EXPORT_TITLE,
    FINAL_EXPORT_TSV,
    FINAL_EXPORT_TXT,
)
from generate_presentation import category_sort_key_from_display, load_csv_rows
from qualification import is_ano_value


EXPORT_COLUMNS = [
    "Kategorie",
    "Jmeno",
    "Prijmeni",
    "Klub",
]


def escape_html(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def filter_postupujici(header: List[str], rows: List[dict]) -> List[dict]:
    filtered: List[dict] = []
    for row in rows:
        postupuje = row.get("Postupuje", "NE")
        if not is_ano_value(postupuje):
            continue
        filtered.append({
            "_sort_poradi": row.get("Pořadí", row.get("Poradi", "")),
            "Kategorie": row.get("Kategorie", ""),
            "Jmeno": row.get("Jméno", row.get("Jmeno", "")),
            "Prijmeni": row.get("Příjmení", row.get("Prijmeni", "")),
            "Klub": row.get("Klub", ""),
        })
    filtered.sort(
        key=lambda row: (
            category_sort_key_from_display(row["Kategorie"]),
            int(str(row["_sort_poradi"]).replace(".", "") or "9999"),
            row["Prijmeni"],
            row["Jmeno"],
        )
    )
    for row in filtered:
        row.pop("_sort_poradi", None)
    return filtered


def write_delimited(rows: List[dict], output_path: Path, delimiter: str) -> None:
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPORT_COLUMNS, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


def write_csv(rows: List[dict], output_path: Path) -> None:
    write_delimited(rows, output_path, ";")


def write_tsv(rows: List[dict], output_path: Path) -> None:
    write_delimited(rows, output_path, "\t")


def write_txt(rows: List[dict], output_path: Path, generated_at: str) -> None:
    by_category: OrderedDict[str, List[dict]] = OrderedDict()
    for row in rows:
        by_category.setdefault(row["Kategorie"], []).append(row)

    lines = [
        FINAL_EXPORT_TITLE,
        f"Vygenerovano: {generated_at}",
        f"Celkem postupujicich: {len(rows)} | Kategorii: {len(by_category)}",
        "",
    ]
    for category, category_rows in by_category.items():
        lines.append(f"=== {category} ({len(category_rows)}) ===")
        for row in category_rows:
            lines.append(f"  {row['Jmeno']} {row['Prijmeni']} - {row['Klub']}")
        lines.append("")

    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_html(rows: List[dict], output_path: Path, generated_at: str) -> None:
    by_category: OrderedDict[str, List[dict]] = OrderedDict()
    for row in rows:
        by_category.setdefault(row["Kategorie"], []).append(row)

    sections: List[str] = []
    for category, category_rows in by_category.items():
        body_rows = []
        for row in category_rows:
            body_rows.append(
                "<tr>"
                f"<td>{escape_html(row['Jmeno'])} {escape_html(row['Prijmeni'])}</td>"
                f"<td>{escape_html(row['Klub'])}</td>"
                "</tr>"
            )
        sections.append(
            f"<section class=\"category\">"
            f"<h2>{escape_html(category)} <span class=\"count\">({len(category_rows)})</span></h2>"
            "<table>"
            "<thead><tr>"
            "<th>Zavodnik</th><th>Klub</th>"
            "</tr></thead>"
            f"<tbody>{''.join(body_rows)}</tbody>"
            "</table>"
            "</section>"
        )

    html = f"""<!DOCTYPE html>
<html lang="cs">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape_html(FINAL_EXPORT_TITLE)}</title>
  <style>
    :root {{
      --text: #1a1a1a;
      --muted: #555;
      --line: #ddd;
      --accent: #0b5cab;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--text);
      margin: 0;
      padding: 24px;
      line-height: 1.4;
    }}
    header {{
      margin-bottom: 24px;
      border-bottom: 2px solid var(--accent);
      padding-bottom: 12px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 1.5rem;
    }}
    .meta {{
      color: var(--muted);
      font-size: 0.95rem;
    }}
    .summary {{
      margin-top: 8px;
      font-weight: 600;
    }}
    h2 {{
      margin: 0 0 8px;
      font-size: 1.05rem;
      color: var(--accent);
    }}
    .count {{
      color: var(--muted);
      font-weight: normal;
      font-size: 0.9rem;
    }}
    .category {{
      margin-bottom: 24px;
      break-inside: avoid;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.92rem;
    }}
    th, td {{
      border: 1px solid var(--line);
      padding: 6px 8px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: #f5f7fa;
    }}
    @media print {{
      body {{ padding: 12px; }}
      .category {{ page-break-inside: avoid; }}
      a {{ color: inherit; text-decoration: none; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{escape_html(FINAL_EXPORT_TITLE)}</h1>
    <div class="meta">Vygenerovano: {escape_html(generated_at)}</div>
    <div class="summary">Celkem postupujicich: {len(rows)} | Kategorii: {len(by_category)}</div>
  </header>
  {''.join(sections)}
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")


def generate_final_export(
    csv_path: Path,
    csv_out: Path,
    tsv_out: Path,
    txt_out: Path,
    html_out: Path,
) -> int:
    if not csv_path.is_file():
        print(f"Chyba: {csv_path} neexistuje, spust nejprve: make excel")
        return 1

    _header, rows = load_csv_rows(csv_path)
    filtered = filter_postupujici(_header, rows)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    write_csv(filtered, csv_out)
    write_tsv(filtered, tsv_out)
    write_txt(filtered, txt_out, generated_at)
    write_html(filtered, html_out, generated_at)

    print(f"CSV:  {csv_out}")
    print(f"TSV:  {tsv_out}")
    print(f"TXT:  {txt_out}")
    print(f"HTML: {html_out}")
    print(f"Postupujicich: {len(filtered)}")
    print("")
    print("Nejprehlednejsi: final-postupujici.txt")
    print("PDF: otevri HTML v prohlizeci -> Tisk -> Ulozit jako PDF")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export konecneho seznamu postupujicich (CSV, TSV, TXT, HTML)"
    )
    parser.add_argument("--input", type=Path, default=EXCEL_CSV, help="Vstupni results-for-excel.csv")
    parser.add_argument("--csv", type=Path, default=FINAL_EXPORT_CSV, help="Vystupni CSV")
    parser.add_argument("--tsv", type=Path, default=FINAL_EXPORT_TSV, help="Vystupni TSV")
    parser.add_argument("--txt", type=Path, default=FINAL_EXPORT_TXT, help="Vystupni TXT")
    parser.add_argument("--html", type=Path, default=FINAL_EXPORT_HTML, help="Vystupni HTML")
    args = parser.parse_args()
    return generate_final_export(args.input, args.csv, args.tsv, args.txt, args.html)


if __name__ == "__main__":
    sys.exit(main())
