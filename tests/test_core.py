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
            {"author": {"__typename": "Bot", "login": "coderabbitai"}, "body": "Nitpick: potential null pointer", "createdAt": _iso(H1_AGO)}
        ]
        res = core.bucket_pr(pr, "me", ignore_bots=True)
        self.assertEqual(res["bucket"], "NEEDS_YOU")

    def test_graphql_github_app_bots_ignored(self):
        for bot_login in ("drips-wave", "vercel", "some-random-ci-app"):
            pr = self._base_pr()
            pr["comments"]["nodes"] = [
                {
                    "author": {"__typename": "Bot", "login": bot_login},
                    "body": "Automated status notification",
                    "createdAt": _iso(H1_AGO),
                }
            ]
            res = core.bucket_pr(pr, "me", ignore_bots=True)
            self.assertEqual(res["bucket"], "WAITING_ON_THEM", f"{bot_login} should be ignored")
            self.assertEqual(res["their_last_comment_author"], "")

    def test_known_app_bots_ignored_without_typename(self):
        for bot_login in ("drips-wave", "vercel"):
            pr = self._base_pr()
            pr["comments"]["nodes"] = [
                {"author": {"login": bot_login}, "body": "Automated status", "createdAt": _iso(H1_AGO)}
            ]
            res = core.bucket_pr(pr, "me", ignore_bots=True)
            self.assertEqual(res["bucket"], "WAITING_ON_THEM", f"{bot_login} should be ignored")

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

    def test_iso_timestamps_emitted(self):
        pr = self._base_pr()
        pr["comments"]["nodes"] = [
            {"author": {"login": "maintainer"}, "body": "Checking now", "createdAt": _iso(H1_AGO)}
        ]
        res = core.bucket_pr(pr, "me", ignore_bots=True)
        self.assertIsNotNone(res["your_activity_at"])
        self.assertIsNotNone(res["their_activity_at"])
        self.assertIsNotNone(res["their_last_comment_at"])
        self.assertTrue(res["your_activity_at"].endswith("Z"))
        self.assertTrue(res["their_activity_at"].endswith("Z"))


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


def _pr(**overrides):
    """Open PR fixture with the fields the new link/bot/CI logic reads."""
    pr = {
        "repository": {"nameWithOwner": "owner/repo", "defaultBranchRef": {"name": "main"}},
        "number": 5,
        "title": "Fix thing",
        "url": "https://github.com/owner/repo/pull/5",
        "isDraft": False,
        "baseRefName": "main",
        "headRefName": "fix-thing",
        "isCrossRepository": True,
        "authorAssociation": "CONTRIBUTOR",
        "body": "",
        "closingIssuesReferences": {"nodes": []},
        "reviews": {"nodes": []},
        "reviewThreads": {"nodes": []},
        "comments": {"nodes": []},
        # statusCheckRollup is null when the head commit has no checks at all.
        "commits": {"nodes": [{"commit": {"committedDate": _iso(H3_AGO), "statusCheckRollup": None}}]},
    }
    pr.update(overrides)
    return pr


