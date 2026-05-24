#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sync config/trainers.yaml -> Cloudflare Access (e-maily) + Render (CLUB_PASSWORDS)."""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
TRAINERS_PATH = ROOT / "config" / "trainers.yaml"
SYNC_ENV_PATH = ROOT / "config" / "sync.env"

CF_API = "https://api.cloudflare.com/client/v4"
RENDER_API = "https://api.render.com/v1"


def parse_yaml_value(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return ""
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value


def load_trainers(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Chybi {path} (zkopiruj z config/trainers.yaml.example)")

    trainers: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    in_trainers = False

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "trainers:":
            in_trainers = True
            continue
        if not in_trainers:
            continue
        if stripped.startswith("- "):
            if current:
                trainers.append(current)
            current = {}
            rest = stripped[2:].strip()
            if rest and ":" in rest:
                key, _, value = rest.partition(":")
                current[key.strip()] = parse_yaml_value(value)
            continue
        if current is not None and ":" in stripped:
            key, _, value = stripped.partition(":")
            current[key.strip()] = parse_yaml_value(value)

    if current:
        trainers.append(current)
    if not trainers:
        raise ValueError("trainers.yaml: prazdny seznam trainers")
    return trainers


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if value or key not in os.environ:
            os.environ[key] = value


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def extract_emails(trainers: List[Dict[str, Any]]) -> List[str]:
    emails: List[str] = []
    seen = set()
    for entry in trainers:
        email = str(entry.get("email", "")).strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        emails.append(email)
    return sorted(emails)


def extract_club_passwords(trainers: List[Dict[str, Any]]) -> Dict[str, str]:
    passwords: Dict[str, str] = {}
    for entry in trainers:
        role = str(entry.get("role", "trener")).strip().lower()
        if role == "stk":
            continue
        club = str(entry.get("club", "")).strip()
        password = entry.get("password")
        if not club or password is None:
            continue
        password_str = str(password)
        if club in passwords and passwords[club] != password_str:
            raise ValueError(f"Duplicitni heslo pro klub: {club}")
        passwords[club] = password_str
    return passwords


def extract_trainer_auth(trainers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for entry in trainers:
        password = entry.get("password")
        if password is None:
            continue
        role = str(entry.get("role", "trener")).strip().lower()
        if role not in ("stk", "trener"):
            role = "trener"
        club = str(entry.get("club", "")).strip()
        email = str(entry.get("email", "")).strip()
        if role == "trener" and not club:
            continue
        item: Dict[str, Any] = {"role": role, "password": str(password)}
        if club:
            item["club"] = club
        if email:
            item["email"] = email
        entries.append(item)
    return entries


def http_json(
    method: str,
    url: str,
    headers: Dict[str, str],
    body: Optional[Any] = None,
) -> Any:
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers = {**headers, "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60, context=ssl_context()) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {method} {url}\n{detail}") from exc
    except urllib.error.URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            raise RuntimeError(
                "SSL certifikaty pro Python chybi. Spust:\n"
                "  python3 -m pip install certifi\n"
                "nebo na Macu: /Applications/Python 3.9/Install Certificates.command"
            ) from exc
        raise


def cf_headers() -> Dict[str, str]:
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Chybi CLOUDFLARE_API_TOKEN v config/sync.env")
    return {"Authorization": f"Bearer {token}"}


def cf_account_id() -> str:
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not account_id:
        raise RuntimeError("Chybi CLOUDFLARE_ACCOUNT_ID v config/sync.env")
    return account_id


def cf_list_apps() -> None:
    account_id = cf_account_id()
    payload = http_json(
        "GET",
        f"{CF_API}/accounts/{account_id}/access/apps",
        cf_headers(),
    )
    if not payload.get("success"):
        raise RuntimeError(f"Cloudflare API chyba: {payload}")
    print("Cloudflare Access aplikace:")
    for app in payload.get("result", []):
        print(f"  app_id={app.get('id')}  name={app.get('name')}  domain={app.get('domain')}")


def cf_list_policies(app_id: str) -> None:
    account_id = cf_account_id()
    payload = http_json(
        "GET",
        f"{CF_API}/accounts/{account_id}/access/apps/{app_id}/policies",
        cf_headers(),
    )
    if not payload.get("success"):
        raise RuntimeError(f"Cloudflare API chyba: {payload}")
    print(f"Policy pro app {app_id}:")
    for policy in payload.get("result", []):
        print(
            f"  policy_id={policy.get('id')}  name={policy.get('name')}  "
            f"decision={policy.get('decision')}"
        )


def is_email_include_rule(rule: Any) -> bool:
    return isinstance(rule, dict) and "email" in rule


def build_include_rules(emails: List[str], current_include: List[Any]) -> List[Any]:
    preserved = [rule for rule in current_include if not is_email_include_rule(rule)]
    email_rules = [{"email": {"email": email}} for email in emails]
    return preserved + email_rules


def cf_reusable_policy_url(account_id: str, policy_id: str) -> str:
    return f"{CF_API}/accounts/{account_id}/access/policies/{policy_id}"


def cf_app_policy_url(account_id: str, app_id: str, policy_id: str) -> str:
    return f"{CF_API}/accounts/{account_id}/access/apps/{app_id}/policies/{policy_id}"


def cf_policy_is_reusable() -> bool:
    value = os.environ.get("CLOUDFLARE_ACCESS_POLICY_REUSABLE", "true").strip().lower()
    return value in ("1", "true", "yes")


def cf_get_access_policy(account_id: str, app_id: str, policy_id: str) -> Dict[str, Any]:
    urls: List[str] = []
    if cf_policy_is_reusable():
        urls.append(cf_reusable_policy_url(account_id, policy_id))
    if app_id:
        urls.append(cf_app_policy_url(account_id, app_id, policy_id))
    if not urls:
        urls.append(cf_reusable_policy_url(account_id, policy_id))

    last_error: Optional[RuntimeError] = None
    for url in urls:
        try:
            payload = http_json("GET", url, cf_headers())
        except RuntimeError as exc:
            last_error = exc
            continue
        if payload.get("success"):
            return payload["result"]
        last_error = RuntimeError(f"Cloudflare GET policy: {payload}")
    if last_error:
        raise last_error
    raise RuntimeError("Cloudflare GET policy: neznamy stav")


def cf_put_access_policy(
    account_id: str,
    app_id: str,
    policy_id: str,
    update_body: Dict[str, Any],
) -> None:
    urls: List[str] = []
    if cf_policy_is_reusable():
        urls.append(cf_reusable_policy_url(account_id, policy_id))
    if app_id:
        urls.append(cf_app_policy_url(account_id, app_id, policy_id))
    if not urls:
        urls.append(cf_reusable_policy_url(account_id, policy_id))

    last_error: Optional[RuntimeError] = None
    for url in urls:
        try:
            result = http_json("PUT", url, cf_headers(), update_body)
        except RuntimeError as exc:
            if "12130" in str(exc) or "reusable policies" in str(exc):
                last_error = exc
                continue
            raise
        if result.get("success"):
            return
        last_error = RuntimeError(f"Cloudflare PUT policy: {result}")
    if last_error:
        raise last_error
    raise RuntimeError("Cloudflare PUT policy: neznamy stav")


def sync_cloudflare(emails: List[str], dry_run: bool) -> None:
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    app_id = os.environ.get("CLOUDFLARE_ACCESS_APP_ID", "").strip()
    policy_id = os.environ.get("CLOUDFLARE_ACCESS_POLICY_ID", "").strip()
    if not account_id or not policy_id:
        print("Cloudflare: preskoceno (chybi ACCOUNT_ID / POLICY_ID)")
        return
    if not emails:
        print("Cloudflare: zadne e-maily v trainers.yaml")
        return

    policy = cf_get_access_policy(account_id, app_id, policy_id)
    current_include = policy.get("include") or []
    new_include = build_include_rules(emails, current_include)

    update_body = {
        "decision": policy.get("decision", "allow"),
        "include": new_include,
        "name": policy.get("name", "Allow trainers"),
    }
    for optional in ("exclude", "require", "precedence", "session_duration"):
        if optional in policy and policy[optional] is not None:
            update_body[optional] = policy[optional]

    print(f"Cloudflare Access: {len(emails)} e-mail(u)")
    for email in emails:
        print(f"  - {email}")

    if dry_run:
        print("Cloudflare: dry-run, nic se neposlalo")
        return

    cf_put_access_policy(account_id, app_id, policy_id, update_body)
    print("Cloudflare: OK")


def render_headers() -> Dict[str, str]:
    api_key = os.environ.get("RENDER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Chybi RENDER_API_KEY v config/sync.env")
    return {"Authorization": f"Bearer {api_key}"}


def render_resolve_service_id() -> str:
    service_id = os.environ.get("RENDER_SERVICE_ID", "").strip()
    if service_id:
        return service_id
    service_name = os.environ.get("RENDER_SERVICE_NAME", "nominace-mcr-beginner-api").strip()
    payload = http_json("GET", f"{RENDER_API}/services?limit=100", render_headers())
    for item in payload:
        service = item.get("service") or {}
        if service.get("name") == service_name:
            return str(service["id"])
    raise RuntimeError(f"Render sluzba '{service_name}' nenalezena (nastav RENDER_SERVICE_ID)")


def render_list_services() -> None:
    payload = http_json("GET", f"{RENDER_API}/services?limit=100", render_headers())
    print("Render sluzby:")
    for item in payload:
        service = item.get("service") or {}
        print(f"  service_id={service.get('id')}  name={service.get('name')}")


def sync_render(
    passwords: Dict[str, str],
    trainer_auth: List[Dict[str, Any]],
    dry_run: bool,
) -> None:
    if not os.environ.get("RENDER_API_KEY", "").strip():
        print("Render: preskoceno (chybi RENDER_API_KEY)")
        return
    if not trainer_auth and not passwords:
        print("Render: zadne heslo v trainers.yaml")
        return

    service_id = render_resolve_service_id()
    env_updates: List[Dict[str, str]] = []

    if trainer_auth:
        auth_json = json.dumps(trainer_auth, ensure_ascii=False)
        print(f"Render TRAINER_AUTH: {len(trainer_auth)} ucet(u)")
        for item in trainer_auth:
            label = item.get("email") or item.get("club") or item.get("role")
            print(f"  - {item.get('role')}: {label}")
        env_updates.append({"key": "TRAINER_AUTH", "value": auth_json})

    if passwords:
        club_json = json.dumps(passwords, ensure_ascii=False)
        print(f"Render CLUB_PASSWORDS: {len(passwords)} klub(u) (legacy)")
        for club in sorted(passwords):
            print(f"  - {club}")
        env_updates.append({"key": "CLUB_PASSWORDS", "value": club_json})

    env_updates.append({"key": "RENDER_SERVICE_ID", "value": service_id})
    print(f"Render RENDER_SERVICE_ID: {service_id}")

    if dry_run:
        print("Render: dry-run, nic se neposlalo")
        return

    result = http_json(
        "PUT",
        f"{RENDER_API}/services/{service_id}/env-vars",
        render_headers(),
        env_updates,
    )
    print(f"Render env-vars: OK ({len(result) if isinstance(result, list) else 'updated'})")

    if os.environ.get("RENDER_REDEPLOY", "true").strip().lower() in ("1", "true", "yes"):
        deploy = http_json(
            "POST",
            f"{RENDER_API}/services/{service_id}/deploys",
            render_headers(),
            {},
        )
        deploy_id = (deploy.get("id") if isinstance(deploy, dict) else None) or "started"
        print(f"Render redeploy: {deploy_id}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync trainers.yaml -> Cloudflare + Render")
    parser.add_argument(
        "--trainers",
        type=Path,
        default=TRAINERS_PATH,
        help=f"Cesta k YAML (default: {TRAINERS_PATH})",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=SYNC_ENV_PATH,
        help=f"Env soubor s tokeny (default: {SYNC_ENV_PATH})",
    )
    parser.add_argument("--dry-run", action="store_true", help="Jen vypis, bez API volani")
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Vypis Cloudflare app/policy ID a Render service ID",
    )
    parser.add_argument("--cloudflare-only", action="store_true")
    parser.add_argument("--render-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(args.env_file)

    if args.discover:
        try:
            cf_list_apps()
        except RuntimeError as exc:
            print(f"Cloudflare discover: {exc}")
        app_id = os.environ.get("CLOUDFLARE_ACCESS_APP_ID", "").strip()
        if app_id:
            try:
                cf_list_policies(app_id)
            except RuntimeError as exc:
                print(f"Cloudflare policies: {exc}")
        try:
            render_list_services()
        except RuntimeError as exc:
            print(f"Render discover: {exc}")
        print("")
        print("Zkopiruj ID do config/sync.env (viz config/sync.env.example)")
        return 0

    trainers = load_trainers(args.trainers)
    emails = extract_emails(trainers)
    passwords = extract_club_passwords(trainers)
    trainer_auth = extract_trainer_auth(trainers)

    print(f"Zdroj: {args.trainers}")
    if args.dry_run:
        print("Rezim: dry-run")

    try:
        if not args.render_only:
            sync_cloudflare(emails, args.dry_run)
        if not args.cloudflare_only:
            sync_render(passwords, trainer_auth, args.dry_run)
    except (RuntimeError, urllib.error.URLError, ValueError) as exc:
        print(f"Chyba: {exc}", file=sys.stderr)
        return 1

    print("Sync hotovo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
