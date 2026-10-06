"""
tests/test_core.py — Unit test suite for 3riage decision engine.

Tests pure logic in core.py with zero external API calls or network dependencies.
Covers:
  - Commit sorting & timestamp extraction
  - Multi-reviewer state aggregation & blocking logic
  - PR bucket classification (NEEDS_YOU, WAITING_ON_THEM, PROBABLY_FINE)
  - Bot filtering vs AI reviewer retention
  - Review threads (resolved vs unresolved)
  - Soft sign-off detection
  - min_age_hours dampening
  - Issue classification (assignee, applied, outbid, author, commenter)
  - Competing applicant counting
  - Maintainer attribution
  - Claims shelf filtering
"""

import unittest
from datetime import datetime, timezone, timedelta

import core


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


NOW = datetime.now(timezone.utc)
H1_AGO = NOW - timedelta(hours=1)
H2_AGO = NOW - timedelta(hours=2)
H3_AGO = NOW - timedelta(hours=3)
H4_AGO = NOW - timedelta(hours=4)
D5_AGO = NOW - timedelta(days=5)
D15_AGO = NOW - timedelta(days=15)


class TestCommitSorting(unittest.TestCase):
    def test_commits_out_of_order(self):
        pr = {
            "commits": {
                "nodes": [
                    {"commit": {"committedDate": _iso(H1_AGO)}},  # newer first
                    {"commit": {"committedDate": _iso(H3_AGO)}},  # older second
                ]
            }
        }
        latest = core._latest_commit_dt(pr)
        self.assertIsNotNone(latest)
        self.assertEqual(latest, H1_AGO.replace(microsecond=0))

    def test_empty_commits(self):
        pr = {"commits": {"nodes": []}}
        self.assertIsNone(core._latest_commit_dt(pr))


class TestMultiReviewerLogic(unittest.TestCase):
    def test_single_approved(self):
        reviews = [
            {"author": {"login": "alice"}, "state": "APPROVED", "submittedAt": _iso(H2_AGO)}
        ]
        state, author, body, _, blocking = core._analyze_reviews(reviews, "me", H3_AGO)
        self.assertEqual(state, "APPROVED")
        self.assertFalse(blocking)
        self.assertEqual(author, "alice")

    def test_single_changes_requested_unanswered(self):
        reviews = [
            {"author": {"login": "alice"}, "state": "CHANGES_REQUESTED", "submittedAt": _iso(H2_AGO)}
        ]
        state, author, _, _, blocking = core._analyze_reviews(reviews, "me", H3_AGO)  # commit was before review
        self.assertEqual(state, "CHANGES_REQUESTED")
        self.assertTrue(blocking)

    def test_single_changes_requested_answered_by_commit(self):
        reviews = [
            {"author": {"login": "alice"}, "state": "CHANGES_REQUESTED", "submittedAt": _iso(H2_AGO)}
        ]
        state, _, _, _, blocking = core._analyze_reviews(reviews, "me", H1_AGO)  # commit was AFTER review
        self.assertFalse(blocking)

    def test_multi_reviewer_approval_does_not_mask_changes_requested(self):
        """
        Reviewer A requests changes at H3_AGO.
        Reviewer B approves at H2_AGO.
        You pushed at H4_AGO (before both).
        Reviewer A's block MUST NOT be masked by Reviewer B's approval.
        """
        reviews = [
            {"author": {"login": "reviewer_a"}, "state": "CHANGES_REQUESTED", "submittedAt": _iso(H3_AGO)},
            {"author": {"login": "reviewer_b"}, "state": "APPROVED", "submittedAt": _iso(H2_AGO)},
        ]
        state, author, _, _, blocking = core._analyze_reviews(reviews, "me", H4_AGO)
        self.assertEqual(state, "CHANGES_REQUESTED")
        self.assertTrue(blocking)
        self.assertEqual(author, "reviewer_a")

    def test_multi_reviewer_both_satisfied_after_commit(self):
        """
        Reviewer A requests changes at H3_AGO.
        Reviewer B approves at H2_AGO.
        You push a commit at H1_AGO (after Reviewer A's review).
        PR should now have zero blocking reviews and reflect approval.
        """
        reviews = [
            {"author": {"login": "reviewer_a"}, "state": "CHANGES_REQUESTED", "submittedAt": _iso(H3_AGO)},
            {"author": {"login": "reviewer_b"}, "state": "APPROVED", "submittedAt": _iso(H2_AGO)},
        ]
        state, _, _, _, blocking = core._analyze_reviews(reviews, "me", H1_AGO)
        self.assertFalse(blocking)
        self.assertEqual(state, "APPROVED")

    def test_same_reviewer_supersedes_own_review(self):
        """
        Reviewer A requests changes at H3_AGO, then approves at H1_AGO.
        """
        reviews = [
            {"author": {"login": "alice"}, "state": "CHANGES_REQUESTED", "submittedAt": _iso(H3_AGO)},
            {"author": {"login": "alice"}, "state": "APPROVED", "submittedAt": _iso(H1_AGO)},
        ]
        state, _, _, _, blocking = core._analyze_reviews(reviews, "me", H4_AGO)
        self.assertEqual(state, "APPROVED")
        self.assertFalse(blocking)


