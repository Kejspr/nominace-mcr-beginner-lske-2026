#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTML prezentace vysledku a nominaci.

Primarni zdroj tabulky: results-for-excel.csv
XML pouze pro medaile a detail kol + metadata turnaje.

Spusteni:
    python3 generate_presentation.py
"""

import argparse
import csv
import json
import sys
import xml.etree.ElementTree as ET
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aggregate_results import category_sort_key
from config import (
    AGGREGATED_XML,
    EXCEL_CSV,
    PRESENTATION_HTML,
    QUALIFYING_PLACES,
)
from nomination_io import format_category_name, xml_text
from qualification import is_ano_value
from utils import normalizuj


def escape_html(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def row_lookup_key(category: str, lastname: str, firstname: str) -> Tuple[str, str, str]:
    return (normalizuj(category), normalizuj(lastname), normalizuj(firstname))


def load_csv_rows(csv_path: Path) -> Tuple[List[str], List[dict]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=";")
        header = next(reader)
        rows = []
        for row in reader:
            if len(row) < len(header):
                row.extend([""] * (len(header) - len(row)))
            rows.append(dict(zip(header, row)))
    return header, rows


def build_xml_enrichment(xml_path: Path) -> Dict[Tuple[str, str, str], dict]:
    root = ET.parse(xml_path).getroot()
    enrichment: Dict[Tuple[str, str, str], dict] = {}

    for category in root.findall("category"):
        disciplina = xml_text(category, "disciplina")
        kategorie1 = xml_text(category, "kategorie1")
        kategorie2 = xml_text(category, "kategorie2")
        display = format_category_name(disciplina, kategorie1, kategorie2)

        for result in category.findall("result"):
            firstname = xml_text(result, "firstname")
            lastname = xml_text(result, "lastname")
            key = row_lookup_key(display, lastname, firstname)

            rounds_parts = []
            starts_elem = result.find("starts")
            if starts_elem is not None:
                for start in starts_elem.findall("start"):
                    round_date = xml_text(start, "round_date")
                    start_points = xml_text(start, "points")
                    start_position = xml_text(start, "position")
                    rounds_parts.append(f"{round_date}: {start_points}b ({start_position})")

            enrichment[key] = {
                "gold": xml_text(result, "gold_medals") or "0",
                "silver": xml_text(result, "silver_medals") or "0",
                "bronze": xml_text(result, "bronze_medals") or "0",
                "rounds": ", ".join(rounds_parts),
            }

    return enrichment


def category_sort_key_from_display(display_name: str) -> tuple:
    upper = display_name.upper()
    for label in (
        "KUMITE BEGINNER",
        "KATA BEGINNER",
        "KUMITE BALLOON",
        "KIHON IDO",
        "KARATE AGILITY",
    ):
        if upper.startswith(label):
            rest = display_name[len(label):].strip()
            return category_sort_key((label.title(), rest, ""))
    parts = display_name.split(None, 1)
    disciplina = parts[0] if parts else ""
    kategorie1 = parts[1] if len(parts) > 1 else ""
    return category_sort_key((disciplina, kategorie1, ""))


def discipline_from_category(category_name: str) -> str:
    upper = category_name.upper()
    for label in (
        "KUMITE BEGINNER",
        "KATA BEGINNER",
        "KUMITE BALLOON",
        "KIHON IDO",
        "KARATE AGILITY",
    ):
        if upper.startswith(label):
            return label
    return category_name.split()[0] if category_name else ""


def rounds_from_csv_row(row: dict, round_columns: List[str]) -> str:
    parts = []
    for column in round_columns:
        value = row.get(column, "").strip()
        if value and value != "-":
            parts.append(f"{column}: {value}b")
    return ", ".join(parts)


def postup_class(value: str, prefix: str) -> str:
    suffix = "ano" if is_ano_value(value) else "ne"
    return f"{prefix}-{suffix}"


LEGEND_LINK_KRAJE = (
    '<a class="col-legend-link" href="#legenda-postupu" '
    'title="Vysvětlení sloupce postup z Kraje">postup z Kraje</a>'
)
LEGEND_LINK_POSTUPUJE = (
    '<a class="col-legend-link" href="#legenda-postupu" '
    'title="Vysvětlení sloupce Postupuje">Postupuje</a>'
)
TABLE_HEAD_POSTUP = (
    f"<th>{LEGEND_LINK_KRAJE}</th><th>{LEGEND_LINK_POSTUPUJE}</th>"
    f'<th class="copy-nomination-col" title="Kopirovat radek pro nominations/*.txt">Txt</th>'
)

COPY_NOMINATION_CELL = (
    '<td class="copy-nomination-cell">'
    '<button type="button" class="copy-nomination-btn" '
    'title="Kopirovat radek pro nominations/ nebo nominations-declined/" '
    'aria-label="Kopirovat radek nominace">Kopie</button>'
    "</td>"
)

COPY_NOMINATION_SCRIPT = """
(function () {
  function nominationLine(row) {
    const first = row.dataset.firstname || "";
    const last = row.dataset.lastname || "";
    const category = row.dataset.category || "";
    return first + " " + last + " - " + category;
  }

  async function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    document.body.removeChild(textarea);
  }

  document.addEventListener("click", async (event) => {
    const button = event.target.closest(".copy-nomination-btn");
    if (!button) return;
    const row = button.closest("tr[data-firstname]");
    if (!row) return;
    const text = nominationLine(row);
    try {
      await copyText(text);
      button.classList.add("copy-nomination-ok");
      const oldTitle = button.title;
      button.title = "Zkopirovano";
      setTimeout(() => {
        button.classList.remove("copy-nomination-ok");
        button.title = oldTitle;
      }, 1500);
    } catch {
      window.prompt("Kopirovani se nezdarilo, zkopiruj rucne:", text);
    }
  });
})();
"""


FILTER_SCRIPT = """
(function () {
  const storageKey = "nominace-mcr-filters";
  const filterData = window.PRESENTATION_FILTER_DATA;
  const clubSelect = document.getElementById("filter-club");
  const mainSelect = document.getElementById("filter-main");
  const detailSelect = document.getElementById("filter-detail");
  const resetButton = document.getElementById("filter-reset");
  const onlyClubCheckbox = document.getElementById("filter-only-club");
  const onlyPostupCheckbox = document.getElementById("filter-only-postup");
  const onlyRemizaCheckbox = document.getElementById("filter-only-remiza");
  const statusEl = document.getElementById("filter-status");

  function saveFilters() {
    localStorage.setItem(storageKey, JSON.stringify({
      club: clubSelect.value,
      main: mainSelect.value,
      detail: detailSelect.value,
      onlyClub: onlyClubCheckbox.checked,
      onlyPostup: onlyPostupCheckbox.checked,
      onlyRemiza: onlyRemizaCheckbox.checked,
    }));
  }

  function loadFilters() {
    try {
      return JSON.parse(localStorage.getItem(storageKey) || "{}");
    } catch {
      return {};
    }
  }

  function populateDetailOptions() {
    const main = mainSelect.value;
    const previous = detailSelect.value;
    detailSelect.innerHTML = "";
    const allOption = document.createElement("option");
    allOption.value = "";
    allOption.textContent = "Vše";
    detailSelect.appendChild(allOption);

    const categories = main
      ? (filterData.categoriesByDiscipline[main] || [])
      : filterData.allCategories;

    for (const category of categories) {
      const option = document.createElement("option");
      option.value = category;
      option.textContent = category.replace(/^[^ ]+ /, "");
      detailSelect.appendChild(option);
    }

    if (categories.includes(previous)) {
      detailSelect.value = previous;
    } else {
      detailSelect.value = "";
    }
  }

  function categoryHasClub(section, club) {
    if (!club) return true;
    const clubs = JSON.parse(section.dataset.clubs || "[]");
    return clubs.includes(club);
  }

  function isPostupRow(row) {
    const postupujeValue = row.dataset.postupuje || "";
    return postupujeValue.startsWith("ANO");
  }

  function isRemizaRow(row) {
    const postupujeValue = row.dataset.postupuje || "";
    const krajeValue = row.dataset.postupKraje || "";
    return postupujeValue.includes("remiza") || krajeValue.includes("remiza");
  }

  function updateOnlyClubState() {
    const hasClub = Boolean(clubSelect.value);
    onlyClubCheckbox.disabled = !hasClub;
    if (!hasClub) onlyClubCheckbox.checked = false;
  }

  function applyFilters() {
    const club = clubSelect.value;
    const main = mainSelect.value;
    const detail = detailSelect.value;
    const onlyClub = onlyClubCheckbox.checked && club;
    const onlyPostup = onlyPostupCheckbox.checked;
    const onlyRemiza = onlyRemizaCheckbox.checked;
    let visibleCategories = 0;
    let visibleRows = 0;
    let highlightedRows = 0;

    document.querySelectorAll(".category").forEach((section) => {
      const matchMain = !main || section.dataset.discipline === main;
      const matchDetail = !detail || section.dataset.category === detail;
      const matchClub = categoryHasClub(section, club);
      let categoryVisible = matchMain && matchDetail && matchClub;
      let categoryRows = 0;

      section.querySelectorAll("tbody tr").forEach((row) => {
        let rowVisible = true;
        if (onlyClub && row.dataset.club !== club) rowVisible = false;
        if (onlyPostup && !isPostupRow(row)) rowVisible = false;
        if (onlyRemiza && !isRemizaRow(row)) rowVisible = false;
        row.hidden = !rowVisible;
        row.classList.toggle("club-highlight", Boolean(club && row.dataset.club === club));
        if (rowVisible) {
          categoryRows += 1;
          visibleRows += 1;
          if (club && row.dataset.club === club) highlightedRows += 1;
        }
      });

      if (categoryVisible && categoryRows === 0) categoryVisible = false;
      section.hidden = !categoryVisible;

      if (categoryVisible) visibleCategories += 1;
    });

    document.querySelectorAll(".discipline").forEach((section) => {
      const hasVisible = Array.from(section.querySelectorAll(".category"))
        .some((category) => !category.hidden);
      section.hidden = !hasVisible;
    });

    let postupuje = 0;
    let remiza = 0;
    let cekatele = 0;

    document.querySelectorAll(".category:not([hidden]) tbody tr:not([hidden])").forEach((row) => {
      if (onlyClub && row.dataset.club !== club) return;

      const postupujeValue = row.dataset.postupuje || "";
      const krajeValue = row.dataset.postupKraje || "";

      if (postupujeValue.startsWith("ANO")) postupuje += 1;
      if (postupujeValue.includes("remiza") || krajeValue.includes("remiza")) remiza += 1;
      if (postupujeValue === "NE (zájem o postup)") cekatele += 1;
    });

    const parts = [visibleCategories + " kategorií", visibleRows + " řádků"];
    if (club) parts.push(highlightedRows + " z vybraného klubu");
    if (onlyClub) parts.push("jen vybraný klub");
    if (onlyPostup) parts.push("jen postupy");
    if (onlyRemiza) parts.push("jen remízy");
    parts.push("Postupuje: " + postupuje);
    parts.push("Remízy: " + remiza);
    parts.push("Čekatelé: " + cekatele);
    statusEl.textContent = "Zobrazeno: " + parts.join(" · ");
    saveFilters();
  }

  window.applyPresentationFilters = applyFilters;
  window.resetPresentationFilters = resetFilters;

  function resetFilters() {
    clubSelect.value = "";
    mainSelect.value = "";
    detailSelect.value = "";
    onlyClubCheckbox.checked = false;
    onlyPostupCheckbox.checked = false;
    onlyRemizaCheckbox.checked = false;
    updateOnlyClubState();
    populateDetailOptions();
    applyFilters();
  }

  filterData.clubs.forEach((club) => {
    const option = document.createElement("option");
    option.value = club;
    option.textContent = club;
    clubSelect.appendChild(option);
  });

  filterData.disciplines.forEach((discipline) => {
    const option = document.createElement("option");
    option.value = discipline;
    option.textContent = discipline;
    mainSelect.appendChild(option);
  });

  const saved = loadFilters();
  if (saved.club && filterData.clubs.includes(saved.club)) clubSelect.value = saved.club;
  if (saved.main && filterData.disciplines.includes(saved.main)) mainSelect.value = saved.main;
  populateDetailOptions();
  if (saved.detail && filterData.allCategories.includes(saved.detail)) {
    detailSelect.value = saved.detail;
  }
  if (saved.onlyClub) onlyClubCheckbox.checked = true;
  if (saved.onlyPostup) onlyPostupCheckbox.checked = true;
  if (saved.onlyRemiza) onlyRemizaCheckbox.checked = true;
  updateOnlyClubState();

  clubSelect.addEventListener("change", () => {
    updateOnlyClubState();
    applyFilters();
  });
  mainSelect.addEventListener("change", () => {
    detailSelect.value = "";
    populateDetailOptions();
    applyFilters();
  });
  detailSelect.addEventListener("change", applyFilters);
  onlyClubCheckbox.addEventListener("change", applyFilters);
  onlyPostupCheckbox.addEventListener("change", applyFilters);
  onlyRemizaCheckbox.addEventListener("change", applyFilters);
  resetButton.addEventListener("click", resetFilters);

  applyFilters();
  if (typeof window.updateNominationMenus === "function") {
    window.updateNominationMenus();
  }
})();
"""


def build_legend_html(qualifying_places: int) -> str:
    limit = qualifying_places
    items = [
        (
            "postup z Kraje: ANO",
            f"Závodník je v prvních {limit} místech kategorie podle součtu bodů z kol.",
        ),
        (
            "Postupuje: ANO",
            "Postup z pořadí nebo doplnění slotu po odmítnutí. "
            f"V kategorii je vždy {limit} postupujících (kromě remízy na hraně).",
        ),
        (
            "Postupuje: ANO (potvrzeno)",
            "Postupuje a klub potvrdil nominaci (soubor v nominations/).",
        ),
        (
            "Postupuje: ANO (remíza)",
            "Aktivní remíza na hraně postupu "
            f"({limit}. místo): soupeři na stejné tabulce pozici by překročili limit "
            f"{limit} postupujících.",
        ),
        (
            "Postupuje: NE (zájem o postup)",
            "Nepostupuje, ale klub projevil zájem (nominations/) – "
            "informace pro ostatní trenéry, slot se plní dle pořadí.",
        ),
        (
            "Postupuje: NE (odmítnuto)",
            "Klub nominaci odmítl (nominations-declined/). "
            "Slot přebírá další v pořadí.",
        ),
        (
            "Postupuje: NE",
            "Nepostupuje (mimo postup z pořadí a bez volného slotu).",
        ),
    ]
    rows = "".join(
        f"<dt>{escape_html(label)}</dt><dd>{escape_html(text)}</dd>"
        for label, text in items
    )
    return (
        f"<section id=\"legenda-postupu\" class=\"legend\">"
        f"<h2>Legenda postupů</h2>"
        f"<p class=\"legend-intro\">Limit postupujících v kategorii: "
        f"<strong>{limit}</strong>.</p>"
        f"<dl>{rows}</dl>"
        f"</section>"
    )


def generate_html(
    xml_path: Path,
    csv_path: Path,
    output_path: Path,
) -> None:
    root = ET.parse(xml_path).getroot()
    _, csv_rows = load_csv_rows(csv_path)
    enrichment = build_xml_enrichment(xml_path)

    tournament_name = xml_text(root, "name")
    tournament_date = xml_text(root, "date")
    competitors = xml_text(root, "number_of_competitors")
    starts = xml_text(root, "number_of_starts")
    clubs = xml_text(root, "number_of_clubs")
    rounds = xml_text(root, "number_of_rounds")

    if not csv_rows:
        output_path.write_text("<html><body>CSV je prazdne.</body></html>", encoding="utf-8")
        return

    sample = csv_rows[0]
    round_columns = [
        key for key in sample
        if key not in {
            "Pořadí", "Kategorie", "Jméno", "Příjmení", "celé Jméno", "Klub",
            "Celkem", "postup z Kraje", "Postupuje", "Poznamka postupu",
        }
    ]

    by_category: OrderedDict[str, List[dict]] = OrderedDict()
    for row in csv_rows:
        category = row.get("Kategorie", "")
        by_category.setdefault(category, []).append(row)

    sorted_categories = sorted(by_category.keys(), key=category_sort_key_from_display)

    all_clubs = sorted({
        row.get("Klub", "").strip()
        for row in csv_rows
        if row.get("Klub", "").strip()
    })
    categories_by_discipline: dict[str, list[str]] = defaultdict(list)
    for category_name in sorted_categories:
        categories_by_discipline[discipline_from_category(category_name)].append(category_name)

    discipline_order = [
        "KARATE AGILITY",
        "KIHON IDO",
        "KUMITE BALLOON",
        "KATA BEGINNER",
        "KUMITE BEGINNER",
    ]
    filter_data = {
        "clubs": all_clubs,
        "disciplines": [d for d in discipline_order if d in categories_by_discipline],
        "categoriesByDiscipline": {
            d: categories_by_discipline[d] for d in discipline_order if d in categories_by_discipline
        },
        "allCategories": sorted_categories,
    }
    filter_json = json.dumps(filter_data, ensure_ascii=False).replace("<", "\\u003c")
    legend_html = build_legend_html(QUALIFYING_PLACES)

    disciplines: dict[str, list[str]] = defaultdict(list)
    for category_name in sorted_categories:
        category_rows = by_category[category_name]
        category_note = category_rows[0].get("Poznamka postupu", "").strip()
        rows_html = []
        clubs_in_category = sorted({
            row.get("Klub", "").strip()
            for row in category_rows
            if row.get("Klub", "").strip()
        })
        disciplina = discipline_from_category(category_name)
        for row in category_rows:
            firstname = row.get("Jméno", "")
            lastname = row.get("Příjmení", "")
            club = row.get("Klub", "")
            key = row_lookup_key(category_name, lastname, firstname)
            extra = enrichment.get(key, {})

            postupuje = row.get("Postupuje", "NE")
            postup_z_kraje = row.get("postup z Kraje", "NE")

            gold = extra.get("gold", "0")
            silver = extra.get("silver", "0")
            bronze = extra.get("bronze", "0")
            medals = []
            if int(gold) > 0:
                medals.append(f"<span class='medal gold'>{gold}</span>")
            if int(silver) > 0:
                medals.append(f"<span class='medal silver'>{silver}</span>")
            if int(bronze) > 0:
                medals.append(f"<span class='medal bronze'>{bronze}</span>")

            rounds_text = extra.get("rounds") or rounds_from_csv_row(row, round_columns)

            rows_html.append(
                f"<tr data-club=\"{escape_html(club)}\""
                f" data-firstname=\"{escape_html(firstname)}\""
                f" data-lastname=\"{escape_html(lastname)}\""
                f" data-category=\"{escape_html(category_name)}\""
                f" data-postupuje=\"{escape_html(postupuje)}\""
                f" data-postup-kraje=\"{escape_html(postup_z_kraje)}\">"
                f"<td>{escape_html(row.get('Pořadí', ''))}</td>"
                f"<td><strong>{escape_html(firstname)} {escape_html(lastname)}</strong></td>"
                f"<td>{escape_html(club)}</td>"
                f"<td>{escape_html(row.get('Celkem', ''))}</td>"
                f"<td>{''.join(medals)}</td>"
                f"<td>{escape_html(rounds_text)}</td>"
                f"<td class='postup-z-kraje-cell {postup_class(postup_z_kraje, 'postup-z-kraje')}'>"
                f"{escape_html(postup_z_kraje)}</td>"
                f"<td class='postupuje-cell {postup_class(postupuje, 'postupuje')}'>"
                f"{escape_html(postupuje)}</td>"
                f"{COPY_NOMINATION_CELL}"
                "</tr>"
            )

        note_html = (
            f"<p class='category-note'>{escape_html(category_note)}</p>"
            if category_note
            else ""
        )
        clubs_json = json.dumps(clubs_in_category, ensure_ascii=False)
        category_block = (
            "<section class='category'"
            f" data-discipline=\"{escape_html(disciplina)}\""
            f" data-category=\"{escape_html(category_name)}\""
            f" data-clubs=\"{escape_html(clubs_json)}\">"
            f"<h3>{escape_html(category_name)}</h3>"
            f"{note_html}"
            "<table>"
            "<thead><tr>"
            "<th>Poz.</th><th>Jmeno</th><th>Klub</th><th>Body</th><th>Medaile</th>"
            "<th>Kola</th>"
            f"{TABLE_HEAD_POSTUP}"
            "</tr></thead>"
            f"<tbody>{''.join(rows_html)}</tbody></table></section>"
        )
        disciplines[disciplina].append(category_block)

    discipline_html = []
    for disciplina in discipline_order:
        blocks = disciplines.get(disciplina)
        if not blocks:
            continue
        discipline_html.append(
            "<section class='discipline'"
            f" data-discipline=\"{escape_html(disciplina)}\">"
            f"<h2>{escape_html(disciplina)}</h2>"
            f"{''.join(blocks)}"
            "</section>"
        )

    login_html = ""
    content_open = '<div id="main-content">'
    tail_scripts = (
        f"  <script>window.PRESENTATION_FILTER_DATA = {filter_json};</script>\n"
        f"  <script>{FILTER_SCRIPT}</script>\n"
        f"  <script>{COPY_NOMINATION_SCRIPT}</script>"
    )

    html = f"""<!DOCTYPE html>
