#!/usr/bin/env python3
"""
triage.py — CLI for 3riage.

Usage:
  3riage                         # full report (or `python triage.py`)
  3riage ui                      # launch local web dashboard
  3riage --mode prs              # PR buckets only
  3riage --mode issues           # unlinked issues only
  3riage --mode claims           # recently merged, ready to claim
  3riage --forks                 # fork assistant
  3riage --repo owner/r          # filter to one repo
  3riage --json                  # machine-readable JSON output
  3riage --include-drafts        # include draft PRs
"""

import json
import os
import sys
import threading
import webbrowser

import click
from dotenv import load_dotenv
from tabulate import tabulate

load_dotenv(".triage.env")

from github_client import GitHubClient
from core import run_triage

# ---------------------------------------------------------------------------
# Colour helpers (no external dep — ANSI only)
# ---------------------------------------------------------------------------

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
BLUE = "\033[94m"
WHITE = "\033[97m"


def _c(text: str, *codes: str) -> str:
    if not sys.stdout.isatty():
        return text
    return "".join(codes) + text + RESET


def _age_badge(days: int | None) -> str:
    if days is None:
        return _c("?d", DIM)
    if days == 0:
        return _c("today", GREEN)
    if days <= 3:
        return _c(f"{days}d", GREEN)
    if days <= 7:
        return _c(f"{days}d", YELLOW)
    return _c(f"{days}d", RED)


# ---------------------------------------------------------------------------
# Section printers
# ---------------------------------------------------------------------------

def _print_header(title: str) -> None:
    click.echo()
    click.echo(_c(f"  {'─' * 60}", DIM))
    click.echo(_c(f"  {title}", BOLD + WHITE))
    click.echo(_c(f"  {'─' * 60}", DIM))


def _print_pr_bucket(bucket_name: str, items: list[dict], color: str) -> None:
    label = {
        "NEEDS_YOU": "⚡ Needs You",
        "WAITING_ON_THEM": "⏳ Waiting on Them",
        "PROBABLY_FINE": "✅ Probably Fine",
    }.get(bucket_name, bucket_name)

    click.echo()
    click.echo(_c(f"  {label} ({len(items)})", BOLD + color))

    if not items:
        click.echo(_c("    — none —", DIM))
        return

    for pr in items:
        dimmed = bucket_name == "PROBABLY_FINE"
        style = DIM if dimmed else ""

        click.echo()
        click.echo(
            _c(f"    [{pr['repo']} #{pr['number']}]", style + CYAN)
            + "  "
            + _c(pr["title"], style + BOLD)
        )
        click.echo(_c(f"    {pr['url']}", style + DIM))

        # Review state badge
        if pr.get("review_state"):
            state_colors = {
                "APPROVED": GREEN,
                "CHANGES_REQUESTED": RED,
                "COMMENTED": YELLOW,
            }
            sc = state_colors.get(pr["review_state"], WHITE)
            who = f" by @{pr['review_author']}" if pr.get("review_author") else ""
            click.echo(_c(f"    Review: {pr['review_state']}{who}", style + sc))
            if pr.get("review_body"):
                click.echo(_c(f"    ↳ \"{pr['review_body']}\"", style + DIM))

        # Last comment snippet
        if pr.get("their_last_comment_body"):
            who = f"@{pr['their_last_comment_author']}" if pr.get("their_last_comment_author") else "them"
            age = _age_badge(pr.get("their_last_comment_days_ago"))
            click.echo(
                _c(f"    Last: {who}", style + MAGENTA)
                + " " + age + "  "
                + _c(f"\"{pr['their_last_comment_body']}\"", style + DIM)
            )


