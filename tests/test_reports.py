"""Report export tests: synthetic banner, confidence, and grounding caveats."""

from __future__ import annotations

import csv
import io
import json
import unittest

from helpers import EngineTestCase, optimize, reports, risk


class TestMarkdown(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.assessment = risk.assess(self.model)

    def test_summary_carries_the_synthetic_banner(self):
        text = reports.summary_markdown(self.assessment)
        self.assertIn("SYNTHETIC", text.upper())
        self.assertIn("not a measurement of any real organisation", text)

    def test_summary_reports_the_headline_figures(self):
        text = reports.summary_markdown(self.assessment)
        self.assertIn(f"{self.assessment.eal_minor / 100:,.0f}", text)
        self.assertIn(f"{self.assessment.eal_low_minor / 100:,.0f}", text)
        self.assertIn(f"{self.assessment.eal_high_minor / 100:,.0f}", text)

    def test_summary_reports_confidence_and_freshness(self):
        text = reports.summary_markdown(self.assessment)
        self.assertIn(self.assessment.confidence_band, text)
        self.assertIn(str(self.assessment.confidence), text)
        self.assertIn("Data freshness", text)

    def test_summary_includes_the_plan_when_supplied(self):
        plan = optimize.optimise(self.model, budget_minor=250_000_000,
                                 max_actions=5).as_dict()
        text = reports.summary_markdown(self.assessment, plan)
        self.assertIn("Recommended plan", text)
        for code in plan["selected"]:
            self.assertIn(code, text)

    def test_summary_survives_no_scenarios(self):
        empty = risk.assess(self.model, selected_actions=set())
        text = reports.summary_markdown(empty)
        self.assertIn("Expected Annual Loss", text)


class TestCsvExports(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.assessment = risk.assess(self.model)

    def test_scenarios_csv_has_a_row_per_scenario(self):
        rows = list(csv.DictReader(io.StringIO(reports.scenarios_csv(self.assessment))))
        self.assertEqual(len(rows), len(self.assessment.scenarios))
        self.assertIn("scenario_code", rows[0])
        self.assertIn("eal", rows[0])

    def test_scenarios_csv_is_ranked_by_exposure(self):
        rows = list(csv.DictReader(io.StringIO(reports.scenarios_csv(self.assessment))))
        eals = [float(r["eal"]) for r in rows]
        self.assertEqual(eals, sorted(eals, reverse=True))

    def test_loss_components_csv_covers_every_component(self):
        rows = list(csv.DictReader(
            io.StringIO(reports.loss_components_csv(self.assessment))))
        expected = sum(len(s.breakdown) for s in self.assessment.scenarios)
        self.assertEqual(len(rows), expected)
        self.assertIn("component_code", rows[0])

    def test_actions_csv_lists_every_candidate_with_selection_state(self):
        plan = optimize.optimise(self.model, budget_minor=250_000_000,
                                 max_actions=5).as_dict()
        rows = list(csv.DictReader(io.StringIO(reports.actions_csv(plan))))
        self.assertEqual(len(rows), len(plan["candidates"]))
        selected = {r["action_code"] for r in rows if r["selected"] == "yes"}
        self.assertEqual(selected, set(plan["selected"]))

    def test_actions_csv_handles_a_missing_plan(self):
        rows = list(csv.DictReader(io.StringIO(reports.actions_csv(None))))
        self.assertEqual(rows, [])


class TestHtml(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.assessment = risk.assess(self.model)

    def test_html_is_a_complete_document_with_the_banner(self):
        html = reports.html_report(self.assessment)
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn("</html>", html)
        self.assertIn("SYNTHETIC DEMONSTRATION DATA", html)

    def test_html_shows_the_headline_eal_and_confidence(self):
        html = reports.html_report(self.assessment)
        self.assertIn(f"{self.assessment.eal_minor / 100:,.0f}", html)
        self.assertIn(self.assessment.confidence_band, html)

    def test_correlation_adjustment_is_a_sane_percentage(self):
        html = reports.html_report(self.assessment)
        expected = reports._correlation_adjustment(self.assessment)
        self.assertIn(f"{expected * 100:.2f}%", html)
        # A double-scaled bug produced values like "11723%".
        self.assertNotIn("000%", html)

    def test_html_lists_every_scenario(self):
        html = reports.html_report(self.assessment)
        for scenario in self.assessment.scenarios:
            self.assertIn(scenario.scenario_code, html)

    def test_html_escapes_untrusted_text(self):
        self.conn.execute(
            "UPDATE scenarios SET name = '<script>alert(1)</script>' "
            "WHERE scenario_code = 'S1'")
        self.conn.commit()
        html = reports.html_report(risk.assess(self.reload_model()))
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_html_includes_the_plan_and_qa(self):
        plan = optimize.optimise(self.model, budget_minor=250_000_000,
                                 max_actions=5).as_dict()
        html = reports.html_report(self.assessment, plan, [
            {"question": "What is our total loss?", "text": "It is the number above.",
             "source": "template", "grounded": True}])
        self.assertIn("Recommended plan", html)
        self.assertIn("Analyst Q&amp;A", html)
        self.assertIn("What is our total loss?", html)


class TestAiContext(EngineTestCase):
    def test_ai_context_is_valid_json_with_the_headline(self):
        assessment = risk.assess(self.model)
        payload = json.loads(reports.ai_context_json(assessment, self.model))
        self.assertEqual(payload["headline"]["confidence"], assessment.confidence)
        self.assertEqual(len(payload["scenarios"]), len(assessment.scenarios))

    def test_ai_context_includes_the_optimisation_when_given(self):
        assessment = risk.assess(self.model)
        plan = optimize.optimise(self.model, budget_minor=250_000_000,
                                 max_actions=5).as_dict()
        payload = json.loads(
            reports.ai_context_json(assessment, self.model, plan))
        self.assertEqual(payload["optimisation"]["selected"], plan["selected"])


if __name__ == "__main__":
    unittest.main()
