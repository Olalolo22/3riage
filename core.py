"""
core.py — Detection engine for 3riage.

Returns pure JSON-serialisable dicts.
No I/O, no printing, no side effects.
CLI and dashboard are thin layers on top of this.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
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


def _iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime(_DT_FMT)


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
# Linked-issue detection (closing keywords / Development sidebar links)
# ---------------------------------------------------------------------------

# GitHub closing keywords: close/closes/closed, fix/fixes/fixed, resolve/resolves/resolved,
# optionally followed by a colon, then #N, owner/repo#N, or a full issue URL.
_CLOSING_KEYWORD_RE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+"
    r"(?:https://github\.com/[\w.\-]+/[\w.\-]+/issues/\d+|(?:[\w.\-]+/[\w.\-]+)?#\d+)",
    re.IGNORECASE,
)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _has_closing_keyword(body: str | None) -> bool:
    """True if the PR body (ignoring HTML comments) contains a GitHub closing keyword."""
    if not body:
        return False
    return bool(_CLOSING_KEYWORD_RE.search(_HTML_COMMENT_RE.sub("", body)))


def _closing_link_info(pr: dict) -> dict:
    """
    Describe whether GitHub has linked this PR to an issue it will close.

    closingIssuesReferences is the source of truth: it covers both closing keywords
    and issues linked by hand from the PR's Development sidebar.
    If the field was not fetched at all, everything is reported as unknown (None)
    so callers never raise a false alarm.
    """
    repo = (pr.get("repository") or {}).get("nameWithOwner", "")
    default_branch = ((pr.get("repository") or {}).get("defaultBranchRef") or {}).get("name")
    base = pr.get("baseRefName")
    targets_default = (base == default_branch) if (base and default_branch) else None

    if "closingIssuesReferences" not in pr:
        return {
            "has_closing_link": None,
            "linked_issues": [],
            "closing_link_reason": None,
            "base_branch": base,
            "default_branch": default_branch,
            "targets_default_branch": targets_default,
        }

    refs = (pr.get("closingIssuesReferences") or {}).get("nodes", []) or []
    linked: list[str] = []
    for ref in refs:
        ref_repo = (ref.get("repository") or {}).get("nameWithOwner", "")
        num = ref.get("number")
        if num is None:
            continue
        linked.append(f"#{num}" if ref_repo.lower() == repo.lower() else f"{ref_repo}#{num}")

    has_link = bool(linked)
    reason = None
    if not has_link:
        if targets_default is False:
            reason = "non_default_base"
        elif _has_closing_keyword(pr.get("body")):
            reason = "keyword_not_linked"
        else:
            reason = "missing_keyword"

    return {
        "has_closing_link": has_link,
        "linked_issues": linked,
        "closing_link_reason": reason,
        "base_branch": base,
        "default_branch": default_branch,
        "targets_default_branch": targets_default,
    }


def _number_mentioned(num: int, text: str | None) -> bool:
    if not text:
        return False
    return re.search(rf"(?<!\d){num}(?!\d)", text) is not None


def _suggest_close_issues(pr: dict, candidates: list[int]) -> tuple[list[int], str | None]:
    """
    Order assigned-issue candidates for a PR missing its closing link.
    Returns (suggested_numbers, confidence) where confidence is
    'strong' (one clear answer), 'ambiguous' (several, user must pick) or None.
    """
    if not candidates:
        return [], None
    candidates = sorted(set(candidates))
    repo = (pr.get("repository") or {}).get("nameWithOwner", "")
    body_refs = {
        n for (r, n) in GitHubClient.extract_issue_refs_from_body(pr.get("body") or "", repo)
        if r.lower() == repo.lower()
    }
    matched = [
        n for n in candidates
        if n in body_refs
        or _number_mentioned(n, pr.get("headRefName"))
        or re.search(rf"#{n}(?!\d)", pr.get("title") or "")
    ]
    ordered = matched + [n for n in candidates if n not in matched]
    if len(candidates) == 1 or len(matched) == 1:
        return ordered, "strong"
    return ordered, "ambiguous"


# ---------------------------------------------------------------------------
# Review bots that leave actionable feedback
# ---------------------------------------------------------------------------

def _bot_base_login(login: str) -> str:
    lo = (login or "").lower()
    return lo[:-5] if lo.endswith("[bot]") else lo


def _is_status_bot(author: dict | None) -> bool:
    """Known automation/deploy/status bots whose comments are never feedback."""
    from github_client import IGNORE_BOT_LOGINS
    return _bot_base_login((author or {}).get("login", "")) in IGNORE_BOT_LOGINS


def _newer_than(dt: datetime | None, ref: datetime | None) -> bool:
    if dt is None:
        return False
    return ref is None or dt > ref


def _actionable_bot_review(pr: dict, me: str, last_commit_dt: datetime | None) -> dict | None:
    """
    Feedback from a bot that the normal bot filter would hide, but that asks for work:
      - a formal CHANGES_REQUESTED review newer than your last commit, not later
        superseded by APPROVED or DISMISSED from the same bot, or
      - an unresolved, non-outdated review thread whose latest comment is from a bot
        and newer than your last commit.
    Returns {login, reason, at, body} for the most recent one, or None.
    """
    me_lo = me.lower()
    found: list[tuple[datetime, dict]] = []

    latest_decision: dict[str, dict] = {}
    for r in pr.get("reviews", {}).get("nodes", []):
        author = r.get("author") or {}
        login = author.get("login", "")
        if not login or login.lower() == me_lo or not _is_bot_author_obj(author):
            continue
        if r.get("state") not in ("CHANGES_REQUESTED", "APPROVED", "DISMISSED"):
            continue
        key = _bot_base_login(login)
        prev = latest_decision.get(key)
        sub = _parse_dt(r.get("submittedAt"))
        if not prev or (sub and sub > (_parse_dt(prev.get("submittedAt")) or datetime.min.replace(tzinfo=timezone.utc))):
            latest_decision[key] = r
    for r in latest_decision.values():
        sub = _parse_dt(r.get("submittedAt"))
        if r.get("state") == "CHANGES_REQUESTED" and _newer_than(sub, last_commit_dt):
            found.append((sub, {
                "login": (r.get("author") or {}).get("login", ""),
                "reason": "changes_requested",
                "body": _snippet(r.get("body")),
            }))

    for thread in pr.get("reviewThreads", {}).get("nodes", []):
        if thread.get("isResolved") or thread.get("isOutdated"):
            continue
        nodes = thread.get("comments", {}).get("nodes", [])
        if not nodes:
            continue
        last = nodes[-1]
        author = last.get("author") or {}
        login = author.get("login", "")
        if not login or login.lower() == me_lo or not _is_bot_author_obj(author):
            continue
        created = _parse_dt(last.get("createdAt"))
        if _newer_than(created, last_commit_dt):
            found.append((created, {"login": login, "reason": "review_thread", "body": _snippet(last.get("body"))}))

    if not found:
        return None
    at, info = max(found, key=lambda x: x[0])
    info["at"] = at
    return info


def _bot_feedback_hint(pr: dict, me: str, last_commit_dt: datetime | None) -> dict | None:
    """
    Soft hint: the latest top-level comment from a bot that is neither a known status bot
    nor an AI reviewer (those already count), posted after your last commit.
    Never changes the bucket.
    """
    me_lo = me.lower()
    best: tuple[datetime, dict] | None = None
    for c in pr.get("comments", {}).get("nodes", []):
        author = c.get("author") or {}
        login = author.get("login", "")
        if not login or login.lower() == me_lo:
            continue
        if not _is_bot_author_obj(author) or _is_status_bot(author):
            continue
        created = _parse_dt(c.get("createdAt"))
        if not _newer_than(created, last_commit_dt):
            continue
        if best is None or created > best[0]:
            best = (created, c)
    if best is None:
        return None
    created, c = best
    return {
        "login": (c.get("author") or {}).get("login", ""),
        "body": _snippet(c.get("body")),
        "at": _iso_utc(created),
        "days_ago": _days_ago(created),
    }


# ---------------------------------------------------------------------------
# CI checks on the head commit
# ---------------------------------------------------------------------------

_CI_PASS = {"SUCCESS"}
_CI_FAIL = {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "STARTUP_FAILURE"}
_CI_EXCLUDED = {"SKIPPED", "NEUTRAL"}
_FIRST_TIMER_ASSOCIATIONS = {"FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER", "NONE"}


def _ci_summary(pr: dict) -> dict:
    """
    Count CI results on the PR's head commit.
    ci_state: SUCCESS | FAILURE | PENDING | NONE | AWAITING_APPROVAL
    AWAITING_APPROVAL means checks have not run, most likely because a maintainer
    must approve workflows for a first-time contributor's fork PR.
    """
    commit_nodes = pr.get("commits", {}).get("nodes", [])
    head = (commit_nodes[-1].get("commit") or {}) if commit_nodes else {}
    if "statusCheckRollup" not in head:
        # CI was not fetched (e.g. token not allowed to read checks): unknown, hide it.
        return {
            "ci_state": None, "ci_passed": None, "ci_failed": None,
            "ci_pending": None, "ci_total": None, "ci_partial": False,
        }
    rollup = head.get("statusCheckRollup")

    passed = failed = pending = waiting = 0
    total_count = 0
    if rollup:
        contexts = rollup.get("contexts") or {}
        total_count = contexts.get("totalCount") or 0
        for node in contexts.get("nodes", []) or []:
            is_status_context = node.get("__typename") == "StatusContext" or (
                "state" in node and "conclusion" not in node and "status" not in node
            )
            if not is_status_context:  # CheckRun
                conclusion = (node.get("conclusion") or "").upper()
                if conclusion in _CI_EXCLUDED:
                    continue
                if conclusion in _CI_PASS:
                    passed += 1
                elif conclusion in _CI_FAIL:
                    failed += 1
                elif conclusion == "ACTION_REQUIRED":
                    waiting += 1
                else:  # not completed yet, or STALE
                    pending += 1
            else:  # StatusContext
                state = (node.get("state") or "").upper()
                if state in _CI_PASS:
                    passed += 1
                elif state in ("FAILURE", "ERROR"):
                    failed += 1
                else:
                    pending += 1

    total = passed + failed + pending + waiting
    first_timer_fork = bool(pr.get("isCrossRepository")) and (
        (pr.get("authorAssociation") or "").upper() in _FIRST_TIMER_ASSOCIATIONS
    )

    if total == 0:
        state = "AWAITING_APPROVAL" if first_timer_fork else "NONE"
    elif failed:
        state = "FAILURE"
    elif waiting and not passed and not pending:
        state = "AWAITING_APPROVAL"
    elif pending or waiting:
        state = "PENDING"
    else:
        state = "SUCCESS"

    return {
        "ci_state": state,
        "ci_passed": passed,
        "ci_failed": failed,
        "ci_pending": pending + waiting,
        "ci_total": total,
        "ci_partial": total_count > len(((rollup or {}).get("contexts") or {}).get("nodes", []) or []),
    }


# ---------------------------------------------------------------------------
# PR bucket logic
# ---------------------------------------------------------------------------

def _latest_commit_dt(pr: dict) -> datetime | None:
    """Safely return the latest commit timestamp across all commits, independent of API ordering."""
    commit_nodes = pr.get("commits", {}).get("nodes", [])
    dts = []
    for c in commit_nodes:
        dt = _parse_dt(c.get("commit", {}).get("committedDate"))
        if dt:
            dts.append(dt)
    return max(dts) if dts else None


def _analyze_reviews(
    reviews: list[dict], me: str, last_commit_dt: datetime | None, ignore_bots: bool = True
) -> tuple[str | None, str, str, datetime | None, bool]:
    """
    Analyze reviews per reviewer to correctly handle multi-reviewer state.
    Returns:
      (aggregate_review_state, primary_author, primary_body, primary_at, has_unanswered_changes_requested)
    """
    me_lo = me.lower()
    by_author: dict[str, dict] = {}
    for r in reviews:
        author_obj = r.get("author") or {}
        author = author_obj.get("login", "")
        if not author or author.lower() == me_lo:
            continue
        if ignore_bots and _is_bot_author_obj(author_obj):
            continue
        submitted_at = _parse_dt(r.get("submittedAt"))
        prev = by_author.get(author.lower())
        if not prev or (submitted_at and submitted_at > (_parse_dt(prev.get("submittedAt")) or datetime.min.replace(tzinfo=timezone.utc))):
            by_author[author.lower()] = r

    if not by_author:
        return None, "", "", None, False

    has_unanswered_changes_requested = False
    blocking_review = None
    approved_count = 0
    decision_reviews = [r for r in by_author.values() if r.get("state") in ("APPROVED", "CHANGES_REQUESTED")]

    for r in by_author.values():
        state = r.get("state")
        sub_at = _parse_dt(r.get("submittedAt"))
        if state == "CHANGES_REQUESTED":
            if not (last_commit_dt and sub_at and last_commit_dt > sub_at):
                has_unanswered_changes_requested = True
                blocking_review = r
                break
        elif state == "APPROVED":
            approved_count += 1

    latest_overall = max(
        by_author.values(),
        key=lambda r: _parse_dt(r.get("submittedAt")) or datetime.min.replace(tzinfo=timezone.utc),
    )
    primary = blocking_review or latest_overall
    primary_author = (primary.get("author") or {}).get("login", "")
    primary_body = _snippet(primary.get("body"))
    primary_at = _parse_dt(primary.get("submittedAt"))

    if has_unanswered_changes_requested:
        aggregate_state = "CHANGES_REQUESTED"
    elif decision_reviews and approved_count == len(decision_reviews):
        aggregate_state = "APPROVED"
    else:
        aggregate_state = primary.get("state")

    return aggregate_state, primary_author, primary_body, primary_at, has_unanswered_changes_requested


def _their_activity(pr: dict, me: str, ignore_bots: bool) -> datetime | None:
    """
    Latest activity on the PR by anyone who is NOT the current user.
    Considers: reviews, unresolved/non-outdated thread comments, top-level comments.
    """
    candidates: list[datetime] = []
    me_lo = me.lower()

    # Reviews by others
    for review in pr.get("reviews", {}).get("nodes", []):
        author_obj = review.get("author") or {}
        author = author_obj.get("login", "")
        if author.lower() == me_lo:
            continue
        if ignore_bots and _is_bot_author_obj(author_obj):
            continue
        dt = _parse_dt(review.get("submittedAt"))
        if dt:
            candidates.append(dt)

    # Unresolved, non-outdated thread last comments by others
    for thread in pr.get("reviewThreads", {}).get("nodes", []):
        if thread.get("isResolved") or thread.get("isOutdated"):
            continue
        for comment in thread.get("comments", {}).get("nodes", []):
            author_obj = comment.get("author") or {}
            author = author_obj.get("login", "")
            if author.lower() == me_lo:
                continue
            if ignore_bots and _is_bot_author_obj(author_obj):
                continue
            dt = _parse_dt(comment.get("createdAt"))
            if dt:
                candidates.append(dt)

    # Top-level PR comments by others
    for comment in pr.get("comments", {}).get("nodes", []):
        author_obj = comment.get("author") or {}
        author = author_obj.get("login", "")
        if author.lower() == me_lo:
            continue
        if ignore_bots and _is_bot_author_obj(author_obj):
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
        if (comment.get("author") or {}).get("login", "").lower() == me_lo:
            dt = _parse_dt(comment.get("createdAt"))
            if dt:
                candidates.append(dt)

    commit_dt = _latest_commit_dt(pr)
    if commit_dt:
        candidates.append(commit_dt)

    return max(candidates) if candidates else None


def _is_bot_login(login: str) -> bool:
    from github_client import _is_bot
    return _is_bot(login)


def _is_bot_author_obj(author: dict | None) -> bool:
    from github_client import _is_bot_author
    return _is_bot_author(author)


def _last_their_comment(pr: dict, me: str, ignore_bots: bool) -> dict | None:
    """Return the most recent top-level comment snippet not by the current user."""
    me_lo = me.lower()
    candidates = []
    for comment in pr.get("comments", {}).get("nodes", []):
        author_obj = comment.get("author") or {}
        author = author_obj.get("login", "")
        if author.lower() == me_lo:
            continue
        if ignore_bots and _is_bot_author_obj(author_obj):
            continue
        dt = _parse_dt(comment.get("createdAt"))
        candidates.append((dt, comment))
    if not candidates:
        return None
    _, comment = max(candidates, key=lambda x: x[0] or datetime.min.replace(tzinfo=timezone.utc))
    return comment


def bucket_pr(
    pr: dict,
    me: str,
    ignore_bots: bool,
    min_age_hours: float = 0,
    assigned_issue_candidates: list[int] | None = None,
) -> dict:
    """
    Classify a single open PR into one of three buckets:
      NEEDS_YOU | WAITING_ON_THEM | PROBABLY_FINE

    assigned_issue_candidates: open issues in the same repo assigned to you and not
    already claimed by another of your PRs. Used to suggest a `Closes #N` line when
    this PR has no linked issue.

    Returns a structured dict ready for serialisation.
    """
    repo = pr["repository"]["nameWithOwner"]
    last_commit_dt = _latest_commit_dt(pr)
    review_state, review_author, review_body, review_at, has_unanswered_changes_requested = _analyze_reviews(
        pr.get("reviews", {}).get("nodes", []), me, last_commit_dt, ignore_bots=ignore_bots
    )

    their_dt = _their_activity(pr, me, ignore_bots)
    your_dt = _your_activity(pr, me)

    # Bots hidden by the normal filter still count when they ask for work after your last push.
    bot_review = _actionable_bot_review(pr, me, last_commit_dt) if ignore_bots else None
    bot_feedback = _bot_feedback_hint(pr, me, last_commit_dt) if ignore_bots else None
    if bot_review and bot_feedback and bot_feedback["login"].lower() == bot_review["login"].lower():
        bot_feedback = None

    # Filter out activity younger than min_age_hours if requested
    if min_age_hours > 0 and their_dt:
        age_hours = (datetime.now(timezone.utc) - their_dt).total_seconds() / 3600.0
        if age_hours < min_age_hours:
            their_dt = None

    # --- Bucket decision ---
    if has_unanswered_changes_requested:
        bucket = "NEEDS_YOU"
    elif bot_review:
        bucket = "NEEDS_YOU"
        if bot_review["reason"] == "changes_requested":
            review_state = "CHANGES_REQUESTED"
            review_author = bot_review["login"]
            review_body = bot_review["body"]
    elif review_state == "APPROVED":
        bucket = "PROBABLY_FINE"
    elif their_dt and your_dt and their_dt > your_dt:
        bucket = "NEEDS_YOU"
    elif your_dt and (not their_dt or your_dt >= their_dt):
        last_comment = _last_their_comment(pr, me, ignore_bots)
        if last_comment and _SIGN_OFF_HINTS.search(last_comment.get("body", "")):
            bucket = "PROBABLY_FINE"
        else:
            bucket = "WAITING_ON_THEM"
    else:
        bucket = "WAITING_ON_THEM"

    last_comment = _last_their_comment(pr, me, ignore_bots)
    snippet_author = ""
    snippet_body = ""
    snippet_when = None
    if last_comment:
        snippet_author = (last_comment.get("author") or {}).get("login", "")
        snippet_body = _snippet(last_comment.get("body", ""))
        snippet_when = _parse_dt(last_comment.get("createdAt"))

    link = _closing_link_info(pr)
    suggested: list[int] = []
    confidence = None
    if link["has_closing_link"] is False and link["closing_link_reason"] != "non_default_base":
        suggested, confidence = _suggest_close_issues(pr, assigned_issue_candidates or [])

    bot_at = bot_review["at"] if bot_review else None

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
        "their_last_comment_at": _iso_utc(snippet_when),
        "their_activity_days_ago": _days_ago(their_dt),
        "their_activity_at": _iso_utc(their_dt),
        "your_activity_days_ago": _days_ago(your_dt),
        "your_activity_at": _iso_utc(your_dt),
        # Linked issue (Kaycee: missing `Closes #N` costs contributors their Wave points)
        **link,
        "suggested_close_issues": suggested,
        "suggestion_confidence": confidence,
        # Bot reviewers that ask for changes after your last push
        "bot_review_actionable": bool(bot_review),
        "bot_review_author": bot_review["login"] if bot_review else "",
        "bot_review_reason": bot_review["reason"] if bot_review else None,
        "bot_review_body": bot_review["body"] if bot_review else "",
        "bot_review_days_ago": _days_ago(bot_at),
        "bot_review_at": _iso_utc(bot_at),
        "bot_feedback": bot_feedback,
        # CI on the head commit (informational only; never changes the bucket)
        **_ci_summary(pr),
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


def _my_last_comment_dt(issue: dict, me: str) -> datetime | None:
    """Timestamp of the current user's latest comment on an issue."""
    me_lo = me.lower()
    dts = []
    for c in issue.get("comments", {}).get("nodes", []):
        if (c.get("author") or {}).get("login", "").lower() == me_lo:
            dt = _parse_dt(c.get("createdAt"))
            if dt:
                dts.append(dt)
    return max(dts) if dts else None


