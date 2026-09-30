"""Assistant tests: grounding, refusals, and template answers."""

from __future__ import annotations

import unittest

from helpers import EngineTestCase, ai, optimize, risk


class TestGrounding(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.assessment = risk.assess(self.model)
        self.context = ai.build_context(self.assessment, self.model)

    def test_numbers_taken_from_context_are_allowed(self):
        grounded, notes = ai.check_grounding(
            f"Total expected annual loss is {self.assessment.eal_minor / 100:,.0f} rupees.",
            self.context)
        self.assertTrue(grounded, notes)

    def test_invented_number_is_rejected(self):
        grounded, notes = ai.check_grounding(
            "Total expected annual loss is 987654321 rupees.", self.context)
        self.assertFalse(grounded)
        self.assertTrue(notes)

    def test_invented_percentage_is_rejected(self):
        grounded, notes = ai.check_grounding(
            "Confidence on this assessment is 97%.", self.context)
        self.assertFalse(grounded)
        self.assertTrue(notes)

    def test_prose_without_numbers_is_grounded(self):
        grounded, notes = ai.check_grounding(
            "The scenario with the largest exposure sits in the payments business unit.",
            self.context)
        self.assertTrue(grounded, notes)

    def test_allowed_numbers_include_scenario_values(self):
        numbers = ai.allowed_numbers(self.context)
        for scenario in self.assessment.scenarios:
            self.assertIn(round(scenario.eal_minor / 100, 2), numbers)
            self.assertIn(round(scenario.p_residual * 100, 3), numbers)
            self.assertIn(round(scenario.sle_minor / 100, 2), numbers)

    def test_every_grounded_number_in_a_context_derived_sentence_passes(self):
        top = max(self.assessment.scenarios, key=lambda s: s.eal_minor)
        text = (f"The largest scenario is {top.scenario_code} on {top.asset_id} with a "
                f"single event loss of {top.sle_minor / 100:,.0f} and a residual "
                f"probability of {top.p_residual * 100:.2f} percent.")
        grounded, notes = ai.check_grounding(text, self.context)
        self.assertTrue(grounded, notes)


class TestUnsupportedTopics(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.assessment = risk.assess(self.model)

    def test_out_of_scope_question_is_refused(self):
        answer = ai.ask("What will the stock price of Acme Corp be next year?",
                        self.assessment, self.model)
        self.assertTrue(answer.refused, answer.text)
        self.assertIn("cannot", answer.text.lower())

    def test_compliance_certificate_request_is_refused(self):
        answer = ai.ask("Can you issue me an ISO 27001 compliance certificate?",
                        self.assessment, self.model)
        self.assertTrue(answer.refused)

    def test_in_scope_question_is_answered(self):
        answer = ai.ask("What is our total expected annual loss?",
                        self.assessment, self.model)
        self.assertFalse(answer.refused)
        self.assertTrue(answer.text)


class TestTemplateAnswers(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.assessment = risk.assess(self.model)

    def test_total_loss_answer_quotes_the_assessment(self):
        answer = ai.ask("What is our total expected annual loss?",
                        self.assessment, self.model)
        self.assertIn(f"{self.assessment.eal_minor / 100:,.0f}", answer.text)

    def test_top_scenario_answer_names_the_largest_scenario(self):
        answer = ai.ask("Which scenario carries the most risk?",
                        self.assessment, self.model)
        top = max(self.assessment.scenarios, key=lambda s: s.eal_minor)
        self.assertIn(top.scenario_code, answer.text)
        self.assertIn(top.name, answer.text)

    def test_asset_answer_names_the_largest_asset(self):
        answer = ai.ask("Which asset should we worry about most?",
                        self.assessment, self.model)
        worst_asset, worst_eal = max(self.assessment.by_asset.items(),
                                     key=lambda kv: kv[1])
        self.assertIn(worst_asset, answer.text)
        self.assertIn(f"{worst_eal / 100:,.0f}", answer.text)

    def test_confidence_answer_reports_the_engine_score(self):
        answer = ai.ask("How confident are you in this data?",
                        self.assessment, self.model)
        self.assertIn(str(self.assessment.confidence), answer.text)
        self.assertIn(self.assessment.confidence_band, answer.text)

    def test_answers_are_grounded(self):
        for question in ("What is our total expected annual loss?",
                         "Which scenario carries the most risk?",
                         "How confident are you in this data?"):
            with self.subTest(question=question):
                answer = ai.ask(question, self.assessment, self.model)
                self.assertTrue(answer.grounded, f"{question}: {answer.warnings}")


class TestPlanAwareAnswers(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.assessment = risk.assess(self.model)
        self.plan = optimize.optimise(
            self.model, budget_minor=250_000_000, max_actions=5).as_dict()

    def test_optimizer_question_uses_the_supplied_plan(self):
        answer = ai.ask("What should we do first with our budget?",
                        self.assessment, self.model, optimiser_result=self.plan)
        self.assertFalse(answer.refused)
        self.assertTrue(answer.grounded, answer.warnings)
        for code in self.plan["selected"]:
            self.assertIn(code, answer.text)

    def test_plan_aware_context_includes_the_plan(self):
        context = ai.build_context(self.assessment, self.model, self.plan)
        self.assertIn("optimisation", context)
        self.assertEqual(context["optimisation"]["selected"], self.plan["selected"])
        self.assertEqual(context["optimisation"]["budget_minor"],
                         self.plan["budget_minor"])


class TestAudit(EngineTestCase):
    def test_asking_records_an_audit_row(self):
        assessment = risk.assess(self.model)
        before = self.conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        ai.ask("What is our total expected annual loss?", assessment, self.model,
               conn=self.conn)
        after = self.conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        self.assertEqual(after, before + 1)

    def test_refusal_is_also_audited(self):
        assessment = risk.assess(self.model)
        before = self.conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        ai.ask("What is the weather in Mumbai?", assessment, self.model,
               conn=self.conn)
        after = self.conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        self.assertEqual(after, before + 1)


if __name__ == "__main__":
    unittest.main()