class TestLinkedIssueDetection(unittest.TestCase):
    def test_linked_pr_has_no_reason(self):
        pr = _pr(closingIssuesReferences={"nodes": [{"number": 7, "repository": {"nameWithOwner": "owner/repo"}}]})
        res = core.bucket_pr(pr, "me", ignore_bots=True)
        self.assertTrue(res["has_closing_link"])
        self.assertEqual(res["linked_issues"], ["#7"])
        self.assertIsNone(res["closing_link_reason"])
        self.assertEqual(res["suggested_close_issues"], [])

    def test_cross_repo_link_keeps_full_ref(self):
        pr = _pr(closingIssuesReferences={"nodes": [{"number": 3, "repository": {"nameWithOwner": "other/lib"}}]})
        res = core.bucket_pr(pr, "me", ignore_bots=True)
        self.assertEqual(res["linked_issues"], ["other/lib#3"])

    def test_missing_keyword(self):
        res = core.bucket_pr(_pr(body="Implements the thing."), "me", ignore_bots=True)
        self.assertIs(res["has_closing_link"], False)
        self.assertEqual(res["closing_link_reason"], "missing_keyword")

    def test_keyword_inside_html_comment_does_not_count(self):
        res = core.bucket_pr(_pr(body="<!-- Closes #12 -->\nDone."), "me", ignore_bots=True)
        self.assertEqual(res["closing_link_reason"], "missing_keyword")

    def test_keyword_present_but_not_linked(self):
        for body in ("Closes #999", "fixes: #4", "Resolved owner/repo#8",
                     "closes https://github.com/owner/repo/issues/2"):
            res = core.bucket_pr(_pr(body=body), "me", ignore_bots=True)
            self.assertEqual(res["closing_link_reason"], "keyword_not_linked", body)

    def test_non_default_base_branch(self):
        res = core.bucket_pr(_pr(body="Closes #12", baseRefName="dev"), "me", ignore_bots=True,
                             assigned_issue_candidates=[12])
        self.assertEqual(res["closing_link_reason"], "non_default_base")
        self.assertIs(res["targets_default_branch"], False)
        self.assertEqual(res["base_branch"], "dev")
        self.assertEqual(res["default_branch"], "main")
        # A keyword would not help, so no copy-paste suggestion is offered.
        self.assertEqual(res["suggested_close_issues"], [])

    def test_unknown_when_field_not_fetched(self):
        pr = _pr()
        del pr["closingIssuesReferences"]
        res = core.bucket_pr(pr, "me", ignore_bots=True)
        self.assertIsNone(res["has_closing_link"])
        self.assertIsNone(res["closing_link_reason"])

    def test_single_assigned_issue_is_strong_suggestion(self):
        res = core.bucket_pr(_pr(), "me", ignore_bots=True, assigned_issue_candidates=[711])
        self.assertEqual(res["suggested_close_issues"], [711])
        self.assertEqual(res["suggestion_confidence"], "strong")

    def test_branch_name_match_is_strong_and_first(self):
        res = core.bucket_pr(_pr(headRefName="fix/711-ticker"), "me", ignore_bots=True,
                             assigned_issue_candidates=[650, 711])
        self.assertEqual(res["suggested_close_issues"], [711, 650])
        self.assertEqual(res["suggestion_confidence"], "strong")

    def test_body_reference_match_is_strong(self):
        res = core.bucket_pr(_pr(body="Refs #650"), "me", ignore_bots=True,
                             assigned_issue_candidates=[711, 650])
        self.assertEqual(res["suggested_close_issues"][0], 650)
        self.assertEqual(res["suggestion_confidence"], "strong")

    def test_several_candidates_without_match_are_ambiguous(self):
        res = core.bucket_pr(_pr(), "me", ignore_bots=True, assigned_issue_candidates=[711, 650])
        self.assertEqual(res["suggested_close_issues"], [650, 711])
        self.assertEqual(res["suggestion_confidence"], "ambiguous")

    def test_branch_digit_boundary(self):
        # "7110" must not match issue 711
        res = core.bucket_pr(_pr(headRefName="feat/7110"), "me", ignore_bots=True,
                             assigned_issue_candidates=[711, 650])
        self.assertEqual(res["suggestion_confidence"], "ambiguous")


class TestMergedPointsAtRisk(unittest.TestCase):
    def _merged(self, **overrides):
        pr = {
            "number": 101, "title": "PR", "url": "u", "mergedAt": _iso(D5_AGO),
            "repository": {"nameWithOwner": "o/r", "defaultBranchRef": {"name": "main"}},
            "baseRefName": "main", "body": "",
            "closingIssuesReferences": {"nodes": []},
        }
        pr.update(overrides)
        return pr

    def test_merged_without_link_is_at_risk(self):
        shelf = core.build_claims_shelf([self._merged()], days=14)
        self.assertTrue(shelf[0]["points_at_risk"])
        self.assertEqual(shelf[0]["closing_link_reason"], "missing_keyword")

    def test_merged_with_link_is_safe(self):
        shelf = core.build_claims_shelf(
            [self._merged(closingIssuesReferences={"nodes": [{"number": 9, "repository": {"nameWithOwner": "o/r"}}]})],
            days=14,
        )
        self.assertFalse(shelf[0]["points_at_risk"])
        self.assertEqual(shelf[0]["linked_issues"], ["#9"])

    def test_merged_without_link_data_is_not_flagged(self):
        pr = self._merged()
        del pr["closingIssuesReferences"]
        shelf = core.build_claims_shelf([pr], days=14)
        self.assertFalse(shelf[0]["points_at_risk"])