def _days_since_my_comment(issue: dict, me: str) -> int | None:
    """Days since the current user last commented on an issue."""
    return _days_ago(_my_last_comment_dt(issue, me))


def _last_maintainer_comment(issue: dict, me: str, ignore_bots: bool) -> dict | None:
    """Most recent comment on the issue by a repository MAINTAINER (OWNER/MEMBER/COLLABORATOR)."""
    repo = issue["repository"]["nameWithOwner"]
    me_lo = me.lower()
    candidates = []
    for comment in issue.get("comments", {}).get("nodes", []):
        author_obj = comment.get("author") or {}
        author = author_obj.get("login", "")
        if author.lower() == me_lo:
            continue
        if ignore_bots and _is_bot_author_obj(author_obj):
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
    m_dt = None
    if maintainer_comment:
        m_author = (maintainer_comment.get("author") or {}).get("login", "")
        m_body = _snippet(maintainer_comment.get("body", ""))
        m_dt = _parse_dt(maintainer_comment.get("createdAt"))
    m_days = _days_ago(m_dt)
    m_iso = _iso_utc(m_dt)

    my_last_dt = _my_last_comment_dt(issue, me)
    my_last_days = _days_ago(my_last_dt)

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
        "my_last_comment_at": _iso_utc(my_last_dt),
        "forked": repo.lower() in forked_parents,
        "maintainer_comment_author": m_author,
        "maintainer_comment_body": m_body,
        "maintainer_comment_days_ago": m_days,
        "maintainer_comment_at": m_iso,
        "last_comment_author": m_author,  # backwards compatibility
        "last_comment_body": m_body,
        "last_comment_days_ago": m_days,
        "last_comment_at": m_iso,
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
        link = _closing_link_info(pr)
        results.append(
            {
                "type": "claim",
                "repo": pr["repository"]["nameWithOwner"],
                "number": pr["number"],
                "title": pr["title"],
                "url": pr.get("url", ""),
                "merged_days_ago": _days_ago(merged_at),
                "merged_at": _iso_utc(merged_at),
                **link,
                # Merged with no linked issue: Drips/bounty settlement usually can't
                # match it to an issue automatically.
                "points_at_risk": link["has_closing_link"] is False,
            }
        )
    return results


