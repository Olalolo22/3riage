"""
app.py — Flask web dashboard server for 3riage.

Supports three modes seamlessly:
  1. Public Multi-User OAuth Mode (GitHub App / OAuth via encrypted HttpOnly cookies)
  2. Local Single-User Mode (GITHUB_TOKEN from env/.triage.env or `3riage ui`)
  3. Curated Sandbox Demo Mode (zero credentials or ?demo=true)

Provides:
  GET  /                  — Dashboard UI
  GET  /api/triage        — Returns JSON from core.run_triage (per-user 30s cache)
  POST /api/refresh       — Invalidates caller's cache and fetches fresh triage data
  POST /api/fork          — Local CLI fork via `gh` (disabled in public OAuth mode)
  GET  /api/auth/login    — Starts GitHub App / OAuth authorization redirect
  GET  /api/auth/callback — Exchanges code, resolves viewer login, sets HttpOnly cookie
  GET|POST /api/auth/logout — Clears encrypted session cookie & caller cache
"""

import hashlib
import os
import secrets
import threading
import time
from typing import Any
from urllib.parse import quote

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, make_response, redirect, render_template, request

load_dotenv(".triage.env")

from auth import (
    build_authorize_url,
    build_redirect_uri,
    clear_session_cookie,
    clear_state_cookie,
    exchange_code_for_token,
    is_oauth_configured,
    is_vercel,
    read_session_cookie,
    refresh_access_token,
    session_needs_refresh,
    set_session_cookie,
    set_state_cookie,
    token_cache_id,
    verify_state_cookie,
)
from core import run_triage
from github_client import GitHubClient
from mock_data import get_mock_triage_data

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_PACKAGED_ASSETS = os.path.join(BASE_DIR, "threeriage_assets")
TEMPLATE_DIR = (
    os.path.join(BASE_DIR, "templates")
    if os.path.isdir(os.path.join(BASE_DIR, "templates"))
    else os.path.join(_PACKAGED_ASSETS, "templates")
)
STATIC_DIR = (
    os.path.join(BASE_DIR, "static")
    if os.path.isdir(os.path.join(BASE_DIR, "static"))
    else os.path.join(_PACKAGED_ASSETS, "static")
)

app = Flask(
    __name__,
    template_folder=TEMPLATE_DIR,
    static_folder=STATIC_DIR,
)

# Per-user in-memory cache: {cache_key: (timestamp, data)}
_CACHE: dict[str, tuple[float, dict]] = {}
_VIEWER_LOGIN_CACHE: dict[str, str] = {}
CACHE_TTL_SECONDS = 30.0
MAX_CACHE_ENTRIES = 200

_REFRESH_STATE_LOCK = threading.Lock()
_REFRESH_TOKEN_LOCKS: dict[str, threading.Lock] = {}
_REFRESH_RESULTS: dict[str, tuple[float, dict[str, Any]]] = {}
_REFRESH_DEDUP_TTL_SECONDS = 15.0


def _refresh_token_key(refresh_tok: str) -> str:
    return hashlib.sha256(refresh_tok.encode("utf-8")).hexdigest()[:16]


def _refresh_with_single_flight(refresh_tok: str) -> dict[str, Any]:
    tok_key = _refresh_token_key(refresh_tok)
    with _REFRESH_STATE_LOCK:
        tok_lock = _REFRESH_TOKEN_LOCKS.setdefault(tok_key, threading.Lock())

    with tok_lock:
        now = time.time()
        with _REFRESH_STATE_LOCK:
            expired = [k for k, (ts, _) in _REFRESH_RESULTS.items() if now - ts >= _REFRESH_DEDUP_TTL_SECONDS]
            for k in expired:
                _REFRESH_RESULTS.pop(k, None)
            cached = _REFRESH_RESULTS.get(tok_key)
            if cached is not None:
                return dict(cached[1])

        new_tokens = refresh_access_token(refresh_tok)
        with _REFRESH_STATE_LOCK:
            _REFRESH_RESULTS[tok_key] = (time.time(), dict(new_tokens))
        return new_tokens


