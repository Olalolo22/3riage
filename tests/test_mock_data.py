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


if __name__ == "__main__":
    unittest.main()
