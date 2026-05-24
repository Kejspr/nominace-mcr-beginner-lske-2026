#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Centralni konfigurace projektu Nominace MCR Beginner.

Vsechny cesty jsou relativni ke koreni projektu (adresar nad src/).
Po zmene hodnot spust: make
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Koren projektu
# ---------------------------------------------------------------------------
# Adresar s original/, pracovni/, nominations/ atd.
# Neměnit, pokud neni zmenena struktura projektu.
BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Vstupni a vystupni soubory (koren projektu)
# ---------------------------------------------------------------------------

# Surova XML z turnajovych kol (libovolny nazev souboru)
ORIGINAL_DIR = BASE_DIR / "original"

# Opravene kopie kol + logy (fix-log-*, nomination-log-*)
WORKING_DIR = BASE_DIR / "pracovni"

# Agregovany souhrn vysledku ze vsech kol (vystup aggregate)
AGGREGATED_XML = BASE_DIR / "aggregated-results.xml"

# Tabulka pro Excel / STK (vystup excel)
EXCEL_CSV = BASE_DIR / "results-for-excel.csv"

# HTML prezentace pro jednani (vystup presentation)
PRESENTATION_HTML = BASE_DIR / "results-presentation.html"

# Render API pro klikaci nominace z HTML (Cloudflare Workers + CORS)
NOMINATION_API_URL = "https://nominace-mcr-beginner-lske-2026.onrender.com"
PRESENTATION_ORIGIN = "https://nominace-mcr-beginner-lske-2026.jan-kaspar.workers.dev"

# Nadpis HTML / aggregated-results.xml
TOURNAMENT_TITLE = "V\u00fdsledky Krajsk\u00e9ho poh\u00e1ru beginner LSKe 2025/2026"

# ---------------------------------------------------------------------------
# Nominace klubu (.txt soubory)
# ---------------------------------------------------------------------------
# nominations/           potvrzeni -> ANO (potvrzeno) u postupujicich z Kraje
# nominations-declined/  odmitnuti -> NE (odmitnuto), uvolni slot pro zajemce
# mimo postup v nominations/ -> NE (zajem o postup), po slotu ANO
#
# Postupuje remiza jen pri aktivni remize na hrane (2+ neodmitnuti na stejne pozici)
# Soubory se vytvareji automaticky po aggregate (1 soubor na klub v obou slozkach).
# Format radku: Jmeno Prijmeni - KARATE AGILITY chlapci U8
# Viz hlavicka v kazdem .txt souboru.

NOMINATIONS_DIR = BASE_DIR / "nominations"
NOMINATIONS_DECLINED_DIR = BASE_DIR / "nominations-declined"

# ---------------------------------------------------------------------------
# Pravidla postupu / nominace
# ---------------------------------------------------------------------------
# Pocet postupovych mist v kategorii.
# Ovlivnuje sloupce "postup z Kraje" a "Postupuje" (pozice 1..N = ANO).
# Pri remize na hrani postupu (pozice = limit): ANO (remiza).
QUALIFYING_PLACES = 3

# ---------------------------------------------------------------------------
# Skenery XML – co preskocit
# ---------------------------------------------------------------------------
# Soubory, ktere se neberou jako turnajove kolo pri fix/aggregate/validate
SKIP_XML_NAMES = frozenset({
    AGGREGATED_XML.name,
    "vysledky-sjednocene.xml",
    "aggregated-results.xml",
})

# Prefixy logu a pomocnych souboru v pracovni/
SKIP_XML_PREFIXES = ("fix-log", "opravy-log", "nomination-log")

# Prefixy vystupnich logu (soubory: {prefix}-YYYYMMDD-HHMMSS.txt)
FIX_LOG_PREFIX = "fix-log"
NOMINATION_LOG_PREFIX = "nomination-log"

# ---------------------------------------------------------------------------
# Pojmenovani kol v pracovni/
# ---------------------------------------------------------------------------
# Sablona ciloveho nazvu po fix: results-1-kolo-{slug}.xml, results-2-kolo-...
# {round} = cislo kola podle data v XML, {slug} = zkratka z nazvu turnaje
WORKING_FILE_TEMPLATE = "results-{round}-kolo-{slug}.xml"

# Volitelne: pevny slug misto automatickeho z XML <name>
# Prazdne = slug se odvodi z nazvu turnaje v prvnim souboru
TOURNAMENT_SLUG = ""

# ---------------------------------------------------------------------------
# Mapovani nazvu klubu (sjednoceni variant v XML)
# ---------------------------------------------------------------------------
CLUB_NAME_MAP = {
    "Gryf Liberec": "GRYF z.s.",
    "Karate ToJo": "Karate ToJo, spolek",
    "SK Karate Shotokan Liberec": "SK KARATE - SHOTOKAN LIBEREC, z.s.",
    "Shotokan Sport Centrum Česká Lípa": "Shotokan Sport Centrum Česká Lípa z.s.",
}
