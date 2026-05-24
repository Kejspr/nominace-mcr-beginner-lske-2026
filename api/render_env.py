#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persist TRAINER_AUTH on Render via API (bez redeploy)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List

RENDER_API = "https://api.render.com/v1"


def build_club_passwords(trainer_auth: List[Dict[str, Any]]) -> Dict[str, str]:
    passwords: Dict[str, str] = {}
    for item in trainer_auth:
        role = str(item.get("role", "trener")).strip().lower()
        club = str(item.get("club", "")).strip()
        password = item.get("password")
        if role == "trener" and club and password is not None:
            passwords[club] = str(password)
    return passwords


def render_configured() -> bool:
    return bool(os.environ.get("RENDER_API_KEY", "").strip()) and bool(
        os.environ.get("RENDER_SERVICE_ID", "").strip()
    )


def _http_json(
    method: str,
    url: str,
    headers: Dict[str, str],
    body: Any = None,
) -> Any:
    data = None
    request_headers = dict(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Render API {exc.code}: {detail}") from exc


def persist_trainer_auth_env(trainer_auth: List[Dict[str, Any]]) -> None:
    api_key = os.environ.get("RENDER_API_KEY", "").strip()
    service_id = os.environ.get("RENDER_SERVICE_ID", "").strip()
    if not api_key or not service_id:
        raise RuntimeError("Chybi RENDER_API_KEY nebo RENDER_SERVICE_ID")

    auth_json = json.dumps(trainer_auth, ensure_ascii=False)
    env_updates: List[Dict[str, str]] = [{"key": "TRAINER_AUTH", "value": auth_json}]
    club_passwords = build_club_passwords(trainer_auth)
    if club_passwords:
        env_updates.append(
            {
                "key": "CLUB_PASSWORDS",
                "value": json.dumps(club_passwords, ensure_ascii=False),
            }
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    _http_json(
        "PUT",
        f"{RENDER_API}/services/{service_id}/env-vars",
        headers,
        env_updates,
    )

    os.environ["TRAINER_AUTH"] = auth_json
    if club_passwords:
        os.environ["CLUB_PASSWORDS"] = json.dumps(club_passwords, ensure_ascii=False)