def _assigned_issues_by_repo(involved_issues: list[dict], me: str) -> dict[str, list[int]]:
    """Map repo (lowercase) -> open issue numbers assigned to you."""
    me_lo = me.lower()
    out: dict[str, list[int]] = {}
    for issue in involved_issues:
        assignees = [(a.get("login") or "").lower() for a in (issue.get("assignees") or {}).get("nodes", [])]
        if me_lo in assignees:
            out.setdefault(issue["repository"]["nameWithOwner"].lower(), []).append(issue["number"])
    return out


def _closing_claims(open_prs: list[dict]) -> dict[tuple[str, int], set[int]]:
    """Map (repo lowercase, issue number) -> numbers of your open PRs that already close it."""
    claims: dict[tuple[str, int], set[int]] = {}
    for pr in open_prs:
        for ref in (pr.get("closingIssuesReferences") or {}).get("nodes", []) or []:
            key = ((ref.get("repository") or {}).get("nameWithOwner", "").lower(), ref.get("number"))
            claims.setdefault(key, set()).add(pr["number"])
    return claims


def _candidates_for_pr(
    pr: dict,
    assigned_by_repo: dict[str, list[int]],
    closing_claims: dict[tuple[str, int], set[int]],
) -> list[int]:
    """Assigned issues in this PR's repo that no OTHER open PR of yours already closes."""
    repo_lo = pr["repository"]["nameWithOwner"].lower()
    return [
        num for num in assigned_by_repo.get(repo_lo, [])
        if not (closing_claims.get((repo_lo, num), set()) - {pr["number"]})
    ]


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

