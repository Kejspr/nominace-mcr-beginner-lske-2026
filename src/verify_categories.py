#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kontrola nominacnich souboru klubu proti aggregated-results.xml.

Spusteni:
    python3 verify_categories.py
"""

import sys
from pathlib import Path

from config import AGGREGATED_XML
from nomination_io import load_nominations


def main() -> int:
    if not AGGREGATED_XML.is_file():
        print(f"Chyba: {AGGREGATED_XML} neexistuje. Spust nejprve aggregate.")
        return 1

    result = load_nominations(AGGREGATED_XML, write_log=True)
    stats = result.stats

    print("")
    print("=" * 60)
    print("KONTROLA NOMINACI")
    print("=" * 60)
    print(f"  OK:                 {stats.get('ok', 0)}")
    print(f"  chyby:              {stats.get('errors', 0)}")
    print(f"    jmeno nenalezeno: {stats.get('name_not_found', 0)}")
    print(f"    spatna kategorie: {stats.get('wrong_category', 0)}")
    print(f"    nejednoznacne:    {stats.get('ambiguous_category', 0)}")
    print(f"    spatny klub:      {stats.get('wrong_club', 0)}")
    if result.log_path:
        print(f"\nLog: {result.log_path}")
    print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
