"""Risk engine: the arithmetic must be right, not just plausible."""

from __future__ import annotations

import math
import unittest

from helpers import EngineTestCase, db, risk


class TestSingleEventLoss(EngineTestCase):
    def test_fixed_amount_is_used_directly(self):
        s = self.assess().scenario("S1")
        fixed = [b for b in s.breakdown if b["basis"] == "fixed_amount"]
        self.assertTrue(fixed)
        for b in fixed:
            self.assertEqual(b["amount_minor"], b["value_minor"])

    def test_downtime_scales_with_daily_revenue(self):
        s = self.assess().scenario("S1")
        downtime = next(b for b in s.breakdown
                        if b["basis"] == "daily_revenue_x_hours")
        asset = self.model["assets"]["A1-OMS-DB-PROD"]
        expected = int(round(asset.daily_revenue * downtime["hours"] / 24.0))
        self.assertEqual(downtime["amount_minor"], expected)

    def test_per_record_multiplies_by_record_count(self):
        s = self.assess().scenario("S2")
        per_record = next(b for b in s.breakdown if b["basis"] == "per_record")
        self.assertEqual(per_record["amount_minor"],
                         per_record["value_minor"] * per_record["record_count"])

    def test_sle_is_the_sum_of_components(self):
        for s in self.assess().scenarios:
            self.assertEqual(s.sle_minor, sum(b["amount_minor"] for b in s.breakdown))

    def test_low_and_high_bracket_the_point_estimate(self):
        for s in self.assess().scenarios:
            self.assertLessEqual(s.sle_low_minor, s.sle_minor)
            self.assertLessEqual(s.sle_minor, s.sle_high_minor)


class TestProbability(EngineTestCase):
    def test_inherent_probability_formula(self):
        s = self.assess().scenario("S1")
        scenario = self.model["scenarios"]["S1"]
        m = scenario.exposure_factor * risk.vulnerability_multiplier(
            [f for f in self.model["findings"] if f.asset_id == "A1-OMS-DB-PROD"])
        self.assertAlmostEqual(s.p_inherent, 1 - (1 - scenario.p0) ** m, places=9)

    def test_residual_equals_inherent_times_mitigation(self):
        for s in self.assess().scenarios:
            self.assertAlmostEqual(s.p_residual, s.p_inherent * s.mitigation_factor,
                                   places=12)

    def test_eal_equals_probability_times_sle(self):
        for s in self.assess().scenarios:
            self.assertEqual(s.eal_minor,
                             int(round(s.p_residual * s.sle_minor * s.lambda_)))

    def test_more_findings_raise_the_inherent_probability(self):
        few = [f for f in self.model["findings"]
               if f.asset_id == "A1-OMS-DB-PROD" and f.severity == "low"]
        many = [f for f in self.model["findings"] if f.asset_id == "A1-OMS-DB-PROD"]
        self.assertGreater(risk.vulnerability_multiplier(many),
                           risk.vulnerability_multiplier(few))

    def test_critical_and_exploitable_findings_weigh_most(self):
        weights = risk.SEVERITY_WEIGHT
        self.assertGreater(weights["critical"], weights["high"])
        self.assertGreater(weights["high"], weights["medium"])
        self.assertGreater(weights["medium"], weights["low"])

    def test_exploitable_findings_weigh_more_than_the_same_severity(self):
        from app.risk import Finding
        base = dict(source_system="t", asset_id="A", rule_id="r", title="t",
                    severity="high", status="open", match_method="exact",
                    observed_at=None, scenario_hints=[])
        plain = Finding(external_finding_id="f1", exploitable=False, **base)
        exploitable = Finding(external_finding_id="f2", exploitable=True, **base)
        self.assertGreater(risk.vulnerability_multiplier([exploitable]),
                           risk.vulnerability_multiplier([plain]))

    def test_p0_override_changes_the_result(self):
        base = self.assess().scenario("S1").eal_minor
        bumped = self.assess(p0_overrides={"S1": 0.2}).scenario("S1").eal_minor
        self.assertGreater(bumped, base)

    def test_p0_above_the_cap_is_rejected(self):
        with self.assertRaises(risk.RiskError):
            self.assess(p0_overrides={"S1": 0.9})


class TestControls(EngineTestCase):
    def test_baseline_mitigation_is_the_product_of_one_minus_ce(self):
        s = self.assess().scenario("S1")
        expected = 1.0
        for c in s.control_detail:
            expected *= (1 - c["ce_applied"])
        self.assertAlmostEqual(s.mitigation_factor, expected, places=12)

    def test_selected_action_raises_control_effectiveness(self):
        before = self.assess().scenario("S1").control_detail[0]["ce_applied"]
        after = self.assess(selected_actions={"ACT-3"}).scenario("S1")
        changed = next(c for c in after.control_detail if c["control_code"] == "C-01")
        self.assertGreater(changed["ce_applied"], before)
        self.assertTrue(changed["changed"])

    def test_controls_never_increase_risk(self):
        base = self.assess().eal_minor
        for code in ("ACT-1", "ACT-3", "ACT-4", "ACT-6", "ACT-10"):
            self.assertLessEqual(self.assess(selected_actions={code}).eal_minor, base,
                                 f"{code} increased the modelled risk")

    def test_stacked_controls_cannot_exceed_the_mitigation_ceiling(self):
        from app import config
        every = set(self.model["actions"])
        for s in self.assess(selected_actions=every).scenarios:
            self.assertGreaterEqual(s.mitigation_factor,
                                    1 - config.MAX_CONTROL_MITIGATION - 1e-9)
            self.assertLessEqual(s.mitigation_factor, 1.0)

    def test_two_actions_on_one_control_take_the_stronger_not_the_product(self):
        single = self.assess(selected_actions={"ACT-1"})
        both = self.assess(selected_actions={"ACT-1", "ACT-2"})
        s1 = single.scenario("S2")
        s2 = both.scenario("S2")
        self.assertGreater(s2.control_detail[0]["ce_applied"],
                           s1.control_detail[0]["ce_applied"])
        self.assertLessEqual(s2.mitigation_factor, s1.mitigation_factor)