# ---------------------------------------------------------------------------
# Maintainer Mode — triage incoming PRs on repos you can merge into
# ---------------------------------------------------------------------------

MAINTAINER_CI_MIN_RATIO = 0.6       # Kaycee: "if there are 10 CI, 6 must pass"
MAINTAINER_LARGE_DIFF_LINES = 1000  # additions + deletions

# Files where malicious or risky changes usually hide: dependencies, install
# scripts, build and CI config. Matched against the full path and the file name.
SENSITIVE_FILE_PATTERNS = (
    ".github/workflows/*",
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", ".npmrc",
    "requirements*.txt", "pyproject.toml", "poetry.lock", "setup.py", "setup.cfg",
    "Cargo.toml", "Cargo.lock", "go.mod", "go.sum",
    "Dockerfile", "docker-compose*.yml", "Makefile", "*.sh",
)


def _sensitive_paths(paths: list[str]) -> list[str]:
    from fnmatch import fnmatch
    hits = []
    for p in paths:
        name = p.rsplit("/", 1)[-1]
        if any(fnmatch(p, pat) or fnmatch(name, pat) for pat in SENSITIVE_FILE_PATTERNS):
            hits.append(p)
    return hits


def _assignment_check(pr: dict, author_lo: str) -> tuple[str, list[str], list[str]]:
    """
    Was the PR author assigned to the issue(s) this PR closes?
    Returns (status, assigned_on, not_assigned_on), status one of:
      assigned | partly_assigned | not_assigned | unverifiable (no linked issue)
    """
    repo = (pr.get("repository") or {}).get("nameWithOwner", "")
    assigned_on, not_assigned_on = [], []
    for ref in (pr.get("closingIssuesReferences") or {}).get("nodes", []) or []:
        ref_repo = (ref.get("repository") or {}).get("nameWithOwner", "")
        label = f"#{ref.get('number')}" if ref_repo.lower() == repo.lower() else f"{ref_repo}#{ref.get('number')}"
        assignees = {(a.get("login") or "").lower() for a in (ref.get("assignees") or {}).get("nodes", [])}
        (assigned_on if author_lo in assignees else not_assigned_on).append(label)
    if not assigned_on and not not_assigned_on:
        return "unverifiable", [], []
    if not not_assigned_on:
        return "assigned", assigned_on, []
    if not assigned_on:
        return "not_assigned", [], not_assigned_on
    return "partly_assigned", assigned_on, not_assigned_on


