#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Nacitani a parsovani nominacnich souboru klubu (.txt)."""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from config import (
    AGGREGATED_XML,
    NOMINATIONS_DECLINED_DIR,
    NOMINATIONS_DIR,
    NOMINATION_LOG_PREFIX,
    WORKING_DIR,
)
from qualification import compute_category_postupuje
from utils import normalizuj

NominationKey = Tuple[str, str, str, str, str]


@dataclass
class CategoryInfo:
    disciplina: str
    kategorie1: str
    kategorie2: str
    display_name: str


@dataclass
class AthleteInCategory:
    firstname: str
    lastname: str
    club: str
    position: str
    points: str
    category: CategoryInfo
    best_round_points: float


@dataclass
class ParsedNominationLine:
    firstname: str
    lastname: str
    category: CategoryInfo
    source_file: str
    line_number: int
    raw_line: str


@dataclass
class NominationLoadResult:
    confirmed: Set[NominationKey] = field(default_factory=set)
    declined: Set[NominationKey] = field(default_factory=set)
    log_path: Optional[Path] = None
    stats: Dict[str, int] = field(default_factory=dict)


class NominationLog:
    def __init__(self) -> None:
        self.lines: List[str] = []
        self.stats = {
            "files": 0,
            "lines_total": 0,
            "ok": 0,
            "errors": 0,
            "name_not_found": 0,
            "wrong_category": 0,
            "ambiguous_category": 0,
            "wrong_club": 0,
            "skipped": 0,
        }

    def ok(self, source: str, line_no: int, raw: str, message: str) -> None:
        self.stats["ok"] += 1
        self.lines.append(f"[OK] {source}:{line_no}")
        self.lines.append(f"  radek: {raw}")
        self.lines.append(f"  {message}")
        self.lines.append("")

    def error(self, source: str, line_no: int, raw: str, message: str, category: str = "CHYBA") -> None:
        self.stats["errors"] += 1
        self.lines.append(f"[{category}] {source}:{line_no}")
        self.lines.append(f"  radek: {raw}")
        for part in message.splitlines():
            self.lines.append(f"  {part}")
        self.lines.append("")

    def write(self, work_dir: Path) -> Path:
        work_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = work_dir / f"{NOMINATION_LOG_PREFIX}-{timestamp}.txt"
        summary = [
            "=" * 60,
            "LOG NOMINACI",
            "=" * 60,
            "",
            *self.lines,
            "=" * 60,
            "SOUHRN",
            "=" * 60,
            f"  souboru:              {self.stats['files']}",
            f"  radku celkem:          {self.stats['lines_total']}",
            f"  OK:                    {self.stats['ok']}",
            f"  chyby:                 {self.stats['errors']}",
            f"    jmeno nenalezeno:    {self.stats['name_not_found']}",
            f"    spatna kategorie:    {self.stats['wrong_category']}",
            f"    nejednoznacne:       {self.stats['ambiguous_category']}",
            f"    spatny klub:         {self.stats['wrong_club']}",
            f"  preskoceno radku:      {self.stats['skipped']}",
            "",
            "Rezim: varovani, pipeline pokracuje.",
            "",
        ]
        path.write_text("\n".join(summary), encoding="utf-8")
        return path


def xml_text(element, tag: str) -> str:
    el = element.find(tag) if element is not None else None
    return (el.text or "").strip() if el is not None else ""


def format_category_name(disciplina: str, kategorie1: str, kategorie2: str) -> str:
    name = f"{disciplina.upper()} {kategorie1}"
    if kategorie2:
        name += f" {kategorie2}"
    return name


def club_nomination_filename(club_name: str) -> str:
    name = club_name.replace(".", "_").replace(" ", "_").replace(",", "_")
    name = re.sub(r"_+", "_", name).strip("_")
    return f"{name}.txt"


def nomination_key(
    firstname: str,
    lastname: str,
    disciplina: str,
    kategorie1: str,
    kategorie2: str,
) -> NominationKey:
    return (
        normalizuj(firstname),
        normalizuj(lastname),
        normalizuj(disciplina),
        normalizuj(kategorie1),
        normalizuj(kategorie2),
    )


def collect_clubs_from_xml(root: ET.Element) -> List[str]:
    clubs: Set[str] = set()
    for category in root.findall("category"):
        for result in category.findall("result"):
            club = xml_text(result, "club")
            if club:
                clubs.add(club)
    return sorted(clubs)


