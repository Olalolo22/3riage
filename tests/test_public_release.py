"""
tests/test_public_release.py — Tests for OAuth cookie auth, multi-user isolation,
CLI ui / auto-username detection, read-only web fork policy, and frontend sync.
"""

import json
import os
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from click.testing import CliRunner

import app as app_module
import auth
import triage
from github_client import GitHubClient

ROOT_DIR = Path(__file__).resolve().parent.parent


def _sample_triage(username: str) -> dict:
    return {
        "username": username,
        "prs": {"NEEDS_YOU": [], "WAITING_ON_THEM": [], "PROBABLY_FINE": []},
        "unlinked_issues": [],
        "claims": [],
        "fork_report": [],
        "summary": {
            "needs_you": 0,
            "waiting_on_them": 0,
            "probably_fine": 0,
            "unlinked_issues": 0,
            "ready_to_claim": 0,
            "repos_need_fork": 0,
        },
    }


class TestAuthCookies(unittest.TestCase):
    def setUp(self):
        self._env_patch = patch.dict(
            os.environ,
            {
                "SESSION_SECRET": "test-secret-key-32-bytes-minimum!!",
                "GITHUB_OAUTH_CLIENT_ID": "Iv1.testclientid",
                "GITHUB_OAUTH_CLIENT_SECRET": "test-client-secret",
            },
            clear=False,
        )
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()

    def test_encrypt_decrypt_roundtrip_and_tamper_rejection(self):
        payload = {"access_token": "ghu_123", "username": "alice", "refresh_token": "ghr_456"}
        token = auth.encrypt_cookie_payload(payload)
        self.assertNotIn("ghu_123", token)  # Must be encrypted, not plain base64
        decoded = auth.decrypt_cookie_payload(token)
        self.assertEqual(decoded, payload)

        # Tampering with ciphertext must fail
        tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
        self.assertIsNone(auth.decrypt_cookie_payload(tampered))

        # Wrong secret must fail
        with patch.dict(os.environ, {"SESSION_SECRET": "different-secret"}):
            self.assertIsNone(auth.decrypt_cookie_payload(token))

    def test_vercel_requires_session_secret(self):
        with patch.dict(os.environ, {"VERCEL": "1", "SESSION_SECRET": ""}):
            self.assertFalse(auth.is_oauth_configured())
        with patch.dict(os.environ, {"VERCEL": "1", "SESSION_SECRET": "prod-secret"}):
            self.assertTrue(auth.is_oauth_configured())


