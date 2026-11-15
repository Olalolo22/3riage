"""
auth.py — GitHub App / OAuth session helpers and encrypted HttpOnly cookies for 3riage.

Supports:
  - GitHub App user-authorization flow (zero repo permissions = read-only public access,
    with automatic refresh_token rotation when short-lived tokens expire)
  - Classic GitHub OAuth App flow (read-only public access by default when scope is unset)
  - Stateless Fernet-encrypted HttpOnly cookies compatible with both local Flask
    and independent Vercel serverless handlers.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import Request, Response

SESSION_COOKIE_NAME = "3riage_session"
STATE_COOKIE_NAME = "3riage_oauth_state"

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"

SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days
STATE_MAX_AGE_SECONDS = 60 * 10  # 10 minutes
REFRESH_LEEWAY_SECONDS = 60

# Process-local fallback secret for local development only.
_EPHEMERAL_DEV_SECRET: str | None = None


def is_vercel() -> bool:
    return bool(os.getenv("VERCEL") or os.getenv("VERCEL_ENV"))


def get_oauth_client_config() -> tuple[str, str]:
    client_id = (
        os.getenv("GITHUB_OAUTH_CLIENT_ID")
        or os.getenv("GITHUB_CLIENT_ID")
        or ""
    ).strip()
    client_secret = (
        os.getenv("GITHUB_OAUTH_CLIENT_SECRET")
        or os.getenv("GITHUB_CLIENT_SECRET")
        or ""
    ).strip()
    return client_id, client_secret


def is_oauth_configured() -> bool:
    client_id, client_secret = get_oauth_client_config()
    if not (client_id and client_secret):
        return False
    # On serverless deployments (Vercel), SESSION_SECRET must be shared across functions.
    if is_vercel() and not _configured_session_secret():
        return False
    return True


def _configured_session_secret() -> str:
    return (
        os.getenv("SESSION_SECRET")
        or os.getenv("TRIAGE_SESSION_SECRET")
        or os.getenv("FLASK_SECRET_KEY")
        or ""
    ).strip()


def _get_session_secret() -> str:
    global _EPHEMERAL_DEV_SECRET
    configured = _configured_session_secret()
    if configured:
        return configured
    if is_vercel():
        raise RuntimeError(
            "SESSION_SECRET must be set in Vercel environment variables for GitHub OAuth."
        )
    if _EPHEMERAL_DEV_SECRET is None:
        _EPHEMERAL_DEV_SECRET = secrets.token_urlsafe(32)
    return _EPHEMERAL_DEV_SECRET


def _get_fernet() -> Fernet:
    secret = _get_session_secret()
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def is_https_request(req: Request) -> bool:
    forwarded_proto = (req.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
    if forwarded_proto:
        return forwarded_proto == "https"
    return bool(req.is_secure)


def build_redirect_uri(req: Request) -> str:
    override = (os.getenv("GITHUB_OAUTH_REDIRECT_URI") or "").strip()
    if override:
        return override

    scheme = (req.headers.get("X-Forwarded-Proto") or req.scheme or "http").split(",")[0].strip()
    host = (req.headers.get("X-Forwarded-Host") or req.host or "127.0.0.1:5000").split(",")[0].strip()
    return f"{scheme}://{host}/api/auth/callback"


def build_authorize_url(req: Request, state: str) -> str:
    client_id, _ = get_oauth_client_config()
    params = {
        "client_id": client_id,
        "redirect_uri": build_redirect_uri(req),
        "state": state,
    }
    scope = (os.getenv("GITHUB_OAUTH_SCOPE") or "").strip()
    if scope:
        params["scope"] = scope
    return f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"


def encrypt_cookie_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return _get_fernet().encrypt(raw).decode("ascii")


def decrypt_cookie_payload(token: str, max_age: int | None = None) -> dict[str, Any] | None:
    if not token:
        return None
    try:
        raw = _get_fernet().decrypt(token.encode("ascii"), ttl=max_age)
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else None
    except (InvalidToken, ValueError, TypeError, RuntimeError):
        return None


def set_state_cookie(resp: Response, req: Request, state: str) -> None:
    value = encrypt_cookie_payload({"state": state, "ts": int(time.time())})
    resp.set_cookie(
        STATE_COOKIE_NAME,
        value,
        max_age=STATE_MAX_AGE_SECONDS,
        httponly=True,
        secure=is_https_request(req),
        samesite="Lax",
        path="/",
    )


def verify_state_cookie(req: Request, expected_state: str) -> bool:
    if not expected_state:
        return False
    cookie_val = req.cookies.get(STATE_COOKIE_NAME, "")
    payload = decrypt_cookie_payload(cookie_val, max_age=STATE_MAX_AGE_SECONDS)
    if not payload:
        return False
    stored_state = str(payload.get("state") or "")
    return bool(stored_state) and secrets.compare_digest(stored_state, expected_state)


def clear_state_cookie(resp: Response, req: Request) -> None:
    resp.set_cookie(
        STATE_COOKIE_NAME,
        "",
        max_age=0,
        expires=0,
        httponly=True,
        secure=is_https_request(req),
        samesite="Lax",
        path="/",
    )


def read_session_cookie(req: Request) -> dict[str, Any] | None:
    cookie_val = req.cookies.get(SESSION_COOKIE_NAME, "")
    payload = decrypt_cookie_payload(cookie_val, max_age=SESSION_MAX_AGE_SECONDS)
    if not payload or not payload.get("access_token") or not payload.get("username"):
        return None
    return payload


def set_session_cookie(resp: Response, req: Request, session_data: dict[str, Any]) -> None:
    value = encrypt_cookie_payload(session_data)
    resp.set_cookie(
        SESSION_COOKIE_NAME,
        value,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=is_https_request(req),
        samesite="Lax",
        path="/",
    )


def clear_session_cookie(resp: Response, req: Request) -> None:
    resp.set_cookie(
        SESSION_COOKIE_NAME,
        "",
        max_age=0,
        expires=0,
        httponly=True,
        secure=is_https_request(req),
        samesite="Lax",
        path="/",
    )


def exchange_code_for_token(code: str, redirect_uri: str) -> dict[str, Any]:
    client_id, client_secret = get_oauth_client_config()
    if not client_id or not client_secret:
        raise RuntimeError("GitHub OAuth client credentials are not configured.")

    resp = requests.post(
        GITHUB_TOKEN_URL,
        headers={"Accept": "application/json"},
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        desc = data.get("error_description") or data["error"]
        raise RuntimeError(f"GitHub OAuth error: {desc}")
    if not data.get("access_token"):
        raise RuntimeError("GitHub OAuth response missing access_token.")
    return _normalize_token_response(data)


def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    client_id, client_secret = get_oauth_client_config()
    if not client_id or not client_secret:
        raise RuntimeError("GitHub OAuth client credentials are not configured.")

    resp = requests.post(
        GITHUB_TOKEN_URL,
        headers={"Accept": "application/json"},
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("error") or not data.get("access_token"):
        desc = data.get("error_description") or data.get("error") or "refresh_failed"
        raise RuntimeError(f"GitHub OAuth refresh failed: {desc}")
    return _normalize_token_response(data)


def _normalize_token_response(data: dict[str, Any]) -> dict[str, Any]:
    now = int(time.time())
    expires_in = data.get("expires_in")
    expires_at = now + int(expires_in) if expires_in else None
    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token") or "",
        "expires_at": expires_at,
    }


def session_needs_refresh(session_data: dict[str, Any]) -> bool:
    expires_at = session_data.get("expires_at")
    if not expires_at:
        return False
    return time.time() >= (float(expires_at) - REFRESH_LEEWAY_SECONDS)


def token_cache_id(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
