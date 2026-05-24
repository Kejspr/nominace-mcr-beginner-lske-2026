#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimalni API pro nominace (Render). Cloudflare serviruje HTML, API uklada nominace."""

import json
import os
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from config import (  # noqa: E402
    AGGREGATED_XML,
    NOMINATIONS_DECLINED_DIR,
    NOMINATIONS_DIR,
    PRESENTATION_ORIGIN,
)
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

try:
    from render_env import persist_trainer_auth_env, render_configured  # noqa: E402
except ImportError:
    from api.render_env import persist_trainer_auth_env, render_configured  # noqa: E402

app = FastAPI(title="Nominace MCR Beginner API", version="0.1.0")

allowed_origins = [
    origin.strip()
    for origin in os.environ.get("ALLOWED_ORIGINS", PRESENTATION_ORIGIN).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

_sessions: Dict[str, "SessionInfo"] = {}


@dataclass(frozen=True)
class SessionInfo:
    role: Literal["stk", "trener"]
    club: Optional[str] = None


@dataclass(frozen=True)
class AuthEntry:
    role: Literal["stk", "trener"]
    password: str
    club: Optional[str] = None
    email: Optional[str] = None


AUTH_OVERRIDES_PATH = ROOT / "data" / "auth_overrides.json"


def auth_entry_key(role: str, club: Optional[str] = None) -> str:
    if role == "stk":
        return "stk"
    return f"trener:{club}"


def load_auth_overrides() -> Dict[str, str]:
    if not AUTH_OVERRIDES_PATH.is_file():
        return {}
    try:
        data = json.loads(AUTH_OVERRIDES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items()}


def save_auth_override(key: str, password: str) -> None:
    overrides = load_auth_overrides()
    overrides[key] = password
    AUTH_OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUTH_OVERRIDES_PATH.write_text(
        json.dumps(overrides, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def clear_auth_override(key: str) -> None:
    overrides = load_auth_overrides()
    if key not in overrides:
        return
    del overrides[key]
    if overrides:
        AUTH_OVERRIDES_PATH.write_text(
            json.dumps(overrides, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    elif AUTH_OVERRIDES_PATH.is_file():
        AUTH_OVERRIDES_PATH.unlink()


def load_trainer_auth_items() -> List[dict]:
    raw = os.environ.get("TRAINER_AUTH", "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="TRAINER_AUTH neni platny JSON") from exc
    if not isinstance(data, list):
        raise HTTPException(status_code=500, detail="TRAINER_AUTH musi byt seznam")
    return [dict(item) for item in data if isinstance(item, dict)]


def update_trainer_auth_password(role: str, club: Optional[str], new_password: str) -> List[dict]:
    items = load_trainer_auth_items()
    if not items:
        raise HTTPException(status_code=503, detail="TRAINER_AUTH neni nakonfigurovano")

    updated = False
    for item in items:
        item_role = str(item.get("role", "trener")).strip().lower()
        item_club = str(item.get("club", "")).strip() or None
        if role == "stk" and item_role == "stk":
            item["password"] = new_password
            updated = True
            break
        if role == "trener" and item_role == "trener" and item_club == club:
            item["password"] = new_password
            updated = True
            break

    if not updated:
        raise HTTPException(status_code=404, detail="Ucet v TRAINER_AUTH nenalezen")
    return items


def apply_auth_overrides(entries: List[AuthEntry]) -> List[AuthEntry]:
    overrides = load_auth_overrides()
    if not overrides:
        return entries
    updated: List[AuthEntry] = []
    for entry in entries:
        key = auth_entry_key(entry.role, entry.club)
        password = overrides.get(key, entry.password)
        updated.append(
            AuthEntry(role=entry.role, password=password, club=entry.club, email=entry.email)
        )
    return updated


def club_passwords() -> Dict[str, str]:
    raw = os.environ.get("CLUB_PASSWORDS", "{}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="CLUB_PASSWORDS neni platny JSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="CLUB_PASSWORDS musi byt objekt")
    return {str(club): str(password) for club, password in data.items()}


def trainer_auth_entries() -> List[AuthEntry]:
    raw = os.environ.get("TRAINER_AUTH", "").strip()
    entries: List[AuthEntry] = []

    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail="TRAINER_AUTH neni platny JSON") from exc
        if not isinstance(data, list):
            raise HTTPException(status_code=500, detail="TRAINER_AUTH musi byt seznam")
        for item in data:
            if not isinstance(item, dict):
                continue
            password = item.get("password")
            if password is None:
                continue
            role = str(item.get("role", "trener")).strip().lower()
            if role not in ("stk", "trener"):
                role = "trener"
            club = str(item.get("club", "")).strip() or None
            email = str(item.get("email", "")).strip() or None
            if role == "trener" and not club:
                continue
            entries.append(
                AuthEntry(
                    role=role,  # type: ignore[arg-type]
                    password=str(password),
                    club=club,
                    email=email,
                )
            )
        if entries:
            return apply_auth_overrides(entries)

    for club, password in club_passwords().items():
        entries.append(AuthEntry(role="trener", password=password, club=club))
    return apply_auth_overrides(entries)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def find_auth_entry_by_email(email: str) -> Optional[AuthEntry]:
    normalized = normalize_email(email)
    if not normalized:
        return None
    for entry in trainer_auth_entries():
        if entry.email and normalize_email(entry.email) == normalized:
            return entry
    return None


def require_session(authorization: Optional[str] = Header(default=None)) -> SessionInfo:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Chybi token")
    token = authorization.removeprefix("Bearer ").strip()
    session = _sessions.get(token)
    if not session:
        raise HTTPException(status_code=401, detail="Neplatny token")
    return session


def require_stk(session: SessionInfo = Depends(require_session)) -> SessionInfo:
    if session.role != "stk":
        raise HTTPException(status_code=403, detail="Pouze STK")
    return session


def validate_new_password(new_password: str) -> str:
    value = new_password.strip()
    if len(value) < 4:
        raise HTTPException(status_code=400, detail="Nove heslo je prilis kratke")
    return value


def apply_password_update(role: str, club: Optional[str], new_password: str) -> None:
    password = validate_new_password(new_password)
    if not render_configured():
        raise HTTPException(
            status_code=503,
            detail="Trvala zmena hesla neni nakonfigurovana (RENDER_API_KEY, RENDER_SERVICE_ID)",
        )

    key = auth_entry_key(role, club)
    items = update_trainer_auth_password(role, club, password)
    try:
        persist_trainer_auth_env(items)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    clear_auth_override(key)


class LoginRequest(BaseModel):
    password: str
    email: Optional[str] = None
    club: Optional[str] = None


class LoginResponse(BaseModel):
    token: str
    role: Literal["stk", "trener"]
    club: Optional[str] = None
    email: Optional[str] = None


class AuthProfileResponse(BaseModel):
    email: str
    role: Literal["stk", "trener"]
    club: Optional[str] = None
    label: str


class PostupujeStateItem(BaseModel):
    firstname: str
    lastname: str
    category: str
    postupuje: str
    postup_kraje: str


class PostupujeStateResponse(BaseModel):
    items: List[PostupujeStateItem]


class LoginAccountOption(BaseModel):
    value: str
    label: str
    role: Literal["stk", "trener"]


class LoginAccountsResponse(BaseModel):
    accounts: List[LoginAccountOption]


class NominationRequest(BaseModel):
    firstname: str
    lastname: str
    category: str = Field(description="Presny nazev kategorie z tabulky")
    action: Literal["confirm", "decline", "clear"]


class NominationResponse(BaseModel):
    ok: bool
    postupuje: str
    postup_kraje: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class ChangePasswordResponse(BaseModel):
    ok: bool


class ResetPasswordRequest(BaseModel):
    target_role: Literal["stk", "trener"]
    club: Optional[str] = None
    new_password: str


class ResetPasswordResponse(BaseModel):
    ok: bool


class PasswordHelpResponse(BaseModel):
    stk_emails: List[str]


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


def build_postupuje_state_items() -> List[PostupujeStateItem]:
    if not AGGREGATED_XML.is_file():
        raise HTTPException(status_code=503, detail="Chybi aggregated-results.xml")

    root = ET.parse(AGGREGATED_XML).getroot()
    nomination_data = load_nominations(AGGREGATED_XML, write_log=False)
    postupuje_map = compute_postupuje_map(root, nomination_data)
    items: List[PostupujeStateItem] = []

    for category in root.findall("category"):
        disciplina = xml_text(category, "disciplina")
        kategorie1 = xml_text(category, "kategorie1")
        kategorie2 = xml_text(category, "kategorie2")
        display = format_category_name(disciplina, kategorie1, kategorie2)
        positions = [xml_text(result, "position") for result in category.findall("result")]
        tied = tied_position_labels(positions)
        for result in category.findall("result"):
            fn = xml_text(result, "firstname")
            ln = xml_text(result, "lastname")
            key = nomination_key(fn, ln, disciplina, kategorie1, kategorie2)
            position = xml_text(result, "position")
            items.append(
                PostupujeStateItem(
                    firstname=fn,
                    lastname=ln,
                    category=display,
                    postupuje=postupuje_map.get(key, "NE"),
                    postup_kraje=regional_qualifier_label(position, tied),
                )
            )
    return items


def lookup_postupuje(firstname: str, lastname: str, category_display: str) -> tuple[str, str]:
    for item in build_postupuje_state_items():
        if item.firstname == firstname and item.lastname == lastname and item.category == category_display:
            return item.postupuje, item.postup_kraje
    raise HTTPException(status_code=404, detail="Zavodnik v kategorii nenalezen")


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "aggregated_xml": AGGREGATED_XML.is_file(),
    }


@app.get("/api/v1/login-accounts", response_model=LoginAccountsResponse)
def login_accounts() -> LoginAccountsResponse:
    accounts: List[LoginAccountOption] = []
    seen_clubs: set[str] = set()
    for entry in trainer_auth_entries():
        if entry.role == "stk":
            if not any(item.value == "stk" for item in accounts):
                accounts.append(LoginAccountOption(value="stk", label="STK", role="stk"))
        elif entry.role == "trener" and entry.club and entry.club not in seen_clubs:
            seen_clubs.add(entry.club)
            accounts.append(
                LoginAccountOption(value=entry.club, label=entry.club, role="trener")
            )
    accounts.sort(key=lambda item: (0 if item.role == "stk" else 1, item.label.lower()))
    return LoginAccountsResponse(accounts=accounts)


@app.get("/api/v1/postupuje-state", response_model=PostupujeStateResponse)
def postupuje_state() -> PostupujeStateResponse:
    return PostupujeStateResponse(items=build_postupuje_state_items())


@app.get("/api/v1/auth-profile", response_model=AuthProfileResponse)
def auth_profile(email: str) -> AuthProfileResponse:
    entry = find_auth_entry_by_email(email)
    if not entry or not entry.email:
        raise HTTPException(status_code=404, detail="Ucet neni v systemu")
    label = "STK" if entry.role == "stk" else (entry.club or "Trener")
    return AuthProfileResponse(
        email=entry.email,
        role=entry.role,
        club=entry.club,
        label=label,
    )


@app.post("/api/v1/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    email = (body.email or "").strip()
    if email:
        auth = find_auth_entry_by_email(email)
        if not auth or not secrets.compare_digest(auth.password, body.password):
            raise HTTPException(status_code=401, detail="Spatne prihlaseni")
    else:
        club = (body.club or "").strip()
        matches: List[AuthEntry] = []
        for entry in trainer_auth_entries():
            if not secrets.compare_digest(entry.password, body.password):
                continue
            if entry.role == "stk" and not club:
                matches.append(entry)
            elif entry.role == "trener" and club and entry.club == club:
                matches.append(entry)
        if not matches:
            raise HTTPException(status_code=401, detail="Spatne prihlaseni")
        auth = matches[0]

    token = secrets.token_urlsafe(32)
    _sessions[token] = SessionInfo(role=auth.role, club=auth.club)
    return LoginResponse(token=token, role=auth.role, club=auth.club, email=auth.email)


@app.get("/api/v1/password-help", response_model=PasswordHelpResponse)
def password_help() -> PasswordHelpResponse:
    emails = sorted(
        {
            entry.email
            for entry in trainer_auth_entries()
            if entry.role == "stk" and entry.email
        }
    )
    return PasswordHelpResponse(stk_emails=emails)


@app.post("/api/v1/change-password", response_model=ChangePasswordResponse)
def change_password(
    body: ChangePasswordRequest,
    session: SessionInfo = Depends(require_session),
) -> ChangePasswordResponse:
    key = auth_entry_key(session.role, session.club)
    current_password = None
    for entry in trainer_auth_entries():
        if auth_entry_key(entry.role, entry.club) == key:
            current_password = entry.password
            break

    if current_password is None or not secrets.compare_digest(current_password, body.old_password):
        raise HTTPException(status_code=401, detail="Spatne stavajici heslo")

    apply_password_update(session.role, session.club, body.new_password)
    return ChangePasswordResponse(ok=True)


@app.post("/api/v1/reset-password", response_model=ResetPasswordResponse)
def reset_password(
    body: ResetPasswordRequest,
    session: SessionInfo = Depends(require_stk),
) -> ResetPasswordResponse:
    del session  # STK session required via dependency

    if body.target_role == "trener":
        club = (body.club or "").strip()
        if not club:
            raise HTTPException(status_code=400, detail="Chybi klub")
        has_account = any(
            entry.role == "trener" and entry.club == club for entry in trainer_auth_entries()
        )
        if not has_account:
            raise HTTPException(status_code=404, detail="Klub nema ucet v TRAINER_AUTH")
        apply_password_update("trener", club, body.new_password)
    else:
        has_stk = any(entry.role == "stk" for entry in trainer_auth_entries())
        if not has_stk:
            raise HTTPException(status_code=404, detail="STK ucet neni v TRAINER_AUTH")
        apply_password_update("stk", None, body.new_password)

    return ResetPasswordResponse(ok=True)


def can_edit_club(session: SessionInfo, athlete_club: str) -> bool:
    if session.role == "stk":
        return True
    return session.club == athlete_club


@app.post("/api/v1/nomination", response_model=NominationResponse)
def set_nomination(
    body: NominationRequest,
    session: SessionInfo = Depends(require_session),
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

    if not athlete_club:
        raise HTTPException(status_code=404, detail="Zavodnik v kategorii nenalezen")

    if not can_edit_club(session, athlete_club):
        raise HTTPException(status_code=403, detail="Trener muze editovat jen svuj klub")

    confirm_path = NOMINATIONS_DIR / club_nomination_filename(athlete_club)
    decline_path = NOMINATIONS_DECLINED_DIR / club_nomination_filename(athlete_club)
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
