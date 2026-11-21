"""
github_client.py — GitHub API client for 3riage.

Uses GraphQL v4 as primary transport. REST only where GraphQL
doesn't expose what we need (e.g. search pagination edge cases).

Rate limit budget:
  - GraphQL: 5,000 points/hour (each node ~1 point)
  - REST search: 30 requests/minute (avoided — we use GraphQL search)
"""

import os
import re
import subprocess
import threading
import requests
from typing import Any

GRAPHQL_URL = "https://api.github.com/graphql"

# Matches: #123  owner/repo#123  https://github.com/owner/repo/issues/123
ISSUE_REF_RE = re.compile(
    r"(?:https://github\.com/([^/\s]+)/([^/\s]+)/issues/(\d+)"
    r"|([a-zA-Z0-9_.\-]+/[a-zA-Z0-9_.\-]+)?#(\d+))"
)

BOT_SUFFIXES = ("[bot]", "-bot", "_bot")

# AI code reviewers are INTENTIONALLY NOT ignored by default, even though
# GitHub GraphQL reports them with __typename == "Bot". Their inline comments
# and reviews represent actionable review feedback to address.
AI_REVIEWER_BOT_LOGINS = {
    "coderabbitai",
    "copilot-pull-request-reviewer",
    "sourcery-ai",
    "greptile-apps",
    "ellipsis-dev",
    "qodo-merge-pro",
    "codiumai",
    "bito-code-review",
    "cubic-dev-ai",
}

# Fallback login list for automation/CI/deploy/bounty-status bots when GraphQL
# __typename metadata is absent (e.g. REST payloads or minimal unit-test dicts).
IGNORE_BOT_LOGINS = {
    "dependabot",
    "github-actions",
    "renovate",
    "stale",
    "codecov",
    "coveralls",
    "snyk-bot",
    "sonarcloud",
    "drips-wave",
    "vercel",
    "netlify",
    "cloudflare-workers-and-pages",
    "changeset-bot",
    "mergify",
    "claassistant",
    "linear",
    "github-pages",
}


def _is_bot(login: str) -> bool:
    lo = login.lower()
    base = lo[:-5] if lo.endswith("[bot]") else lo
    if base in AI_REVIEWER_BOT_LOGINS:
        return False
    return any(lo.endswith(s) for s in BOT_SUFFIXES) or base in IGNORE_BOT_LOGINS


def _is_bot_author(author: dict | None) -> bool:
    """Return True if a GraphQL Actor dict represents a non-AI-reviewer bot."""
    if not author:
        return False
    login = (author.get("login") or "").strip()
    lo = login.lower()
    base = lo[:-5] if lo.endswith("[bot]") else lo
    if base in AI_REVIEWER_BOT_LOGINS:
        return False
    if author.get("__typename") == "Bot":
        return True
    return _is_bot(login)


