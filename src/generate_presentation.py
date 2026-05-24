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
    NOMINATION_API_URL,
    PRESENTATION_HTML,
    QUALIFYING_PLACES,
)
from nomination_io import format_category_name, xml_text
from qualification import analyze_category_qualification, is_ano_value
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
TABLE_HEAD_POSTUP = f"<th>{LEGEND_LINK_KRAJE}</th><th>{LEGEND_LINK_POSTUPUJE}</th><th></th>"


NOMINATION_SCRIPT = """
(function () {
  const apiUrl = window.NOMINATION_API_URL;
  const sessionKey = "nominace-mcr-session";
  const filterData = window.PRESENTATION_FILTER_DATA;

  const roleSelect = document.getElementById("login-role");
  const clubWrap = document.getElementById("login-club-wrap");
  const clubSelect = document.getElementById("login-club");
  const passwordInput = document.getElementById("login-password");
  const loginButton = document.getElementById("login-submit");
  const logoutButton = document.getElementById("login-logout");
  const loginStatus = document.getElementById("login-status");

  function loadSession() {
    try {
      return JSON.parse(sessionStorage.getItem(sessionKey) || "null");
    } catch {
      return null;
    }
  }

  function saveSession(session) {
    if (session) {
      sessionStorage.setItem(sessionKey, JSON.stringify(session));
    } else {
      sessionStorage.removeItem(sessionKey);
    }
  }

  function canEditRow(row, session) {
    if (!session || !session.token) return false;
    if (session.role === "stk") return true;
    return row.dataset.club === session.club;
  }

  function applyClubFilterForSession(session) {
    const filterClubSelect = document.getElementById("filter-club");
    if (!filterClubSelect || !session) return;
    if (session.role === "trener" && session.club && filterData.clubs.includes(session.club)) {
      filterClubSelect.value = session.club;
      filterClubSelect.dispatchEvent(new Event("change"));
    }
  }

  function clearClubFilter() {
    const filterClubSelect = document.getElementById("filter-club");
    if (!filterClubSelect) return;
    filterClubSelect.value = "";
    filterClubSelect.dispatchEvent(new Event("change"));
  }

  function updateLoginUi() {
    const session = loadSession();
    const loggedIn = Boolean(session && session.token);
    roleSelect.disabled = loggedIn;
    clubSelect.disabled = loggedIn;
    passwordInput.disabled = loggedIn;
    loginButton.hidden = loggedIn;
    logoutButton.hidden = !loggedIn;

    if (loggedIn) {
      const label = session.role === "stk"
        ? "STK (vsechny kluby)"
        : (session.club || "trener");
      loginStatus.textContent = "Prihlasen: " + label;
      applyClubFilterForSession(session);
    } else {
      loginStatus.textContent = "";
    }
    updateActionMenus();
  }

  function updateActionMenus() {
    const session = loadSession();
    const loggedIn = Boolean(session && session.token);

    document.querySelectorAll("tbody tr[data-firstname]").forEach((row) => {
      const cell = row.querySelector(".nomination-actions");
      const wrap = row.querySelector(".nomination-menu-wrap");
      if (!cell) return;
      const allowed = canEditRow(row, session);
      cell.hidden = !allowed;
      if (!allowed && wrap) {
        closeMenu(wrap);
      }
    });

    document.querySelectorAll("table thead th:last-child").forEach((header) => {
      header.hidden = !loggedIn;
    });
  }

  function closeMenu(wrap) {
    if (!wrap) return;
    const panel = wrap.querySelector(".nomination-menu-panel");
    const button = wrap.querySelector(".nomination-menu-btn");
    if (panel) panel.hidden = true;
    if (button) button.setAttribute("aria-expanded", "false");
  }

  function closeAllMenus() {
    document.querySelectorAll(".nomination-menu-wrap").forEach(closeMenu);
  }

  function setRowPostup(row, postupuje, postupKraje) {
    row.dataset.postupuje = postupuje;
    row.dataset.postupKraje = postupKraje;
    const krajeCell = row.querySelector(".postup-z-kraje-cell");
    const postupujeCell = row.querySelector(".postupuje-cell");
    if (krajeCell) {
      krajeCell.textContent = postupKraje;
      krajeCell.className = "postup-z-kraje-cell " + (postupKraje.startsWith("ANO") ? "postup-z-kraje-ano" : "postup-z-kraje-ne");
    }
    if (postupujeCell) {
      postupujeCell.textContent = postupuje;
      postupujeCell.className = "postupuje-cell " + (postupuje.startsWith("ANO") ? "postupuje-ano" : "postupuje-ne");
    }
  }

  function formatApiError(data, status) {
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) {
      return data.detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
    }
    return "HTTP " + status;
  }

  async function sendNomination(row, action) {
    const session = loadSession();
    if (!session || !session.token) {
      alert("Nejdriv se prihlas.");
      return;
    }
    if (!canEditRow(row, session)) {
      alert("Nemas opravneni pro tento radek.");
      return;
    }

    const payload = {
      firstname: row.dataset.firstname,
      lastname: row.dataset.lastname,
      category: row.dataset.category,
      action: action,
    };

    loginStatus.textContent = "Ukladam...";
    try {
      const response = await fetch(apiUrl + "/api/v1/nomination", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer " + session.token,
        },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(formatApiError(data, response.status));
      }
      setRowPostup(row, data.postupuje, data.postup_kraje);
      loginStatus.textContent = "Ulozeno.";
      closeAllMenus();
      if (typeof window.applyPresentationFilters === "function") {
        window.applyPresentationFilters();
      }
    } catch (error) {
      loginStatus.textContent = "Chyba: " + error.message;
      alert("Chyba: " + error.message);
    }
    updateLoginUi();
  }

  async function login() {
    const role = roleSelect.value;
    const club = clubSelect.value;
    const password = passwordInput.value;
    if (!password) {
      alert("Zadej heslo.");
      return;
    }
    if (role === "trener" && !club) {
      alert("Vyber klub.");
      return;
    }

    const body = { password: password };
    if (role === "trener") body.club = club;

    loginStatus.textContent = "Prihlasuji...";
    try {
      const response = await fetch(apiUrl + "/api/v1/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(formatApiError(data, response.status));
      }
      saveSession({
        token: data.token,
        role: data.role,
        club: data.club || null,
      });
      passwordInput.value = "";
    } catch (error) {
      loginStatus.textContent = "Chyba: " + error.message;
      alert("Prihlaseni selhalo: " + error.message);
      return;
    }
    updateLoginUi();
  }

  function logout() {
    saveSession(null);
    closeAllMenus();
    clearClubFilter();
    updateLoginUi();
  }

  function toggleClubField() {
    const isStk = roleSelect.value === "stk";
    clubWrap.hidden = isStk;
    if (isStk) clubSelect.value = "";
  }

  filterData.clubs.forEach((club) => {
    const option = document.createElement("option");
    option.value = club;
    option.textContent = club;
    clubSelect.appendChild(option);
  });

  document.querySelectorAll(".nomination-menu-wrap").forEach((wrap) => {
    const button = wrap.querySelector(".nomination-menu-btn");
    const panel = wrap.querySelector(".nomination-menu-panel");
    if (!button || !panel) return;

    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const willOpen = panel.hidden;
      closeAllMenus();
      panel.hidden = !willOpen;
      button.setAttribute("aria-expanded", willOpen ? "true" : "false");
    });

    panel.querySelectorAll("[data-action]").forEach((item) => {
      item.addEventListener("click", () => {
        const row = wrap.closest("tr");
        if (row) sendNomination(row, item.dataset.action);
      });
    });
  });

  document.addEventListener("click", closeAllMenus);
  roleSelect.addEventListener("change", toggleClubField);
  loginButton.addEventListener("click", login);
  logoutButton.addEventListener("click", logout);
  passwordInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") login();
  });

  window.updateNominationMenus = updateActionMenus;
  toggleClubField();
  updateLoginUi();
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
    const krajeValue = row.dataset.postupKraje || "";
    return postupujeValue.startsWith("ANO") || krajeValue.startsWith("ANO");
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
            "Postup z pořadí (místo v top "
            f"{limit} podle bodů). Nominace ho nemění.",
        ),
        (
            "Postupuje: ANO (potvrzeno)",
            "Postup z Kraje a klub potvrdil nominaci (soubor v nominations/).",
        ),
        (
            "Postupuje: ANO (remíza)",
            "Aktivní remíza na hraně postupu "
            f"({limit}. místo): stejný počet neodmítnutých na stejné pozici.",
        ),
        (
            "Postupuje: NE (zájem o postup)",
            "Mimo postup z pořadí, ale klub projevil zájem (nominations/) "
            "a není volný slot.",
        ),
        (
            "Postupuje: NE (odmítnuto)",
            "Klub nominaci odmítl (nominations-declined/). U postupujícího "
            "uvolní slot pro zájemce.",
        ),
        (
            "Postupuje: NE",
            "Nepostupuje (mimo postup z pořadí, bez aktivní nominace nebo slotu).",
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


def generate_html(xml_path: Path, csv_path: Path, output_path: Path) -> None:
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
        positions = [row.get("Pořadí", "") for row in category_rows]
        category_note = (
            category_rows[0].get("Poznamka postupu", "").strip()
            or analyze_category_qualification(positions).summary
        )
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

            action_cell = (
                '<td class="nomination-actions">'
                '<div class="nomination-menu-wrap">'
                '<button type="button" class="nomination-menu-btn" '
                'aria-label="Akce nominace" aria-expanded="false" '
                'aria-haspopup="true">&#8942;</button>'
                '<div class="nomination-menu-panel" hidden>'
                '<button type="button" data-action="confirm">Potvrdit nominaci</button>'
                '<button type="button" data-action="decline">Odmítnout</button>'
                '<button type="button" data-action="clear">Zrušit potvrzení / zájem o postup</button>'
                "</div></div></td>"
            )

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
                f"{action_cell}"
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
    .nomination-login {{
      background: white; border-radius: 12px; padding: 16px 20px;
      margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    }}
    .nomination-login-row {{
      display: flex; flex-wrap: wrap; gap: 16px; align-items: end;
    }}
    .nomination-login-row label {{
      display: flex; flex-direction: column; gap: 4px; min-width: 160px; flex: 1;
      font-size: 12px; font-weight: 600; color: #555; text-transform: uppercase;
    }}
    .nomination-login-row select,
    .nomination-login-row input,
    .nomination-login-row button {{
      font: inherit; padding: 8px 10px; border: 1px solid #ccc; border-radius: 8px; background: white;
    }}
    .nomination-login-row button {{ cursor: pointer; flex: 0; min-width: auto; text-transform: none; }}
    #login-status {{ font-size: 14px; color: #555; align-self: center; flex: 2; min-width: 200px; text-transform: none; font-weight: normal; }}
    .nomination-actions {{ width: 44px; text-align: center; position: relative; }}
    .nomination-actions[hidden] {{ display: none; }}
    .nomination-menu-btn {{
      width: 32px; height: 32px; border: 1px solid #c5cae9; border-radius: 8px;
      background: #eef2ff; color: #3949ab; cursor: pointer; font-size: 18px; line-height: 1;
    }}
    .nomination-menu-btn:hover {{ background: #e8eaf6; }}
    .nomination-menu-panel {{
      position: absolute; right: 0; top: calc(100% + 4px); z-index: 20;
      min-width: 180px; background: white; border: 1px solid #ddd; border-radius: 8px;
      box-shadow: 0 4px 16px rgba(0,0,0,0.12); display: flex; flex-direction: column; padding: 4px;
    }}
    .nomination-menu-panel[hidden] {{ display: none !important; }}
    .nomination-menu-panel button {{
      border: none; background: none; text-align: left; padding: 8px 12px;
      font: inherit; cursor: pointer; border-radius: 6px;
    }}
    .nomination-menu-panel button:hover {{ background: #f5f5f5; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>{escape_html(tournament_name)}</h1>
      <div class="stats">
        <span>Datum: {escape_html(tournament_date)}</span>
        <span>Zavodnici: {escape_html(competitors)}</span>
        <span>Starty: {escape_html(starts)}</span>
        <span>Kluby: {escape_html(clubs)}</span>
        <span>Kola: {escape_html(rounds)}</span>
      </div>
    </header>
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
    <section class="nomination-login">
      <div class="nomination-login-row">
        <label>Role
          <select id="login-role">
            <option value="trener">Trenér klubu</option>
            <option value="stk">STK</option>
          </select>
        </label>
        <label id="login-club-wrap">Klub
          <select id="login-club"><option value="">-- vyber --</option></select>
        </label>
        <label>Heslo
          <input type="password" id="login-password" autocomplete="current-password">
        </label>
        <button type="button" id="login-submit">Přihlásit</button>
        <button type="button" id="login-logout" hidden>Odhlásit</button>
        <span id="login-status"></span>
      </div>
    </section>
    {''.join(discipline_html)}
    {legend_html}
  </div>
  <script>window.PRESENTATION_FILTER_DATA = {filter_json};</script>
  <script>window.NOMINATION_API_URL = {json.dumps(NOMINATION_API_URL)};</script>
  <script>{FILTER_SCRIPT}</script>
  <script>{NOMINATION_SCRIPT}</script>
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