def collect_categories_from_xml(root: ET.Element) -> List[CategoryInfo]:
    categories: List[CategoryInfo] = []
    seen: Set[str] = set()
    for category in root.findall("category"):
        disciplina = xml_text(category, "disciplina")
        kategorie1 = xml_text(category, "kategorie1")
        kategorie2 = xml_text(category, "kategorie2")
        display = format_category_name(disciplina, kategorie1, kategorie2)
        if display not in seen:
            seen.add(display)
            categories.append(CategoryInfo(disciplina, kategorie1, kategorie2, display))
    return categories


def discipline_labels_from_categories(categories: List[CategoryInfo]) -> Tuple[str, ...]:
    """Discipliny z XML, serazene od nejdelsiho (pro parsovani radku nominace)."""
    labels = sorted(
        {cat.disciplina.upper() for cat in categories if cat.disciplina},
        key=len,
        reverse=True,
    )
    return tuple(labels)


def build_athlete_index(root: ET.Element) -> Tuple[Dict[NominationKey, AthleteInCategory], Dict[str, List[AthleteInCategory]]]:
    by_key: Dict[NominationKey, AthleteInCategory] = {}
    by_name: Dict[str, List[AthleteInCategory]] = {}

    for category in root.findall("category"):
        disciplina = xml_text(category, "disciplina")
        kategorie1 = xml_text(category, "kategorie1")
        kategorie2 = xml_text(category, "kategorie2")
        cat_info = CategoryInfo(disciplina, kategorie1, kategorie2, format_category_name(disciplina, kategorie1, kategorie2))

        for result in category.findall("result"):
            firstname = xml_text(result, "firstname")
            lastname = xml_text(result, "lastname")
            club = xml_text(result, "club")
            position = xml_text(result, "position")
            points = xml_text(result, "points")

            best_round = 0.0
            starts = result.find("starts")
            if starts is not None:
                for start in starts.findall("start"):
                    try:
                        best_round = max(best_round, float(xml_text(start, "points").replace(",", ".")))
                    except ValueError:
                        pass

            athlete = AthleteInCategory(
                firstname=firstname,
                lastname=lastname,
                club=club,
                position=position,
                points=points,
                category=cat_info,
                best_round_points=best_round,
            )
            key = nomination_key(firstname, lastname, disciplina, kategorie1, kategorie2)
            by_key[key] = athlete

            name_key = f"{normalizuj(firstname)} {normalizuj(lastname)}"
            by_name.setdefault(name_key, []).append(athlete)
            name_key_rev = f"{normalizuj(lastname)} {normalizuj(firstname)}"
            if name_key_rev != name_key:
                by_name.setdefault(name_key_rev, []).append(athlete)

    return by_key, by_name


def nominations_template(club: str, declined: bool = False) -> str:
    if declined:
        return (
            f"# Klub: {club}\n"
            "# Ucel: zavodnici, ktere klub NENOMINUJE\n"
            "#       (prepousti slot, nominuje jinde, nebo jiny duvod)\n"
            "#       i kdyz by mohli postoupit z Kraje\n"
            "#\n"
            "# Format - jeden radek = jedna disciplina:\n"
            "#   Jmeno Prijmeni - KATEGORIE\n"
            "#\n"
            "# Minimalne: KARATE AGILITY chlapci U8\n"
            "# Presneji: zkopiruj sloupec Kategorie z results-for-excel.csv\n"
            "# Priklad:\n"
            "#   Vincent Jelínek - KARATE AGILITY chlapci U8\n"
            "#\n"
            "# Radky zacinajici # se ignoruji.\n"
            "# Prazdne radky se ignoruji.\n"
            "\n"
        )
    return (
        f"# Klub: {club}\n"
        "# Ucel: potvrzeni postupu (ANO potvrzeno) nebo zajem mimo postup\n"
        "#       mimo postup z poradi = NE (zajem o postup), po uvolneni slotu ANO\n"
        "#\n"
        "# Format - jeden radek = jedna disciplina:\n"
        "#   Jmeno Prijmeni - KATEGORIE\n"
        "#\n"
        "# Minimalne: KARATE AGILITY chlapci U8\n"
        "# Presneji: zkopiruj sloupec Kategorie z results-for-excel.csv\n"
        "# Priklad:\n"
        "#   Simon Vele - KARATE AGILITY chlapci U8\n"
        "#   Nela Skorcikova - KATA BEGINNER divky U8\n"
        "#\n"
        "# Radky zacinajici # se ignoruji.\n"
        "# Prazdne radky se ignoruji.\n"
        "\n"
    )