def _print_issues(issues: list[dict]) -> None:
    _print_header("Unlinked Issues  (no PR from you yet)")

    active = [i for i in issues if not i.get("is_dimmed")]
    dimmed = [i for i in issues if i.get("is_dimmed")]

    if not active and not dimmed:
        click.echo(_c("    — none —", DIM))
        return

    rows = []
    for i in active + dimmed:
        style = DIM if i.get("is_dimmed") else ""
        role_colors = {
            "assignee": RED,
            "applied": MAGENTA,
            "commenter": YELLOW,
            "mentioned": CYAN,
            "author": DIM,
            "outbid": DIM,
        }
        role_c = role_colors.get(i["role"], WHITE)

        if i["role"] == "applied" and i.get("applicant_count", 0) > 1:
            role_display = f"applied ({i['applicant_count']} apps)"
        elif i["role"] == "outbid":
            role_display = "outbid"
        else:
            role_display = i["role"]

        age_my = _age_badge(i.get("days_since_my_comment"))
        age_them = _age_badge(i.get("maintainer_comment_days_ago"))
        forked = _c("✓", GREEN) if i.get("forked") else _c("✗", RED)

        rows.append(
            [
                _c(f"{i['repo']} #{i['number']}", style + CYAN),
                _c(role_display, style + role_c),
                age_my,
                age_them,
                forked,
                _c(i["title"][:48], style + BOLD),
            ]
        )

    headers = ["Repo & Issue", "Role", "My last", "Maintainer", "Forked", "Title"]
    click.echo()
    click.echo(
        tabulate(rows, headers=headers, tablefmt="plain")
        .replace("\n", "\n  ")
    )

    for i in active + dimmed:
        click.echo()
        style = DIM if i.get("is_dimmed") else ""
        click.echo(_c(f"  [{i['repo']} #{i['number']}]", CYAN) + "  " + _c(i["title"], BOLD + style))

        if i.get("maintainer_comment_body"):
            who = f"Maintainer @{i['maintainer_comment_author']}"
            age = _age_badge(i.get("maintainer_comment_days_ago"))
            click.echo(_c(f"  ↳ {who} ({age}): \"{i['maintainer_comment_body']}\"", style + WHITE))

        if i.get("role") == "applied":
            click.echo(
                _c(f"  ↳ Status: Applied ({i.get('applicant_count', 1)} total applicants, unassigned)", MAGENTA)
            )
        elif i.get("role") == "outbid":
            assignees_str = ", ".join(f"@{a}" for a in i.get("applicant_list", []))
            click.echo(_c(f"  ↳ Status: Assigned to {assignees_str} (bid closed)", DIM))

        click.echo(_c(f"  → {i['url']}", DIM))


def _print_claims(claims: list[dict]) -> None:
    _print_header("🏆 Ready to Claim  (merged in last 14 days)")

    if not claims:
        click.echo(_c("    — none —", DIM))
        return

    for c in claims:
        age = _age_badge(c.get("merged_days_ago"))
        click.echo()
        click.echo(
            _c(f"  [{c['repo']} #{c['number']}]", CYAN)
            + "  "
            + _c(c["title"], BOLD)
            + "  merged "
            + age
        )
        click.echo(_c(f"  {c['url']}", DIM))


def _print_fork_report(fork_report: list[dict]) -> None:
    _print_header("🍴 Fork Status")

    needs_fork = [f for f in fork_report if f.get("needs_fork")]
    has_fork = [f for f in fork_report if not f.get("needs_fork")]

    if not fork_report:
        click.echo(_c("    — no relevant repos —", DIM))
        return

    if needs_fork:
        click.echo(_c(f"\n  Needs fork ({len(needs_fork)}):", BOLD + RED))
        for f in needs_fork:
            click.echo(_c(f"    {f['repo']}  [{f['role']}]", YELLOW))

    if has_fork:
        click.echo(_c(f"\n  Already forked / write access ({len(has_fork)}):", BOLD + GREEN))
        for f in has_fork:
            note = "write access" if f.get("has_write_access") else "forked"
            click.echo(_c(f"    {f['repo']}  [{note}]", DIM))