class TestPRBucketing(unittest.TestCase):
    def _base_pr(self):
        return {
            "repository": {"nameWithOwner": "owner/repo"},
            "number": 1,
            "title": "Fix something",
            "url": "https://github.com/owner/repo/pull/1",
            "isDraft": False,
            "reviews": {"nodes": []},
            "reviewThreads": {"nodes": []},
            "comments": {"nodes": []},
            "commits": {"nodes": [{"commit": {"committedDate": _iso(H3_AGO)}}]},
        }

    def test_bucket_approved_is_probably_fine(self):
        pr = self._base_pr()
        pr["reviews"]["nodes"] = [
            {"author": {"login": "reviewer"}, "state": "APPROVED", "submittedAt": _iso(H2_AGO)}
        ]
        res = core.bucket_pr(pr, "me", ignore_bots=True)
        self.assertEqual(res["bucket"], "PROBABLY_FINE")

    def test_bucket_changes_requested_without_commit_needs_you(self):
        pr = self._base_pr()
        pr["reviews"]["nodes"] = [
            {"author": {"login": "reviewer"}, "state": "CHANGES_REQUESTED", "submittedAt": _iso(H2_AGO)}
        ]
        res = core.bucket_pr(pr, "me", ignore_bots=True)
        self.assertEqual(res["bucket"], "NEEDS_YOU")

    def test_bucket_changes_requested_with_commit_waiting_on_them(self):
        pr = self._base_pr()
        pr["reviews"]["nodes"] = [
            {"author": {"login": "reviewer"}, "state": "CHANGES_REQUESTED", "submittedAt": _iso(H3_AGO)}
        ]
        pr["commits"]["nodes"] = [{"commit": {"committedDate": _iso(H1_AGO)}}]  # pushed after
        res = core.bucket_pr(pr, "me", ignore_bots=True)
        self.assertEqual(res["bucket"], "WAITING_ON_THEM")

    def test_bucket_newer_comment_from_them_needs_you(self):
        pr = self._base_pr()
        pr["comments"]["nodes"] = [
            {"author": {"login": "maintainer"}, "body": "Can you check line 40?", "createdAt": _iso(H1_AGO)}
        ]
        res = core.bucket_pr(pr, "me", ignore_bots=True)
        self.assertEqual(res["bucket"], "NEEDS_YOU")

    def test_bucket_newer_commit_from_you_waiting_on_them(self):
        pr = self._base_pr()
        pr["comments"]["nodes"] = [
            {"author": {"login": "maintainer"}, "body": "Please rebase", "createdAt": _iso(H3_AGO)}
        ]
        pr["commits"]["nodes"] = [{"commit": {"committedDate": _iso(H1_AGO)}}]
        res = core.bucket_pr(pr, "me", ignore_bots=True)
        self.assertEqual(res["bucket"], "WAITING_ON_THEM")

    def test_soft_signoff_comment_probably_fine(self):
        pr = self._base_pr()
        pr["commits"]["nodes"] = [{"commit": {"committedDate": _iso(H1_AGO)}}]
        pr["comments"]["nodes"] = [
            {"author": {"login": "maintainer"}, "body": "LGTM! Will merge soon.", "createdAt": _iso(H2_AGO)}
        ]
        res = core.bucket_pr(pr, "me", ignore_bots=True)
        self.assertEqual(res["bucket"], "PROBABLY_FINE")

    def test_bot_comment_ignored(self):
        pr = self._base_pr()
        pr["comments"]["nodes"] = [
            {"author": {"login": "dependabot[bot]"}, "body": "Bumping version", "createdAt": _iso(H1_AGO)}
        ]
        res = core.bucket_pr(pr, "me", ignore_bots=True)
        self.assertEqual(res["bucket"], "WAITING_ON_THEM")

    def test_ai_reviewer_not_ignored(self):
        pr = self._base_pr()
        pr["comments"]["nodes"] = [
            {"author": {"login": "coderabbitai"}, "body": "Nitpick: potential null pointer", "createdAt": _iso(H1_AGO)}
        ]
        res = core.bucket_pr(pr, "me", ignore_bots=True)
        self.assertEqual(res["bucket"], "NEEDS_YOU")

    def test_unresolved_review_thread_triggers_needs_you(self):
        pr = self._base_pr()
        pr["reviewThreads"]["nodes"] = [
            {
                "isResolved": False,
                "isOutdated": False,
                "comments": {"nodes": [{"author": {"login": "reviewer"}, "createdAt": _iso(H1_AGO)}]},
            }
        ]
        res = core.bucket_pr(pr, "me", ignore_bots=True)
        self.assertEqual(res["bucket"], "NEEDS_YOU")

    def test_resolved_review_thread_ignored(self):
        pr = self._base_pr()
        pr["reviewThreads"]["nodes"] = [
            {
                "isResolved": True,
                "isOutdated": False,
                "comments": {"nodes": [{"author": {"login": "reviewer"}, "createdAt": _iso(H1_AGO)}]},
            }
        ]
        res = core.bucket_pr(pr, "me", ignore_bots=True)
        self.assertEqual(res["bucket"], "WAITING_ON_THEM")

    def test_min_age_hours_dampens_fresh_activity(self):
        pr = self._base_pr()
        # Maintainer commented 30 minutes ago
        pr["comments"]["nodes"] = [
            {"author": {"login": "maintainer"}, "body": "Looking now...", "createdAt": _iso(NOW - timedelta(minutes=30))}
        ]
        # With min_age_hours=2, this 30m activity is ignored, keeping PR in WAITING_ON_THEM
        res = core.bucket_pr(pr, "me", ignore_bots=True, min_age_hours=2.0)
        self.assertEqual(res["bucket"], "WAITING_ON_THEM")