def ensure_nomination_files(aggregated_path: Path) -> List[Path]:
    if not aggregated_path.is_file():
        return []

    root = ET.parse(aggregated_path).getroot()
    clubs = collect_clubs_from_xml(root)
    created: List[Path] = []

    for directory, declined in ((NOMINATIONS_DIR, False), (NOMINATIONS_DECLINED_DIR, True)):
        directory.mkdir(parents=True, exist_ok=True)
        for club in clubs:
            target = directory / club_nomination_filename(club)
            if not target.exists():
                target.write_text(nominations_template(club, declined=declined), encoding="utf-8")
                created.append(target)

    return created


def extract_club_from_file(path: Path) -> Optional[str]:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("# klub:"):
                return stripped.split(":", 1)[1].strip()
    except OSError:
        return None
    return None


def split_name_and_category(line: str, discipline_labels: Tuple[str, ...]) -> Tuple[str, str]:
    for separator in (" - ", " – ", " — "):
        if separator in line:
            left, right = line.split(separator, 1)
            return left.strip(), right.strip()

    upper_line = line.upper()
    for label in discipline_labels:
        idx = upper_line.find(label)
        if idx > 0:
            return line[:idx].strip(), line[idx:].strip()

    return line.strip(), ""


def match_categories(category_text: str, categories: List[CategoryInfo]) -> List[CategoryInfo]:
    if not category_text:
        return []

    norm_input = normalizuj(category_text)
    exact = [cat for cat in categories if normalizuj(cat.display_name) == norm_input]
    if exact:
        return exact

    partial = [
        cat for cat in categories
        if normalizuj(cat.display_name).startswith(norm_input)
        or norm_input.startswith(normalizuj(cat.display_name))
    ]
    if partial:
        return partial

    token_matches = []
    for cat in categories:
        norm_cat = normalizuj(cat.display_name)
        if all(token in norm_cat for token in norm_input.split() if len(token) >= 2):
            token_matches.append(cat)
    return token_matches


def find_athlete_by_name(
    name_text: str,
    expected_club: Optional[str],
    category: CategoryInfo,
    by_name: Dict[str, List[AthleteInCategory]],
) -> Tuple[Optional[AthleteInCategory], Optional[str]]:
    candidates = by_name.get(normalizuj(name_text), [])
    if not candidates:
        parts = name_text.split()
        if len(parts) >= 2:
            reversed_name = " ".join(parts[-1:] + parts[:-1])
            candidates = by_name.get(normalizuj(reversed_name), [])

    if not candidates:
        return None, None

    cat_norm = (
        normalizuj(category.disciplina),
        normalizuj(category.kategorie1),
        normalizuj(category.kategorie2),
    )

    in_category = [
        athlete for athlete in candidates
        if (
            normalizuj(athlete.category.disciplina),
            normalizuj(athlete.category.kategorie1),
            normalizuj(athlete.category.kategorie2),
        ) == cat_norm
    ]

    if not in_category:
        details = [
            f"  - {item.category.display_name} [{item.position}, {item.points} b, {item.club}]"
            for item in candidates
        ]
        return None, "jmeno nalezeno, kategorie nesedi:\n" + "\n".join(details)

    if expected_club:
        club_matches = [item for item in in_category if item.club == expected_club]
        if not club_matches:
            actual = in_category[0]
            return None, (
                f"jmeno nalezeno v kategorii, ale klub v XML: {actual.club}"
                f" (cekano: {expected_club})"
            )
        return club_matches[0], None

    if len(in_category) == 1:
        return in_category[0], None

    clubs = {item.club for item in in_category}
    if len(clubs) == 1:
        return in_category[0], None

    return None, "vice zavodniku se stejnym jmenem, upresni klub v souboru"