def _run_fork_assistant(fork_report: list[dict]) -> None:
    needs_fork = [f for f in fork_report if f.get("needs_fork")]
    if not needs_fork:
        click.echo(_c("  ✓ No repos need forking.", GREEN))
        return

    click.echo(_c(f"\n  {len(needs_fork)} repo(s) need a fork:\n", BOLD))
    for f in needs_fork:
        repo = f["repo"]
        if click.confirm(f"  Fork {repo}?", default=False):
            ok, msg = GitHubClient.fork_repo(repo)
            if ok:
                click.echo(_c(f"  ✓ {msg}", GREEN))
                click.echo(_c("    (fork is being created — check GitHub in ~10 seconds)", DIM))
            else:
                click.echo(_c(f"  ✗ {msg}", RED))


def _print_summary(summary: dict) -> None:
    click.echo()
    click.echo(_c("  ─" * 31, DIM))
    parts = [
        _c(f"⚡ {summary['needs_you']} need your attention", RED if summary["needs_you"] else DIM),
        _c(f"⏳ {summary['waiting_on_them']} waiting on them", YELLOW),
        _c(f"✅ {summary['probably_fine']} probably fine", GREEN),
        _c(f"📋 {summary['unlinked_issues']} unlinked issues", CYAN),
        _c(f"🏆 {summary['ready_to_claim']} ready to claim", MAGENTA),
        _c(f"🍴 {summary['repos_need_fork']} repos need fork", YELLOW if summary["repos_need_fork"] else DIM),
    ]
    click.echo("  " + "   ".join(parts))
    click.echo()


# ---------------------------------------------------------------------------
# Auth resolution helper
# ---------------------------------------------------------------------------

def _resolve_cli_auth(ignore_bots: bool = True) -> tuple[GitHubClient, str]:
    token = (os.getenv("GITHUB_TOKEN") or "").strip() or _gh_auth_token()
    if not token:
        raise RuntimeError(
            "No GitHub token found. Run `gh auth login`, or set GITHUB_TOKEN in .triage.env."
        )

    username = (os.getenv("GITHUB_USERNAME") or "").strip()
    client = GitHubClient(token=token, username=username, ignore_bots=ignore_bots)
    if not username:
        username = client.get_viewer_login()
    return client, username


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group(invoke_without_command=True)
@click.option("--mode", type=click.Choice(["all", "prs", "issues", "claims", "forks"]), default="all",
              help="What to show: all (default), prs, issues, claims, forks.")
@click.option("--repo", default=None, help="Filter to a single repo (owner/repo).")
@click.option("--json", "output_json", is_flag=True, help="Output raw JSON instead of formatted text.")
@click.option("--include-drafts", is_flag=True, default=None, help="Include draft PRs (overrides TRIAGE_INCLUDE_DRAFTS).")
@click.option("--min-age-hours", default=None, type=float, help="Ignore activity younger than N hours (overrides TRIAGE_MIN_AGE_HOURS).")
@click.option("--forks", "run_forks", is_flag=True, help="Run interactive fork assistant after report.")
@click.option("--claims-days", default=14, show_default=True, help="How many days back to look for merged PRs.")
@click.pass_context
def cli(ctx, mode, repo, output_json, include_drafts, min_age_hours, run_forks, claims_days):
    """
    3riage — GitHub contribution triage tool.

    Shows PRs where the ball is in your court, issues you're involved in
    with no PR yet, and repos you haven't forked.

    Run `3riage ui` to launch the local web dashboard.
    """
    if ctx.invoked_subcommand is not None:
        return

    # --- Config ---
    ignore_bots = os.getenv("TRIAGE_IGNORE_BOTS", "true").lower() != "false"
    ignore_repos = set(filter(None, os.getenv("TRIAGE_IGNORE_REPOS", "").split(",")))
    only_repos = set(filter(None, os.getenv("TRIAGE_ONLY_REPOS", "").split(",")))

    # Drafts config: CLI flag overrides env var
    env_drafts = os.getenv("TRIAGE_INCLUDE_DRAFTS", "false").lower() == "true"
    final_include_drafts = include_drafts if include_drafts is not None else env_drafts

    # Min age hours: CLI flag overrides env var
    try:
        env_min_age = float(os.getenv("TRIAGE_MIN_AGE_HOURS", "0") or "0")
    except ValueError:
        env_min_age = 0.0
    final_min_age = min_age_hours if min_age_hours is not None else env_min_age

    if repo:
        only_repos = {repo}

    # --- Auth ---
    try:
        client, username = _resolve_cli_auth(ignore_bots=ignore_bots)
    except Exception as e:
        click.echo(_c(f"Error: {e}", RED), err=True)
        sys.exit(1)

    if not output_json:
        click.echo(_c(f"\n  3riage  @{username}", BOLD + CYAN))
        click.echo(_c("  Fetching from GitHub…", DIM))

    try:
        data = run_triage(
            client,
            include_drafts=final_include_drafts,
            ignore_bots=ignore_bots,
            ignore_repos=ignore_repos,
            only_repos=only_repos,
            claims_days=claims_days,
            min_age_hours=final_min_age,
        )
    except Exception as e:
        click.echo(_c(f"\nError fetching data: {e}", RED), err=True)
        sys.exit(1)

    # --- JSON output ---
    if output_json:
        click.echo(json.dumps(data, indent=2, default=str))
        return

    # --- Formatted output ---
    if mode in ("all", "prs"):
        _print_header("Pull Requests")
        _print_pr_bucket("NEEDS_YOU", data["prs"]["NEEDS_YOU"], RED)
        _print_pr_bucket("WAITING_ON_THEM", data["prs"]["WAITING_ON_THEM"], YELLOW)
        _print_pr_bucket("PROBABLY_FINE", data["prs"]["PROBABLY_FINE"], GREEN)

    if mode in ("all", "issues"):
        _print_issues(data["unlinked_issues"])

    if mode in ("all", "claims"):
        _print_claims(data["claims"])

    if mode in ("all", "forks"):
        _print_fork_report(data["fork_report"])

    if mode == "all":
        _print_summary(data["summary"])

    if run_forks or mode == "forks":
        _run_fork_assistant(data["fork_report"])


