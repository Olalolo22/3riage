"""
tests/test_mock_data.py — Tests for 3riage curated sandbox dataset.
"""

import unittest
from mock_data import get_mock_triage_data


class TestMockData(unittest.TestCase):
    def setUp(self):
        self.data = get_mock_triage_data()

    def test_top_level_keys(self):
        required_keys = {"username", "prs", "unlinked_issues", "claims", "fork_report", "summary"}
        self.assertTrue(required_keys.issubset(self.data.keys()))
        self.assertEqual(self.data["username"], "demo-contributor")

    def test_prs_counts_and_structure(self):
        prs = self.data["prs"]
        self.assertEqual(len(prs["NEEDS_YOU"]), 6)
        self.assertEqual(len(prs["WAITING_ON_THEM"]), 6)
        self.assertEqual(len(prs["PROBABLY_FINE"]), 3)
        total_prs = sum(len(v) for v in prs.values())
        self.assertEqual(total_prs, 15)

        for bucket, items in prs.items():
            for item in items:
                self.assertEqual(item["type"], "pr")
                self.assertEqual(item["bucket"], bucket)
                self.assertIn("repo", item)
                self.assertIn("number", item)
                self.assertIn("title", item)
                self.assertIn("url", item)

    def test_unlinked_issues_structure(self):
        issues = self.data["unlinked_issues"]
        self.assertEqual(len(issues), 6)
        roles = [i["role"] for i in issues]
        self.assertEqual(roles.count("assignee"), 2)
        self.assertEqual(roles.count("applied"), 2)
        self.assertEqual(roles.count("outbid"), 2)

        # Outbid issues must be dimmed
        for i in issues:
            if i["role"] == "outbid":
                self.assertTrue(i["is_dimmed"])
            else:
                self.assertFalse(i["is_dimmed"])

    def test_claims_shelf_structure(self):
        claims = self.data["claims"]
        self.assertEqual(len(claims), 11)
        for claim in claims:
            self.assertEqual(claim["type"], "claim")
            self.assertIn("repo", claim)
            self.assertIn("number", claim)
            self.assertIn("title", claim)
            self.assertIn("url", claim)
            self.assertLessEqual(claim["merged_days_ago"], 14)

    def test_summary_counters(self):
        summary = self.data["summary"]
        self.assertEqual(summary["needs_you"], 6)
        self.assertEqual(summary["waiting_on_them"], 6)
        self.assertEqual(summary["probably_fine"], 3)
        self.assertEqual(summary["unlinked_issues"], 6)
        self.assertEqual(summary["ready_to_claim"], 11)
        self.assertEqual(summary["repos_need_fork"], 1)


    def _all_prs(self):
        return [p for items in self.data["prs"].values() for p in items]

    def test_pr_schema_matches_engine(self):
        """Every key core.bucket_pr emits must exist on every demo PR (and vice versa)."""
        import core
        engine_pr = core.bucket_pr(
            {
                "repository": {"nameWithOwner": "o/r", "defaultBranchRef": {"name": "main"}},
                "number": 1, "title": "t", "url": "u", "isDraft": False,
                "baseRefName": "main", "body": "",
                "closingIssuesReferences": {"nodes": []},
                "reviews": {"nodes": []}, "reviewThreads": {"nodes": []}, "comments": {"nodes": []},
                "commits": {"nodes": []},
            },
            "me",
            ignore_bots=True,
        )
        engine_keys = set(engine_pr.keys())
        for p in self._all_prs():
            self.assertEqual(set(p.keys()), engine_keys, f"{p['repo']}#{p['number']}")

    def test_claim_schema_matches_engine(self):
        import core
        engine_claim = core.build_claims_shelf(
            [{"number": 1, "title": "t", "url": "u", "mergedAt": "2099-01-01T00:00:00Z",
              "repository": {"nameWithOwner": "o/r", "defaultBranchRef": {"name": "main"}},
              "baseRefName": "main", "body": "", "closingIssuesReferences": {"nodes": []}}],
        )[0]
        for c in self.data["claims"]:
            self.assertEqual(set(c.keys()), set(engine_claim.keys()), f"{c['repo']}#{c['number']}")

    def test_demo_showcases_every_new_case(self):
        prs = self._all_prs()
        reasons = {p["closing_link_reason"] for p in prs}
        self.assertTrue({"missing_keyword", "non_default_base", "keyword_not_linked"} <= reasons)
        self.assertTrue(any(p["suggestion_confidence"] == "strong" and p["suggested_close_issues"] for p in prs))
        self.assertTrue(any(p["bot_review_actionable"] and p["bucket"] == "NEEDS_YOU" for p in prs))
        self.assertTrue(any(p["bot_feedback"] and p["bot_feedback"].get("at") for p in prs))
        states = {p["ci_state"] for p in prs}
        self.assertTrue({"SUCCESS", "FAILURE", "PENDING", "NONE", "AWAITING_APPROVAL"} <= states)
        self.assertTrue(any(c["points_at_risk"] for c in self.data["claims"]))

    def test_suggestions_point_at_assigned_unlinked_issues(self):
        assigned = {(i["repo"], i["number"]) for i in self.data["unlinked_issues"] if i["role"] == "assignee"}
        for p in self._all_prs():
            for n in p["suggested_close_issues"]:
                self.assertIn((p["repo"], n), assigned)

    def test_new_summary_counters(self):
        s = self.data["summary"]
        self.assertEqual(s["unlinked_prs"], sum(1 for p in self._all_prs() if p["has_closing_link"] is False))
        self.assertEqual(s["points_at_risk"], 2)


if __name__ == "__main__":
    unittest.main()
