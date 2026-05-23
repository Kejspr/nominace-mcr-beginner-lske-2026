#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimalni API pro nominace (Render). Cloudflare serviruje HTML, API uklada nominace."""

import json
import os
import secrets
import sys
from pathlib import Path
from typing import Dict, Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from config import AGGREGATED_XML, NOMINATIONS_DECLINED_DIR, NOMINATIONS_DIR  # noqa: E402
from nomination_io import (  # noqa: E402
    club_nomination_filename,
    compute_postupuje_map,
    format_category_name,
    load_nominations,
    nomination_key,
    xml_text,
)
import xml.etree.ElementTree as ET  # noqa: E402
from qualification import regional_qualifier_label, tied_position_labels  # noqa: E402

app = FastAPI(title="Nominace MCR Beginner API", version="0.1.0")

allowed_origins = [
    origin.strip()
    for origin in os.environ.get("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
if allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

_sessions: Dict[str, str] = {}


def club_passwords() -> Dict[str, str]:
    raw = os.environ.get("CLUB_PASSWORDS", "{}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="CLUB_PASSWORDS neni platny JSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="CLUB_PASSWORDS musi byt objekt")
    return {str(club): str(password) for club, password in data.items()}


def require_token(authorization: Optional[str] = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Chybi token")
    token = authorization.removeprefix("Bearer ").strip()
    club = _sessions.get(token)
    if not club:
        raise HTTPException(status_code=401, detail="Neplatny token")
    return club


class LoginRequest(BaseModel):
    club: str
    password: str


class LoginResponse(BaseModel):
    token: str
    club: str


class NominationRequest(BaseModel):
    firstname: str
    lastname: str
    category: str = Field(description="Presny nazev kategorie z tabulky")
    action: Literal["confirm", "decline", "clear"]


class NominationResponse(BaseModel):
    ok: bool
    postupuje: str
    postup_kraje: str


def nomination_line(firstname: str, lastname: str, category: str) -> str:
    return f"{firstname} {lastname} - {category}"


def read_nomination_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if stripped and not stripped.startswith("#"):
            lines.append(stripped)
    return lines


def write_nomination_lines(path: Path, lines: list[str]) -> None:
    header = []
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw.strip().startswith("#") or not raw.strip():
                header.append(raw)
            else:
                break
    if not header:
        header = [f"# Klub: {path.stem.replace('_', ' ')}", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(header + lines) + ("\n" if lines or header else "")
    path.write_text(body, encoding="utf-8")


def remove_line_for_athlete(lines: list[str], firstname: str, lastname: str, category: str) -> list[str]:
    prefix = f"{firstname} {lastname} - "
    suffix = f" - {category}"
    kept: list[str] = []
    for line in lines:
        if line.startswith(prefix) and line.endswith(suffix):
            continue
        if line == nomination_line(firstname, lastname, category):
            continue
        kept.append(line)
    return kept


def append_line(lines: list[str], line: str) -> list[str]:
    if line in lines:
        return lines
    return lines + [line]


def lookup_postupuje(firstname: str, lastname: str, category_display: str) -> tuple[str, str]:
    if not AGGREGATED_XML.is_file():
        raise HTTPException(status_code=503, detail="Chybi aggregated-results.xml")

    root = ET.parse(AGGREGATED_XML).getroot()
    nomination_data = load_nominations(AGGREGATED_XML, write_log=False)
    postupuje_map = compute_postupuje_map(root, nomination_data)

    for category in root.findall("category"):
        disciplina = xml_text(category, "disciplina")
        kategorie1 = xml_text(category, "kategorie1")
        kategorie2 = xml_text(category, "kategorie2")
        display = format_category_name(disciplina, kategorie1, kategorie2)
        if display != category_display:
            continue
        positions = [xml_text(result, "position") for result in category.findall("result")]
        tied = tied_position_labels(positions)
        for result in category.findall("result"):
            fn = xml_text(result, "firstname")
            ln = xml_text(result, "lastname")
            if fn != firstname or ln != lastname:
                continue
            key = nomination_key(fn, ln, disciplina, kategorie1, kategorie2)
            postupuje = postupuje_map.get(key, "NE")
            position = xml_text(result, "position")
            postup_kraje = regional_qualifier_label(position, tied)
            return postupuje, postup_kraje

    raise HTTPException(status_code=404, detail="Zavodnik v kategorii nenalezen")


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "aggregated_xml": AGGREGATED_XML.is_file(),
    }


@app.post("/api/v1/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    passwords = club_passwords()
    expected = passwords.get(body.club)
    if expected is None or not secrets.compare_digest(expected, body.password):
        raise HTTPException(status_code=401, detail="Spatny klub nebo heslo")
    token = secrets.token_urlsafe(32)
    _sessions[token] = body.club
    return LoginResponse(token=token, club=body.club)


@app.post("/api/v1/nomination", response_model=NominationResponse)
def set_nomination(
    body: NominationRequest,
    club: str = Depends(require_token),
) -> NominationResponse:
    if not AGGREGATED_XML.is_file():
        raise HTTPException(status_code=503, detail="Chybi aggregated-results.xml na serveru")

    root = ET.parse(AGGREGATED_XML).getroot()
    athlete_club = None
    for category in root.findall("category"):
        display = format_category_name(
            xml_text(category, "disciplina"),
            xml_text(category, "kategorie1"),
            xml_text(category, "kategorie2"),
        )
        if display != body.category:
            continue
        for result in category.findall("result"):
            if xml_text(result, "firstname") == body.firstname and xml_text(result, "lastname") == body.lastname:
                athlete_club = xml_text(result, "club")
                break
        if athlete_club:
            break

    if athlete_club != club:
        raise HTTPException(status_code=403, detail="Zavodnik nepatri do vaseho klubu")

    confirm_path = NOMINATIONS_DIR / club_nomination_filename(club)
    decline_path = NOMINATIONS_DECLINED_DIR / club_nomination_filename(club)
    line = nomination_line(body.firstname, body.lastname, body.category)

    confirm_lines = read_nomination_lines(confirm_path)
    decline_lines = read_nomination_lines(decline_path)
    confirm_lines = remove_line_for_athlete(confirm_lines, body.firstname, body.lastname, body.category)
    decline_lines = remove_line_for_athlete(decline_lines, body.firstname, body.lastname, body.category)

    if body.action == "confirm":
        confirm_lines = append_line(confirm_lines, line)
    elif body.action == "decline":
        decline_lines = append_line(decline_lines, line)

    write_nomination_lines(confirm_path, confirm_lines)
    write_nomination_lines(decline_path, decline_lines)

    postupuje, postup_kraje = lookup_postupuje(body.firstname, body.lastname, body.category)
    return NominationResponse(ok=True, postupuje=postupuje, postup_kraje=postup_kraje)