def evaluate_incoming_pr(pr: dict, me: str) -> dict | None:
    """
    Score one incoming PR on Kaycee's four checks (assignment, blast radius,
    linked issue, CI ratio) plus first-timer and sensitive-file signals.
    Returns None for PRs that should not be shown (your own, or bot-authored).
    """
    author = pr.get("author") or {}
    author_login = author.get("login", "") or "ghost"
    author_lo = author_login.lower()
    if author_lo == me.lower():
        return None
    if author.get("__typename") == "Bot" or _is_bot_login(author_login):
        return None

    link = _closing_link_info(pr)
    assignment, assigned_on, not_assigned_on = _assignment_check(pr, author_lo)
    additions = pr.get("additions") or 0
    deletions = pr.get("deletions") or 0
    changed_files = pr.get("changedFiles") or 0
    paths = [f.get("path", "") for f in (pr.get("files") or {}).get("nodes", []) or []]
    sensitive = _sensitive_paths(paths)
    large_diff = additions + deletions > MAINTAINER_LARGE_DIFF_LINES
    association = (pr.get("authorAssociation") or "").upper()
    first_timer = association in _FIRST_TIMER_ASSOCIATIONS
    ci = _ci_summary(pr)

    completed = (ci["ci_passed"] or 0) + (ci["ci_failed"] or 0)
    ci_below = bool(ci["ci_failed"]) and completed > 0 and (ci["ci_passed"] or 0) / completed < MAINTAINER_CI_MIN_RATIO

    reasons: list[dict] = []

    def add(code: str, label: str, tone: str) -> None:
        reasons.append({"code": code, "label": label, "tone": tone})

    if assignment == "not_assigned":
        add("not_assigned", "Not assigned", "red")
    elif assignment == "partly_assigned":
        add("partly_assigned", "Partly assigned", "red")
    elif assignment == "unverifiable":
        add("cant_verify", "Can't verify assignment", "yellow")
    else:
        add("assigned", "Assigned", "green")
    if large_diff:
        add("large_diff", f"Large diff +{additions:,} / -{deletions:,}", "red")
    if sensitive:
        add("sensitive_files", "Touches sensitive files", "red")
    if first_timer:
        add("first_timer", "First-time contributor", "yellow")
    if link["has_closing_link"] is False:
        add("no_linked_issue", "No linked issue", "yellow")
    if ci_below:
        add("ci_below", f"CI {ci['ci_passed']}/{completed} passing", "red")
    elif ci["ci_state"] == "AWAITING_APPROVAL":
        add("ci_awaiting", "CI awaiting approval", "yellow")

    risky_unverified = assignment == "unverifiable" and (large_diff or first_timer or bool(sensitive))
    if pr.get("isDraft"):
        bucket = "DRAFTS"
    elif assignment in ("not_assigned", "partly_assigned") or risky_unverified:
        bucket = "SUSPICIOUS"
    elif link["has_closing_link"] is False or ci_below:
        bucket = "BOUNCE_BACK"
    else:
        bucket = "REVIEW_NOW"

    created = _parse_dt(pr.get("createdAt"))
    return {
        "type": "incoming_pr",
        "bucket": bucket,
        "repo": (pr.get("repository") or {}).get("nameWithOwner", ""),
        "number": pr["number"],
        "title": pr.get("title", ""),
        "url": pr.get("url", ""),
        "is_draft": bool(pr.get("isDraft")),
        "author": author_login,
        "author_association": association,
        "is_first_timer": first_timer,
        "created_days_ago": _days_ago(created),
        "created_at": _iso_utc(created),
        "assignment_status": assignment,
        "assigned_on": assigned_on,
        "not_assigned_on": not_assigned_on,
        **link,
        "additions": additions,
        "deletions": deletions,
        "changed_files": changed_files,
        "large_diff": large_diff,
        "sensitive_files": sensitive,
        "files_partial": changed_files > len(paths),
        **ci,
        "ci_below_threshold": ci_below,
        "reasons": reasons,
    }


