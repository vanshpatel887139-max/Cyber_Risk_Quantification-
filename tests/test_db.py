"""Database, auth, capability, and money-conversion tests."""

from __future__ import annotations

import unittest

from helpers import EngineTestCase, config, db, risk


class TestPasswords(EngineTestCase):
    def test_passwords_are_hashed_not_stored(self):
        stored = self.conn.execute(
            "SELECT password_hash FROM users WHERE username='admin'").fetchone()[0]
        self.assertNotIn("admin123", stored)

    def test_correct_password_verifies(self):
        stored = self.conn.execute(
            "SELECT password_hash FROM users WHERE username='analyst'").fetchone()[0]
        self.assertTrue(db.verify_password("analyst123", stored))

    def test_wrong_password_is_rejected(self):
        stored = self.conn.execute(
            "SELECT password_hash FROM users WHERE username='analyst'").fetchone()[0]
        self.assertFalse(db.verify_password("wrong", stored))

    def test_hashes_are_salted_so_equal_passwords_differ(self):
        first = db.hash_password("same-password")
        second = db.hash_password("same-password")
        self.assertNotEqual(first, second)
        self.assertTrue(db.verify_password("same-password", first))
        self.assertTrue(db.verify_password("same-password", second))


class TestSessions(EngineTestCase):
    def test_session_round_trips(self):
        user_id = self.conn.execute(
            "SELECT id FROM users WHERE username='admin'").fetchone()["id"]
        token, _ = db.create_session(self.conn, user_id)
        self.assertEqual(db.user_for_token(self.conn, token)["username"], "admin")

    def test_unknown_token_returns_nothing(self):
        self.assertIsNone(db.user_for_token(self.conn, "not-a-real-token"))

    def test_logout_invalidates_the_session(self):
        user_id = self.conn.execute(
            "SELECT id FROM users WHERE username='admin'").fetchone()["id"]
        token, _ = db.create_session(self.conn, user_id)
        self.conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        self.conn.commit()
        self.assertIsNone(db.user_for_token(self.conn, token))

    def test_expired_session_is_ignored(self):
        user_id = self.conn.execute(
            "SELECT id FROM users WHERE username='admin'").fetchone()["id"]
        token, _ = db.create_session(self.conn, user_id)
        self.conn.execute(
            "UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00' "
            "WHERE token = ?", (token,))
        self.conn.commit()
        self.assertIsNone(db.user_for_token(self.conn, token))


class TestCapabilities(EngineTestCase):
    def test_admin_can_do_everything(self):
        for capability in ("data.write", "assumptions.write", "actions.write",
                           "scenario.write", "budget.write", "assessment.run",
                           "optimiser.run", "view", "ai.ask", "report.export",
                           "users.manage", "audit.read"):
            with self.subTest(capability=capability):
                self.assertTrue(db.has_capability(config.ROLE_ADMIN, capability))

    def test_analyst_can_run_the_model_but_not_manage_users(self):
        self.assertTrue(db.has_capability(config.ROLE_ANALYST, "data.write"))
        self.assertTrue(db.has_capability(config.ROLE_ANALYST, "optimiser.run"))
        self.assertTrue(db.has_capability(config.ROLE_ANALYST, "ai.ask"))
        self.assertFalse(db.has_capability(config.ROLE_ANALYST, "users.manage"))

    def test_executive_is_read_only(self):
        self.assertTrue(db.has_capability(config.ROLE_EXEC, "view"))
        self.assertTrue(db.has_capability(config.ROLE_EXEC, "report.export"))
        self.assertTrue(db.has_capability(config.ROLE_EXEC, "assessment.run"))
        self.assertFalse(db.has_capability(config.ROLE_EXEC, "data.write"))
        self.assertFalse(db.has_capability(config.ROLE_EXEC, "optimiser.run"))

    def test_unknown_role_has_no_capabilities(self):
        self.assertFalse(db.has_capability("ghost", "view"))

    def test_no_role_but_admin_can_manage_users(self):
        for role in (config.ROLE_ANALYST, config.ROLE_EXEC):
            self.assertFalse(db.has_capability(role, "users.manage"))


class TestMoney(EngineTestCase):
    def test_to_minor_converts_rupees_to_paise(self):
        self.assertEqual(db.to_minor(1234.56), 123456)
        self.assertEqual(db.to_minor(0), 0)

    def test_to_minor_rounds_half_up(self):
        self.assertEqual(db.to_minor(10.005), 1001)

    def test_to_major_is_the_inverse(self):
        self.assertAlmostEqual(db.to_major(123456), 1234.56, places=2)

    def test_seeded_money_is_in_minor_units(self):
        revenue = self.conn.execute(
            "SELECT daily_revenue FROM assets WHERE asset_id='A1-OMS-DB-PROD'"
        ).fetchone()[0]
        self.assertGreater(revenue, 1_000_000)
        self.assertIsInstance(revenue, int)

    def test_action_costs_are_in_minor_units(self):
        cost = self.conn.execute(
            "SELECT cost FROM actions WHERE action_code='ACT-1'").fetchone()[0]
        self.assertGreater(cost, 10_000_000)
        self.assertIsInstance(cost, int)


class TestAudit(EngineTestCase):
    def test_audit_records_action_and_severity(self):
        db.audit(self.conn, "test.event", entity="unit", detail={"k": 1},
                 username="admin", role="admin", severity="alert")
        row = self.conn.execute(
            "SELECT * FROM audit_events WHERE action='test.event'").fetchone()
        self.assertEqual(row["severity"], "alert")
        self.assertEqual(row["entity"], "unit")
        self.assertIn("k", row["detail_json"])

    def test_freshness_bands_stale_data(self):
        self.conn.execute(
            "UPDATE assets SET observed_at = '2000-01-01T00:00:00+00:00'")
        self.conn.commit()
        assessment = risk.assess(self.reload_model())
        bands = {s["band"] for s in assessment.freshness["sources"].values()}
        self.assertTrue(bands)
        self.assertNotIn("fresh", bands)


if __name__ == "__main__":
    unittest.main()