class TestIssueClassification(unittest.TestCase):
    def _base_issue(self):
        return {
            "repository": {"nameWithOwner": "owner/repo"},
            "number": 10,
            "title": "Database connection leaks",
            "url": "https://github.com/owner/repo/issues/10",
            "author": {"login": "author_user"},
            "assignees": {"nodes": []},
            "comments": {"nodes": []},
        }

    def test_assigned_to_me(self):
        issue = self._base_issue()
        issue["assignees"]["nodes"] = [{"login": "me"}]
        role, is_dimmed, _, _ = core._analyze_issue_role_and_applications(issue, "me")
        self.assertEqual(role, "assignee")
        self.assertFalse(is_dimmed)

    def test_assigned_to_someone_else_is_outbid(self):
        issue = self._base_issue()
        issue["assignees"]["nodes"] = [{"login": "rival_dev"}]
        role, is_dimmed, _, _ = core._analyze_issue_role_and_applications(issue, "me")
        self.assertEqual(role, "outbid")
        self.assertTrue(is_dimmed)

    def test_drips_wave_application_detected(self):
        issue = self._base_issue()
        issue["comments"]["nodes"] = [
            {
                "author": {"login": "me"},
                "body": "@me has applied to work on this issue as part of the Stellar Wave Program\n<!-- wave:application-id:123 -->",
                "createdAt": _iso(H2_AGO),
            }
        ]
        role, is_dimmed, count, _ = core._analyze_issue_role_and_applications(issue, "me")
        self.assertEqual(role, "applied")
        self.assertFalse(is_dimmed)
        self.assertEqual(count, 1)

    def test_manual_execution_plan_proposal_detected(self):
        issue = self._base_issue()
        issue["comments"]["nodes"] = [
            {
                "author": {"login": "me"},
                "body": "Hi maintainer, I would like to work on this issue. Here is my execution plan...",
                "createdAt": _iso(H2_AGO),
            }
        ]
        role, is_dimmed, count, _ = core._analyze_issue_role_and_applications(issue, "me")
        self.assertEqual(role, "applied")
        self.assertFalse(is_dimmed)
        self.assertEqual(count, 1)

    def test_competing_applicants_counted(self):
        issue = self._base_issue()
        issue["comments"]["nodes"] = [
            {"author": {"login": "me"}, "body": "<!-- wave:application-id:1 -->", "createdAt": _iso(H3_AGO)},
            {"author": {"login": "bob"}, "body": "<!-- wave:application-id:2 -->", "createdAt": _iso(H2_AGO)},
            {"author": {"login": "charlie"}, "body": "I would like to work on this issue please", "createdAt": _iso(H1_AGO)},
        ]
        role, _, count, applicants = core._analyze_issue_role_and_applications(issue, "me")
        self.assertEqual(role, "applied")
        self.assertEqual(count, 3)
        self.assertIn("bob", applicants)
        self.assertIn("charlie", applicants)

    def test_maintainer_comment_attribution(self):
        issue = self._base_issue()
        issue["comments"]["nodes"] = [
            {"author": {"login": "owner"}, "authorAssociation": "OWNER", "body": "Maintainer notes", "createdAt": _iso(H3_AGO)},
            {"author": {"login": "random_applicant"}, "authorAssociation": "NONE", "body": "pick me", "createdAt": _iso(H1_AGO)},
        ]
        m_comment = core._last_maintainer_comment(issue, "me", ignore_bots=True)
        self.assertIsNotNone(m_comment)
        self.assertEqual(m_comment["author"]["login"], "owner")
        self.assertEqual(m_comment["body"], "Maintainer notes")


class TestClaimsShelf(unittest.TestCase):
    def test_claims_shelf_window(self):
        merged_prs = [
            {"number": 101, "title": "PR 1", "mergedAt": _iso(D5_AGO), "repository": {"nameWithOwner": "o/r"}},
            {"number": 102, "title": "PR 2", "mergedAt": _iso(D15_AGO), "repository": {"nameWithOwner": "o/r"}},
        ]
        shelf = core.build_claims_shelf(merged_prs, days=14)
        self.assertEqual(len(shelf), 1)
        self.assertEqual(shelf[0]["number"], 101)


if __name__ == "__main__":
    unittest.main()
