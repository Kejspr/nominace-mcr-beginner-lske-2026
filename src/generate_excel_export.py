#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Export agregovanych vysledku do CSV pro Excel.

Vstup:  aggregated-results.xml, nominations/*.txt, nominations-declined/*.txt
Vystup: results-for-excel.csv, pracovni/nomination-log-*.txt

Spusteni:
    python3 generate_excel_export.py
"""

import argparse
import csv
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from aggregate_results import category_sort_key
from config import AGGREGATED_XML, EXCEL_CSV
from nomination_io import (
    compute_postupuje_map,
    format_category_name,
    load_nominations,
    nomination_key,
    xml_text,
)
from qualification import analyze_category_qualification, regional_qualifier_label, tied_position_labels
from utils import round_mapping_from_dates


def collect_round_dates(root: ET.Element) -> list[str]:
    dates: list[str] = []
    for category in root.findall("category"):
        for result in category.findall("result"):
            starts = result.find("starts")
            if starts is None:
                continue
            for start in starts.findall("start"):
                round_date = xml_text(start, "round_date")
                if round_date:
                    dates.append(round_date)
    return dates


def read_round_points(result: ET.Element) -> dict[str, str]:
    points_by_date: dict[str, str] = {}
    starts = result.find("starts")
    if starts is None:
        return points_by_date

    for start in starts.findall("start"):
        round_date = xml_text(start, "round_date")
        points = xml_text(start, "points")
        if round_date:
            points_by_date[round_date] = points if points else "-"
    return points_by_date


def sort_categories(root: ET.Element) -> list[ET.Element]:
    categories = list(root.findall("category"))

    def sort_key(category: ET.Element) -> tuple:
        disciplina = xml_text(category, "disciplina")
        kategorie1 = xml_text(category, "kategorie1")
        kategorie2 = xml_text(category, "kategorie2")
        return category_sort_key((disciplina, kategorie1, kategorie2))

    return sorted(categories, key=sort_key)


def generate_csv(input_path: Path, output_path: Path) -> int:
    nomination_data = load_nominations(input_path, write_log=True)
    root = ET.parse(input_path).getroot()
    postupuje_map = compute_postupuje_map(root, nomination_data)
    round_mapping = round_mapping_from_dates(collect_round_dates(root))
    row_count = 0

    with output_path.open("w", encoding="utf-8-sig", newline="") as csvfile:
        writer = csv.writer(csvfile, delimiter=";")

        header = [
            "Pořadí",
            "Kategorie",
            "Jméno",
            "Příjmení",
            "celé Jméno",
            "Klub",
        ]
        for round_date in round_mapping.dates:
            header.append(round_mapping.label_for_date(round_date))
        header.extend(["Celkem", "postup z Kraje", "Postupuje", "Poznamka postupu"])
        writer.writerow(header)

        for category in sort_categories(root):
            disciplina = xml_text(category, "disciplina")
            kategorie1 = xml_text(category, "kategorie1")
            kategorie2 = xml_text(category, "kategorie2")
            category_name = format_category_name(disciplina, kategorie1, kategorie2)
            positions = [xml_text(result, "position") for result in category.findall("result")]
            tied = tied_position_labels(positions)
            category_note = analyze_category_qualification(positions).summary

            for result in category.findall("result"):
                position = xml_text(result, "position")
                firstname = xml_text(result, "firstname")
                lastname = xml_text(result, "lastname")
                club = xml_text(result, "club")
                points_total = xml_text(result, "points")
                round_points = read_round_points(result)
                key = nomination_key(firstname, lastname, disciplina, kategorie1, kategorie2)

                row = [
                    position,
                    category_name,
                    firstname,
                    lastname,
                    f"{firstname} {lastname}",
                    club,
                ]
                for round_date in round_mapping.dates:
                    row.append(round_points.get(round_date, "-"))
                row.append(points_total)
                row.append(regional_qualifier_label(position, tied))
                row.append(postupuje_map.get(key, "NE"))
                row.append(category_note)
                writer.writerow(row)
                row_count += 1

    return row_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Export agregovanych vysledku do CSV pro Excel")
    parser.add_argument("--input", type=Path, default=AGGREGATED_XML, help="Vstupni aggregated-results.xml")
    parser.add_argument("--output", type=Path, default=EXCEL_CSV, help="Vystupni CSV soubor")
    args = parser.parse_args()

    if not args.input.is_file():
        print(f"Chyba: vstupni soubor neexistuje: {args.input}")
        return 1

    row_count = generate_csv(args.input, args.output)
    print(f"CSV vygenerovano: {args.output}")
    print(f"Pocet radku: {row_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
