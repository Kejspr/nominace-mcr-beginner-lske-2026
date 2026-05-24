#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vygeneruje / doplni config/trainers.yaml ze vsech klubu v aggregated-results.xml."""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
TRAINERS_PATH = ROOT / "config" / "trainers.yaml"
AGGREGATED_XML = ROOT / "aggregated-results.xml"

sys.path.insert(0, str(ROOT / "tools"))
from sync_trainers import load_trainers  # noqa: E402


def clubs_from_xml(path: Path) -> List[str]:
    root = ET.parse(path).getroot()
    clubs = {
        (result.findtext("club") or "").strip()
        for category in root.findall("category")
        for result in category.findall("result")
    }
    return sorted(club for club in clubs if club)


def load_existing_passwords(path: Path) -> Dict[str, str]:
    if not path.is_file():
        return {}
    passwords: Dict[str, str] = {}
    for entry in load_trainers(path):
        role = str(entry.get("role", "trener")).strip().lower()
        club = str(entry.get("club", "")).strip()
        password = entry.get("password")
        if role == "trener" and club and password is not None:
            passwords[club] = str(password)
    return passwords


def load_stk_entry(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    for entry in load_trainers(path):
        if str(entry.get("role", "")).strip().lower() == "stk":
            return dict(entry)
    return None


def yaml_line(key: str, value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'    {key}: "{escaped}"'


def write_trainers_yaml(
    path: Path,
    stk: Dict[str, Any],
    clubs: List[str],
    club_passwords: Dict[str, str],
    default_password: str,
) -> None:
    lines = [
        "# Lokalne, mimo git. Sync: make sync-trainers",
        "#",
        "# Prihlaseni: STK nebo klub + heslo (e-mail neni potreba).",
        "# E-mail je volitelny jen pro Cloudflare Access (CLOUDFLARE_SYNC=true).",
        "#",
        "trainers:",
        "  - role: stk",
        f'    password: "{stk.get("password", "heslo-stk")}"',
    ]
    stk_email = str(stk.get("email", "")).strip()
    if stk_email:
        lines.append(yaml_line("email", stk_email))

    for club in clubs:
        password = club_passwords.get(club, default_password)
        lines.extend(
            [
                "",
                "  - role: trener",
                yaml_line("club", club),
                f'    password: "{password.replace(chr(34), "")}"',
            ]
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Doplni trainers.yaml o vsechny kluby z XML")
    parser.add_argument(
        "--trainers",
        type=Path,
        default=TRAINERS_PATH,
        help=f"Vystup (default: {TRAINERS_PATH})",
    )
    parser.add_argument(
        "--xml",
        type=Path,
        default=AGGREGATED_XML,
        help=f"Zdroj klubu (default: {AGGREGATED_XML})",
    )
    parser.add_argument(
        "--default-password",
        default="heslo-klubu",
        help="Vychozi heslo pro novy klub (default: heslo-klubu)",
    )
    parser.add_argument(
        "--stk-password",
        default=None,
        help="Heslo STK (default: z existujiciho trainers.yaml nebo heslo-stk)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.xml.is_file():
        print(f"Chyba: {args.xml} neexistuje, spust make aggregate", file=sys.stderr)
        return 1

    clubs = clubs_from_xml(args.xml)
    if not clubs:
        print("Chyba: v XML nejsou zadne kluby", file=sys.stderr)
        return 1

    existing_stk = load_stk_entry(args.trainers) or {}
    stk_password = args.stk_password or str(existing_stk.get("password", "heslo-stk"))
    stk = {"password": stk_password}
    if existing_stk.get("email"):
        stk["email"] = existing_stk["email"]

    club_passwords = load_existing_passwords(args.trainers)
    write_trainers_yaml(args.trainers, stk, clubs, club_passwords, args.default_password)

    print(f"Zapsano: {args.trainers} ({len(clubs)} klubu + STK)")
    for club in clubs:
        pw = club_passwords.get(club, args.default_password)
        tag = "" if club in club_passwords else " (nove)"
        print(f"  - {club}{tag}")
    print("Dalsi krok: make sync-trainers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