class GitHubClient:
    def __init__(self, token: str, username: str = "", ignore_bots: bool = True):
        self.username = username
        self.ignore_bots = ignore_bots
        self._init_thread_id = threading.get_ident()
        self._thread_local = threading.local()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/vnd.github+json",
            }
        )

    def _get_session(self) -> requests.Session:
        if threading.get_ident() == self._init_thread_id or type(self.session) is not requests.Session:
            return self.session
        sess = getattr(self._thread_local, "session", None)
        if sess is None:
            sess = requests.Session()
            sess.headers.update(self.session.headers)
            self._thread_local.session = sess
        return sess

    # ------------------------------------------------------------------
    # Low-level
    # ------------------------------------------------------------------

    def _gql(self, query: str, variables: dict) -> dict:
        resp = self._get_session().post(
            GRAPHQL_URL, json={"query": query, "variables": variables}, timeout=(5, 12)
        )
        resp.raise_for_status()
        body = resp.json()
        if "errors" in body:
            raise RuntimeError(f"GraphQL errors: {body['errors']}")
        return body["data"]

    _VIEWER_QUERY = """
    query {
      viewer {
        login
      }
    }
    """

    def get_viewer_login(self) -> str:
        """Return the authenticated GitHub user's login for the current token."""
        data = self._gql(self._VIEWER_QUERY, {})
        login = (data.get("viewer") or {}).get("login", "")
        if not login:
            raise RuntimeError("Could not resolve authenticated GitHub login from viewer query.")
        self.username = login
        return login

    # ------------------------------------------------------------------
    # Open PRs authored by the user
    # ------------------------------------------------------------------

    _PR_QUERY = """
    query($login: String!, $after: String) {
      user(login: $login) {
        pullRequests(states: OPEN, first: 50, after: $after,
                     orderBy: {field: UPDATED_AT, direction: DESC}) {
          pageInfo { hasNextPage endCursor }
          nodes {
            number title url isDraft
            repository { nameWithOwner }
            body
            closingIssuesReferences(first: 10) {
              nodes { number repository { nameWithOwner } }
            }
            reviews(last: 10) {
              nodes { author { __typename login } state body submittedAt }
            }
            reviewThreads(first: 50) {
              nodes {
                isResolved isOutdated
                comments(last: 1) {
                  nodes { author { __typename login } body createdAt }
                }
              }
            }
            comments(last: 10) {
              nodes { author { __typename login } body createdAt }
            }
            commits(last: 1) {
              nodes { commit { committedDate } }
            }
          }
        }
      }
    }
    """

    def get_open_prs(self, include_drafts: bool = False) -> list[dict]:
        prs = []
        after = None
        while True:
            data = self._gql(self._PR_QUERY, {"login": self.username, "after": after})
            page = data["user"]["pullRequests"]
            for pr in page["nodes"]:
                if pr["isDraft"] and not include_drafts:
                    continue
                prs.append(pr)
            if not page["pageInfo"]["hasNextPage"]:
                break
            after = page["pageInfo"]["endCursor"]
        return prs

    # ------------------------------------------------------------------
    # Recently merged PRs (for "Ready to Claim" shelf)
    # ------------------------------------------------------------------

    _MERGED_PR_QUERY = """
    query($login: String!, $after: String) {
      user(login: $login) {
        pullRequests(states: MERGED, first: 20, after: $after,
                     orderBy: {field: UPDATED_AT, direction: DESC}) {
          pageInfo { hasNextPage endCursor }
          nodes {
            number title url
            mergedAt
            repository { nameWithOwner }
          }
        }
      }
    }
    """

    def get_merged_prs(self, limit: int = 20) -> list[dict]:
        data = self._gql(self._MERGED_PR_QUERY, {"login": self.username, "after": None})
        return data["user"]["pullRequests"]["nodes"][:limit]

    # ------------------------------------------------------------------
    # Involved open issues (GraphQL search — avoids REST 30/min limit)
    # ------------------------------------------------------------------

    _ISSUE_SEARCH_QUERY = """
    query($q: String!, $after: String) {
      search(query: $q, type: ISSUE, first: 50, after: $after) {
        issueCount
        pageInfo { hasNextPage endCursor }
        nodes {
          ... on Issue {
            number title url state
            repository { nameWithOwner }
            author { __typename login }
            assignees(first: 10) { nodes { login } }
            comments(last: 20) {
              nodes { author { __typename login } authorAssociation body createdAt }
            }
          }
        }
      }
    }
    """

    def get_involved_issues(self) -> list[dict]:
        q = f"is:issue is:open involves:{self.username}"
        issues = []
        after = None
        while True:
            data = self._gql(self._ISSUE_SEARCH_QUERY, {"q": q, "after": after})
            page = data["search"]
            issues.extend(page["nodes"])
            if not page["pageInfo"]["hasNextPage"]:
                break
            after = page["pageInfo"]["endCursor"]
        return issues

    # ------------------------------------------------------------------
    # User's forks
    # ------------------------------------------------------------------

    _FORKS_QUERY = """
    query($after: String) {
      viewer {
        repositories(isFork: true, first: 100, after: $after) {
          pageInfo { hasNextPage endCursor }
          nodes {
            nameWithOwner
            parent { nameWithOwner }
          }
        }
      }
    }
    """

    def get_forked_parents(self) -> set[str]:
        """Return the set of upstream 'owner/repo' you have already forked."""
        forked = set()
        after = None
        while True:
            data = self._gql(self._FORKS_QUERY, {"after": after})
            page = data["viewer"]["repositories"]
            for repo in page["nodes"]:
                if repo.get("parent"):
                    forked.add(repo["parent"]["nameWithOwner"].lower())
            if not page["pageInfo"]["hasNextPage"]:
                break
            after = page["pageInfo"]["endCursor"]
        return forked

    # ------------------------------------------------------------------
    # Repos you have direct write access to (collab / org member)
    # ------------------------------------------------------------------

    _COLLAB_REPOS_QUERY = """
    query($after: String) {
      viewer {
        repositories(
          affiliations: [COLLABORATOR, ORGANIZATION_MEMBER]
          first: 100
          after: $after
        ) {
          pageInfo { hasNextPage endCursor }
          nodes { nameWithOwner viewerPermission }
        }
      }
    }
    """

    def get_write_access_repos(self) -> set[str]:
        """Return repos where you have WRITE or ADMIN permission."""
        repos = set()
        after = None
        while True:
            data = self._gql(self._COLLAB_REPOS_QUERY, {"after": after})
            page = data["viewer"]["repositories"]
            for repo in page["nodes"]:
                if repo.get("viewerPermission") in ("WRITE", "ADMIN", "MAINTAIN"):
                    repos.add(repo["nameWithOwner"].lower())
            if not page["pageInfo"]["hasNextPage"]:
                break
            after = page["pageInfo"]["endCursor"]
        return repos

    # ------------------------------------------------------------------
    # Fork action (write action — uses gh CLI, not the read-only token)
    # ------------------------------------------------------------------

    @staticmethod
    def fork_repo(repo: str) -> tuple[bool, str]:
        """
        Fork owner/repo via `gh repo fork --clone=false`.
        Returns (success, message).
        Forks asynchronously; GitHub takes a few seconds to complete.
        """
        try:
            result = subprocess.run(
                ["gh", "repo", "fork", repo, "--clone=false"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return True, result.stdout.strip() or f"Fork of {repo} initiated."
            return False, result.stderr.strip()
        except FileNotFoundError:
            return False, "`gh` CLI not found. Install from https://cli.github.com/"
        except subprocess.TimeoutExpired:
            return False, "Fork request timed out."

    # ------------------------------------------------------------------
    # Helpers used by core.py
    # ------------------------------------------------------------------

    @staticmethod
    def extract_issue_refs_from_body(body: str, pr_repo: str) -> set[tuple[str, int]]:
        """
        Parse PR body for issue references beyond closingIssuesReferences.
        Returns a set of (owner/repo, issue_number) tuples.
        """
        if not body:
            return set()
        refs = set()
        for m in ISSUE_REF_RE.finditer(body):
            if m.group(1):  # full URL form
                owner, repo_name, num = m.group(1), m.group(2), int(m.group(3))
                refs.add((f"{owner}/{repo_name}", num))
            elif m.group(5):  # #123 or owner/repo#123 form
                num = int(m.group(5))
                repo = m.group(4) if m.group(4) else pr_repo
                refs.add((repo, num))
        return refs

    def filter_bots(self, comments: list[dict]) -> list[dict]:
        if not self.ignore_bots:
            return comments
        return [c for c in comments if not _is_bot(c.get("author", {}).get("login", ""))]
