"""Stateless signed session tokens (preziji redeploy API)."""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Literal, Optional, TypedDict


class SessionPayload(TypedDict):
    role: Literal["stk", "trener"]
    club: Optional[str]


SESSION_TTL_SECONDS = 7 * 24 * 3600


def _session_secret() -> bytes:
    explicit = os.environ.get("SESSION_SECRET", "").strip()
    if explicit:
        return explicit.encode("utf-8")
    raw = os.environ.get("TRAINER_AUTH", "").strip()
    if raw:
        return hashlib.sha256(raw.encode("utf-8")).digest()
    return b"nominace-mcr-beginner-dev-session-key"


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def encode_session_token(*, role: str, club: Optional[str]) -> str:
    payload = {
        "role": role,
        "club": club,
        "exp": int(time.time()) + SESSION_TTL_SECONDS,
    }
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64url_encode(
        hmac.new(_session_secret(), body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{sig}"


def decode_session_token(token: str) -> Optional[SessionPayload]:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expected = _b64url_encode(
        hmac.new(_session_secret(), body.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        return None
    role = payload.get("role")
    if role not in ("stk", "trener"):
        return None
    club = payload.get("club")
    if club is not None and not isinstance(club, str):
        return None
    return SessionPayload(role=role, club=club)