def _prune_cache_if_needed() -> None:
    if len(_CACHE) < MAX_CACHE_ENTRIES:
        return
    now = time.time()
    expired = [k for k, (ts, _) in _CACHE.items() if now - ts >= CACHE_TTL_SECONDS]
    for k in expired:
        _CACHE.pop(k, None)
    while len(_CACHE) >= MAX_CACHE_ENTRIES:
        oldest_key = min(_CACHE, key=lambda k: _CACHE[k][0])
        _CACHE.pop(oldest_key, None)


def _invalidate_user_cache(token: str | None) -> None:
    if not token:
        return
    prefix = f"{token_cache_id(token)}:"
    for key in [k for k in _CACHE if k.startswith(prefix)]:
        _CACHE.pop(key, None)


def _resolve_username(token: str, explicit_username: str | None = None) -> str:
    if explicit_username:
        return explicit_username
    cid = token_cache_id(token)
    if cid in _VIEWER_LOGIN_CACHE:
        return _VIEWER_LOGIN_CACHE[cid]
    login = GitHubClient(token=token).get_viewer_login()
    _VIEWER_LOGIN_CACHE[cid] = login
    return login


def _resolve_active_auth() -> tuple[str, str | None, str | None, dict[str, Any] | None, tuple[int, str, str, bool] | None]:
    """
    Determine auth mode for the current HTTP request.
    Returns: (auth_mode, token, username, refreshed_session_data, auth_error_info)
      auth_mode in {"demo", "oauth", "env"}
      auth_error_info is None or (status_code, error_code, message, clear_cookie)
    """
    if os.getenv("TRIAGE_FORCE_DEMO", "").lower() in ("1", "true"):
        return "demo", None, None, None, None

    demo_param = request.args.get("demo", "").lower()
    if demo_param in ("true", "1"):
        return "demo", None, None, None, None

    session_data = read_session_cookie(request)
    if session_data:
        refreshed_session: dict[str, Any] | None = None
        if session_needs_refresh(session_data):
            refresh_tok = session_data.get("refresh_token")
            if not refresh_tok:
                return (
                    "oauth",
                    None,
                    None,
                    None,
                    (401, "session_expired", "GitHub session expired. Please reconnect.", True),
                )
            try:
                new_tokens = _refresh_with_single_flight(refresh_tok)
                session_data = {**session_data, **new_tokens}
                refreshed_session = session_data
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else 502
                if status in (400, 401, 403):
                    return (
                        "oauth",
                        None,
                        None,
                        None,
                        (401, "session_expired", "GitHub session expired or revoked. Please reconnect.", True),
                    )
                return (
                    "oauth",
                    None,
                    None,
                    None,
                    (503, "upstream_unavailable", "Temporarily unable to reach GitHub to refresh session. Please retry.", False),
                )
            except requests.RequestException:
                return (
                    "oauth",
                    None,
                    None,
                    None,
                    (503, "upstream_unavailable", "Temporarily unable to reach GitHub to refresh session. Please retry.", False),
                )
            except RuntimeError:
                return (
                    "oauth",
                    None,
                    None,
                    None,
                    (401, "session_expired", "GitHub session expired or revoked. Please reconnect.", True),
                )

        return (
            "oauth",
            session_data["access_token"],
            session_data["username"],
            refreshed_session,
            None,
        )

    env_token = (os.getenv("GITHUB_TOKEN") or "").strip()
    if env_token:
        env_username = (os.getenv("GITHUB_USERNAME") or "").strip() or None
        return "env", env_token, env_username, None, None

    return "demo", None, None, None, None


def _auth_error_response(auth_error_info: tuple[int, str, str, bool]) -> Any:
    status_code, error_code, message, should_clear = auth_error_info
    resp = make_response(
        jsonify(
            {
                "status": "error",
                "auth_error": error_code,
                "error": message,
                "oauth_configured": is_oauth_configured(),
            }
        ),
        status_code,
    )
    if should_clear:
        clear_session_cookie(resp, request)
    return resp


