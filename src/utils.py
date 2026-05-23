#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sdílené utility pro zpracování XML výsledků LSKe."""

import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from config import CLUB_NAME_MAP

@dataclass
class Zavodnik:
    jmeno: str
    prijmeni: str
    competitor_id: str
    club: str
    club_id: str
    soubor: str

    @property
    def cele_jmeno(self) -> str:
        return f"{self.jmeno} {self.prijmeni}"


# ---------------------------------------------------------------------------
# Textové utility
# ---------------------------------------------------------------------------

def bez_diakritiky(text: str) -> str:
    """Odstraní diakritiku z textu."""
    if not text:
        return ""
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def normalizuj(text: str) -> str:
    """Normalizuje text pro porovnání (lowercase + bez diakritiky)."""
    return bez_diakritiky(text.lower().strip()) if text else ""


def normalize_club(club: str) -> str:
    """Sjednoti znamy alias klubu (stejne mapovani jako fix_xml_data)."""
    if not club:
        return ""
    club = club.strip()
    return CLUB_NAME_MAP.get(club, club)


def clubs_equivalent(club1: str, club2: str) -> bool:
    if not club1 or not club2:
        return False
    return normalizuj(normalize_club(club1)) == normalizuj(normalize_club(club2))


def names_are_swapped(
    first1: str,
    last1: str,
    first2: str,
    last2: str,
) -> bool:
    if normalizuj(first1) == normalizuj(first2) and normalizuj(last1) == normalizuj(last2):
        return False
    if normalizuj(first1) == normalizuj(last1):
        return False
    return (
        normalizuj(first1) == normalizuj(last2)
        and normalizuj(last1) == normalizuj(first2)
    )


def levenshtein(s1: str, s2: str) -> int:
    """Levenshtein distance s optimalizací pro krátké řetězce."""
    if s1 == s2:
        return 0
    if not s1:
        return len(s2)
    if not s2:
        return len(s1)
    if len(s1) < len(s2):
        s1, s2 = s2, s1
    # Early exit
    if len(s1) - len(s2) > 5:
        return len(s1) - len(s2)
    prev = list(range(len(s2) + 1))
    for c1 in s1:
        curr = [prev[0] + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j] + (c1 != c2), prev[j + 1] + 1, curr[j] + 1))
        prev = curr
    return prev[-1]


# ---------------------------------------------------------------------------
# Turnajove soubory a kola
# ---------------------------------------------------------------------------

@dataclass
class RoundFileAssignment:
    """Mapovani original -> pracovni soubor dle data kola."""
    source: Path
    target: Path
    round_number: int
    round_date: str
    round_label: str


@dataclass
class RoundMapping:
    """Dynamicke mapovani kol podle dat v XML (libovolny pocet kol)."""
    dates: list[str]
    date_to_key: dict[str, str]
    key_to_label: dict[str, str]

    def label_for_date(self, date: str) -> str:
        key = self.date_to_key.get(date, "")
        return self.key_to_label.get(key, date)


def _text(element, tag: str) -> str:
    el = element.find(tag)
    return (el.text or "").strip() if el is not None else ""


def read_tournament_date(path: Path) -> str:
    try:
        root = ET.parse(path).getroot()
        return _text(root, "date")
    except Exception:
        return ""


def should_skip_xml(path: Path) -> bool:
    from config import SKIP_XML_NAMES, SKIP_XML_PREFIXES

    name = path.name
    if name in SKIP_XML_NAMES:
        return True
    return any(name.startswith(prefix) for prefix in SKIP_XML_PREFIXES)


def is_tournament_xml(path: Path) -> bool:
    """True if XML looks like a round export (has categories with results)."""
    try:
        root = ET.parse(path).getroot()
        for category in root.findall(".//category"):
            if category.findall("result"):
                return True
        return False
    except Exception:
        return False


def list_tournament_xml_files(directory: Path) -> list[Path]:
    """Vrati vsechna turnajova XML v adresari (libovolny nazev souboru)."""
    if not directory.is_dir():
        return []

    files = [
        path for path in sorted(directory.glob("*.xml"))
        if path.is_file() and not should_skip_xml(path) and is_tournament_xml(path)
    ]
    return files


def read_tournament_name(path: Path) -> str:
    try:
        root = ET.parse(path).getroot()
        return _text(root, "name")
    except Exception:
        return ""


