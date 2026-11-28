"""
tests/test_maintainer.py — Maintainer Mode: Kaycee's four checks on incoming PRs.
"""

import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import core

NOW = datetime.now(timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _issue(num, assignees, repo="org/app"):
    return {
        "number": num,
        "repository": {"nameWithOwner": repo},
        "assignees": {"nodes": [{"login": a} for a in assignees]},
    }


def _incoming(**overrides):
    pr = {
        "number": 40, "title": "Fix parser", "url": "https://github.com/org/app/pull/40",
        "isDraft": False, "createdAt": _iso(NOW - timedelta(hours=5)), "body": "Closes #12",
        "author": {"__typename": "User", "login": "contributor"},
        "authorAssociation": "CONTRIBUTOR", "isCrossRepository": True,
        "baseRefName": "main", "headRefName": "fix-parser",
        "repository": {"nameWithOwner": "org/app", "defaultBranchRef": {"name": "main"}},
        "additions": 40, "deletions": 10, "changedFiles": 2,
        "files": {"nodes": [{"path": "src/parser.py"}, {"path": "tests/test_parser.py"}]},
        "closingIssuesReferences": {"nodes": [_issue(12, ["contributor"])]},
        "commits": {"nodes": [{"commit": {
            "committedDate": _iso(NOW - timedelta(hours=4)),
            "statusCheckRollup": {"state": "SUCCESS", "contexts": {"totalCount": 3, "nodes": [
                {"__typename": "CheckRun", "conclusion": "SUCCESS", "status": "COMPLETED"}] * 3}},
        }}]},
    }
    pr.update(overrides)
    return pr


def _codes(item):
    return {r["code"] for r in item["reasons"]}


class TestAssignment(unittest.TestCase):
    def test_assigned_clean_pr_is_review_now(self):
        item = core.evaluate_incoming_pr(_incoming(), "maint")
        self.assertEqual(item["assignment_status"], "assigned")
        self.assertEqual(item["assigned_on"], ["#12"])
        self.assertEqual(item["bucket"], "REVIEW_NOW")
        self.assertIn("assigned", _codes(item))

    def test_assignee_match_is_case_insensitive(self):
        pr = _incoming(closingIssuesReferences={"nodes": [_issue(12, ["Contributor"])]})
        self.assertEqual(core.evaluate_incoming_pr(pr, "maint")["assignment_status"], "assigned")

    def test_not_assigned_is_suspicious(self):
        pr = _incoming(closingIssuesReferences={"nodes": [_issue(12, ["someone-else"])]})
        item = core.evaluate_incoming_pr(pr, "maint")
        self.assertEqual(item["assignment_status"], "not_assigned")
        self.assertEqual(item["not_assigned_on"], ["#12"])
        self.assertEqual(item["bucket"], "SUSPICIOUS")

    def test_issue_with_no_assignee_is_not_assigned(self):
        pr = _incoming(closingIssuesReferences={"nodes": [_issue(12, [])]})
        self.assertEqual(core.evaluate_incoming_pr(pr, "maint")["bucket"], "SUSPICIOUS")

    def test_partly_assigned(self):
        pr = _incoming(closingIssuesReferences={"nodes": [_issue(12, ["contributor"]), _issue(14, ["other"])]})
        item = core.evaluate_incoming_pr(pr, "maint")
        self.assertEqual(item["assignment_status"], "partly_assigned")
        self.assertEqual((item["assigned_on"], item["not_assigned_on"]), (["#12"], ["#14"]))
        self.assertEqual(item["bucket"], "SUSPICIOUS")

    def test_cross_repo_issue_label(self):
        pr = _incoming(closingIssuesReferences={"nodes": [_issue(3, ["contributor"], repo="org/lib")]})
        self.assertEqual(core.evaluate_incoming_pr(pr, "maint")["assigned_on"], ["org/lib#3"])


class TestUnverifiable(unittest.TestCase):
    def _unlinked(self, **kw):
        return _incoming(body="Some fix", closingIssuesReferences={"nodes": []}, **kw)

    def test_no_link_low_risk_bounces_back(self):
        item = core.evaluate_incoming_pr(self._unlinked(), "maint")
        self.assertEqual(item["assignment_status"], "unverifiable")
        self.assertEqual(item["bucket"], "BOUNCE_BACK")
        self.assertTrue({"cant_verify", "no_linked_issue"} <= _codes(item))

    def test_no_link_plus_large_diff_is_suspicious(self):
        item = core.evaluate_incoming_pr(self._unlinked(additions=2900, deletions=150), "maint")
        self.assertTrue(item["large_diff"])
        self.assertEqual(item["bucket"], "SUSPICIOUS")

    def test_no_link_plus_first_timer_is_suspicious(self):
        item = core.evaluate_incoming_pr(self._unlinked(authorAssociation="FIRST_TIME_CONTRIBUTOR"), "maint")
        self.assertTrue(item["is_first_timer"])
        self.assertEqual(item["bucket"], "SUSPICIOUS")

    def test_no_link_plus_sensitive_files_is_suspicious(self):
        files = {"nodes": [{"path": "package.json"}, {"path": "src/a.js"}]}
        item = core.evaluate_incoming_pr(self._unlinked(files=files), "maint")
        self.assertEqual(item["sensitive_files"], ["package.json"])
        self.assertEqual(item["bucket"], "SUSPICIOUS")


class TestRiskSignals(unittest.TestCase):
    def test_large_diff_threshold(self):
        self.assertFalse(core.evaluate_incoming_pr(_incoming(additions=600, deletions=400), "m")["large_diff"])
        self.assertTrue(core.evaluate_incoming_pr(_incoming(additions=600, deletions=401), "m")["large_diff"])

    def test_sensitive_path_matching(self):
        paths = [".github/workflows/ci.yml", "web/package-lock.json", "scripts/install.sh",
                 "requirements-dev.txt", "docker/Dockerfile", "src/app.py", "README.md"]
        self.assertEqual(core._sensitive_paths(paths), paths[:5])

    def test_assigned_but_large_diff_still_reviewable(self):
        item = core.evaluate_incoming_pr(_incoming(additions=3000), "maint")
        self.assertEqual(item["bucket"], "REVIEW_NOW")
        self.assertIn("large_diff", _codes(item))

    def test_files_partial_flag(self):
        self.assertTrue(core.evaluate_incoming_pr(_incoming(changedFiles=140), "m")["files_partial"])


class TestCIAndLink(unittest.TestCase):
    def _ci(self, passed, failed, pending=0):
        nodes = ([{"__typename": "CheckRun", "conclusion": "SUCCESS", "status": "COMPLETED"}] * passed
                 + [{"__typename": "CheckRun", "conclusion": "FAILURE", "status": "COMPLETED"}] * failed
                 + [{"__typename": "CheckRun", "conclusion": None, "status": "IN_PROGRESS"}] * pending)
        return {"nodes": [{"commit": {"committedDate": _iso(NOW), "statusCheckRollup": {
            "state": "FAILURE", "contexts": {"totalCount": len(nodes), "nodes": nodes}}}}]}

    def test_ci_below_six_of_ten_bounces(self):
        item = core.evaluate_incoming_pr(_incoming(commits=self._ci(5, 5)), "maint")
        self.assertTrue(item["ci_below_threshold"])
        self.assertEqual(item["bucket"], "BOUNCE_BACK")

    def test_ci_at_six_of_ten_is_fine(self):
        item = core.evaluate_incoming_pr(_incoming(commits=self._ci(6, 4)), "maint")
        self.assertFalse(item["ci_below_threshold"])
        self.assertEqual(item["bucket"], "REVIEW_NOW")

    def test_running_checks_do_not_count_against_ratio(self):
        item = core.evaluate_incoming_pr(_incoming(commits=self._ci(3, 1, pending=6)), "maint")
        self.assertFalse(item["ci_below_threshold"])

    def test_assigned_but_no_closing_link_bounces(self):
        """Linked manually? No: no link at all means assignment is unverifiable."""
        pr = _incoming(body="fix", closingIssuesReferences={"nodes": []})
        self.assertEqual(core.evaluate_incoming_pr(pr, "maint")["bucket"], "BOUNCE_BACK")

    def test_ci_not_fetched_does_not_bounce(self):
        pr = _incoming(commits={"nodes": [{"commit": {"committedDate": _iso(NOW)}}]})
        item = core.evaluate_incoming_pr(pr, "maint")
        self.assertIsNone(item["ci_state"])
        self.assertEqual(item["bucket"], "REVIEW_NOW")


class TestScopeAndBuckets(unittest.TestCase):
    def test_own_pr_excluded(self):
        pr = _incoming(author={"__typename": "User", "login": "Maint"})
        self.assertIsNone(core.evaluate_incoming_pr(pr, "maint"))

    def test_bot_pr_excluded(self):
        for author in ({"__typename": "Bot", "login": "dependabot"}, {"login": "renovate[bot]"}):
            self.assertIsNone(core.evaluate_incoming_pr(_incoming(author=author), "maint"))

    def test_draft_grouped_even_if_suspicious(self):
        pr = _incoming(isDraft=True, closingIssuesReferences={"nodes": [_issue(12, ["other"])]})
        item = core.evaluate_incoming_pr(pr, "maint")
        self.assertEqual(item["bucket"], "DRAFTS")
        self.assertIn("not_assigned", _codes(item))

    def test_run_maintainer_triage_buckets_and_filters(self):
        client = MagicMock()
        client.username = "maint"
        client.get_maintained_repos_with_open_prs.return_value = (["org/app", "org/skip"], False)
        older = _incoming(number=1, createdAt=_iso(NOW - timedelta(days=3)))
        newer = _incoming(number=2, createdAt=_iso(NOW - timedelta(hours=1)))
        drive_by = _incoming(number=3, closingIssuesReferences={"nodes": [_issue(12, [])]})
        own = _incoming(number=4, author={"login": "maint"})
        client.get_incoming_prs.return_value = [older, newer, drive_by, own]

        data = core.run_maintainer_triage(client, ignore_repos={"org/skip"})
        client.get_incoming_prs.assert_called_once_with(["org/app"])
        self.assertEqual(data["view"], "maintainer")
        self.assertEqual([p["number"] for p in data["maintainer"]["REVIEW_NOW"]], [2, 1])
        self.assertEqual([p["number"] for p in data["maintainer"]["SUSPICIOUS"]], [3])
        s = data["summary"]
        self.assertEqual((s["review_now"], s["suspicious"], s["bounce_back"], s["drafts"]), (2, 1, 0, 0))
        self.assertEqual(s["repos_scanned"], 1)
        self.assertFalse(s["repos_truncated"])


if __name__ == "__main__":
    unittest.main()