def _build_triage_payload(
    *,
    data: dict[str, Any],
    cached: bool,
    is_demo: bool,
    auth_mode: str,
    age_seconds: float | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "ok",
        "cached": cached,
        "is_demo": is_demo,
        "auth_mode": auth_mode,
        "oauth_configured": is_oauth_configured(),
        "can_fork_via_cli": auth_mode == "env" and not is_vercel(),
        "data": data,
    }
    if age_seconds is not None:
        payload["age_seconds"] = age_seconds
    return payload


def _attach_refreshed_cookie(resp: Any, refreshed_session: dict[str, Any] | None) -> Any:
    if refreshed_session is not None:
        set_session_cookie(resp, request, refreshed_session)
    return resp


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/triage", methods=["GET"])
def get_triage():
    return _execute_triage(force_refresh_override=False)


def _execute_triage(force_refresh_override: bool = False):
    auth_mode, token, username, refreshed_session, auth_error_info = _resolve_active_auth()

    if auth_error_info:
        return _auth_error_response(auth_error_info)

    if auth_mode == "demo" or not token:
        return jsonify(
            _build_triage_payload(
                data=get_mock_triage_data(),
                cached=False,
                is_demo=True,
                auth_mode="demo",
            )
        )

    force_refresh = force_refresh_override or request.args.get("refresh", "false").lower() == "true"
    if force_refresh:
        _invalidate_user_cache(token)

    include_drafts = request.args.get(
        "drafts", os.getenv("TRIAGE_INCLUDE_DRAFTS", "false")
    ).lower() == "true"
    repo_filter = request.args.get("repo", "").strip() or None

    try:
        min_age_hours = float(request.args.get("min_age", os.getenv("TRIAGE_MIN_AGE_HOURS", "0") or "0"))
    except ValueError:
        min_age_hours = 0.0

    user_cid = token_cache_id(token)
    cache_key = f"{user_cid}:{include_drafts}:{repo_filter}:{min_age_hours}"
    now = time.time()

    if not force_refresh and cache_key in _CACHE:
        cached_time, cached_data = _CACHE[cache_key]
        if now - cached_time < CACHE_TTL_SECONDS:
            resp = make_response(
                jsonify(
                    _build_triage_payload(
                        data=cached_data,
                        cached=True,
                        is_demo=False,
                        auth_mode=auth_mode,
                        age_seconds=round(now - cached_time, 1),
                    )
                )
            )
            return _attach_refreshed_cookie(resp, refreshed_session)

    ignore_bots = os.getenv("TRIAGE_IGNORE_BOTS", "true").lower() != "false"
    ignore_repos = set(filter(None, os.getenv("TRIAGE_IGNORE_REPOS", "").split(",")))
    only_repos = {repo_filter} if repo_filter else set(filter(None, os.getenv("TRIAGE_ONLY_REPOS", "").split(",")))

    try:
        resolved_username = _resolve_username(token, username)
        client = GitHubClient(token=token, username=resolved_username, ignore_bots=ignore_bots)
        data = run_triage(
            client=client,
            include_drafts=include_drafts,
            ignore_bots=ignore_bots,
            ignore_repos=ignore_repos,
            only_repos=only_repos,
            claims_days=14,
            min_age_hours=min_age_hours,
        )
        _prune_cache_if_needed()
        _CACHE[cache_key] = (now, data)
        resp = make_response(
            jsonify(
                _build_triage_payload(
                    data=data,
                    cached=False,
                    is_demo=False,
                    auth_mode=auth_mode,
                )
            )
        )
        return _attach_refreshed_cookie(resp, refreshed_session)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 401 and auth_mode == "oauth":
            _invalidate_user_cache(token)
            resp = make_response(
                jsonify(
                    {
                        "status": "error",
                        "auth_error": "token_revoked",
                        "error": "GitHub session expired or revoked. Please reconnect.",
                        "oauth_configured": is_oauth_configured(),
                    }
                ),
                401,
            )
            clear_session_cookie(resp, request)
            return resp
        resp = make_response(jsonify({"status": "error", "error": str(e)}), 500)
        return _attach_refreshed_cookie(resp, refreshed_session)
    except Exception as e:
        resp = make_response(jsonify({"status": "error", "error": str(e)}), 500)
        return _attach_refreshed_cookie(resp, refreshed_session)


