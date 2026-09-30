"""HTTP-level tests against the real FastAPI app and a temporary database."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

_TMP = tempfile.mkdtemp(prefix="crp-api-tests-")
os.environ["CRP_DATA_DIR"] = _TMP
os.environ["CRP_LLM_ENABLED"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from app import config, db, demo_data  # noqa: E402
from app.main import app  # noqa: E402

db.init_db()
with db.connect() as _conn:
    if db.table_count(_conn, "assets") == 0:
        demo_data.seed(_conn)


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp_db = Path(config.DB_PATH)
        self._db_backup = self._tmp_db.with_suffix(".apitest-backup")
        shutil.copyfile(self._tmp_db, self._db_backup)
        # Startup event seeds an empty database; run it so behaviour matches a
        # real cold start.
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        shutil.copyfile(self._db_backup, self._tmp_db)
        self._db_backup.unlink(missing_ok=True)

    def login(self, username="admin", password="admin123"):
        response = self.client.post("/api/login",
                                    json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()


class TestHealthAndAuth(ApiTestCase):
    def test_health_is_public(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["currency"], config.DEFAULT_CURRENCY)

    def test_root_serves_the_dashboard(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_protected_routes_require_authentication(self):
        self.client.cookies.clear()
        for route in ("/api/overview", "/api/assessment", "/api/catalog",
                      "/api/optimise/frontier", "/api/audit"):
            with self.subTest(route=route):
                self.assertIn(self.client.get(route).status_code, (401, 403))

    def test_login_rejects_a_bad_password(self):
        response = self.client.post("/api/login",
                                    json={"username": "admin", "password": "nope"})
        self.assertEqual(response.status_code, 401)

    def test_login_returns_the_user_and_role(self):
        body = self.login()
        self.assertEqual(body["username"], "admin")
        self.assertIn("role", body)

    def test_me_works_after_login(self):
        self.login()
        self.assertEqual(self.client.get("/api/me").json()["username"], "admin")

    def test_logout_clears_the_session(self):
        self.login()
        self.assertEqual(self.client.post("/api/logout").status_code, 200)
        self.assertIn(self.client.get("/api/me").status_code, (401, 403))


class TestModelEndpoints(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login()

    def test_overview_reports_counts_and_the_synthetic_flag(self):
        body = self.client.get("/api/overview").json()
        self.assertGreater(body["counts"]["assets"], 0)
        self.assertGreater(body["counts"]["scenarios"], 0)
        self.assertEqual(body["synthetic_asset_share"], 1.0)
        self.assertTrue(body["recent_datasets"])

    def test_catalog_lists_assets_controls_and_actions(self):
        body = self.client.get("/api/catalog").json()
        self.assertTrue(body["assets"])
        self.assertTrue(body["actions"])
        self.assertTrue(body["controls"])

    def test_assessment_reports_eal_and_confidence(self):
        body = self.client.get("/api/assessment").json()
        assessment = body["assessment"]
        self.assertGreater(assessment["eal_minor"], 0)
        self.assertGreater(assessment["confidence"], 0)
        self.assertTrue(assessment["scenarios"])

    def test_assessment_eal_is_never_above_the_uncertainty_ceiling(self):
        assessment = self.client.get("/api/assessment").json()["assessment"]
        self.assertLessEqual(assessment["eal_minor"], assessment["eal_high_minor"])
        self.assertGreaterEqual(assessment["eal_minor"], assessment["eal_low_minor"])

    def test_what_if_raises_exposure_when_probability_rises(self):
        base = self.client.get("/api/assessment").json()["assessment"]["eal_minor"]
        bumped = self.client.post("/api/scenarios/S1/whatif",
                                  json={"p0": 0.2}).json()
        self.assertGreater(bumped["assessment"]["eal_minor"], base)

    def test_what_if_rejects_an_out_of_range_probability(self):
        response = self.client.post("/api/scenarios/S1/whatif", json={"p0": 5})
        self.assertEqual(response.status_code, 422)

    def test_what_if_on_an_unknown_scenario_is_rejected(self):
        self.assertEqual(
            self.client.post("/api/scenarios/NOPE/whatif", json={"p0": 0.1}).status_code,
            404)

    def test_optimise_respects_the_budget(self):
        plan = self.client.post("/api/optimise",
                                json={"budget_minor": 250_000_000,
                                      "max_actions": 5}).json()["plan"]
        self.assertLessEqual(plan["cost_minor"], 250_000_000)
        self.assertLessEqual(plan["capacity_used"], 5)
        self.assertTrue(plan["optimal"])

    def test_optimise_rejects_a_zero_budget(self):
        self.assertEqual(
            self.client.post("/api/optimise",
                             json={"budget_minor": 0, "max_actions": 5}).status_code,
            422)

    def test_frontier_is_monotonic(self):
        body = self.client.get(
            "/api/optimise/frontier?budget_max=400000000&steps=5").json()
        points = body["frontier"]
        self.assertGreaterEqual(len(points), 3)
        eals = [p["plan_eal_minor"] for p in points]
        self.assertEqual(eals, sorted(eals, reverse=True))
        self.assertEqual(body["currency"], config.DEFAULT_CURRENCY)


class TestAssistantEndpoints(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login()

    def test_ai_status_reports_the_template_fallback(self):
        body = self.client.get("/api/ai/status").json()
        self.assertFalse(body["llm_enabled"])
        self.assertIn("mode", body)

    def test_ask_answers_an_in_scope_question(self):
        body = self.client.post("/api/ask",
                                json={"question": "What is our total expected annual loss?"}
                                ).json()
        self.assertFalse(body["refused"])
        self.assertIn("text", body)
        self.assertIn("expected annual loss", body["text"].lower())

    def test_ask_refuses_an_out_of_scope_question(self):
        body = self.client.post(
            "/api/ask",
            json={"question": "Will we be attacked next year?"}).json()
        self.assertTrue(body["refused"])
        self.assertIn("cannot answer", body["text"].lower())

    def test_ask_rejects_an_empty_question(self):
        # Pydantic enforces min_length=1, so a whitespace-only string is
        # accepted by the schema and handled by the assistant itself.
        self.assertIn(
            self.client.post("/api/ask", json={"question": ""}).status_code, (200, 422))
        body = self.client.post("/api/ask", json={"question": "   "}).json()
        self.assertIn("text", body)

    def test_ask_rejects_an_overlong_question(self):
        response = self.client.post("/api/ask", json={"question": "x" * 2000})
        self.assertEqual(response.status_code, 422)


class TestReportEndpoints(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login()

    def test_markdown_report_carries_the_synthetic_banner(self):
        response = self.client.get("/api/report/summary.md")
        self.assertEqual(response.status_code, 200)
        self.assertIn("SYNTHETIC", response.text.upper())

    def test_scenarios_csv_has_a_header_and_rows(self):
        response = self.client.get("/api/report/scenarios.csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn("scenario_code", response.text)
        self.assertIn("S1", response.text)

    def test_board_html_is_a_document(self):
        response = self.client.get("/api/report/board.html?budget_minor=250000000")
        self.assertEqual(response.status_code, 200)
        self.assertIn("<!doctype html>", response.text.lower())
        self.assertIn("SYNTHETIC", response.text.upper())

    def test_actions_csv_is_available_with_a_plan(self):
        response = self.client.get(
            "/api/report/actions.csv?budget_minor=250000000")
        self.assertEqual(response.status_code, 200)
        self.assertIn("action_code", response.text)

    def test_audit_log_is_returned_for_admins(self):
        body = self.client.get("/api/audit?limit=10").json()
        self.assertIn("events", body)


class TestIngestEndpoint(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login()

    def test_upload_reports_row_counts(self):
        response = self.client.post(
            "/api/ingest",
            data={"dataset_type": "assets", "commit": "true"},
            files={"file": ("a.csv",
                            b"asset_id,name,asset_type,business_unit,criticality\n"
                            b"A-API,Api asset,server,IT,2\n", "text/csv")})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["rows_ok"], 1)
        self.assertEqual(body["rows_quarantined"], 0)

    def test_dry_run_upload_reports_validated(self):
        response = self.client.post(
            "/api/ingest",
            data={"dataset_type": "assets", "commit": "false"},
            files={"file": ("a.csv",
                            b"asset_id,name,asset_type,business_unit,criticality\n"
                            b"A-DRY,Dry run,server,IT,2\n", "text/csv")})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "validated")

    def test_quarantined_rows_are_listed(self):
        self.client.post(
            "/api/ingest",
            data={"dataset_type": "assets", "commit": "true"},
            files={"file": ("a.csv",
                            b"asset_id,name,asset_type,business_unit,criticality\n"
                            b",Missing id,server,IT,2\n", "text/csv")})
        body = self.client.get("/api/quarantine?limit=5").json()
        self.assertTrue(body["rows"])
        self.assertTrue(body["rows"][0]["reason"])

    def test_unknown_dataset_type_is_a_400(self):
        response = self.client.post(
            "/api/ingest",
            data={"dataset_type": "spaceships", "commit": "true"},
            files={"file": ("a.csv", b"a,b\n1,2\n", "text/csv")})
        self.assertEqual(response.status_code, 400)


class TestStaticAssets(ApiTestCase):
    """The dashboard is plain JS with no build step, so nothing would catch a
    syntax error at runtime. These checks make a broken page a test failure."""

    def test_dashboard_is_served(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_dashboard_references_its_assets(self):
        html = self.client.get("/").text
        self.assertIn("/static/app.js", html)
        self.assertIn("/static/styles.css", html)
        self.assertIn('id="login-btn"', html)
        self.assertIn('id="username"', html)
        self.assertIn('id="password"', html)

    def test_javascript_parses(self):
        source = (_ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
        node = shutil.which("node")
        if node is None:
            self.skipTest("node not available to syntax-check app.js")
        result = subprocess.run([node, "--check", str(_ROOT / "app" / "static" / "app.js")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0,
                         f"app.js failed to parse:\n{result.stderr}")

    def test_javascript_has_balanced_template_literals(self):
        source = (_ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
        # Each "${" needs a matching "}"; a missing brace is the common edit slip.
        opens, closes = source.count("${"), source.count("}")
        self.assertGreaterEqual(closes, opens,
                                "unbalanced ${ } interpolation in app.js")

    def test_stylesheet_is_served(self):
        response = self.client.get("/static/styles.css")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/css", response.headers["content-type"])

    def test_script_is_served(self):
        response = self.client.get("/static/app.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response.headers["content-type"])


class TestDemoReset(ApiTestCase):
    def test_reset_restores_the_d0_synthetic_dataset(self):
        self.login()
        response = self.client.post("/api/demo/reset?variant=D0")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(self.client.get("/api/overview").json()["counts"]["assets"])


if __name__ == "__main__":
    unittest.main()