class TestAppOAuthAndMultiUserIsolation(unittest.TestCase):
    def setUp(self):
        app_module._CACHE.clear()
        app_module._VIEWER_LOGIN_CACHE.clear()
        self.env_patch = patch.dict(
            os.environ,
            {
                "SESSION_SECRET": "unit-test-session-secret-xyz",
                "GITHUB_OAUTH_CLIENT_ID": "Iv1.test123",
                "GITHUB_OAUTH_CLIENT_SECRET": "secret123",
                "GITHUB_TOKEN": "",
                "GITHUB_USERNAME": "",
                "VERCEL": "",
                "VERCEL_ENV": "",
                "TRIAGE_FORCE_DEMO": "",
            },
            clear=False,
        )
        self.env_patch.start()
        self.client = app_module.app.test_client()

    def tearDown(self):
        self.env_patch.stop()
        app_module._CACHE.clear()
        app_module._REFRESH_RESULTS.clear()
        app_module._REFRESH_TOKEN_LOCKS.clear()

    def test_default_falls_back_to_demo_mode(self):
        res = self.client.get("/api/triage")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["is_demo"])
        self.assertEqual(body["auth_mode"], "demo")
        self.assertTrue(body["oauth_configured"])
        self.assertFalse(body["can_fork_via_cli"])

    def test_oauth_login_sets_state_cookie_and_redirects(self):
        res = self.client.get("/api/auth/login")
        self.assertEqual(res.status_code, 302)
        loc = res.headers["Location"]
        self.assertIn("https://github.com/login/oauth/authorize", loc)
        self.assertIn("client_id=Iv1.test123", loc)
        self.assertIn("state=", loc)
        set_cookie = res.headers.get("Set-Cookie", "")
        self.assertIn(auth.STATE_COOKIE_NAME, set_cookie)
        self.assertIn("HttpOnly", set_cookie)

    def test_oauth_callback_rejects_invalid_state(self):
        res = self.client.get("/api/auth/callback?code=abc&state=wrong")
        self.assertEqual(res.status_code, 302)
        self.assertIn("auth_error=invalid_state", res.headers["Location"])

    @patch("app.GitHubClient.get_viewer_login", return_value="octo_dev")
    @patch(
        "app.exchange_code_for_token",
        return_value={"access_token": "ghu_live_token", "refresh_token": "ghr_live", "expires_at": None},
    )
    def test_oauth_callback_sets_encrypted_session_cookie(self, mock_exchange, mock_viewer):
        login_res = self.client.get("/api/auth/login")
        location = login_res.headers["Location"]
        state = location.split("state=")[1].split("&")[0]

        cb_res = self.client.get(f"/api/auth/callback?code=good_code&state={state}")
        self.assertEqual(cb_res.status_code, 302)
        self.assertEqual(cb_res.headers["Location"], "/")
        cookies = cb_res.headers.getlist("Set-Cookie")
        session_headers = [c for c in cookies if auth.SESSION_COOKIE_NAME in c]
        self.assertTrue(session_headers)
        self.assertIn("HttpOnly", session_headers[0])
        mock_exchange.assert_called_once()
        mock_viewer.assert_called_once()

    @patch("app.run_triage")
    def test_multi_user_cache_isolation_and_selective_refresh(self, mock_run_triage):
        mock_run_triage.side_effect = lambda client, **kwargs: _sample_triage(client.username)

        client_a = app_module.app.test_client()
        client_b = app_module.app.test_client()

        tok_a = auth.encrypt_cookie_payload({"access_token": "token_A", "username": "alice", "refresh_token": ""})
        tok_b = auth.encrypt_cookie_payload({"access_token": "token_B", "username": "bob", "refresh_token": ""})
        client_a.set_cookie(auth.SESSION_COOKIE_NAME, tok_a)
        client_b.set_cookie(auth.SESSION_COOKIE_NAME, tok_b)

        res_a1 = client_a.get("/api/triage").get_json()
        res_b1 = client_b.get("/api/triage").get_json()
        self.assertEqual(res_a1["data"]["username"], "alice")
        self.assertEqual(res_b1["data"]["username"], "bob")
        self.assertFalse(res_a1["cached"])
        self.assertFalse(res_b1["cached"])
        self.assertEqual(mock_run_triage.call_count, 2)

        # Second request hits each user's isolated cache
        res_a2 = client_a.get("/api/triage").get_json()
        res_b2 = client_b.get("/api/triage").get_json()
        self.assertTrue(res_a2["cached"])
        self.assertTrue(res_b2["cached"])
        self.assertEqual(res_a2["data"]["username"], "alice")
        self.assertEqual(res_b2["data"]["username"], "bob")
        self.assertEqual(mock_run_triage.call_count, 2)

        # Refreshing User A must NOT clear User B's cache
        res_a3 = client_a.post("/api/refresh").get_json()
        self.assertFalse(res_a3["cached"])
        self.assertEqual(mock_run_triage.call_count, 3)

        res_b3 = client_b.get("/api/triage").get_json()
        self.assertTrue(res_b3["cached"])
        self.assertEqual(res_b3["data"]["username"], "bob")
        self.assertEqual(mock_run_triage.call_count, 3)

    @patch("app.run_triage")
    @patch("app.refresh_access_token")
    def test_expired_github_app_token_auto_refreshes(self, mock_refresh, mock_run_triage):
        mock_refresh.return_value = {
            "access_token": "token_new",
            "refresh_token": "refresh_new",
            "expires_at": int(time.time()) + 28800,
        }
        mock_run_triage.return_value = _sample_triage("alice")

        expired_cookie = auth.encrypt_cookie_payload(
            {
                "access_token": "token_old",
                "refresh_token": "refresh_old",
                "expires_at": int(time.time()) - 10,
                "username": "alice",
            }
        )
        self.client.set_cookie(auth.SESSION_COOKIE_NAME, expired_cookie)
        res = self.client.get("/api/triage")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["data"]["username"], "alice")
        mock_refresh.assert_called_once_with("refresh_old")
        self.assertIn(auth.SESSION_COOKIE_NAME, res.headers.get("Set-Cookie", ""))

        # Second near-simultaneous request with same pre-refresh cookie deduplicates refresh
        res2 = self.client.get("/api/triage")
        self.assertEqual(res2.status_code, 200)
        mock_refresh.assert_called_once_with("refresh_old")

    @patch("app.refresh_access_token")
    def test_transient_refresh_failure_returns_503_without_clearing_cookie(self, mock_refresh):
        mock_refresh.side_effect = requests.Timeout("GitHub timeout")

        expired_cookie = auth.encrypt_cookie_payload(
            {
                "access_token": "token_old",
                "refresh_token": "refresh_transient",
                "expires_at": int(time.time()) - 10,
                "username": "alice",
            }
        )
        self.client.set_cookie(auth.SESSION_COOKIE_NAME, expired_cookie)
        res = self.client.get("/api/triage")
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.get_json()["auth_error"], "upstream_unavailable")
        self.assertNotIn(f"{auth.SESSION_COOKIE_NAME}=;", res.headers.get("Set-Cookie", ""))

    @patch("app.run_triage")
    @patch("app.refresh_access_token")
    def test_refreshed_cookie_preserved_when_triage_errors(self, mock_refresh, mock_run_triage):
        mock_refresh.return_value = {
            "access_token": "token_new",
            "refresh_token": "refresh_new",
            "expires_at": int(time.time()) + 28800,
        }
        resp_502 = requests.Response()
        resp_502.status_code = 502
        mock_run_triage.side_effect = requests.HTTPError("502 Bad Gateway", response=resp_502)

        expired_cookie = auth.encrypt_cookie_payload(
            {
                "access_token": "token_old",
                "refresh_token": "refresh_keep_on_500",
                "expires_at": int(time.time()) - 10,
                "username": "alice",
            }
        )
        self.client.set_cookie(auth.SESSION_COOKIE_NAME, expired_cookie)
        res = self.client.get("/api/triage")
        self.assertEqual(res.status_code, 500)
        set_cookie = res.headers.get("Set-Cookie", "")
        self.assertIn(auth.SESSION_COOKIE_NAME, set_cookie)
        self.assertNotIn(f"{auth.SESSION_COOKIE_NAME}=;", set_cookie)

    @patch("app.run_triage")
    def test_revoked_oauth_token_returns_401_and_clears_cookie(self, mock_run_triage):
        resp_401 = requests.Response()
        resp_401.status_code = 401
        mock_run_triage.side_effect = requests.HTTPError("401 Unauthorized", response=resp_401)

        cookie = auth.encrypt_cookie_payload({"access_token": "revoked_tok", "username": "alice", "refresh_token": ""})
        self.client.set_cookie(auth.SESSION_COOKIE_NAME, cookie)

        res = self.client.get("/api/triage")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["auth_error"], "token_revoked")
        set_cookie = res.headers.get("Set-Cookie", "")
        self.assertIn(f"{auth.SESSION_COOKIE_NAME}=;", set_cookie)

    def test_web_oauth_fork_endpoint_is_read_only_forbidden(self):
        cookie = auth.encrypt_cookie_payload({"access_token": "tok_a", "username": "alice", "refresh_token": ""})
        self.client.set_cookie(auth.SESSION_COOKIE_NAME, cookie)

        res = self.client.post("/api/fork", json={"repo": "owner/repo"})
        self.assertEqual(res.status_code, 403)
        self.assertIn("read-only", res.get_json()["error"].lower())

    @patch("app.refresh_access_token")
    def test_vercel_fork_rejects_before_refreshing_token(self, mock_refresh):
        expired_cookie = auth.encrypt_cookie_payload(
            {
                "access_token": "token_old",
                "refresh_token": "refresh_unused",
                "expires_at": int(time.time()) - 10,
                "username": "alice",
            }
        )
        self.client.set_cookie(auth.SESSION_COOKIE_NAME, expired_cookie)
        with patch.dict(os.environ, {"VERCEL": "1"}, clear=False):
            res = self.client.post("/api/fork", json={"repo": "owner/repo"})
        self.assertEqual(res.status_code, 403)
        mock_refresh.assert_not_called()

    def test_logout_clears_session_and_returns_to_demo(self):
        cookie = auth.encrypt_cookie_payload({"access_token": "tok_a", "username": "alice", "refresh_token": ""})
        self.client.set_cookie(auth.SESSION_COOKIE_NAME, cookie)

        res = self.client.post("/api/auth/logout")
        self.assertEqual(res.status_code, 200)
        self.assertIn(f"{auth.SESSION_COOKIE_NAME}=;", res.headers.get("Set-Cookie", ""))