class TestSuggestionCandidates(unittest.TestCase):
    def test_issue_closed_by_another_pr_is_not_suggested(self):
        issues = [
            {"repository": {"nameWithOwner": "Owner/Repo"}, "number": 711, "assignees": {"nodes": [{"login": "Me"}]}},
            {"repository": {"nameWithOwner": "owner/repo"}, "number": 650, "assignees": {"nodes": [{"login": "me"}]}},
            {"repository": {"nameWithOwner": "owner/repo"}, "number": 800, "assignees": {"nodes": [{"login": "rival"}]}},
        ]
        other_pr = _pr(number=9, closingIssuesReferences={"nodes": [{"number": 650, "repository": {"nameWithOwner": "owner/repo"}}]})
        this_pr = _pr(number=5)
        by_repo = core._assigned_issues_by_repo(issues, "me")
        claims = core._closing_claims([other_pr, this_pr])
        self.assertEqual(core._candidates_for_pr(this_pr, by_repo, claims), [711])
        # The PR that already closes #650 still sees it (it is its own link).
        self.assertIn(650, core._candidates_for_pr(other_pr, by_repo, claims))


class TestActionableBotReviews(unittest.TestCase):
    BOT = {"__typename": "Bot", "login": "repo-guard"}

    def test_bot_changes_requested_after_commit_needs_you(self):
        pr = _pr(reviews={"nodes": [
            {"author": self.BOT, "state": "CHANGES_REQUESTED", "body": "Add tests", "submittedAt": _iso(H1_AGO)}
        ]})
        res = core.bucket_pr(pr, "me", ignore_bots=True)
        self.assertEqual(res["bucket"], "NEEDS_YOU")
        self.assertTrue(res["bot_review_actionable"])
        self.assertEqual(res["bot_review_reason"], "changes_requested")
        self.assertEqual(res["review_state"], "CHANGES_REQUESTED")
        self.assertEqual(res["review_author"], "repo-guard")

    def test_bot_changes_requested_before_commit_is_answered(self):
        pr = _pr(
            reviews={"nodes": [{"author": self.BOT, "state": "CHANGES_REQUESTED", "submittedAt": _iso(H4_AGO)}]},
        )
        res = core.bucket_pr(pr, "me", ignore_bots=True)
        self.assertEqual(res["bucket"], "WAITING_ON_THEM")
        self.assertFalse(res["bot_review_actionable"])

    def test_later_bot_approval_clears_it(self):
        pr = _pr(reviews={"nodes": [
            {"author": self.BOT, "state": "CHANGES_REQUESTED", "submittedAt": _iso(H2_AGO)},
            {"author": self.BOT, "state": "APPROVED", "submittedAt": _iso(H1_AGO)},
        ]})
        res = core.bucket_pr(pr, "me", ignore_bots=True)
        self.assertFalse(res["bot_review_actionable"])
        self.assertNotEqual(res["bucket"], "NEEDS_YOU")

    def test_dismissed_bot_review_cleared(self):
        pr = _pr(reviews={"nodes": [
            {"author": self.BOT, "state": "CHANGES_REQUESTED", "submittedAt": _iso(H2_AGO)},
            {"author": self.BOT, "state": "DISMISSED", "submittedAt": _iso(H1_AGO)},
        ]})
        self.assertFalse(core.bucket_pr(pr, "me", ignore_bots=True)["bot_review_actionable"])

    def test_bot_approval_alone_does_not_mark_probably_fine(self):
        pr = _pr(reviews={"nodes": [{"author": self.BOT, "state": "APPROVED", "submittedAt": _iso(H1_AGO)}]})
        self.assertEqual(core.bucket_pr(pr, "me", ignore_bots=True)["bucket"], "WAITING_ON_THEM")

    def _thread(self, created, resolved=False, outdated=False, author=None):
        return {
            "isResolved": resolved, "isOutdated": outdated,
            "comments": {"nodes": [{"author": author or self.BOT, "body": "Use a constant here", "createdAt": _iso(created)}]},
        }

    def test_unresolved_bot_thread_after_commit_needs_you(self):
        res = core.bucket_pr(_pr(reviewThreads={"nodes": [self._thread(H1_AGO)]}), "me", ignore_bots=True)
        self.assertEqual(res["bucket"], "NEEDS_YOU")
        self.assertEqual(res["bot_review_reason"], "review_thread")

    def test_bot_thread_older_than_commit_stays_waiting(self):
        """Fixed in a later push but never marked resolved: must not stick in NEEDS_YOU."""
        res = core.bucket_pr(_pr(reviewThreads={"nodes": [self._thread(H4_AGO)]}), "me", ignore_bots=True)
        self.assertEqual(res["bucket"], "WAITING_ON_THEM")
        self.assertFalse(res["bot_review_actionable"])

    def test_outdated_or_resolved_bot_thread_ignored(self):
        for t in (self._thread(H1_AGO, outdated=True), self._thread(H1_AGO, resolved=True)):
            res = core.bucket_pr(_pr(reviewThreads={"nodes": [t]}), "me", ignore_bots=True)
            self.assertFalse(res["bot_review_actionable"])

    def test_thread_where_you_replied_last_is_not_actionable(self):
        t = self._thread(H1_AGO, author={"login": "me"})
        res = core.bucket_pr(_pr(reviewThreads={"nodes": [t]}), "me", ignore_bots=True)
        self.assertFalse(res["bot_review_actionable"])

    def test_status_bot_comment_still_ignored_and_no_hint(self):
        pr = _pr(comments={"nodes": [
            {"author": {"__typename": "Bot", "login": "drips-wave"}, "body": "Wave status", "createdAt": _iso(H1_AGO)}
        ]})
        res = core.bucket_pr(pr, "me", ignore_bots=True)
        self.assertEqual(res["bucket"], "WAITING_ON_THEM")
        self.assertIsNone(res["bot_feedback"])

    def test_unknown_bot_comment_is_soft_hint_only(self):
        pr = _pr(comments={"nodes": [
            {"author": {"__typename": "Bot", "login": "gas-reporter"}, "body": "Gas +4% on settle()", "createdAt": _iso(H1_AGO)}
        ]})
        res = core.bucket_pr(pr, "me", ignore_bots=True)
        self.assertEqual(res["bucket"], "WAITING_ON_THEM")
        self.assertEqual(res["bot_feedback"]["login"], "gas-reporter")
        self.assertTrue(res["bot_feedback"]["at"].endswith("Z"))

    def test_unknown_bot_comment_before_commit_no_hint(self):
        pr = _pr(comments={"nodes": [
            {"author": {"__typename": "Bot", "login": "gas-reporter"}, "body": "old", "createdAt": _iso(H4_AGO)}
        ]})
        self.assertIsNone(core.bucket_pr(pr, "me", ignore_bots=True)["bot_feedback"])


