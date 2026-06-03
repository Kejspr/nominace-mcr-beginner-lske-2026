#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agregace vysledku ze vsech kol Krajskeho poharu beginner LSKe.

Scita body ze vsech kol, spocita medaile a vytvori celkovy zebricek
v kazde kategorii.

Vstup:  pracovni/*.xml  (libovolny nazev, viz config.py)
Vystup: aggregated-results.xml  (viz config.py)

Spusteni:
    python3 aggregate_results.py
    python3 aggregate_results.py --output jiny_nazev.xml

Cesty: config.py
"""

import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from config import AGGREGATED_XML, BASE_DIR, TOURNAMENT_TITLE, WORKING_DIR
from nomination_io import ensure_nomination_files
from utils import clubs_equivalent, discover_rounds, list_tournament_xml_files, names_are_swapped


DISCIPLINE_ORDER = {
    "karate agility": 1,
    "kihon ido": 2,
    "kumite balloon": 3,
    "kata beginner": 4,
    "kumite beginner": 5,
}


def xml_text(element, tag: str) -> str:
    el = element.find(tag) if element is not None else None
    return (el.text or "").strip() if el is not None else ""


def parse_points(value: str) -> float:
    if not value:
        return 0.0
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return 0.0


def category_sort_key(category_key: tuple) -> tuple:
    disciplina, kategorie1, kategorie2 = category_key
    disc_order = DISCIPLINE_ORDER.get(disciplina.lower(), 999)

    kat1_lower = kategorie1.lower().strip()
    is_boys = any(x in kat1_lower for x in ("chlapci", "chlap"))
    is_girls = any(x in kat1_lower for x in ("divky", "dívky"))
    gender_order = 1 if is_boys else (2 if is_girls else 999)

    age_order = 999
    for idx, token in enumerate(("u8", "u10", "u12", "u14"), start=1):
        if token in kat1_lower:
            age_order = idx
            break

    weight_order = 0
    if kategorie2:
        kat2_lower = kategorie2.lower().strip()
        try:
            if "+" in kat2_lower:
                weight_order = int(kat2_lower.replace("+", "").replace("kg", "").strip())
            elif "-" in kat2_lower:
                weight_order = -int(kat2_lower.replace("-", "").replace("kg", "").strip())
        except ValueError:
            pass

    return (disc_order, age_order, gender_order, weight_order, kategorie1, kategorie2 or "")


def load_results_from_xml(path: Path) -> list[dict]:
    results = []
    try:
        root = ET.parse(path).getroot()
        tournament_id = xml_text(root, "id")
        tournament_date = xml_text(root, "date")
        tournament_name = xml_text(root, "name")

        for category in root.findall("category"):
            disciplina = xml_text(category, "disciplina")
            kategorie1 = xml_text(category, "kategorie1")
            kategorie2 = xml_text(category, "kategorie2")
            category_key = (disciplina, kategorie1, kategorie2)

            for result in category.findall("result"):
                results.append({
                    "tournament_id": tournament_id,
                    "tournament_date": tournament_date,
                    "tournament_name": tournament_name,
                    "disciplina": disciplina,
                    "kategorie1": kategorie1,
                    "kategorie2": kategorie2,
                    "category_key": category_key,
                    "competitor_id": xml_text(result, "competitor_id"),
                    "firstname": xml_text(result, "firstname"),
                    "lastname": xml_text(result, "lastname"),
                    "birthday": xml_text(result, "birthday"),
                    "club": xml_text(result, "club"),
                    "club_id": xml_text(result, "club_id"),
                    "points": parse_points(xml_text(result, "points")),
                    "position": xml_text(result, "position"),
                    "source_file": path.name,
                })
    except Exception as exc:
        print(f"  Chyba pri cteni {path.name}: {exc}")

    return results


def merge_duplicate_athletes(category_data: dict) -> None:
    def is_same_athlete(first1: str, last1: str, club1: str, data1: dict, first2: str, last2: str, club2: str, data2: dict) -> bool:
        if first1 == first2 and last1 == last2:
            return clubs_equivalent(club1, club2) or not club1 or not club2
        if names_are_swapped(first1, last1, first2, last2) and clubs_equivalent(club1, club2):
            return True
        if data1["competitor_ids"] & data2["competitor_ids"]:
            return True
        return False

    def merge_into(data1: dict, data2: dict) -> None:
        if len(data2["starts"]) > len(data1["starts"]):
            data1["firstname"] = data2["firstname"]
            data1["lastname"] = data2["lastname"]
            data1["birthday"] = data2["birthday"]
            data1["club"] = data2["club"] or data1["club"]
            data1["club_id"] = data2["club_id"] or data1["club_id"]
        data1["competitor_ids"].update(data2["competitor_ids"])
        data1["total_points"] += data2["total_points"]
        data1["gold_medals"] += data2["gold_medals"]
        data1["silver_medals"] += data2["silver_medals"]
        data1["bronze_medals"] += data2["bronze_medals"]
        data1["starts"].extend(data2["starts"])
        try:
            if int(data2["birthday"]) < int(data1["birthday"]):
                data1["birthday"] = data2["birthday"]
        except ValueError:
            pass

    for category_key in list(category_data.keys()):
        athletes = list(category_data[category_key].items())
        keys_to_remove = set()

        for i, (key1, data1) in enumerate(athletes):
            if key1 in keys_to_remove:
                continue

            first1, last1, _ = key1
            club1 = (data1["club"] or "").strip()

            for key2, data2 in athletes[i + 1:]:
                if key2 in keys_to_remove:
                    continue

                first2, last2, _ = key2
                club2 = (data2["club"] or "").strip()

                if is_same_athlete(first1, last1, club1, data1, first2, last2, club2, data2):
                    merge_into(data1, data2)
                    keys_to_remove.add(key2)

        for key in keys_to_remove:
            del category_data[category_key][key]


def build_aggregated_xml(all_results: list[dict], output_path: Path) -> dict:
    category_data = defaultdict(lambda: defaultdict(lambda: {
        "competitor_ids": set(),
        "firstname": "",
        "lastname": "",
        "birthday": "",
        "club": "",
        "club_id": "",
        "total_points": 0.0,
        "gold_medals": 0,
        "silver_medals": 0,
        "bronze_medals": 0,
        "starts": [],
    }))

    for row in all_results:
        category_key = row["category_key"]
        athlete_key = (
            row["firstname"].lower().strip(),
            row["lastname"].lower().strip(),
            row["birthday"],
        )
        athlete = category_data[category_key][athlete_key]

        if not athlete["firstname"]:
            athlete["firstname"] = row["firstname"]
            athlete["lastname"] = row["lastname"]
            athlete["birthday"] = row["birthday"]
            athlete["club"] = row["club"]
            athlete["club_id"] = row["club_id"]

        athlete["competitor_ids"].add(row["competitor_id"])
        athlete["total_points"] += row["points"]

        position = row["position"].replace(".", "").strip()
        if position == "1":
            athlete["gold_medals"] += 1
        elif position == "2":
            athlete["silver_medals"] += 1
        elif position == "3":
            athlete["bronze_medals"] += 1

        athlete["starts"].append({
            "round_date": row["tournament_date"],
            "points": row["points"],
            "position": row["position"],
        })

    merge_duplicate_athletes(category_data)

    root = ET.Element("tournament")
    ET.SubElement(root, "id").text = "aggregated"
    ET.SubElement(root, "name").text = TOURNAMENT_TITLE
    ET.SubElement(root, "source").text = "lske.karate-draw.cz"
    ET.SubElement(root, "date").text = datetime.now().strftime("%Y-%m-%d")

    round_dates = sorted({row["tournament_date"] for row in all_results if row["tournament_date"]})
    competitor_ids = {row["competitor_id"] for row in all_results if row["competitor_id"]}
    clubs = {row["club"] for row in all_results if row["club"]}

    ET.SubElement(root, "number_of_competitors").text = str(len(competitor_ids))
    ET.SubElement(root, "number_of_starts").text = str(len(all_results))
    ET.SubElement(root, "number_of_clubs").text = str(len(clubs))
    ET.SubElement(root, "number_of_rounds").text = str(len(round_dates))

    total_athletes = 0

    for category_key in sorted(category_data.keys(), key=category_sort_key):
        disciplina, kategorie1, kategorie2 = category_key
        athletes = list(category_data[category_key].values())
        athletes.sort(key=lambda item: (
            item["total_points"],
            item["gold_medals"],
            item["silver_medals"],
            item["bronze_medals"],
        ), reverse=True)

        category_elem = ET.SubElement(root, "category")
        ET.SubElement(category_elem, "type").text = "individual"

        name = f"{disciplina};{kategorie1}"
        if kategorie2:
            name += f";{kategorie2}"
        ET.SubElement(category_elem, "name").text = name
        ET.SubElement(category_elem, "disciplina").text = disciplina
        ET.SubElement(category_elem, "kategorie1").text = kategorie1
        ET.SubElement(category_elem, "kategorie2").text = kategorie2
        ET.SubElement(category_elem, "total").text = str(len(athletes))

        current_rank = 1
        for index, athlete in enumerate(athletes):
            if index > 0:
                previous = athletes[index - 1]
                if (
                    athlete["total_points"] == previous["total_points"]
                    and athlete["gold_medals"] == previous["gold_medals"]
                    and athlete["silver_medals"] == previous["silver_medals"]
                    and athlete["bronze_medals"] == previous["bronze_medals"]
                ):
                    rank_text = f"{current_rank}."
                else:
                    current_rank = index + 1
                    rank_text = f"{current_rank}."
            else:
                rank_text = f"{current_rank}."

            result_elem = ET.SubElement(category_elem, "result")
            ET.SubElement(result_elem, "position").text = rank_text

            competitor_ids_list = sorted(athlete["competitor_ids"])
            ET.SubElement(result_elem, "competitor_id").text = competitor_ids_list[0] if competitor_ids_list else ""
            if len(competitor_ids_list) > 1:
                ET.SubElement(result_elem, "competitor_ids").text = ",".join(competitor_ids_list)

            ET.SubElement(result_elem, "firstname").text = athlete["firstname"]
            ET.SubElement(result_elem, "lastname").text = athlete["lastname"]
            ET.SubElement(result_elem, "birthday").text = athlete["birthday"]
            ET.SubElement(result_elem, "club").text = athlete["club"]
            ET.SubElement(result_elem, "club_id").text = athlete["club_id"]

            points_text = str(int(athlete["total_points"])) if athlete["total_points"].is_integer() else str(athlete["total_points"])
            ET.SubElement(result_elem, "points").text = points_text
            ET.SubElement(result_elem, "gold_medals").text = str(athlete["gold_medals"])
            ET.SubElement(result_elem, "silver_medals").text = str(athlete["silver_medals"])
            ET.SubElement(result_elem, "bronze_medals").text = str(athlete["bronze_medals"])

            starts_elem = ET.SubElement(result_elem, "starts")
            for start in sorted(athlete["starts"], key=lambda item: item["round_date"]):
                start_elem = ET.SubElement(starts_elem, "start")
                ET.SubElement(start_elem, "round_date").text = start["round_date"]
                start_points = start["points"]
                start_points_text = str(int(start_points)) if float(start_points).is_integer() else str(start_points)
                ET.SubElement(start_elem, "points").text = start_points_text
                ET.SubElement(start_elem, "position").text = start["position"]

            total_athletes += 1

    tree = ET.ElementTree(root)
    ET.indent(tree, space="\t")
    tree.write(output_path, encoding="utf-8", xml_declaration=True)

    return {
        "categories": len(category_data),
        "athletes": total_athletes,
        "starts": len(all_results),
        "rounds": len(round_dates),
    }


def list_round_files(work_dir: Path) -> list[Path]:
    return list_tournament_xml_files(work_dir)


def aggregate(work_dir: Path, output_path: Path) -> dict:
    round_files = list_round_files(work_dir)

    if not round_files:
        print(f"Zadne XML soubory v {work_dir}")
        return {}

    print(f"Nacitam {len(round_files)} kol...")
    rounds = discover_rounds(round_files)
    for index, date in enumerate(rounds.dates, start=1):
        label = rounds.key_to_label.get(f"round_{index}", date)
        print(f"  {label}: {date}")

    all_results = []
    for path in round_files:
        rows = load_results_from_xml(path)
        all_results.extend(rows)
        print(f"  {path.name}: {len(rows)} vysledku")

    stats = build_aggregated_xml(all_results, output_path)
    created = ensure_nomination_files(output_path)
    if created:
        print(f"\nNominace: vytvoreno {len(created)} novych souboru v nominations/ a nominations-declined/")
    print(f"\nSouhrnny soubor vytvoren: {output_path.name}")
    print(f"  Kategorii: {stats['categories']}")
    print(f"  Zavodniku: {stats['athletes']}")
    print(f"  Startu:    {stats['starts']}")
    print(f"  Kol:       {stats['rounds']}")
    return stats


def main() -> None:
    output_path = AGGREGATED_XML

    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_path = BASE_DIR / sys.argv[idx + 1]

    if not WORKING_DIR.exists():
        print(f"Slozka {WORKING_DIR.name}/ neexistuje.")
        print("Nejprve spust: python3 fix_xml_data.py")
        return

    aggregate(WORKING_DIR, output_path)


if __name__ == "__main__":
    main()