MAINTAINER_BUCKETS = ("SUSPICIOUS", "BOUNCE_BACK", "REVIEW_NOW", "DRAFTS")


def run_maintainer_triage(
    client: GitHubClient,
    ignore_repos: set[str] | None = None,
    only_repos: set[str] | None = None,
) -> dict:
    """
    Read-only triage of PRs other people opened on repos you can merge into.
    Never comments, labels, closes or merges anything.
    """
    ignore_repos = {r.lower() for r in (ignore_repos or set())}
    only_repos = {r.lower() for r in (only_repos or set())}

    repos, truncated = client.get_maintained_repos_with_open_prs()
    repos = [
        r for r in repos
        if r.lower() not in ignore_repos and (not only_repos or r.lower() in only_repos)
    ]
    prs = client.get_incoming_prs(repos)

    buckets: dict[str, list] = {b: [] for b in MAINTAINER_BUCKETS}
    for pr in prs:
        item = evaluate_incoming_pr(pr, client.username)
        if item:
            buckets[item["bucket"]].append(item)
    for items in buckets.values():
        items.sort(key=lambda i: i.get("created_at") or "", reverse=True)

    return {
        "username": client.username,
        "view": "maintainer",
        "maintainer": buckets,
        "summary": {
            "suspicious": len(buckets["SUSPICIOUS"]),
            "bounce_back": len(buckets["BOUNCE_BACK"]),
            "review_now": len(buckets["REVIEW_NOW"]),
            "drafts": len(buckets["DRAFTS"]),
            "repos_scanned": len(repos),
            "repos_truncated": truncated,
        },
    }


