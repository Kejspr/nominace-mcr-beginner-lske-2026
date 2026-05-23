#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kontrola kvality dat v XML vysledcich LSKe.

Spusteni:
    python3 validate_data.py
    python3 validate_data.py /cesta/k/xml

Vychozi adresar: original/ (viz config.py)
"""

import sys
from collections import defaultdict
from pathlib import Path

from config import ORIGINAL_DIR
from utils import clubs_equivalent, levenshtein, nacti_vsechny_xml, names_are_swapped, normalizuj, normalize_club


def check_athlete_names(athletes: list) -> int:
    print("=" * 60)
    print("KONTROLA JMEN ZAVODNIKU")
    print("=" * 60)

    issues = 0

    print("\n-- Jmena stejna bez diakritiky, ruzny original --")
    by_normalized = defaultdict(list)
    for athlete in athletes:
        key = f"{normalizuj(athlete.jmeno)} {normalizuj(athlete.prijmeni)}"
        by_normalized[key].append(athlete)

    diacritics_conflicts = {
        key: values for key, values in by_normalized.items()
        if len({(item.jmeno, item.prijmeni) for item in values}) > 1
    }

    if diacritics_conflicts:
        for norm, variants in sorted(diacritics_conflicts.items()):
            unique_names = {(item.jmeno, item.prijmeni) for item in variants}
            print(f"\n  {norm}")
            for jmeno, prijmeni in sorted(unique_names):
                files = [
                    item.soubor for item in variants
                    if item.jmeno == jmeno and item.prijmeni == prijmeni
                ]
                print(f"     -> \"{jmeno} {prijmeni}\" ({', '.join(sorted(set(files)))})")
            issues += 1
    else:
        print("  Zadne nesrovnalosti")

    print("\n-- Velmi podobna jmena (rozdil 1 znak) --")
    unique_athletes = list({(item.jmeno, item.prijmeni): item for item in athletes}.values())
    suspicious = []

    for i, first in enumerate(unique_athletes):
        for second in unique_athletes[i + 1:]:
            first_name_norm = normalizuj(first.jmeno)
            last_name_norm = normalizuj(first.prijmeni)
            second_name_norm = normalizuj(second.jmeno)
            second_last_name_norm = normalizuj(second.prijmeni)
            first_name_distance = levenshtein(first_name_norm, second_name_norm)
            last_name_distance = levenshtein(last_name_norm, second_last_name_norm)

            if (first_name_distance == 1 and last_name_norm == second_last_name_norm) or (
                last_name_distance == 1 and first_name_norm == second_name_norm
            ):
                suspicious.append((first, second, first_name_distance, last_name_distance))

    if suspicious:
        for first, second, first_name_distance, last_name_distance in suspicious:
            where = "jmenu" if first_name_distance == 1 else "prijmeni"
            print(f"\n  Rozdil 1 znak ve {where}:")
            print(f"     -> \"{first.cele_jmeno}\" (ID: {first.competitor_id}, {first.soubor})")
            print(f"     -> \"{second.cele_jmeno}\" (ID: {second.competitor_id}, {second.soubor})")
            issues += 1
    else:
        print("  Zadne podezrele pary")

    print(f"\n-> Celkem problemu se jmeny: {issues}\n")
    return issues


def check_swapped_names(athletes: list) -> int:
    print("=" * 60)
    print("KONTROLA PROHOZENYCH JMEN / PRIJMENI")
    print("=" * 60)

    issues = 0

    print("\n-- Stejne competitor_id, ruzne poradi jmena --")
    by_id: dict[str, dict[tuple[str, str], set[str]]] = defaultdict(lambda: defaultdict(set))
    for athlete in athletes:
        if not athlete.competitor_id:
            continue
        by_id[athlete.competitor_id][(athlete.jmeno, athlete.prijmeni)].add(athlete.soubor)

    id_conflicts = {
        competitor_id: variants
        for competitor_id, variants in by_id.items()
        if len(variants) > 1
    }

    if id_conflicts:
        for competitor_id, variants in sorted(id_conflicts.items(), key=lambda item: item[0]):
            print(f"\n  ID {competitor_id}:")
            for (jmeno, prijmeni), files in sorted(variants.items()):
                print(f"     -> \"{jmeno} {prijmeni}\" ({', '.join(sorted(files))})")
            issues += 1
    else:
        print("  Zadne nesrovnalosti")

    print("\n-- Prohozene jmeno/prijmeni (stejny klub, stejne ID slova) --")
    seen_pairs: set[tuple[str, str, str]] = set()
    swapped_pairs = []

    for i, first in enumerate(athletes):
        for second in athletes[i + 1:]:
            if not clubs_equivalent(first.club, second.club):
                continue
            if not names_are_swapped(first.jmeno, first.prijmeni, second.jmeno, second.prijmeni):
                continue

            pair_key = (
                normalizuj(normalize_club(first.club)),
                normalizuj(first.jmeno),
                normalizuj(first.prijmeni),
            )
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            swapped_pairs.append((first, second))

    if swapped_pairs:
        for first, second in swapped_pairs:
            print(f"\n  Klub: {normalize_club(first.club)}")
            print(f"     -> \"{first.cele_jmeno}\" (ID: {first.competitor_id}, {first.soubor})")
            print(f"     -> \"{second.cele_jmeno}\" (ID: {second.competitor_id}, {second.soubor})")
            issues += 1
    else:
        print("  Zadne prohozene pary")

    print(f"\n-> Celkem problemu s prohozenymi jmeny: {issues}\n")
    return issues


def check_club_names(athletes: list) -> int:
    print("=" * 60)
    print("KONTROLA NAZVU KLUBU")
    print("=" * 60)

    issues = 0
    clubs: dict[str, dict] = {}

    for athlete in athletes:
        if not athlete.club:
            continue
        if athlete.club not in clubs:
            clubs[athlete.club] = {"ids": set(), "files": set(), "count": 0}
        clubs[athlete.club]["ids"].add(athlete.club_id)
        clubs[athlete.club]["files"].add(athlete.soubor)
        clubs[athlete.club]["count"] += 1

    print(f"\nUnikatnich klubu: {len(clubs)}")
    for idx, (name, data) in enumerate(sorted(clubs.items()), 1):
        ids = sorted(data["ids"])
        ids_text = ids[0] if len(ids) == 1 else ids
        print(f"  {idx:2d}. {name}  (ID: {ids_text}, {data['count']}x)")

    print("\n-- Kluby stejne bez diakritiky, ruzny original --")
    normalized_clubs = defaultdict(list)
    for name in clubs:
        normalized_clubs[normalizuj(name)].append(name)

    diacritics_conflicts = {key: values for key, values in normalized_clubs.items() if len(values) > 1}
    if diacritics_conflicts:
        for norm, variants in sorted(diacritics_conflicts.items()):
            print(f"\n  {norm}")
            for variant in variants:
                print(f"     -> \"{variant}\"  (ID: {sorted(clubs[variant]['ids'])}, {clubs[variant]['count']}x)")
            issues += 1
    else:
        print("  Zadne nesrovnalosti")

    print("\n-- Podobne kluby (rozdil <= 3 znaky) --")
    club_names = list(clubs.keys())
    similar = []
    for i, first in enumerate(club_names):
        for second in club_names[i + 1:]:
            distance = levenshtein(normalizuj(first), normalizuj(second))
            if 0 < distance <= 3:
                similar.append((first, second, distance))

    if similar:
        for first, second, distance in sorted(similar, key=lambda item: item[2]):
            print(f"\n  Rozdil {distance} znak(y):")
            print(f"     -> \"{first}\"  ({clubs[first]['count']}x)")
            print(f"     -> \"{second}\"  ({clubs[second]['count']}x)")
            issues += 1
    else:
        print("  Zadne podobne kluby")

    print("\n-- Kluby s vice ID --")
    multiple_ids = {name: data for name, data in clubs.items() if len(data["ids"]) > 1}
    if multiple_ids:
        for name, data in sorted(multiple_ids.items()):
            print(f"  \"{name}\"  ID: {sorted(data['ids'])}")
            issues += 1
    else:
        print("  Zadne kluby s vice ID")

    print(f"\n-> Celkem problemu s kluby: {issues}\n")
    return issues


def main() -> None:
    if len(sys.argv) > 1:
        directory = Path(sys.argv[1])
    else:
        directory = ORIGINAL_DIR

    athletes = nacti_vsechny_xml(directory)
    if not athletes:
        return

    name_issues = check_athlete_names(athletes)
    swapped_issues = check_swapped_names(athletes)
    club_issues = check_club_names(athletes)

    print("=" * 60)
    print("SOUHRN")
    print("=" * 60)
    total = name_issues + swapped_issues + club_issues
    if total == 0:
        print("Data jsou cista, zadne problemy nenalezeny.")
    else:
        print(
            f"Nalezeno {total} problemu "
            f"({name_issues} jmena, {swapped_issues} prohozena jmena, {club_issues} kluby)."
        )
        print("Spust python3 fix_xml_data.py pro opravu dat.")


if __name__ == "__main__":
    main()