class TestCLIAndPackagingSync(unittest.TestCase):
    def test_cli_help_and_ui_help(self):
        runner = CliRunner()
        res = runner.invoke(triage.cli, ["--help"])
        self.assertEqual(res.exit_code, 0)
        self.assertIn("ui", res.output)

        res_ui = runner.invoke(triage.cli, ["ui", "--help"])
        self.assertEqual(res_ui.exit_code, 0)
        self.assertIn("--demo", res_ui.output)
        self.assertIn("--no-browser", res_ui.output)

    @patch("triage.run_triage")
    @patch.object(GitHubClient, "_gql", return_value={"viewer": {"login": "auto_user"}})
    def test_cli_auto_detects_username_when_only_token_present(self, mock_gql, mock_run_triage):
        mock_run_triage.return_value = _sample_triage("auto_user")
        runner = CliRunner()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_dummy", "GITHUB_USERNAME": ""}, clear=False):
            res = runner.invoke(triage.cli, ["--json"])
        self.assertEqual(res.exit_code, 0, res.output)
        parsed = json.loads(res.output)
        self.assertEqual(parsed["username"], "auto_user")
        mock_gql.assert_called_once()

    def test_frontend_copies_are_identical_and_no_inline_copy_onclick(self):
        root_html = (ROOT_DIR / "index.html").read_text(encoding="utf-8")
        tpl_html = (ROOT_DIR / "templates" / "index.html").read_text(encoding="utf-8")
        pub_html = (ROOT_DIR / "public" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(root_html, tpl_html)
        self.assertEqual(root_html, pub_html)
        self.assertIn("btn-external-only", root_html)

        main_js = (ROOT_DIR / "static" / "main.js").read_text(encoding="utf-8")
        pub_js = (ROOT_DIR / "public" / "static" / "main.js").read_text(encoding="utf-8")
        self.assertEqual(main_js, pub_js)
        self.assertNotIn("onclick=", main_js)

        style_css = (ROOT_DIR / "static" / "style.css").read_text(encoding="utf-8")
        pub_css = (ROOT_DIR / "public" / "static" / "style.css").read_text(encoding="utf-8")
        self.assertEqual(style_css, pub_css)

    def test_run_triage_external_only_excludes_self_owned_repos(self):
        from datetime import datetime, timezone
        from core import run_triage

        now_iso = datetime.now(timezone.utc).isoformat()
        fake_client = MagicMock()
        fake_client.username = "Olalolo22"
        fake_client.get_open_prs.return_value = [
            {
                "number": 10,
                "title": "Own repo PR",
                "url": "https://github.com/Olalolo22/3riage/pull/10",
                "isDraft": False,
                "repository": {"nameWithOwner": "olalolo22/3riage"},
                "body": "",
                "closingIssuesReferences": {"nodes": []},
                "reviews": {"nodes": []},
                "reviewThreads": {"nodes": []},
                "comments": {"nodes": []},
                "commits": {"nodes": [{"commit": {"committedDate": now_iso}}]},
            },
            {
                "number": 20,
                "title": "External PR",
                "url": "https://github.com/ext-org/ext-repo/pull/20",
                "isDraft": False,
                "repository": {"nameWithOwner": "ext-org/ext-repo"},
                "body": "",
                "closingIssuesReferences": {"nodes": []},
                "reviews": {"nodes": []},
                "reviewThreads": {"nodes": []},
                "comments": {"nodes": []},
                "commits": {"nodes": [{"commit": {"committedDate": now_iso}}]},
            },
        ]
        fake_client.get_merged_prs.return_value = [
            {
                "number": 1,
                "title": "Own merged PR",
                "url": "https://github.com/Olalolo22/3riage/pull/1",
                "mergedAt": now_iso,
                "repository": {"nameWithOwner": "Olalolo22/3riage"},
            },
            {
                "number": 2,
                "title": "External merged PR",
                "url": "https://github.com/ext-org/ext-repo/pull/2",
                "mergedAt": now_iso,
                "repository": {"nameWithOwner": "ext-org/ext-repo"},
            },
        ]
        fake_client.get_involved_issues.return_value = []
        fake_client.get_forked_parents.return_value = set()
        fake_client.get_write_access_repos.return_value = set()

        data = run_triage(fake_client, external_only=True)
        self.assertEqual(data["summary"]["waiting_on_them"], 1)
        self.assertEqual(data["prs"]["WAITING_ON_THEM"][0]["repo"], "ext-org/ext-repo")
        self.assertEqual(data["summary"]["ready_to_claim"], 1)
        self.assertEqual(data["claims"][0]["repo"], "ext-org/ext-repo")

    def test_graphql_queries_fetch_link_bot_and_ci_fields(self):
        pr_q = GitHubClient._PR_QUERY
        for field in ("baseRefName", "headRefName", "isCrossRepository", "authorAssociation",
                      "defaultBranchRef", "closingIssuesReferences", "statusCheckRollup",
                      "totalCount", "... on CheckRun", "... on StatusContext",
                      "reviewThreads", "isOutdated"):
            self.assertIn(field, pr_q, field)
        merged_q = GitHubClient._MERGED_PR_QUERY
        for field in ("closingIssuesReferences", "baseRefName", "defaultBranchRef", "body"):
            self.assertIn(field, merged_q, field)

    def test_open_pr_query_falls_back_without_ci_on_graphql_error(self):
        client = GitHubClient(token="t", username="octocat")
        self.assertNotIn("statusCheckRollup", GitHubClient._PR_QUERY_NO_CI)
        self.assertNotIn("__CI_FIELDS__", GitHubClient._PR_QUERY)
        page = {"user": {"pullRequests": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [{"number": 1, "isDraft": False}],
        }}}
        calls = []

        def fake_gql(query, variables):
            calls.append(query)
            if "statusCheckRollup" in query:
                raise RuntimeError("GraphQL errors: Resource not accessible by integration")
            return page

        with patch.object(client, "_gql", side_effect=fake_gql):
            prs = client.get_open_prs()
        self.assertEqual(len(prs), 1)
        self.assertEqual(len(calls), 2)
        self.assertNotIn("statusCheckRollup", calls[1])

    def test_open_pr_query_raises_unrelated_errors(self):
        client = GitHubClient(token="t", username="octocat")
        with patch.object(client, "_gql", side_effect=RuntimeError("GraphQL errors: bad login")):
            with self.assertRaises(RuntimeError):
                client.get_open_prs()

    def test_run_triage_suggests_assigned_issue_and_flags_merged_risk(self):
        from datetime import datetime, timezone, timedelta
        from core import run_triage

        now = datetime.now(timezone.utc)
        iso = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        fake_client = MagicMock()
        fake_client.username = "contrib"
        fake_client.extract_issue_refs_from_body = GitHubClient.extract_issue_refs_from_body
        base_repo = {"nameWithOwner": "org/app", "defaultBranchRef": {"name": "main"}}
        fake_client.get_open_prs.return_value = [
            {
                "number": 30, "title": "Ticker bound", "url": "u30", "isDraft": False,
                "repository": base_repo, "baseRefName": "main", "headRefName": "ticker",
                "body": "", "closingIssuesReferences": {"nodes": []},
                "reviews": {"nodes": []}, "reviewThreads": {"nodes": []}, "comments": {"nodes": []},
                "commits": {"nodes": [{"commit": {"committedDate": iso(now - timedelta(hours=2))}}]},
            },
            {
                "number": 31, "title": "Own repo", "url": "u31", "isDraft": False,
                "repository": {"nameWithOwner": "contrib/tool", "defaultBranchRef": {"name": "main"}},
                "baseRefName": "main", "body": "", "closingIssuesReferences": {"nodes": []},
                "reviews": {"nodes": []}, "reviewThreads": {"nodes": []}, "comments": {"nodes": []},
                "commits": {"nodes": [{"commit": {"committedDate": iso(now)}}]},
            },
        ]
        fake_client.get_merged_prs.return_value = [
            {
                "number": 7, "title": "Merged unlinked", "url": "u7", "mergedAt": iso(now - timedelta(days=1)),
                "repository": base_repo, "baseRefName": "main", "body": "",
                "closingIssuesReferences": {"nodes": []},
            },
        ]
        fake_client.get_involved_issues.return_value = [
            {
                "number": 711, "title": "Bind ticker", "url": "i711", "state": "OPEN",
                "repository": {"nameWithOwner": "org/app"}, "author": {"login": "maint"},
                "assignees": {"nodes": [{"login": "contrib"}]}, "comments": {"nodes": []},
            },
        ]
        fake_client.get_forked_parents.return_value = set()
        fake_client.get_write_access_repos.return_value = set()

        data = run_triage(fake_client)
        prs = {p["number"]: p for items in data["prs"].values() for p in items}
        self.assertEqual(prs[30]["suggested_close_issues"], [711])
        self.assertEqual(prs[30]["suggestion_confidence"], "strong")
        self.assertTrue(data["claims"][0]["points_at_risk"])
        # Own-repo PR without a link is not counted as a problem.
        self.assertEqual(data["summary"]["unlinked_prs"], 1)
        self.assertEqual(data["summary"]["points_at_risk"], 1)

    def test_github_client_thread_local_sessions(self):
        from concurrent.futures import ThreadPoolExecutor

        client = GitHubClient(token="ghu_test_token", username="octocat")
        main_sess = client._get_session()
        self.assertIs(main_sess, client.session)

        def worker(_):
            s = client._get_session()
            return id(s), s.headers.get("Authorization")

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(worker, range(8)))

        for sess_id, auth_hdr in results:
            self.assertNotEqual(sess_id, id(main_sess))
            self.assertEqual(auth_hdr, "Bearer ghu_test_token")


if __name__ == "__main__":
    unittest.main()