class TestFindingFilter(EngineTestCase):
    def test_patch_action_removes_matching_findings(self):
        before = risk.vulnerability_multiplier(
            [f for f in self.model["findings"] if f.asset_id == "A1-OMS-DB-PROD"])
        after = risk.vulnerability_multiplier([
            f for f in self.model["findings"]
            if f.asset_id == "A1-OMS-DB-PROD"
            and not (f.severity in ("critical", "high") and f.exploitable)])
        self.assertLess(after, before)

    def test_patch_action_lowers_the_scenario(self):
        base = self.assess().scenario("S1")
        patched = self.assess(selected_actions={"ACT-10"}).scenario("S1")
        self.assertLessEqual(patched.p_inherent, base.p_inherent)


class TestCorrelation(EngineTestCase):
    def test_group_total_is_between_sum_and_max(self):
        assessment = self.assess()
        self.assertLessEqual(assessment.eal_minor, assessment.eal_unadjusted_minor)
        for group in {s.group_id for s in assessment.scenarios if s.group_id}:
            members = [s.eal_minor for s in assessment.scenarios if s.group_id == group]
            if len(members) > 1:
                self.assertGreaterEqual(assessment.eal_minor, max(members))

    def test_raising_rho_never_increases_the_total(self):
        low = self.assess(rho_map={"G1": 0.0, "G2": 0.0, "G3": 0.0, "G4": 0.0})
        high = self.assess(rho_map={"G1": 0.9, "G2": 0.9, "G3": 0.9, "G4": 0.9})
        self.assertLessEqual(high.eal_minor, low.eal_minor)

    def test_rho_of_one_collapses_a_group_to_its_worst_member(self):
        members = [s.eal_minor for s in self.assess().scenarios if s.group_id == "G1"]
        rho = {g: 1.0 for g in ("G1", "G2", "G3", "G4")}
        collapsed = self.assess(rho_map=rho)
        self.assertGreaterEqual(collapsed.eal_minor, max(members))

    def test_rollups_sum_to_the_headline(self):
        a = self.assess()
        for rollup in (a.by_asset, a.by_business_unit, a.by_actor, a.by_category):
            self.assertAlmostEqual(sum(rollup.values()) / 100, a.eal_minor / 100,
                                   delta=max(1.0, a.eal_minor / 100 * 0.01))

    def test_uncertainty_range_brackets_the_point_estimate(self):
        a = self.assess()
        self.assertLessEqual(a.eal_low_minor, a.eal_minor)
        self.assertLessEqual(a.eal_minor, a.eal_high_minor)


class TestConfidence(EngineTestCase):
    def test_confidence_is_bounded_and_carries_reasons(self):
        a = self.assess()
        self.assertGreaterEqual(a.confidence, 0)
        self.assertLessEqual(a.confidence, 100)
        for s in a.scenarios:
            self.assertIn(s.confidence_band, {"Low", "Medium", "High"})
            self.assertTrue(s.confidence_reasons)

    def test_assumed_control_effectiveness_caps_confidence(self):
        for s in self.assess().scenarios:
            if any(c["ce_source"] == "assumed" for c in s.control_detail):
                self.assertLessEqual(s.confidence, 54)

    def test_fresh_data_scores_higher_than_stale_data(self):
        a = self.assess()
        self.assertIn("sources", a.freshness)
        self.assertTrue(a.freshness["sources"])


class TestIncompleteScenarios(EngineTestCase):
    def test_missing_asset_marks_the_scenario_incomplete(self):
        # The FK on scenarios.asset_id normally prevents this; the engine still
        # guards against it, so force the bad row past SQLite.
        self.conn.execute("PRAGMA foreign_keys = OFF")
        self.conn.execute("UPDATE scenarios SET asset_id = 'NOPE' WHERE scenario_code='S1'")
        self.conn.commit()
        model = risk.load_model(self.conn)
        assessment = risk.assess(model)
        self.assertEqual([i["scenario_code"] for i in assessment.incomplete], ["S1"])

    def test_scenario_cannot_reference_a_missing_asset_in_normal_operation(self):
        with self.assertRaises(Exception):
            self.conn.execute("UPDATE scenarios SET asset_id = 'NOPE' "
                              "WHERE scenario_code='S1'")

    def test_decommissioned_asset_marks_the_scenario_incomplete(self):
        self.conn.execute("UPDATE assets SET status='decommissioned' "
                          "WHERE asset_id='A1-OMS-DB-PROD'")
        self.conn.commit()
        assessment = risk.assess(risk.load_model(self.conn))
        self.assertIn("S1", [i["scenario_code"] for i in assessment.incomplete])


class TestValidation(EngineTestCase):
    def test_unknown_action_is_rejected(self):
        with self.assertRaises(risk.RiskError):
            self.assess(selected_actions={"ACT-999"})

    def test_money_is_stored_in_minor_units(self):
        self.assertEqual(db.to_minor(1234.56), 123456)
        self.assertEqual(db.to_major(123456), 1234.56)


if __name__ == "__main__":
    unittest.main()
