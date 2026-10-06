"""
app.py — Flask web dashboard server for 3riage.

Binds to 127.0.0.1. Provides:
  GET  /             — Dashboard UI
  GET  /api/triage   — Returns JSON from core.run_triage (with 30s in-memory cache)
  POST /api/refresh  — Invalidates cache and fetches fresh triage data
  POST /api/fork     — Executes `gh repo fork <repo> --clone=false`
"""

import os
import time
from typing import Any
from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv

load_dotenv(".triage.env")

from github_client import GitHubClient
from core import run_triage

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

# In-memory cache: {cache_key: (timestamp, data)}
_CACHE: dict[str, tuple[float, dict]] = {}
CACHE_TTL_SECONDS = 30.0


def _get_client() -> tuple[GitHubClient | None, str | None]:
    token = os.getenv("GITHUB_TOKEN")
    username = os.getenv("GITHUB_USERNAME")
    if not token or not username:
        return None, "GITHUB_TOKEN and GITHUB_USERNAME must be set in .triage.env"
    ignore_bots = os.getenv("TRIAGE_IGNORE_BOTS", "true").lower() != "false"
    return GitHubClient(token=token, username=username, ignore_bots=ignore_bots), None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/triage", methods=["GET"])
def get_triage():
    force_refresh = request.args.get("refresh", "false").lower() == "true"
    include_drafts = request.args.get(
        "drafts", os.getenv("TRIAGE_INCLUDE_DRAFTS", "false")
    ).lower() == "true"
    repo_filter = request.args.get("repo", "").strip() or None

    try:
        min_age_hours = float(request.args.get("min_age", os.getenv("TRIAGE_MIN_AGE_HOURS", "0") or "0"))
    except ValueError:
        min_age_hours = 0.0

    cache_key = f"{include_drafts}:{repo_filter}:{min_age_hours}"
    now = time.time()

    if not force_refresh and cache_key in _CACHE:
        cached_time, cached_data = _CACHE[cache_key]
        if now - cached_time < CACHE_TTL_SECONDS:
            return jsonify({"status": "ok", "cached": True, "age_seconds": round(now - cached_time, 1), "data": cached_data})

    client, err = _get_client()
    if err or not client:
        return jsonify({"status": "error", "error": err or "Client initialization failed"}), 400

    ignore_bots = os.getenv("TRIAGE_IGNORE_BOTS", "true").lower() != "false"
    ignore_repos = set(filter(None, os.getenv("TRIAGE_IGNORE_REPOS", "").split(",")))
    only_repos = {repo_filter} if repo_filter else set(filter(None, os.getenv("TRIAGE_ONLY_REPOS", "").split(",")))

    try:
        data = run_triage(
            client=client,
            include_drafts=include_drafts,
            ignore_bots=ignore_bots,
            ignore_repos=ignore_repos,
            only_repos=only_repos,
            claims_days=14,
            min_age_hours=min_age_hours,
        )
        _CACHE[cache_key] = (now, data)
        return jsonify({"status": "ok", "cached": False, "data": data})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/refresh", methods=["POST"])
def refresh():
    _CACHE.clear()
    return get_triage()


@app.route("/api/fork", methods=["POST"])
def fork_repo():
    payload = request.get_json(silent=True) or {}
    repo = payload.get("repo", "").strip()
    if not repo or "/" not in repo:
        return jsonify({"status": "error", "error": "Invalid repo specified. Expected 'owner/repo'."}), 400

    success, msg = GitHubClient.fork_repo(repo)
    if success:
        _CACHE.clear()
        return jsonify({"status": "ok", "message": msg})
    else:
        return jsonify({"status": "error", "error": msg}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)