def tournament_slug_from_name(name: str) -> str:
    if not name:
        return "turnaj"

    cleaned = re.sub(r"^\d+\.\s*kolo\s*", "", name, flags=re.IGNORECASE).strip()
    slug = bez_diakritiky(cleaned)
    slug = slug.replace("/", "-").replace(" ", "-")
    slug = re.sub(r"[^A-Za-z0-9\-]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "turnaj"


def tournament_slug_from_path(path: Path) -> str:
    from config import TOURNAMENT_SLUG

    if TOURNAMENT_SLUG:
        return TOURNAMENT_SLUG
    return tournament_slug_from_name(read_tournament_name(path))


def working_filename(round_number: int, slug: str) -> str:
    from config import WORKING_FILE_TEMPLATE

    return WORKING_FILE_TEMPLATE.format(round=round_number, slug=slug)


def sort_round_files(files: list[Path]) -> list[Path]:
    def sort_key(path: Path) -> tuple:
        date = read_tournament_date(path)
        if date:
            return (0, date, path.name.lower())
        return (1, path.name.lower(), path.name.lower())

    return sorted(files, key=sort_key)


def assign_working_files(source_files: list[Path], working_dir: Path) -> list[RoundFileAssignment]:
    """Priradi kola 1..N podle data a sestavi cilove nazvy v pracovni/."""
    ordered = sort_round_files(source_files)
    if not ordered:
        return []

    slug = tournament_slug_from_path(ordered[0])
    assignments: list[RoundFileAssignment] = []

    for round_number, source in enumerate(ordered, start=1):
        round_date = read_tournament_date(source)
        target_name = working_filename(round_number, slug)
        assignments.append(RoundFileAssignment(
            source=source,
            target=working_dir / target_name,
            round_number=round_number,
            round_date=round_date,
            round_label=f"{round_number}. kolo",
        ))

    return assignments


def discover_rounds(files: list[Path]) -> RoundMapping:
    """Sestavi mapovani kol podle <date> v XML, serazeno casove."""
    dated: list[tuple[str, Path]] = []
    undated: list[Path] = []

    for path in files:
        date = read_tournament_date(path)
        if date:
            dated.append((date, path))
        else:
            undated.append(path)

    dates = sorted({date for date, _ in dated})
    for path in sorted(undated):
        fallback = f"file:{path.name}"
        if fallback not in dates:
            dates.append(fallback)

    date_to_key: dict[str, str] = {}
    key_to_label: dict[str, str] = {}
    for index, date in enumerate(dates, start=1):
        key = f"round_{index}"
        date_to_key[date] = key
        if date.startswith("file:"):
            key_to_label[key] = date.removeprefix("file:")
        else:
            key_to_label[key] = f"{index}. kolo"

    return RoundMapping(dates=dates, date_to_key=date_to_key, key_to_label=key_to_label)


def round_mapping_from_dates(dates: list[str]) -> RoundMapping:
    """Sestavi mapovani kol z dat (napr. z aggregated-results.xml)."""
    unique = sorted(set(dates))
    date_to_key: dict[str, str] = {}
    key_to_label: dict[str, str] = {}
    for index, date in enumerate(unique, start=1):
        key = f"round_{index}"
        date_to_key[date] = key
        key_to_label[key] = f"{index}. kolo"
    return RoundMapping(dates=unique, date_to_key=date_to_key, key_to_label=key_to_label)


# ---------------------------------------------------------------------------
# Nacitani XML
# ---------------------------------------------------------------------------

def nacti_xml(soubor: Path) -> list:
    """Načte závodníky z XML souboru."""
    zavodnici = []
    try:
        root = ET.parse(soubor).getroot()
        for category in root.findall(".//category"):
            for result in category.findall("result"):
                jmeno = _text(result, "firstname")
                prijmeni = _text(result, "lastname")
                if jmeno and prijmeni:
                    zavodnici.append(Zavodnik(
                        jmeno=jmeno,
                        prijmeni=prijmeni,
                        competitor_id=_text(result, "competitor_id"),
                        club=_text(result, "club"),
                        club_id=_text(result, "club_id"),
                        soubor=soubor.name,
                    ))
    except Exception as e:
        print(f"  ⚠️  Chyba při čtení {soubor.name}: {e}")
    return zavodnici


def nacti_vsechny_xml(adresar: Path) -> list:
    """Nacte zavodniky ze vsech turnajovych XML v adresari."""
    soubory = list_tournament_xml_files(adresar)
    if not soubory:
        print(f"⚠️  Žádné XML soubory v {adresar}")
        return []
    vsichni = []
    print(f"Načítám {len(soubory)} XML souborů...")
    for s in soubory:
        zavodnici = nacti_xml(s)
        vsichni.extend(zavodnici)
        print(f"  {s.name}: {len(zavodnici)} záznamů")
    print(f"  → Celkem: {len(vsichni)} záznamů\n")
    return vsichni