def _is_own_repo(repo: str, me_lo: str) -> bool:
    return bool(me_lo) and repo.split("/", 1)[0].lower() == me_lo


def run_triage(
    client: GitHubClient,
    include_drafts: bool = False,
    ignore_bots: bool = True,
    ignore_repos: set[str] | None = None,
    only_repos: set[str] | None = None,
    claims_days: int = 14,
    min_age_hours: float = 0,
    external_only: bool = False,
) -> dict:
    """
    Run a full triage and return a structured JSON-serialisable dict.
    """
    ignore_repos = {r.lower() for r in (ignore_repos or set())}
    only_repos = {r.lower() for r in (only_repos or set())}
    me_lo = (client.username or "").lower()

    def _repo_allowed(repo: str) -> bool:
        r = repo.lower()
        if external_only and me_lo and r.split("/", 1)[0] == me_lo:
            return False
        if ignore_repos and r in ignore_repos:
            return False
        if only_repos and r not in only_repos:
            return False
        return True

    # Fetch all data concurrently to minimize latency on serverless hosts
    with ThreadPoolExecutor(max_workers=5) as pool:
        f_open = pool.submit(client.get_open_prs, include_drafts=include_drafts)
        f_merged = pool.submit(client.get_merged_prs, limit=20)
        f_issues = pool.submit(client.get_involved_issues)
        f_forks = pool.submit(client.get_forked_parents)
        f_write = pool.submit(client.get_write_access_repos)

        open_prs = [
            pr for pr in f_open.result()
            if _repo_allowed(pr["repository"]["nameWithOwner"])
        ]
        merged_prs = [
            pr for pr in f_merged.result()
            if _repo_allowed(pr["repository"]["nameWithOwner"])
        ]
        involved_issues = [
            i for i in f_issues.result()
            if _repo_allowed(i["repository"]["nameWithOwner"])
        ]
        forked_parents = f_forks.result()
        write_access_repos = f_write.result()

    # Compute
    linked = _build_linked_set(open_prs, client)

    assigned_by_repo = _assigned_issues_by_repo(involved_issues, client.username)
    closing_claims = _closing_claims(open_prs)

    bucketed_prs: dict[str, list] = {"NEEDS_YOU": [], "WAITING_ON_THEM": [], "PROBABLY_FINE": []}
    for pr in open_prs:
        result = bucket_pr(
            pr,
            client.username,
            ignore_bots,
            min_age_hours=min_age_hours,
            assigned_issue_candidates=_candidates_for_pr(pr, assigned_by_repo, closing_claims),
        )
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
            # External repos only: linking matters for Wave/bounty settlement, not your own repos.
            "unlinked_prs": sum(
                1 for items in bucketed_prs.values() for p in items
                if p.get("has_closing_link") is False and not _is_own_repo(p["repo"], me_lo)
            ),
            "points_at_risk": sum(
                1 for c in claims if c.get("points_at_risk") and not _is_own_repo(c["repo"], me_lo)
            ),
        },
    }