class TestCISummary(unittest.TestCase):
    def _with_ci(self, nodes, total=None, **pr_overrides):
        commit = {"committedDate": _iso(H3_AGO), "statusCheckRollup": {
            "state": "PENDING",
            "contexts": {"totalCount": len(nodes) if total is None else total, "nodes": nodes},
        }}
        return _pr(commits={"nodes": [{"commit": commit}]}, **pr_overrides)

    def test_counts_and_exclusions(self):
        nodes = [
            {"__typename": "CheckRun", "conclusion": "SUCCESS", "status": "COMPLETED"},
            {"__typename": "CheckRun", "conclusion": "SUCCESS", "status": "COMPLETED"},
            {"__typename": "CheckRun", "conclusion": "FAILURE", "status": "COMPLETED"},
            {"__typename": "CheckRun", "conclusion": "SKIPPED", "status": "COMPLETED"},
            {"__typename": "CheckRun", "conclusion": "NEUTRAL", "status": "COMPLETED"},
            {"__typename": "CheckRun", "conclusion": None, "status": "IN_PROGRESS"},
            {"__typename": "StatusContext", "state": "SUCCESS"},
            {"__typename": "StatusContext", "state": "ERROR"},
        ]
        res = core.bucket_pr(self._with_ci(nodes), "me", ignore_bots=True)
        self.assertEqual(res["ci_state"], "FAILURE")
        self.assertEqual((res["ci_passed"], res["ci_failed"], res["ci_pending"], res["ci_total"]), (3, 2, 1, 6))
        self.assertFalse(res["ci_partial"])

    def test_all_passing(self):
        nodes = [{"__typename": "CheckRun", "conclusion": "SUCCESS", "status": "COMPLETED"}] * 4
        res = core.bucket_pr(self._with_ci(nodes), "me", ignore_bots=True)
        self.assertEqual(res["ci_state"], "SUCCESS")
        self.assertEqual(res["ci_total"], 4)

    def test_pending(self):
        nodes = [
            {"__typename": "CheckRun", "conclusion": "SUCCESS", "status": "COMPLETED"},
            {"__typename": "CheckRun", "conclusion": None, "status": "QUEUED"},
        ]
        self.assertEqual(core.bucket_pr(self._with_ci(nodes), "me", ignore_bots=True)["ci_state"], "PENDING")

    def test_no_checks_on_first_timer_fork_awaits_approval(self):
        pr = _pr(authorAssociation="FIRST_TIME_CONTRIBUTOR", isCrossRepository=True)
        self.assertEqual(core.bucket_pr(pr, "me", ignore_bots=True)["ci_state"], "AWAITING_APPROVAL")

    def test_no_checks_for_regular_contributor_is_none(self):
        pr = _pr(authorAssociation="CONTRIBUTOR")
        self.assertEqual(core.bucket_pr(pr, "me", ignore_bots=True)["ci_state"], "NONE")

    def test_action_required_only_awaits_approval(self):
        nodes = [{"__typename": "CheckRun", "conclusion": "ACTION_REQUIRED", "status": "COMPLETED"}] * 2
        res = core.bucket_pr(self._with_ci(nodes), "me", ignore_bots=True)
        self.assertEqual(res["ci_state"], "AWAITING_APPROVAL")
        self.assertEqual(res["ci_failed"], 0)

    def test_ci_not_fetched_is_unknown(self):
        pr = _pr(commits={"nodes": [{"commit": {"committedDate": _iso(H3_AGO)}}]})
        res = core.bucket_pr(pr, "me", ignore_bots=True)
        self.assertIsNone(res["ci_state"])
        self.assertIsNone(res["ci_total"])

    def test_partial_when_more_than_fetched(self):
        nodes = [{"__typename": "CheckRun", "conclusion": "SUCCESS", "status": "COMPLETED"}] * 50
        self.assertTrue(core.bucket_pr(self._with_ci(nodes, total=63), "me", ignore_bots=True)["ci_partial"])

    def test_ci_never_changes_bucket(self):
        failing = [{"__typename": "CheckRun", "conclusion": "FAILURE", "status": "COMPLETED"}] * 3
        approved = {"nodes": [{"author": {"login": "rev"}, "state": "APPROVED", "submittedAt": _iso(H1_AGO)}]}
        self.assertEqual(core.bucket_pr(self._with_ci(failing), "me", ignore_bots=True)["bucket"], "WAITING_ON_THEM")
        self.assertEqual(
            core.bucket_pr(self._with_ci(failing, reviews=approved), "me", ignore_bots=True)["bucket"],
            "PROBABLY_FINE",
        )


if __name__ == "__main__":
    unittest.main()