<html lang="cs">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape_html(tournament_name)}</title>
  <style>
    body {{ font-family: Segoe UI, sans-serif; margin: 0; background: #eef2ff; color: #222; }}
    .container {{ max-width: 1400px; margin: 0 auto; padding: 24px; }}
    header {{ background: #3949ab; color: white; padding: 24px; border-radius: 12px; margin-bottom: 24px; }}
    header h1 {{ margin: 0 0 12px; }}
    .stats {{ display: flex; gap: 16px; flex-wrap: wrap; align-items: start; }}
    .stats span {{ background: rgba(255,255,255,0.15); padding: 6px 12px; border-radius: 8px; }}
    a.col-legend-link {{
      color: #3949ab; text-decoration: none; font-weight: 600;
    }}
    a.col-legend-link:hover {{ text-decoration: underline; }}
    .discipline {{ background: white; border-radius: 12px; padding: 16px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
    .category {{ margin-top: 16px; }}
    .category-note {{ margin: 4px 0 12px; padding: 8px 12px; background: #fff8e1; border-left: 4px solid #f9a825; font-size: 14px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ border-bottom: 1px solid #e0e0e0; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f5f5f5; }}
    .postupuje-ano, .postup-z-kraje-ano {{ color: #2e7d32; font-weight: bold; }}
    .postupuje-ne, .postup-z-kraje-ne {{ color: #c62828; }}
    .medal {{ display: inline-block; min-width: 18px; text-align: center; border-radius: 4px; margin-right: 4px; color: white; font-size: 12px; }}
    .gold {{ background: #f9a825; }}
    .silver {{ background: #90a4ae; }}
    .bronze {{ background: #8d6e63; }}
    .filters {{
      background: white; border-radius: 12px; padding: 16px 20px;
      margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    }}
    .filters-row {{ display: flex; flex-wrap: wrap; gap: 16px; align-items: end; }}
    .filter-field {{ display: flex; flex-direction: column; gap: 4px; min-width: 180px; flex: 1; }}
    .filter-field label {{ font-size: 12px; font-weight: 600; color: #555; text-transform: uppercase; }}
    .filter-field select, .filters button {{
      font: inherit; padding: 8px 10px; border: 1px solid #ccc; border-radius: 8px; background: white;
    }}
    .filters button {{ cursor: pointer; flex: 0; min-width: auto; }}
    .filter-checkboxes {{ display: flex; flex-wrap: wrap; gap: 20px; margin-top: 14px; }}
    .filter-checkboxes label {{
      display: flex; align-items: center; gap: 8px; font-size: 14px; color: #333; cursor: pointer;
    }}
    .filter-checkboxes input {{ width: 16px; height: 16px; cursor: pointer; }}
    .filter-checkboxes input:disabled + span {{ color: #999; cursor: not-allowed; }}
    .filter-status {{ margin-top: 12px; font-size: 14px; color: #555; }}
    tr.club-highlight {{ background: #e8f5e9; }}
    tr.club-highlight td {{ border-bottom-color: #c8e6c9; }}
    tr.club-highlight td:nth-child(3) {{ font-weight: 600; color: #2e7d32; }}
    .legend {{
      background: white; border-radius: 12px; padding: 20px 24px;
      margin-top: 32px; margin-bottom: 24px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.08);
      scroll-margin-top: 24px;
    }}
    .legend h2 {{ margin: 0 0 8px; font-size: 20px; color: #3949ab; }}
    .legend-intro {{ margin: 0 0 16px; font-size: 14px; color: #555; }}
    .legend dl {{ margin: 0; display: grid; gap: 12px; }}
    .legend dt {{ font-weight: 600; font-size: 14px; color: #222; }}
    .legend dd {{ margin: 4px 0 0; font-size: 14px; color: #444; line-height: 1.45; }}
    .copy-nomination-col {{ width: 44px; text-align: center; }}
    .copy-nomination-cell {{ width: 44px; text-align: center; }}
    .copy-nomination-btn {{
      min-width: 52px; height: 28px; padding: 0 6px; border: 1px solid #c5cae9; border-radius: 8px;
      background: #eef2ff; color: #3949ab; cursor: pointer; font-size: 11px; font-weight: 600; line-height: 1;
    }}
    .copy-nomination-btn:hover {{ background: #e8eaf6; }}
    .copy-nomination-btn.copy-nomination-ok {{ background: #c8e6c9; border-color: #81c784; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>{escape_html(tournament_name)}</h1>
      <div class="stats" id="header-stats">
        <span>Datum: {escape_html(tournament_date)}</span>
        <span>Zavodnici: {escape_html(competitors)}</span>
        <span>Starty: {escape_html(starts)}</span>
        <span>Kluby: {escape_html(clubs)}</span>
        <span>Kola: {escape_html(rounds)}</span>
      </div>
    </header>
    {login_html}
    {content_open}
    <section class="filters">
      <div class="filters-row">
        <div class="filter-field">
          <label for="filter-club">Klub</label>
          <select id="filter-club"><option value="">Vše</option></select>
        </div>
        <div class="filter-field">
          <label for="filter-main">Hlavní</label>
          <select id="filter-main"><option value="">Vše</option></select>
        </div>
        <div class="filter-field">
          <label for="filter-detail">Detail</label>
          <select id="filter-detail"><option value="">Vše</option></select>
        </div>
        <button type="button" id="filter-reset">Zrušit filtry</button>
      </div>
      <div class="filter-checkboxes">
        <label>
          <input type="checkbox" id="filter-only-club" disabled>
          <span>Jen vybraný klub</span>
        </label>
        <label>
          <input type="checkbox" id="filter-only-postup">
          <span>Jen postupy</span>
        </label>
        <label>
          <input type="checkbox" id="filter-only-remiza">
          <span>Jen remízy</span>
        </label>
      </div>
      <p class="filter-status" id="filter-status"></p>
    </section>
    {''.join(discipline_html)}
    {legend_html}
    </div>
  </div>
{tail_scripts}
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generuje HTML prezentaci vysledku")
    parser.add_argument("--input", type=Path, default=AGGREGATED_XML)
    parser.add_argument("--csv", type=Path, default=EXCEL_CSV)
    parser.add_argument("--output", type=Path, default=PRESENTATION_HTML)
    args = parser.parse_args()

    if not args.input.is_file():
        print(f"Chyba: {args.input} neexistuje")
        return 1
    if not args.csv.is_file():
        print(f"Chyba: {args.csv} neexistuje, spust nejprve excel export")
        return 1

    generate_html(args.input, args.csv, args.output)
    print(f"HTML prezentace: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
