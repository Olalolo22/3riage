"""
core.py — Detection engine for 3riage.

Returns pure JSON-serialisable dicts.
No I/O, no printing, no side effects.
CLI and dashboard are thin layers on top of this.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from github_client import GitHubClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DT_FMT = "%Y-%m-%dT%H:%M:%SZ"
_SIGN_OFF_HINTS = re.compile(
    r"\b(lgtm|looks good|approved|ship it|ready to merge|merged|great work|nice work|well done)\b",
    re.IGNORECASE,
)


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, _DT_FMT).replace(tzinfo=timezone.utc)
    except ValueError:
        # ISO format with timezone offset
        return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _days_ago(dt: datetime | None) -> int | None:
    if dt is None:
        return None
    delta = datetime.now(timezone.utc) - dt
    return delta.days


def _snippet(text: str | None, length: int = 120) -> str:
    if not text:
        return ""
    text = text.strip().replace("\n", " ")
    return text[:length] + ("…" if len(text) > length else "")


def classify(comment: str) -> str:
    """
    Stub classifier — v1 always returns 'unknown'.
    Replace with an AI-backed implementation in a later version
    without touching the engine logic.
    """
    return "unknown"


# ---------------------------------------------------------------------------
# PR bucket logic
# ---------------------------------------------------------------------------

def _latest_review(reviews: list[dict], me: str) -> dict | None:
    """Return the most recent review NOT by the current user."""
    others = [r for r in reviews if r.get("author", {}).get("login", "").lower() != me.lower()]
    if not others:
        return None
    return max(others, key=lambda r: _parse_dt(r.get("submittedAt")) or datetime.min.replace(tzinfo=timezone.utc))


def _their_activity(pr: dict, me: str, ignore_bots: bool) -> datetime | None:
    """
    Latest activity on the PR by anyone who is NOT the current user.
    Considers: reviews, unresolved/non-outdated thread comments, top-level comments.
    """
    candidates: list[datetime] = []
    me_lo = me.lower()

    # Reviews by others
    for review in pr.get("reviews", {}).get("nodes", []):
        author = review.get("author", {}).get("login", "")
        if author.lower() == me_lo:
            continue
        if ignore_bots and _is_bot_login(author):
            continue
        dt = _parse_dt(review.get("submittedAt"))
        if dt:
            candidates.append(dt)

    # Unresolved, non-outdated thread last comments by others
    for thread in pr.get("reviewThreads", {}).get("nodes", []):
        if thread.get("isResolved") or thread.get("isOutdated"):
            continue
        for comment in thread.get("comments", {}).get("nodes", []):
            author = comment.get("author", {}).get("login", "")
            if author.lower() == me_lo:
                continue
            if ignore_bots and _is_bot_login(author):
                continue
            dt = _parse_dt(comment.get("createdAt"))
            if dt:
                candidates.append(dt)

    # Top-level PR comments by others
    for comment in pr.get("comments", {}).get("nodes", []):
        author = comment.get("author", {}).get("login", "")
        if author.lower() == me_lo:
            continue
        if ignore_bots and _is_bot_login(author):
            continue
        dt = _parse_dt(comment.get("createdAt"))
        if dt:
            candidates.append(dt)

    return max(candidates) if candidates else None


def _your_activity(pr: dict, me: str) -> datetime | None:
    """Latest activity by the current user: comments or last commit."""
    candidates: list[datetime] = []
    me_lo = me.lower()

    for comment in pr.get("comments", {}).get("nodes", []):
        if comment.get("author", {}).get("login", "").lower() == me_lo:
            dt = _parse_dt(comment.get("createdAt"))
            if dt:
                candidates.append(dt)

    commit_nodes = pr.get("commits", {}).get("nodes", [])
    if commit_nodes:
        dt = _parse_dt(commit_nodes[-1]["commit"].get("committedDate"))
        if dt:
            candidates.append(dt)

    return max(candidates) if candidates else None


def _is_bot_login(login: str) -> bool:
    from github_client import _is_bot
    return _is_bot(login)


def _last_their_comment(pr: dict, me: str, ignore_bots: bool) -> dict | None:
    """Return the most recent top-level comment snippet not by the current user."""
    me_lo = me.lower()
    candidates = []
    for comment in pr.get("comments", {}).get("nodes", []):
        author = comment.get("author", {}).get("login", "")
        if author.lower() == me_lo:
            continue
        if ignore_bots and _is_bot_login(author):
            continue
        dt = _parse_dt(comment.get("createdAt"))
        candidates.append((dt, comment))
    if not candidates:
        return None
    _, comment = max(candidates, key=lambda x: x[0] or datetime.min.replace(tzinfo=timezone.utc))
    return comment


def bucket_pr(pr: dict, me: str, ignore_bots: bool) -> dict:
    """
    Classify a single open PR into one of three buckets:
      NEEDS_YOU | WAITING_ON_THEM | PROBABLY_FINE

    Returns a structured dict ready for serialisation.
    """
    repo = pr["repository"]["nameWithOwner"]
    latest_review = _latest_review(pr.get("reviews", {}).get("nodes", []), me)
    review_state = latest_review["state"] if latest_review else None
    review_body = _snippet(latest_review.get("body")) if latest_review else ""
    review_author = latest_review.get("author", {}).get("login", "") if latest_review else ""
    review_at = _parse_dt(latest_review.get("submittedAt")) if latest_review else None

    their_dt = _their_activity(pr, me, ignore_bots)
    your_dt = _your_activity(pr, me)

    # --- Bucket decision ---
    if review_state == "APPROVED":
        bucket = "PROBABLY_FINE"
    elif review_state == "CHANGES_REQUESTED":
        # Only "needs you" if you haven't pushed after the review
        commit_nodes = pr.get("commits", {}).get("nodes", [])
        last_commit_dt = _parse_dt(commit_nodes[-1]["commit"].get("committedDate")) if commit_nodes else None
        if last_commit_dt and review_at and last_commit_dt > review_at:
            # You pushed after the review — ball is back in their court
            bucket = "WAITING_ON_THEM"
        else:
            bucket = "NEEDS_YOU"
    elif their_dt and your_dt and their_dt > your_dt:
        bucket = "NEEDS_YOU"
    elif your_dt and (not their_dt or your_dt >= their_dt):
        # Check for soft sign-off
        last_comment = _last_their_comment(pr, me, ignore_bots)
        if last_comment and _SIGN_OFF_HINTS.search(last_comment.get("body", "")):
            bucket = "PROBABLY_FINE"
        else:
            bucket = "WAITING_ON_THEM"
    else:
        # No activity from anyone yet
        bucket = "WAITING_ON_THEM"

    last_comment = _last_their_comment(pr, me, ignore_bots)
    snippet_author = ""
    snippet_body = ""
    snippet_when = None
    if last_comment:
        snippet_author = last_comment.get("author", {}).get("login", "")
        snippet_body = _snippet(last_comment.get("body", ""))
        snippet_when = _parse_dt(last_comment.get("createdAt"))

    return {
        "type": "pr",
        "bucket": bucket,
        "repo": repo,
        "number": pr["number"],
        "title": pr["title"],
        "url": pr["url"],
        "is_draft": pr.get("isDraft", False),
        "review_state": review_state,
        "review_author": review_author,
        "review_body": review_body,
        "their_last_comment_author": snippet_author,
        "their_last_comment_body": snippet_body,
        "their_last_comment_days_ago": _days_ago(snippet_when),
        "their_activity_days_ago": _days_ago(their_dt),
        "your_activity_days_ago": _days_ago(your_dt),
    }


# ---------------------------------------------------------------------------
# Involved issues — unlinked detection
# ---------------------------------------------------------------------------

def _build_linked_set(prs: list[dict], client: GitHubClient) -> set[tuple[str, int]]:
    """
    Build the set of (owner/repo, issue_number) referenced by open PRs.
    Combines closingIssuesReferences (GraphQL) AND body regex parsing.
    """
    linked: set[tuple[str, int]] = set()
    for pr in prs:
        repo = pr["repository"]["nameWithOwner"]
        # Method 1: closingIssuesReferences
        for ref in pr.get("closingIssuesReferences", {}).get("nodes", []):
            linked.add((ref["repository"]["nameWithOwner"], ref["number"]))
        # Method 2: regex over PR body (catches Refs #, Addresses #, raw URLs)
        body_refs = client.extract_issue_refs_from_body(pr.get("body", "") or "", repo)
        linked.update(body_refs)
    return linked


_APPLICATION_RE = re.compile(
    r"(?:"
    r"<!--\s*wave:application"
    r"|has applied to work on this issue"
    r"|\b(?:would like|can i|please assign|i can fix|want to|interested in)\s+(?:to\s+)?(?:work on|tackle|take|fix|handle)\b"
    r"|\bplease assign (?:this to )?me\b"
    r"|\bhere is my (?:execution )?plan\b"
    r")",
    re.IGNORECASE,
)


def _is_maintainer(comment: dict, repo: str) -> bool:
    """Check if comment author is a maintainer/owner/collaborator of the repo."""
    assoc = comment.get("authorAssociation", "")
    if assoc in ("OWNER", "MEMBER", "COLLABORATOR"):
        return True
    owner = repo.split("/")[0].lower() if "/" in repo else ""
    author = comment.get("author", {}).get("login", "").lower()
    return author == owner


def _analyze_issue_role_and_applications(issue: dict, me: str) -> tuple[str, bool, int, list[str]]:
    """
    Determine your role and check for bounty applications.
    Returns (role, is_dimmed, applicant_count, applicant_logins).

    Roles:
      - 'assignee': Formally assigned to you (top priority debt)
      - 'outbid': Assigned to someone else (dimmed — bid closed)
      - 'applied': You submitted an application/proposal and issue is unassigned
      - 'commenter': You participated in discussion, did not apply
      - 'author': You opened the issue (dimmed if not assigned)
      - 'mentioned': You were tagged
    """
    me_lo = me.lower()
    author = issue.get("author", {}).get("login", "").lower()
    assignee_logins = [a["login"].lower() for a in issue.get("assignees", {}).get("nodes", [])]

    # Assignee cases
    if me_lo in assignee_logins:
        return "assignee", False, 0, []
    if assignee_logins:
        # Assigned to someone else — your bid was not picked
        return "outbid", True, len(assignee_logins), assignee_logins

    # Scan comments for applications and your participation
    applicants = set()
    me_applied = False
    me_commented = False

    for c in issue.get("comments", {}).get("nodes", []):
        c_author = c.get("author", {}).get("login", "").lower()
        body = c.get("body", "") or ""
        if _APPLICATION_RE.search(body):
            applicants.add(c_author)
            if c_author == me_lo:
                me_applied = True
        if c_author == me_lo:
            me_commented = True

    applicant_count = len(applicants)
    applicant_list = sorted(list(applicants))

    if me_applied:
        return "applied", False, applicant_count, applicant_list
    if me_commented:
        return "commenter", False, applicant_count, applicant_list
    if author == me_lo:
        return "author", True, applicant_count, applicant_list
    return "mentioned", False, applicant_count, applicant_list


def _days_since_my_comment(issue: dict, me: str) -> int | None:
    """Days since the current user last commented on an issue."""
    me_lo = me.lower()
    my_comments = [
        c for c in issue.get("comments", {}).get("nodes", [])
        if c.get("author", {}).get("login", "").lower() == me_lo
    ]
    if not my_comments:
        return None
    last = max(_parse_dt(c["createdAt"]) for c in my_comments if _parse_dt(c["createdAt"]))
    return _days_ago(last)


def _last_maintainer_comment(issue: dict, me: str, ignore_bots: bool) -> dict | None:
    """Most recent comment on the issue by a repository MAINTAINER (OWNER/MEMBER/COLLABORATOR)."""
    repo = issue["repository"]["nameWithOwner"]
    me_lo = me.lower()
    candidates = []
    for comment in issue.get("comments", {}).get("nodes", []):
        author = comment.get("author", {}).get("login", "")
        if author.lower() == me_lo:
            continue
        if ignore_bots and _is_bot_login(author):
            continue
        if _is_maintainer(comment, repo):
            dt = _parse_dt(comment.get("createdAt"))
            candidates.append((dt, comment))
    if not candidates:
        return None
    _, comment = max(candidates, key=lambda x: x[0] or datetime.min.replace(tzinfo=timezone.utc))
    return comment


def classify_issue(issue: dict, me: str, ignore_bots: bool, linked: set, forked_parents: set[str]) -> dict | None:
    """
    Returns a structured dict for an unlinked involved issue, or None if it should be skipped.
    """
    repo = issue["repository"]["nameWithOwner"]
    issue_key = (repo, issue["number"])
    if issue_key in linked:
        return None  # Already have a PR for this

    role, is_dimmed, applicant_count, applicant_list = _analyze_issue_role_and_applications(issue, me)

    maintainer_comment = _last_maintainer_comment(issue, me, ignore_bots)
    m_author = ""
    m_body = ""
    m_days = None
    if maintainer_comment:
        m_author = maintainer_comment.get("author", {}).get("login", "")
        m_body = _snippet(maintainer_comment.get("body", ""))
        m_days = _days_ago(_parse_dt(maintainer_comment.get("createdAt")))

    my_last_days = _days_since_my_comment(issue, me)

    return {
        "type": "issue",
        "repo": repo,
        "number": issue["number"],
        "title": issue["title"],
        "url": issue["url"],
        "role": role,
        "is_dimmed": is_dimmed,
        "applicant_count": applicant_count,
        "applicant_list": applicant_list,
        "days_since_my_comment": my_last_days,
        "forked": repo.lower() in forked_parents,
        "maintainer_comment_author": m_author,
        "maintainer_comment_body": m_body,
        "maintainer_comment_days_ago": m_days,
        "last_comment_author": m_author,  # backwards compatibility
        "last_comment_body": m_body,
        "last_comment_days_ago": m_days,
        "classify": classify(m_body),  # stub
    }


# ---------------------------------------------------------------------------
# Merged PRs — "Ready to Claim" shelf
# ---------------------------------------------------------------------------

def build_claims_shelf(merged_prs: list[dict], days: int = 14) -> list[dict]:
    """
    Return recently merged PRs (within `days`) formatted for the claims shelf.
    """
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    results = []
    for pr in merged_prs:
        merged_at = _parse_dt(pr.get("mergedAt"))
        if not merged_at or merged_at.timestamp() < cutoff:
            continue
        results.append(
            {
                "type": "claim",
                "repo": pr["repository"]["nameWithOwner"],
                "number": pr["number"],
                "title": pr["title"],
                "url": pr["url"],
                "merged_days_ago": _days_ago(merged_at),
            }
        )
    return results


# ---------------------------------------------------------------------------
# Fork assistant data
# ---------------------------------------------------------------------------

def build_fork_report(
    involved_issues: list[dict],
    me: str,
    forked_parents: set[str],
    write_access_repos: set[str],
) -> list[dict]:
    """
    Returns repos that appear in assigned/involved issues where you have no fork
    AND no direct write access.
    """
    seen = set()
    results = []
    for issue in involved_issues:
        role, _, _, _ = _analyze_issue_role_and_applications(issue, me)
        if role not in ("assignee", "applied", "commenter"):
            continue
        repo = issue["repository"]["nameWithOwner"]
        repo_lo = repo.lower()
        if repo_lo in seen:
            continue
        seen.add(repo_lo)
        has_fork = repo_lo in forked_parents
        has_write = repo_lo in write_access_repos
        results.append(
            {
                "repo": repo,
                "role": role,
                "has_fork": has_fork,
                "has_write_access": has_write,
                "needs_fork": not has_fork and not has_write,
            }
        )
    return results


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_triage(
    client: GitHubClient,
    include_drafts: bool = False,
    ignore_bots: bool = True,
    ignore_repos: set[str] | None = None,
    only_repos: set[str] | None = None,
    claims_days: int = 14,
) -> dict:
    """
    Run a full triage and return a structured JSON-serialisable dict.
    """
    ignore_repos = {r.lower() for r in (ignore_repos or set())}
    only_repos = {r.lower() for r in (only_repos or set())}

    def _repo_allowed(repo: str) -> bool:
        r = repo.lower()
        if ignore_repos and r in ignore_repos:
            return False
        if only_repos and r not in only_repos:
            return False
        return True

    # Fetch all data
    open_prs = [
        pr for pr in client.get_open_prs(include_drafts=include_drafts)
        if _repo_allowed(pr["repository"]["nameWithOwner"])
    ]
    merged_prs = client.get_merged_prs(limit=20)
    involved_issues = [
        i for i in client.get_involved_issues()
        if _repo_allowed(i["repository"]["nameWithOwner"])
    ]
    forked_parents = client.get_forked_parents()
    write_access_repos = client.get_write_access_repos()

    # Compute
    linked = _build_linked_set(open_prs, client)

    bucketed_prs: dict[str, list] = {"NEEDS_YOU": [], "WAITING_ON_THEM": [], "PROBABLY_FINE": []}
    for pr in open_prs:
        result = bucket_pr(pr, client.username, ignore_bots)
        bucketed_prs[result["bucket"]].append(result)

    unlinked_issues = []
    for issue in involved_issues:
        result = classify_issue(issue, client.username, ignore_bots, linked, forked_parents)
        if result:
            unlinked_issues.append(result)

    # Sort unlinked: active roles first (assignee > applied > commenter > mentioned), then dimmed (author, outbid)
    role_priority = {
        "assignee": 0,
        "applied": 1,
        "commenter": 2,
        "mentioned": 3,
        "author": 4,
        "outbid": 5,
    }
    unlinked_issues.sort(
        key=lambda i: (
            1 if i.get("is_dimmed") else 0,
            role_priority.get(i.get("role"), 9),
            -(i.get("days_since_my_comment") or 0),
        )
    )

    claims = build_claims_shelf(merged_prs, days=claims_days)
    fork_report = build_fork_report(involved_issues, client.username, forked_parents, write_access_repos)

    return {
        "username": client.username,
        "prs": bucketed_prs,
        "unlinked_issues": unlinked_issues,
        "claims": claims,
        "fork_report": fork_report,
        "summary": {
            "needs_you": len(bucketed_prs["NEEDS_YOU"]),
            "waiting_on_them": len(bucketed_prs["WAITING_ON_THEM"]),
            "probably_fine": len(bucketed_prs["PROBABLY_FINE"]),
            "unlinked_issues": len(unlinked_issues),
            "ready_to_claim": len(claims),
            "repos_need_fork": sum(1 for f in fork_report if f["needs_fork"]),
        },
    }