@app.route("/api/refresh", methods=["POST"])
def refresh():
    return _execute_triage(force_refresh_override=True)


@app.route("/api/fork", methods=["POST"])
def fork_repo():
    payload = request.get_json(silent=True) or {}
    repo = payload.get("repo", "").strip()
    if not repo or "/" not in repo:
        return jsonify({"status": "error", "error": "Invalid repo specified. Expected 'owner/repo'."}), 400

    if (
        payload.get("demo")
        or request.args.get("demo", "").lower() in ("true", "1")
        or os.getenv("TRIAGE_FORCE_DEMO", "").lower() in ("1", "true")
    ):
        return jsonify({"status": "ok", "message": f"Demo mode: Simulated fork created for {repo}"})

    if is_vercel():
        return (
            jsonify(
                {
                    "status": "error",
                    "error": "Public web mode is read-only. Use the Fork on GitHub link instead.",
                }
            ),
            403,
        )

    auth_mode, token, _, refreshed_session, auth_error_info = _resolve_active_auth()
    if auth_error_info:
        return _auth_error_response(auth_error_info)

    if auth_mode == "demo":
        return jsonify({"status": "ok", "message": f"Demo mode: Simulated fork created for {repo}"})

    if auth_mode != "env":
        resp = make_response(
            jsonify(
                {
                    "status": "error",
                    "error": "Public web mode is read-only. Use the Fork on GitHub link instead.",
                }
            ),
            403,
        )
        return _attach_refreshed_cookie(resp, refreshed_session)

    success, msg = GitHubClient.fork_repo(repo)
    if success:
        _invalidate_user_cache(token)
        return jsonify({"status": "ok", "message": msg})
    return jsonify({"status": "error", "error": msg}), 500


@app.route("/api/auth/login", methods=["GET"])
def auth_login():
    if not is_oauth_configured():
        return redirect("/?auth_error=oauth_not_configured")

    state = secrets.token_urlsafe(24)
    authorize_url = build_authorize_url(request, state)
    resp = make_response(redirect(authorize_url))
    set_state_cookie(resp, request, state)
    return resp


@app.route("/api/auth/callback", methods=["GET"])
def auth_callback():
    oauth_error = request.args.get("error", "").strip()
    if oauth_error:
        resp = make_response(redirect(f"/?auth_error={quote(oauth_error)}"))
        clear_state_cookie(resp, request)
        return resp

    code = request.args.get("code", "").strip()
    state = request.args.get("state", "").strip()
    if not code or not verify_state_cookie(request, state):
        resp = make_response(redirect("/?auth_error=invalid_state"))
        clear_state_cookie(resp, request)
        return resp

    try:
        redirect_uri = build_redirect_uri(request)
        token_data = exchange_code_for_token(code, redirect_uri)
        login = GitHubClient(token=token_data["access_token"]).get_viewer_login()
        session_data = {
            **token_data,
            "username": login,
        }
        resp = make_response(redirect("/"))
        set_session_cookie(resp, request, session_data)
        clear_state_cookie(resp, request)
        return resp
    except Exception:
        resp = make_response(redirect("/?auth_error=oauth_failed"))
        clear_state_cookie(resp, request)
        return resp


@app.route("/api/auth/logout", methods=["GET", "POST"])
def auth_logout():
    session_data = read_session_cookie(request)
    if session_data and session_data.get("access_token"):
        _invalidate_user_cache(session_data["access_token"])

    if request.method == "POST" or "application/json" in (request.headers.get("Accept") or ""):
        resp = make_response(jsonify({"status": "ok"}))
    else:
        resp = make_response(redirect("/"))

    clear_session_cookie(resp, request)
    clear_state_cookie(resp, request)
    return resp


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)