@cli.command("ui")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host interface to bind.")
@click.option("--port", default=5000, show_default=True, type=int, help="Port to serve dashboard on.")
@click.option("--no-browser", is_flag=True, help="Do not open browser automatically.")
@click.option("--demo", is_flag=True, help="Start dashboard in curated sandbox demo mode.")
def ui(host: str, port: int, no_browser: bool, demo: bool) -> None:
    """Launch the local 3riage web dashboard."""
    if demo:
        os.environ["TRIAGE_FORCE_DEMO"] = "1"
        click.echo(_c("\n  3riage ui  [sandbox demo mode]", BOLD + MAGENTA))
    else:
        token = (os.getenv("GITHUB_TOKEN") or "").strip() or _gh_auth_token()
        if token:
            os.environ["GITHUB_TOKEN"] = token
            username = (os.getenv("GITHUB_USERNAME") or "").strip()
            if not username:
                try:
                    username = GitHubClient(token=token).get_viewer_login()
                    os.environ["GITHUB_USERNAME"] = username
                except Exception as e:
                    click.echo(_c(f"Warning: could not resolve GitHub username ({e}); falling back to demo mode.", YELLOW), err=True)
                    os.environ.pop("GITHUB_TOKEN", None)
            if os.getenv("GITHUB_TOKEN") and os.getenv("GITHUB_USERNAME"):
                click.echo(_c(f"\n  3riage ui  @{os.environ['GITHUB_USERNAME']}", BOLD + CYAN))
        else:
            click.echo(
                _c("\n  3riage ui  [demo mode — run `gh auth login` or set GITHUB_TOKEN for live data]", YELLOW)
            )

    url = f"http://{host}:{port}"
    click.echo(_c(f"  Dashboard running at {url}", GREEN))

    if not no_browser:
        timer = threading.Timer(0.8, lambda: webbrowser.open(url))
        timer.daemon = True
        timer.start()

    from app import app as flask_app
    flask_app.run(host=host, port=port, debug=False)


def _gh_auth_token() -> str | None:
    """Try to get a token from the gh CLI if GITHUB_TOKEN isn't set."""
    import subprocess
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


if __name__ == "__main__":
    cli()
