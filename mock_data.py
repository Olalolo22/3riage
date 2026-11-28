"""
mock_data.py — Curated sample dataset for 3riage demo / sandbox mode.

Matches the exact schema of core.run_triage():
  - 15 PRs (6 NEEDS_YOU, 6 WAITING_ON_THEM, 3 PROBABLY_FINE)
  - 6 Issue Bids (2 assigned to contributor, 2 active bids in review, 2 outbid / assigned to competitor)
  - 11 Claims Shelf items (merged across fictional repos in the last 14 days)
  - Fork reports & accurate summary counters

All repos, usernames, and amounts are completely fictional.
"""

from datetime import datetime, timedelta, timezone
from typing import Any


def _mock_iso(now: datetime, days: int | None, extra_hours: float = 0.0) -> str | None:
    if days is None:
        return None
    dt = now - timedelta(days=days, hours=extra_hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ci(state: str, passed: int, failed: int = 0, pending: int = 0) -> dict[str, Any]:
    return {
        "ci_state": state,
        "ci_passed": passed,
        "ci_failed": failed,
        "ci_pending": pending,
        "ci_total": passed + failed + pending,
        "ci_partial": False,
    }


def _pr_defaults(item: dict[str, Any]) -> dict[str, Any]:
    """Fields added for linked-issue, review-bot and CI checks (schema-synced with core.bucket_pr)."""
    return {
        "has_closing_link": True,
        "linked_issues": [f"#{max(1, item['number'] - 9)}"],
        "closing_link_reason": None,
        "base_branch": "main",
        "default_branch": "main",
        "targets_default_branch": True,
        "suggested_close_issues": [],
        "suggestion_confidence": None,
        "bot_review_actionable": False,
        "bot_review_author": "",
        "bot_review_reason": None,
        "bot_review_body": "",
        "bot_review_days_ago": None,
        "bot_review_at": None,
        "bot_feedback": None,
        **_ci("SUCCESS", 6),
    }


# Curated demo cases, keyed by (repo, number). Each one showcases a feature.
_PR_OVERRIDES: dict[tuple[str, int], dict[str, Any]] = {
    # Missing `Closes #N`, and the only assigned issue in the repo is #97 -> strong suggestion.
    ("nexus-mesh/relayer-node", 215): {
        "has_closing_link": False,
        "linked_issues": [],
        "closing_link_reason": "missing_keyword",
        "suggested_close_issues": [97],
        "suggestion_confidence": "strong",
        **_ci("SUCCESS", 8),
    },
    # Reviewer mentions ARM64 CI failure -> red CI.
    ("hyperion-zk/circuit-std", 54): _ci("FAILURE", 7, failed=2),
    # Custom review bot requested changes after the last push.
    ("stellar-vault/liquidity-engine", 330): {
        "review_state": "CHANGES_REQUESTED",
        "review_author": "vault-guard",
        "review_body": "Missing invariant test for the flash loan repayment path. Add it before merge.",
        "their_last_comment_author": "vault-guard",
        "their_last_comment_body": "Missing invariant test for the flash loan repayment path. Add it before merge.",
        "bot_review_actionable": True,
        "bot_review_author": "vault-guard",
        "bot_review_reason": "changes_requested",
        "bot_review_body": "Missing invariant test for the flash loan repayment path. Add it before merge.",
        "bot_review_days_ago": 2,
        **_ci("SUCCESS", 5),
    },
    # Targets a release branch, so GitHub ignores the closing keyword.
    ("solstice-network/settlement-core", 149): {
        "has_closing_link": False,
        "linked_issues": [],
        "closing_link_reason": "non_default_base",
        "base_branch": "release/v0.9",
        "targets_default_branch": False,
    },
    # Body says "Fixes #1081" but no such issue -> keyword not linked.
    ("aether-stream/contracts", 94): {
        "has_closing_link": False,
        "linked_issues": [],
        "closing_link_reason": "keyword_not_linked",
        **_ci("NONE", 0),
    },
    # First-time contributor fork: checks haven't run yet.
    ("nexus-mesh/relayer-node", 221): _ci("AWAITING_APPROVAL", 0),
    # Unknown bot left a comment after the last push -> soft hint, bucket unchanged.
    ("chronos-protocol/time-oracle", 102): {
        "bot_feedback": {
            "login": "gas-reporter",
            "body": "Gas usage on settle() increased by 4.2% compared to main.",
            "days_ago": 1,
        },
        **_ci("PENDING", 4, pending=3),
    },
}

# Merged PRs with no linked issue: points may not settle automatically.
_CLAIMS_AT_RISK = {("nexus-mesh/relayer-node", 212), ("aether-stream/contracts", 76)}


def get_mock_triage_data() -> dict[str, Any]:
    prs_needs_you = [
        {
            "type": "pr",
            "bucket": "NEEDS_YOU",
            "repo": "solstice-network/settlement-core",
            "number": 142,
            "title": "feat: optimistic settlement rollback on verification timeout",
            "url": "https://github.com/solstice-network/settlement-core/pull/142",
            "is_draft": False,
            "review_state": "CHANGES_REQUESTED",
            "review_author": "core_maintainer_kai",
            "review_body": "Please add regression tests for replay nonces before we can merge this.",
            "their_last_comment_author": "core_maintainer_kai",
            "their_last_comment_body": "Please add regression tests for replay nonces before we can merge this.",
            "their_last_comment_days_ago": 1,
            "their_activity_days_ago": 1,
            "your_activity_days_ago": 3,
        },
        {
            "type": "pr",
            "bucket": "NEEDS_YOU",
            "repo": "aether-stream/contracts",
            "number": 88,
            "title": "fix: underflow in streaming fee rate calculation on fractional balances",
            "url": "https://github.com/aether-stream/contracts/pull/88",
            "is_draft": False,
            "review_state": "COMMENTED",
            "review_author": "cadence_coder",
            "review_body": "Have you verified how this interacts with fractional token balances under 6 decimals?",
            "their_last_comment_author": "cadence_coder",
            "their_last_comment_body": "Have you verified how this interacts with fractional token balances under 6 decimals?",
            "their_last_comment_days_ago": 2,
            "their_activity_days_ago": 2,
            "your_activity_days_ago": 4,
        },
        {
            "type": "pr",
            "bucket": "NEEDS_YOU",
            "repo": "nexus-mesh/relayer-node",
            "number": 215,
            "title": "refactor: isolate gossipsub packet decompression buffer",
            "url": "https://github.com/nexus-mesh/relayer-node/pull/215",
            "is_draft": False,
            "review_state": "CHANGES_REQUESTED",
            "review_author": "relayer_lead",
            "review_body": "Unbounded buffer allocation on uncompressed frames introduces OOM risk under spam. Use pooled buffers.",
            "their_last_comment_author": "relayer_lead",
            "their_last_comment_body": "Unbounded buffer allocation on uncompressed frames introduces OOM risk under spam. Use pooled buffers.",
            "their_last_comment_days_ago": 3,
            "their_activity_days_ago": 3,
            "your_activity_days_ago": 6,
        },
        {
            "type": "pr",
            "bucket": "NEEDS_YOU",
            "repo": "hyperion-zk/circuit-std",
            "number": 54,
            "title": "perf: batch multi-scalar multiplication in groth16 verifier",
            "url": "https://github.com/hyperion-zk/circuit-std/pull/54",
            "is_draft": False,
            "review_state": "COMMENTED",
            "review_author": "zk_wizard",
            "review_body": "CI failed on ARM64 targets. Can you check the assembly intrinsics fallback?",
            "their_last_comment_author": "zk_wizard",
            "their_last_comment_body": "CI failed on ARM64 targets. Can you check the assembly intrinsics fallback?",
            "their_last_comment_days_ago": 1,
            "their_activity_days_ago": 1,
            "your_activity_days_ago": 5,
        },
        {
            "type": "pr",
            "bucket": "NEEDS_YOU",
            "repo": "chronos-protocol/time-oracle",
            "number": 91,
            "title": "feat: pyth-compatible medianizer with staleness threshold",
            "url": "https://github.com/chronos-protocol/time-oracle/pull/91",
            "is_draft": False,
            "review_state": "CHANGES_REQUESTED",
            "review_author": "validator_sam",
            "review_body": "Staleness check needs to verify both publisher timestamp and slot delta.",
            "their_last_comment_author": "validator_sam",
            "their_last_comment_body": "Staleness check needs to verify both publisher timestamp and slot delta.",
            "their_last_comment_days_ago": 4,
            "their_activity_days_ago": 4,
            "your_activity_days_ago": 7,
        },
        {
            "type": "pr",
            "bucket": "NEEDS_YOU",
            "repo": "stellar-vault/liquidity-engine",
            "number": 330,
            "title": "fix: reentrancy guard order on flash loan repayment",
            "url": "https://github.com/stellar-vault/liquidity-engine/pull/330",
            "is_draft": False,
            "review_state": "COMMENTED",
            "review_author": "sol_architect",
            "review_body": "Did you run the invariant fuzz tests with echidna/medusa on this branch?",
            "their_last_comment_author": "sol_architect",
            "their_last_comment_body": "Did you run the invariant fuzz tests with echidna/medusa on this branch?",
            "their_last_comment_days_ago": 2,
            "their_activity_days_ago": 2,
            "your_activity_days_ago": 4,
        },
    ]

    prs_waiting_on_them = [
        {
            "type": "pr",
            "bucket": "WAITING_ON_THEM",
            "repo": "solstice-network/settlement-core",
            "number": 149,
            "title": "perf: zero-copy deserialization for batch transfer logs",
            "url": "https://github.com/solstice-network/settlement-core/pull/149",
            "is_draft": False,
            "review_state": None,
            "review_author": "",
            "review_body": "",
            "their_last_comment_author": "core_maintainer_kai",
            "their_last_comment_body": "Looks clean, will review after tomorrow's testnet deployment.",
            "their_last_comment_days_ago": 4,
            "their_activity_days_ago": 4,
            "your_activity_days_ago": 2,
        },
        {
            "type": "pr",
            "bucket": "WAITING_ON_THEM",
            "repo": "aether-stream/contracts",
            "number": 94,
            "title": "docs: clarify escrow release invariants in architecture spec",
            "url": "https://github.com/aether-stream/contracts/pull/94",
            "is_draft": False,
            "review_state": None,
            "review_author": "",
            "review_body": "",
            "their_last_comment_author": "cadence_coder",
            "their_last_comment_body": "Thanks for drafting this, will read through this afternoon.",
            "their_last_comment_days_ago": 3,
            "their_activity_days_ago": 3,
            "your_activity_days_ago": 1,
        },
        {
            "type": "pr",
            "bucket": "WAITING_ON_THEM",
            "repo": "nexus-mesh/relayer-node",
            "number": 221,
            "title": "chore: upgrade libp2p transport to v0.52 and prune unused deps",
            "url": "https://github.com/nexus-mesh/relayer-node/pull/221",
            "is_draft": False,
            "review_state": None,
            "review_author": "",
            "review_body": "",
            "their_last_comment_author": "",
            "their_last_comment_body": "",
            "their_last_comment_days_ago": None,
            "their_activity_days_ago": None,
            "your_activity_days_ago": 3,
        },
        {
            "type": "pr",
            "bucket": "WAITING_ON_THEM",
            "repo": "hyperion-zk/circuit-std",
            "number": 61,
            "title": "test: add formal verification harness for poseidon permutation",
            "url": "https://github.com/hyperion-zk/circuit-std/pull/61",
            "is_draft": False,
            "review_state": None,
            "review_author": "",
            "review_body": "",
            "their_last_comment_author": "",
            "their_last_comment_body": "",
            "their_last_comment_days_ago": None,
            "their_activity_days_ago": None,
            "your_activity_days_ago": 2,
        },
        {
            "type": "pr",
            "bucket": "WAITING_ON_THEM",
            "repo": "chronos-protocol/time-oracle",
            "number": 102,
            "title": "ci: add automated gas benchmarking on PR branches",
            "url": "https://github.com/chronos-protocol/time-oracle/pull/102",
            "is_draft": False,
            "review_state": None,
            "review_author": "",
            "review_body": "",
            "their_last_comment_author": "validator_sam",
            "their_last_comment_body": "Queued for merge review behind release candidate.",
            "their_last_comment_days_ago": 5,
            "their_activity_days_ago": 5,
            "your_activity_days_ago": 4,
        },
        {
            "type": "pr",
            "bucket": "WAITING_ON_THEM",
            "repo": "stellar-vault/liquidity-engine",
            "number": 342,
            "title": "refactor: extract invariant checker to standalone crate",
            "url": "https://github.com/stellar-vault/liquidity-engine/pull/342",
            "is_draft": False,
            "review_state": None,
            "review_author": "",
            "review_body": "",
            "their_last_comment_author": "",
            "their_last_comment_body": "",
            "their_last_comment_days_ago": None,
            "their_activity_days_ago": None,
            "your_activity_days_ago": 1,
        },
    ]

    prs_probably_fine = [
        {
            "type": "pr",
            "bucket": "PROBABLY_FINE",
            "repo": "solstice-network/settlement-core",
            "number": 153,
            "title": "fix: handle edge-case EOF in binary wire codec",
            "url": "https://github.com/solstice-network/settlement-core/pull/153",
            "is_draft": False,
            "review_state": "APPROVED",
            "review_author": "core_maintainer_kai",
            "review_body": "LGTM, queueing for release v0.9.1.",
            "their_last_comment_author": "core_maintainer_kai",
            "their_last_comment_body": "LGTM, queueing for release v0.9.1.",
            "their_last_comment_days_ago": 1,
            "their_activity_days_ago": 1,
            "your_activity_days_ago": 2,
        },
        {
            "type": "pr",
            "bucket": "PROBABLY_FINE",
            "repo": "nexus-mesh/relayer-node",
            "number": 228,
            "title": "docs: add relayer setup guide for testnet node operators",
            "url": "https://github.com/nexus-mesh/relayer-node/pull/228",
            "is_draft": False,
            "review_state": "APPROVED",
            "review_author": "relayer_lead",
            "review_body": "Clean and precise. Approved.",
            "their_last_comment_author": "relayer_lead",
            "their_last_comment_body": "Clean and precise. Approved.",
            "their_last_comment_days_ago": 2,
            "their_activity_days_ago": 2,
            "your_activity_days_ago": 3,
        },
        {
            "type": "pr",
            "bucket": "PROBABLY_FINE",
            "repo": "hyperion-zk/circuit-std",
            "number": 67,
            "title": "chore: update circuit benchmarks in README",
            "url": "https://github.com/hyperion-zk/circuit-std/pull/67",
            "is_draft": False,
            "review_state": "APPROVED",
            "review_author": "zk_wizard",
            "review_body": "Looks good, merging after merge queue clears.",
            "their_last_comment_author": "zk_wizard",
            "their_last_comment_body": "Looks good, merging after merge queue clears.",
            "their_last_comment_days_ago": 1,
            "their_activity_days_ago": 1,
            "your_activity_days_ago": 1,
        },
    ]

    unlinked_issues = [
        {
            "type": "issue",
            "repo": "nexus-mesh/relayer-node",
            "number": 97,
            "title": "perf: memory leak in batch state tree verification loop",
            "url": "https://github.com/nexus-mesh/relayer-node/issues/97",
            "role": "assignee",
            "is_dimmed": False,
            "applicant_count": 3,
            "applicant_list": ["demo-contributor", "bounty_hunter_99", "zk_coder"],
            "days_since_my_comment": 1,
            "forked": True,
            "maintainer_comment_author": "relayer_lead",
            "maintainer_comment_body": "Assigned to @demo-contributor. Target release is v0.8.2.",
            "maintainer_comment_days_ago": 1,
            "last_comment_author": "relayer_lead",
            "last_comment_body": "Assigned to @demo-contributor. Target release is v0.8.2.",
            "last_comment_days_ago": 1,
            "classify": "unknown",
        },
        {
            "type": "issue",
            "repo": "solstice-network/settlement-core",
            "number": 164,
            "title": "feat: support deterministic multi-sig withdrawal schemes",
            "url": "https://github.com/solstice-network/settlement-core/issues/164",
            "role": "assignee",
            "is_dimmed": False,
            "applicant_count": 2,
            "applicant_list": ["demo-contributor", "sol_architect"],
            "days_since_my_comment": 2,
            "forked": True,
            "maintainer_comment_author": "core_maintainer_kai",
            "maintainer_comment_body": "Assigned to @demo-contributor. Please open PR against feat/multisig.",
            "maintainer_comment_days_ago": 2,
            "last_comment_author": "core_maintainer_kai",
            "last_comment_body": "Assigned to @demo-contributor. Please open PR against feat/multisig.",
            "last_comment_days_ago": 2,
            "classify": "unknown",
        },
        {
            "type": "issue",
            "repo": "chronos-protocol/time-oracle",
            "number": 112,
            "title": "bug: TWAP window calculation overflows on 32-bit platforms",
            "url": "https://github.com/chronos-protocol/time-oracle/issues/112",
            "role": "applied",
            "is_dimmed": False,
            "applicant_count": 2,
            "applicant_list": ["demo-contributor", "sol_architect"],
            "days_since_my_comment": 1,
            "forked": True,
            "maintainer_comment_author": "validator_sam",
            "maintainer_comment_body": "Reviewing proposals today.",
            "maintainer_comment_days_ago": 1,
            "last_comment_author": "validator_sam",
            "last_comment_body": "Reviewing proposals today.",
            "last_comment_days_ago": 1,
            "classify": "unknown",
        },
        {
            "type": "issue",
            "repo": "hyperion-zk/circuit-std",
            "number": 75,
            "title": "feat: implement lookup argument tables for sha256 round constants",
            "url": "https://github.com/hyperion-zk/circuit-std/issues/75",
            "role": "applied",
            "is_dimmed": False,
            "applicant_count": 3,
            "applicant_list": ["demo-contributor", "bounty_hunter_99", "zk_wizard"],
            "days_since_my_comment": 3,
            "forked": False,
            "maintainer_comment_author": "zk_wizard",
            "maintainer_comment_body": "Evaluating implementation plans from applicants.",
            "maintainer_comment_days_ago": 2,
            "last_comment_author": "zk_wizard",
            "last_comment_body": "Evaluating implementation plans from applicants.",
            "last_comment_days_ago": 2,
            "classify": "unknown",
        },
        {
            "type": "issue",
            "repo": "aether-stream/contracts",
            "number": 108,
            "title": "audit: prevent duplicate stream IDs on concurrent initialization",
            "url": "https://github.com/aether-stream/contracts/issues/108",
            "role": "outbid",
            "is_dimmed": True,
            "applicant_count": 4,
            "applicant_list": ["cryptovoyager"],
            "days_since_my_comment": 3,
            "forked": True,
            "maintainer_comment_author": "cadence_coder",
            "maintainer_comment_body": "Assigned to @cryptovoyager who submitted the first complete spec.",
            "maintainer_comment_days_ago": 3,
            "last_comment_author": "cadence_coder",
            "last_comment_body": "Assigned to @cryptovoyager who submitted the first complete spec.",
            "last_comment_days_ago": 3,
            "classify": "unknown",
        },
        {
            "type": "issue",
            "repo": "stellar-vault/liquidity-engine",
            "number": 356,
            "title": "feat: dynamic fee curve based on pool utilization ratio",
            "url": "https://github.com/stellar-vault/liquidity-engine/issues/356",
            "role": "outbid",
            "is_dimmed": True,
            "applicant_count": 5,
            "applicant_list": ["bounty_hunter_99"],
            "days_since_my_comment": 5,
            "forked": True,
            "maintainer_comment_author": "sol_architect",
            "maintainer_comment_body": "Assigned to @bounty_hunter_99 based on prior pool benchmark PR.",
            "maintainer_comment_days_ago": 4,
            "last_comment_author": "sol_architect",
            "last_comment_body": "Assigned to @bounty_hunter_99 based on prior pool benchmark PR.",
            "last_comment_days_ago": 4,
            "classify": "unknown",
        },
    ]

    claims = [
        {
            "type": "claim",
            "repo": "solstice-network/settlement-core",
            "number": 138,
            "title": "feat: add batch settlement proof verification endpoint",
            "url": "https://github.com/solstice-network/settlement-core/pull/138",
            "merged_days_ago": 1,
        },
        {
            "type": "claim",
            "repo": "nexus-mesh/relayer-node",
            "number": 212,
            "title": "fix: handle websocket reconnect deadlock under network partition",
            "url": "https://github.com/nexus-mesh/relayer-node/pull/212",
            "merged_days_ago": 2,
        },
        {
            "type": "claim",
            "repo": "aether-stream/contracts",
            "number": 82,
            "title": "feat: enable linear stream cancellation with partial settlement",
            "url": "https://github.com/aether-stream/contracts/pull/82",
            "merged_days_ago": 3,
        },
        {
            "type": "claim",
            "repo": "hyperion-zk/circuit-std",
            "number": 49,
            "title": "perf: parallelize commitment witness generation",
            "url": "https://github.com/hyperion-zk/circuit-std/pull/49",
            "merged_days_ago": 4,
        },
        {
            "type": "claim",
            "repo": "chronos-protocol/time-oracle",
            "number": 89,
            "title": "fix: prevent stale timestamp ingestion in historical oracle feed",
            "url": "https://github.com/chronos-protocol/time-oracle/pull/89",
            "merged_days_ago": 6,
        },
        {
            "type": "claim",
            "repo": "stellar-vault/liquidity-engine",
            "number": 319,
            "title": "refactor: simplify token vault deposit authorization checks",
            "url": "https://github.com/stellar-vault/liquidity-engine/pull/319",
            "merged_days_ago": 7,
        },
        {
            "type": "claim",
            "repo": "solstice-network/settlement-core",
            "number": 131,
            "title": "test: add integration test suite for cross-chain settlement relay",
            "url": "https://github.com/solstice-network/settlement-core/pull/131",
            "merged_days_ago": 8,
        },
        {
            "type": "claim",
            "repo": "nexus-mesh/relayer-node",
            "number": 204,
            "title": "perf: cache peer reputation scores to reduce lock contention",
            "url": "https://github.com/nexus-mesh/relayer-node/pull/204",
            "merged_days_ago": 10,
        },
        {
            "type": "claim",
            "repo": "aether-stream/contracts",
            "number": 76,
            "title": "chore: bump solc optimizer runs and prune gas in token bridge",
            "url": "https://github.com/aether-stream/contracts/pull/76",
            "merged_days_ago": 11,
        },
        {
            "type": "claim",
            "repo": "hyperion-zk/circuit-std",
            "number": 44,
            "title": "feat: add zero-knowledge range proof helper library",
            "url": "https://github.com/hyperion-zk/circuit-std/pull/44",
            "merged_days_ago": 12,
        },
        {
            "type": "claim",
            "repo": "chronos-protocol/time-oracle",
            "number": 83,
            "title": "feat: emit granular telemetry events on oracle updates",
            "url": "https://github.com/chronos-protocol/time-oracle/pull/83",
            "merged_days_ago": 13,
        },
    ]

    fork_report = [
        {
            "repo": "hyperion-zk/circuit-std",
            "role": "applied",
            "has_fork": False,
            "has_write_access": False,
            "needs_fork": True,
        },
        {
            "repo": "nexus-mesh/relayer-node",
            "role": "assignee",
            "has_fork": True,
            "has_write_access": False,
            "needs_fork": False,
        },
        {
            "repo": "solstice-network/settlement-core",
            "role": "assignee",
            "has_fork": True,
            "has_write_access": False,
            "needs_fork": False,
        },
    ]

    now = datetime.now(timezone.utc)

    for bucket_items in (prs_needs_you, prs_waiting_on_them, prs_probably_fine):
        for idx, item in enumerate(bucket_items):
            offset_h = (idx * 2 + 1) % 7
            item["their_last_comment_at"] = _mock_iso(now, item.get("their_last_comment_days_ago"), offset_h)
            item["their_activity_at"] = _mock_iso(now, item.get("their_activity_days_ago"), offset_h)
            item["your_activity_at"] = _mock_iso(now, item.get("your_activity_days_ago"), (offset_h + 2) % 9)
            item.update(_pr_defaults(item))
            item.update(_PR_OVERRIDES.get((item["repo"], item["number"]), {}))
            item["bot_review_at"] = _mock_iso(now, item.get("bot_review_days_ago"), offset_h)
            if item.get("bot_feedback"):
                item["bot_feedback"] = {
                    **item["bot_feedback"],
                    "at": _mock_iso(now, item["bot_feedback"].get("days_ago"), 3),
                }

    for idx, issue in enumerate(unlinked_issues):
        offset_h = (idx * 3 + 1) % 8
        issue["my_last_comment_at"] = _mock_iso(now, issue.get("days_since_my_comment"), offset_h)
        m_iso = _mock_iso(now, issue.get("maintainer_comment_days_ago"), (offset_h + 1) % 6)
        issue["maintainer_comment_at"] = m_iso
        issue["last_comment_at"] = m_iso

    for idx, claim in enumerate(claims):
        claim["merged_at"] = _mock_iso(now, claim.get("merged_days_ago"), (idx * 2 + 1) % 9)
        at_risk = (claim["repo"], claim["number"]) in _CLAIMS_AT_RISK
        claim.update({
            "has_closing_link": not at_risk,
            "linked_issues": [] if at_risk else [f"#{max(1, claim['number'] - 9)}"],
            "closing_link_reason": "missing_keyword" if at_risk else None,
            "base_branch": "main",
            "default_branch": "main",
            "targets_default_branch": True,
            "points_at_risk": at_risk,
        })

    all_prs = prs_needs_you + prs_waiting_on_them + prs_probably_fine

    return {
        "username": "demo-contributor",
        "prs": {
            "NEEDS_YOU": prs_needs_you,
            "WAITING_ON_THEM": prs_waiting_on_them,
            "PROBABLY_FINE": prs_probably_fine,
        },
        "unlinked_issues": unlinked_issues,
        "claims": claims,
        "fork_report": fork_report,
        "summary": {
            "needs_you": len(prs_needs_you),
            "waiting_on_them": len(prs_waiting_on_them),
            "probably_fine": len(prs_probably_fine),
            "unlinked_issues": len(unlinked_issues),
            "ready_to_claim": len(claims),
            "repos_need_fork": 1,
            "unlinked_prs": sum(1 for p in all_prs if p["has_closing_link"] is False),
            "points_at_risk": sum(1 for c in claims if c["points_at_risk"]),
        },
    }


# ---------------------------------------------------------------------------
# Maintainer Mode demo
# ---------------------------------------------------------------------------

def _mock_incoming_pr(
    now: datetime,
    *,
    repo: str,
    number: int,
    title: str,
    author: str,
    hours_ago: float,
    association: str = "CONTRIBUTOR",
    linked: list[tuple[int, list[str]]] | None = None,
    additions: int = 60,
    deletions: int = 12,
    paths: list[str] | None = None,
    changed_files: int | None = None,
    ci: tuple[int, int, int] | None = (6, 0, 0),
    draft: bool = False,
    body: str = "",
) -> dict[str, Any]:
    """Raw GitHub-shaped PR; run through core.evaluate_incoming_pr so the demo uses real logic."""
    paths = list(paths or ["src/main.py"])
    total_files = changed_files if changed_files is not None else len(paths)
    # GitHub returns up to 100 file paths; pad the sample so it matches the file count.
    paths += [f"src/generated/module_{i}.ts" for i in range(len(paths), min(total_files, 100))]
    nodes = []
    if ci is not None:
        passed, failed, pending = ci
        nodes = (
            [{"__typename": "CheckRun", "conclusion": "SUCCESS", "status": "COMPLETED"}] * passed
            + [{"__typename": "CheckRun", "conclusion": "FAILURE", "status": "COMPLETED"}] * failed
            + [{"__typename": "CheckRun", "conclusion": None, "status": "IN_PROGRESS"}] * pending
        )
    rollup = {"state": "SUCCESS", "contexts": {"totalCount": len(nodes), "nodes": nodes}} if nodes else None
    created = now - timedelta(hours=hours_ago)
    return {
        "number": number,
        "title": title,
        "url": f"https://github.com/{repo}/pull/{number}",
        "isDraft": draft,
        "createdAt": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "body": body,
        "author": {"__typename": "User", "login": author},
        "authorAssociation": association,
        "isCrossRepository": True,
        "baseRefName": "dev",
        "headRefName": f"fix-{number}",
        "repository": {"nameWithOwner": repo, "defaultBranchRef": {"name": "dev"}},
        "additions": additions,
        "deletions": deletions,
        "changedFiles": total_files,
        "files": {"nodes": [{"path": p} for p in paths]},
        "closingIssuesReferences": {"nodes": [
            {"number": n, "repository": {"nameWithOwner": repo},
             "assignees": {"nodes": [{"login": a} for a in assignees]}}
            for n, assignees in (linked or [])
        ]},
        "commits": {"nodes": [{"commit": {
            "committedDate": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "statusCheckRollup": rollup,
        }}]},
    }


def get_mock_maintainer_data(
    ci_min_ratio: float | None = None, large_diff_lines: int | None = None
) -> dict[str, Any]:
    from core import MAINTAINER_BUCKETS, evaluate_incoming_pr, maintainer_settings

    settings = maintainer_settings(ci_min_ratio, large_diff_lines)
    now = datetime.now(timezone.utc)
    api = "demo-contributor/payout-router"
    web = "lagos-oss/wave-dashboard"
    raw = [
        # Clean: assigned, small diff, CI green.
        _mock_incoming_pr(now, repo=api, number=58, title="fix: retry webhook delivery on 502 from payout provider",
                          author="ada-builds", hours_ago=3, linked=[(51, ["ada-builds"])],
                          paths=["router/webhooks.py", "tests/test_webhooks.py"], ci=(8, 0, 0)),
        _mock_incoming_pr(now, repo=web, number=212, title="feat: show wave deadline countdown on issue cards",
                          author="tobi-dev", hours_ago=20, linked=[(198, ["tobi-dev"])],
                          paths=["app/components/IssueCard.tsx", "app/lib/time.ts"], additions=140, deletions=22,
                          ci=(6, 0, 0)),
        # Kaycee's nightmare: never assigned, 3,000-line diff, touches package.json and CI.
        _mock_incoming_pr(now, repo=web, number=219, title="refactor: complete rewrite of dashboard state management",
                          author="quickfix-9000", hours_ago=6, association="FIRST_TIME_CONTRIBUTOR",
                          linked=[(201, ["tobi-dev"])], additions=3120, deletions=40, changed_files=58,
                          paths=["package.json", "package-lock.json", ".github/workflows/deploy.yml",
                                 "app/store/index.ts", "scripts/postinstall.sh"], ci=None),
        # No linked issue from a first-timer: can't verify, and risky.
        _mock_incoming_pr(now, repo=api, number=61, title="fix typo and improve performance",
                          author="new-hand-22", hours_ago=9, association="FIRST_TIME_CONTRIBUTOR",
                          paths=["router/core.py", "requirements.txt"], additions=410, deletions=380, ci=None),
        # Assigned in practice, but forgot `Closes #N`: send it back.
        _mock_incoming_pr(now, repo=api, number=57, title="feat: add idempotency keys to batch payout endpoint",
                          author="kemi-o", hours_ago=30, body="Implements the idempotency work we discussed.",
                          paths=["router/batch.py", "tests/test_batch.py"], ci=(7, 0, 0)),
        # Assigned, linked, but CI 4/10.
        _mock_incoming_pr(now, repo=web, number=215, title="perf: virtualize the contributor leaderboard",
                          author="ifeoma-ui", hours_ago=44, linked=[(190, ["ifeoma-ui"])],
                          paths=["app/components/Leaderboard.tsx"], additions=260, deletions=90, ci=(4, 6, 0)),
        # Closes two issues but was only assigned one.
        _mock_incoming_pr(now, repo=api, number=60, title="feat: currency rounding + refund reconciliation",
                          author="dayo-codes", hours_ago=14, linked=[(44, ["dayo-codes"]), (45, ["kemi-o"])],
                          paths=["router/money.py", "router/refunds.py"], additions=320, deletions=48, ci=(9, 1, 0)),
        # Draft.
        _mock_incoming_pr(now, repo=web, number=220, title="wip: dark mode for wave dashboard",
                          author="tobi-dev", hours_ago=2, linked=[(205, ["tobi-dev"])], draft=True,
                          paths=["app/styles/theme.css"], ci=(2, 0, 3)),
    ]

    buckets: dict[str, list] = {b: [] for b in MAINTAINER_BUCKETS}
    for pr in raw:
        item = evaluate_incoming_pr(pr, "demo-contributor", settings)
        if item:
            buckets[item["bucket"]].append(item)
    for items in buckets.values():
        items.sort(key=lambda i: i.get("created_at") or "", reverse=True)

    return {
        "username": "demo-contributor",
        "view": "maintainer",
        "maintainer": buckets,
        "summary": {
            "suspicious": len(buckets["SUSPICIOUS"]),
            "bounce_back": len(buckets["BOUNCE_BACK"]),
            "review_now": len(buckets["REVIEW_NOW"]),
            "drafts": len(buckets["DRAFTS"]),
            "repos_scanned": 2,
            "repos_truncated": False,
        },
        "settings": settings,
    }