def parse_nomination_file(
    path: Path,
    categories: List[CategoryInfo],
    by_name: Dict[str, List[AthleteInCategory]],
    log: NominationLog,
    declined: bool,
) -> List[ParsedNominationLine]:
    folder = "nominations-declined" if declined else "nominations"
    source = f"{folder}/{path.name}"
    log.stats["files"] += 1

    expected_club = extract_club_from_file(path)
    parsed_entries: List[ParsedNominationLine] = []
    discipline_labels = discipline_labels_from_categories(categories)

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        log.error(source, 0, "", f"soubor nelze precist: {exc}")
        log.stats["skipped"] += 1
        return parsed_entries

    for line_no, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        log.stats["lines_total"] += 1
        name_text, category_text = split_name_and_category(line, discipline_labels)

        if not category_text:
            log.error(source, line_no, line, "chybi kategorie v radku")
            log.stats["skipped"] += 1
            continue

        matched_categories = match_categories(category_text, categories)
        if not matched_categories:
            log.error(source, line_no, line, f"kategorie nenalezena: {category_text}")
            log.stats["wrong_category"] += 1
            log.stats["skipped"] += 1
            continue

        if len(matched_categories) > 1:
            options = "\n".join(f"  - {cat.display_name}" for cat in matched_categories)
            log.error(
                source,
                line_no,
                line,
                f"nejednoznacna kategorie: {category_text}\n{options}",
                category="CHYBA",
            )
            log.stats["ambiguous_category"] += 1
            log.stats["skipped"] += 1
            continue

        category = matched_categories[0]
        athlete, error = find_athlete_by_name(name_text, expected_club, category, by_name)
        if athlete is None:
            if error and "cekano:" in error:
                log.error(source, line_no, line, error)
                log.stats["wrong_club"] += 1
            elif error and "jmeno nalezeno" in error:
                log.error(source, line_no, line, error)
                log.stats["wrong_category"] += 1
            else:
                log.error(source, line_no, line, "jmeno v XML nenalezeno")
                log.stats["name_not_found"] += 1
            log.stats["skipped"] += 1
            continue

        entry = ParsedNominationLine(
            firstname=athlete.firstname,
            lastname=athlete.lastname,
            category=category,
            source_file=source,
            line_number=line_no,
            raw_line=line,
        )
        parsed_entries.append(entry)
        log.ok(
            source,
            line_no,
            line,
            f"{athlete.firstname} {athlete.lastname} -> {category.display_name}",
        )

    return parsed_entries


def load_nominations(
    aggregated_path: Path = AGGREGATED_XML,
    write_log: bool = True,
) -> NominationLoadResult:
    ensure_nomination_files(aggregated_path)
    result = NominationLoadResult()
    log = NominationLog()

    if not aggregated_path.is_file():
        return result

    root = ET.parse(aggregated_path).getroot()
    categories = collect_categories_from_xml(root)
    _, by_name = build_athlete_index(root)

    for directory, declined, target_set in (
        (NOMINATIONS_DIR, False, result.confirmed),
        (NOMINATIONS_DECLINED_DIR, True, result.declined),
    ):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.txt")):
            entries = parse_nomination_file(path, categories, by_name, log, declined=declined)
            for entry in entries:
                key = nomination_key(
                    entry.firstname,
                    entry.lastname,
                    entry.category.disciplina,
                    entry.category.kategorie1,
                    entry.category.kategorie2,
                )
                target_set.add(key)

    overlap = result.confirmed & result.declined
    if overlap:
        for key in overlap:
            result.confirmed.discard(key)
        log.error(
            "nominations",
            0,
            "",
            f"{len(overlap)} zaznamu je v obou slozkach, pouzit nominations-declined/",
        )
        log.stats["skipped"] += len(overlap)

    if write_log:
        result.log_path = log.write(WORKING_DIR)
        result.stats = log.stats.copy()
        if log.stats["errors"]:
            print(
                f"Varovani: {log.stats['errors']} radku preskoceno "
                f"(viz {result.log_path.name})"
            )

    return result


def parse_points(value: str) -> float:
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return 0.0


def compute_postupuje_map(root: ET.Element, nomination_data: NominationLoadResult) -> Dict[NominationKey, str]:
    postupuje: Dict[NominationKey, str] = {}
    confirmed = nomination_data.confirmed
    declined = nomination_data.declined

    for category in root.findall("category"):
        disciplina = xml_text(category, "disciplina")
        kategorie1 = xml_text(category, "kategorie1")
        kategorie2 = xml_text(category, "kategorie2")
        rows = []
        for result in category.findall("result"):
            firstname = xml_text(result, "firstname")
            lastname = xml_text(result, "lastname")
            position = xml_text(result, "position")
            key = nomination_key(firstname, lastname, disciplina, kategorie1, kategorie2)
            rows.append((
                key,
                position,
                key in declined,
                key in confirmed,
            ))

        postupuje.update(compute_category_postupuje(rows))

    return postupuje
