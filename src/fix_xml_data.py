#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Oprava dat v XML vysledcich LSKe.

Originalni soubory v 'original/' (libovolny nazev) zustanou beze zmeny.
Do 'pracovni/' se zapisou opravene kopie s jednotnym pojmenovanim:
  results-1-kolo-{slug}.xml, results-2-kolo-{slug}.xml, ...
Cislo kola se urci podle <date> v XML (casove razeni).

Existujici spravne soubory v pracovni/ se neprepisuji.

Cesty: config.py

Spusteni:
    python3 fix_xml_data.py
    make fix
"""

import io
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from config import CLUB_NAME_MAP, FIX_LOG_PREFIX, ORIGINAL_DIR, WORKING_DIR
from utils import assign_working_files, list_tournament_xml_files, names_are_swapped, normalizuj, normalize_club


def xml_text(element, tag: str) -> str:
    child = element.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def build_canonical_competitor_names(source_files: list[Path]) -> dict[str, tuple[str, str]]:
    counts: dict[str, Counter] = defaultdict(Counter)
    for path in source_files:
        root = ET.parse(path).getroot()
        for result in root.findall(".//result"):
            competitor_id = xml_text(result, "competitor_id")
            firstname = xml_text(result, "firstname")
            lastname = xml_text(result, "lastname")
            if competitor_id and firstname and lastname:
                counts[competitor_id][(firstname, lastname)] += 1

    canonical: dict[str, tuple[str, str]] = {}
    for competitor_id, counter in counts.items():
        if counter:
            canonical[competitor_id] = counter.most_common(1)[0][0]
    return canonical


def build_canonical_name_orders(source_files: list[Path]) -> dict[tuple[str, frozenset[str]], tuple[str, str]]:
    """Nejcastejsi poradi jmena/prijmeni pro stejny klub a stejnou dvojici slov."""
    counts: dict[tuple[str, frozenset[str]], Counter] = defaultdict(Counter)
    for path in source_files:
        root = ET.parse(path).getroot()
        for result in root.findall(".//result"):
            firstname = xml_text(result, "firstname")
            lastname = xml_text(result, "lastname")
            club = normalize_club(xml_text(result, "club"))
            if not firstname or not lastname or not club:
                continue
            tokens = frozenset({normalizuj(firstname), normalizuj(lastname)})
            if len(tokens) < 2:
                continue
            key = (normalizuj(club), tokens)
            counts[key][(firstname, lastname)] += 1

    canonical: dict[tuple[str, frozenset[str]], tuple[str, str]] = {}
    for key, counter in counts.items():
        if len(counter) > 1:
            canonical[key] = counter.most_common(1)[0][0]
    return canonical


def fix_weight_format(text: str) -> str:
    if not text:
        return text
    return re.sub(r"([+-])(\d+)(kg)", r"\1\2 kg", text)


def tree_to_bytes(tree: ET.ElementTree) -> bytes:
    ET.indent(tree, space="\t")
    buffer = io.BytesIO()
    tree.write(buffer, encoding="utf-8", xml_declaration=True)
    return buffer.getvalue()


def normalize_xml_bytes(data: bytes) -> bytes:
    root = ET.fromstring(data)
    return tree_to_bytes(ET.ElementTree(root))


def apply_fixes(
    tree: ET.ElementTree,
    canonical_names: dict[str, tuple[str, str]],
    token_canonical: dict[tuple[str, frozenset[str]], tuple[str, str]],
) -> tuple[dict, list[str], bool]:
    stats = {"clubs": 0, "categories": 0, "names": 0}
    changes: list[str] = []
    modified = False
    root = tree.getroot()

    def fix_name_order(
        firstname_elem,
        lastname_elem,
        firstname: str,
        lastname: str,
        canon_first: str,
        canon_last: str,
        reason: str,
    ) -> None:
        nonlocal modified
        message = (
            f"  jmeno: '{firstname} {lastname}' -> '{canon_first} {canon_last}' "
            f"({reason})"
        )
        changes.append(message)
        firstname_elem.text = canon_first
        lastname_elem.text = canon_last
        stats["names"] += 1
        modified = True

    for category in root.findall("category"):
        weight_elem = category.find("kategorie2")
        if weight_elem is not None and weight_elem.text:
            fixed = fix_weight_format(weight_elem.text.strip())
            if fixed != weight_elem.text.strip():
                message = f"  kategorie: '{weight_elem.text.strip()}' -> '{fixed}'"
                changes.append(message)
                weight_elem.text = fixed
                stats["categories"] += 1
                modified = True

        for result in category.findall("result"):
            club_elem = result.find("club")
            club_text = ""
            if club_elem is not None and club_elem.text:
                original = club_elem.text.strip()
                club_text = original
                if original in CLUB_NAME_MAP:
                    updated = CLUB_NAME_MAP[original]
                    if original != updated:
                        message = f"  klub: '{original}' -> '{updated}'"
                        changes.append(message)
                        club_elem.text = updated
                        club_text = updated
                        stats["clubs"] += 1
                        modified = True

            competitor_id = xml_text(result, "competitor_id")
            firstname_elem = result.find("firstname")
            lastname_elem = result.find("lastname")
            if firstname_elem is None or lastname_elem is None:
                continue

            firstname = (firstname_elem.text or "").strip()
            lastname = (lastname_elem.text or "").strip()
            if not firstname or not lastname:
                continue

            canon_first, canon_last = None, None
            reason = ""

            club_for_token = normalize_club(club_text) if club_text else ""
            if club_for_token:
                tokens = frozenset({normalizuj(firstname), normalizuj(lastname)})
                token_key = (normalizuj(club_for_token), tokens)
                canonical = token_canonical.get(token_key)
                if canonical and names_are_swapped(firstname, lastname, canonical[0], canonical[1]):
                    canon_first, canon_last = canonical
                    reason = f"klub {club_for_token}"

            if not canon_first and competitor_id:
                canonical = canonical_names.get(competitor_id)
                if canonical and names_are_swapped(firstname, lastname, canonical[0], canonical[1]):
                    canon_first, canon_last = canonical
                    reason = f"ID {competitor_id}"

            if not canon_first:
                continue
            if (firstname, lastname) == (canon_first, canon_last):
                continue

            fix_name_order(
                firstname_elem,
                lastname_elem,
                firstname,
                lastname,
                canon_first,
                canon_last,
                reason,
            )

    return stats, changes, modified


def build_fixed_bytes(
    source_path: Path,
    canonical_names: dict[str, tuple[str, str]],
    token_canonical: dict[tuple[str, frozenset[str]], tuple[str, str]],
) -> tuple[bytes, dict, list[str], bool]:
    tree = ET.parse(source_path)
    stats, changes, modified = apply_fixes(tree, canonical_names, token_canonical)
    return tree_to_bytes(tree), stats, changes, modified


def working_file_is_current(
    source_path: Path,
    target_path: Path,
    canonical_names: dict[str, tuple[str, str]],
    token_canonical: dict[tuple[str, frozenset[str]], tuple[str, str]],
) -> bool:
    if not target_path.is_file():
        return False
    try:
        expected = build_fixed_bytes(source_path, canonical_names, token_canonical)[0]
        existing = normalize_xml_bytes(target_path.read_bytes())
        return existing == expected
    except Exception:
        return False


def fix_xml_file(
    source_path: Path,
    target_path: Path,
    canonical_names: dict[str, tuple[str, str]],
    token_canonical: dict[tuple[str, frozenset[str]], tuple[str, str]],
) -> tuple[dict, list[str]]:
    stats = {"clubs": 0, "categories": 0, "names": 0, "skipped": 0}

    try:
        if working_file_is_current(source_path, target_path, canonical_names, token_canonical):
            message = f"  Preskoceno: {target_path.name} je aktualni"
            print(message)
            stats["skipped"] = 1
            return stats, [message]

        expected_bytes, fix_stats, changes, modified = build_fixed_bytes(
            source_path,
            canonical_names,
            token_canonical,
        )
        stats["clubs"] = fix_stats["clubs"]
        stats["categories"] = fix_stats["categories"]
        stats["names"] = fix_stats["names"]

        for message in changes:
            print(message)

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(expected_bytes)

        if modified:
            print(f"  Ulozeno (opraveno): {target_path.parent.name}/{target_path.name}")
        else:
            print(f"  Ulozeno (bez zmen v datech): {target_path.parent.name}/{target_path.name}")

    except Exception as exc:
        message = f"  Chyba pri zpracovani {source_path.name}: {exc}"
        print(message)
        changes = [message]
        return stats, changes

    return stats, changes


def cleanup_working_tournament_files(keep_targets: set[Path]) -> list[Path]:
    removed = []
    for path in list_tournament_xml_files(WORKING_DIR):
        if path not in keep_targets and path.exists():
            path.unlink()
            removed.append(path)
    return removed


def main() -> None:
    started_at = datetime.now()

    if not ORIGINAL_DIR.exists():
        print(f"Slozka {ORIGINAL_DIR.name}/ neexistuje.")
        return

    source_files = list_tournament_xml_files(ORIGINAL_DIR)
    if not source_files:
        print(f"Zadne turnajove XML v {ORIGINAL_DIR.name}/")
        return

    WORKING_DIR.mkdir(exist_ok=True)
    assignments = assign_working_files(source_files, WORKING_DIR)
    canonical_names = build_canonical_competitor_names(source_files)
    token_canonical = build_canonical_name_orders(source_files)

    print(f"Pracovni kopie -> {WORKING_DIR.name}/")
    print(f"Originalni soubory v {ORIGINAL_DIR.name}/ zustanou BEZE ZMENY.\n")

    print("Mapovani souboru (kolo dle data v XML):")
    for item in assignments:
        date_info = item.round_date or "bez data"
        print(
            f"  {item.round_label} ({date_info}): "
            f"{ORIGINAL_DIR.name}/{item.source.name} -> {WORKING_DIR.name}/{item.target.name}"
        )
    print()

    keep_targets = {item.target for item in assignments}
    removed = cleanup_working_tournament_files(keep_targets)
    if removed:
        print("Odstraneny stare pracovni soubory:")
        for path in removed:
            print(f"  - {path.name}")
        print()

    totals = {"clubs": 0, "categories": 0, "names": 0, "skipped": 0, "written": 0}
    log_lines = [
        "Mapovani souboru:",
        *[
            f"  {item.round_label} ({item.round_date or 'bez data'}): "
            f"{item.source.name} -> {item.target.name}"
            for item in assignments
        ],
        "",
    ]

    for item in assignments:
        header = (
            f"\n{item.source.name} -> {item.target.name} "
            f"({item.round_label}, {item.round_date or 'bez data'})"
        )
        separator = "-" * min(len(header) - 1, 70)
        print(header)
        print(separator)
        log_lines.extend([header, separator])

        stats, changes = fix_xml_file(item.source, item.target, canonical_names, token_canonical)
        log_lines.extend(changes)

        if stats["skipped"]:
            log_lines.append("  SKIP - pracovni soubor je aktualni")
        elif stats["clubs"] == 0 and stats["categories"] == 0 and stats["names"] == 0:
            print("  Zadne zmeny v datech")
            log_lines.append("  OK - zadne zmeny v datech")

        if stats["skipped"]:
            summary = f"  -> Preskoceno (aktualni)"
        else:
            summary = (
                f"  -> Opraveno: {stats['clubs']} klubu, "
                f"{stats['categories']} kategorii, {stats['names']} jmen"
            )
            totals["written"] += 1
        log_lines.append(summary)
        print(summary)

        totals["clubs"] += stats["clubs"]
        totals["categories"] += stats["categories"]
        totals["names"] += stats["names"]
        totals["skipped"] += stats["skipped"]

    summary_lines = [
        "",
        "=" * 50,
        "SOUHRN",
        "=" * 50,
        f"  Pocet kol:           {len(assignments)}",
        f"  Zapsano:             {totals['written']}",
        f"  Preskoceno:          {totals['skipped']}",
        f"  Opraveno klubu:      {totals['clubs']}",
        f"  Opraveno kategorii:  {totals['categories']}",
        f"  Opraveno jmen:       {totals['names']}",
    ]
    for line in summary_lines:
        print(line)
    log_lines.extend(summary_lines)

    print(f"\n  -> Pracovni soubory jsou v: {WORKING_DIR.name}/")
    print("  -> Spust python3 aggregate_results.py nebo: make aggregate")

    log_name = f"{FIX_LOG_PREFIX}-{started_at.strftime('%Y%m%d-%H%M%S')}.txt"
    log_path = WORKING_DIR / log_name
    log_header = [
        f"LOG OPRAV — {started_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Zpracovano souboru: {len(assignments)}",
        "=" * 50,
    ]
    log_path.write_text("\n".join(log_header + log_lines) + "\n", encoding="utf-8")
    print(f"\n  Log ulozen: {WORKING_DIR.name}/{log_name}")


if __name__ == "__main__":
    main()
