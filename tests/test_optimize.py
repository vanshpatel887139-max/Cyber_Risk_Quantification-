"""Optimiser tests: feasibility, budget, dependencies, ROSI, frontier."""

from __future__ import annotations

import unittest

from helpers import EngineTestCase, optimize, risk

from app import config


def candidates_for(model) -> dict:
    """Mirror of the candidate construction inside optimize.optimise()."""
    return {
        code: optimize.Candidate(
            action_code=code, name=a.name, category=a.category, cost=a.cost,
            lead_time_days=a.lead_time_days, capacity_group=a.capacity_group,
            requires_actions=a.requires_actions, effect_type=a.effect_type,
            effect=a.effect, description=a.description,
        )
        for code, a in model["actions"].items()
    }


class TestFeasibility(EngineTestCase):
    def test_optimal_plan_respects_budget_and_action_cap(self):
        budget = 250_000_000
        result = optimize.optimise(self.model, budget_minor=budget, max_actions=5)
        self.assertLessEqual(result.cost_minor, budget)
        self.assertLessEqual(len(result.selected), 5)
        self.assertTrue(result.selected)

    def test_zero_budget_selects_nothing(self):
        result = optimize.optimise(self.model, budget_minor=0, max_actions=5)
        self.assertEqual(result.selected, [])
        self.assertEqual(result.cost_minor, 0)
        self.assertEqual(result.reduction_minor, 0)
        self.assertIsNone(result.rosi)

    def test_plan_never_increases_risk(self):
        baseline = risk.assess(self.model).eal_minor
        for budget in (0, 5_000_000, 100_000_000, 500_000_000):
            with self.subTest(budget=budget):
                result = optimize.optimise(self.model, budget_minor=budget,
                                           max_actions=6)
                self.assertLessEqual(result.plan_eal_minor, baseline)
                self.assertGreaterEqual(result.reduction_minor, 0)

    def test_dependencies_are_honoured(self):
        candidates = candidates_for(self.model)
        result = optimize.optimise(self.model, budget_minor=500_000_000,
                                   max_actions=8)
        for code in result.selected:
            for required in candidates[code].requires_actions:
                self.assertIn(required, result.selected,
                              f"{code} selected without prerequisite {required}")

    def test_preselected_actions_are_kept(self):
        candidates = candidates_for(self.model)
        cheapest = min(candidates.values(), key=lambda c: c.cost)
        result = optimize.optimise(self.model, budget_minor=cheapest.cost,
                                   max_actions=5, preselected={cheapest.action_code})
        self.assertIn(cheapest.action_code, result.selected)
        self.assertGreaterEqual(result.cost_minor, cheapest.cost)

    def test_unknown_preselected_action_is_rejected(self):
        with self.assertRaises(risk.RiskError):
            optimize.optimise(self.model, budget_minor=100_000_000, max_actions=5,
                              preselected={"ACT-DOES-NOT-EXIST"})

    def test_over_budget_preselection_is_rejected(self):
        candidates = candidates_for(self.model)
        prereq_dependent = next((c for c in candidates.values() if c.requires_actions), None)
        if prereq_dependent is None:
            self.skipTest("no dependent action in the demo catalogue")
        with self.assertRaises(risk.RiskError):
            optimize.optimise(self.model, budget_minor=0, max_actions=5,
                              preselected={prereq_dependent.action_code})

    def test_check_feasibility_reports_issues_for_a_bad_subset(self):
        candidates = candidates_for(self.model)
        codes = set(candidates)
        issues = optimize.check_feasibility(codes, candidates, 0, 1)
        codes_reported = {i.code for i in issues}
        self.assertIn("OVER_BUDGET", codes_reported)
        self.assertIn("OVER_CAPACITY", codes_reported)

    def test_exact_search_reports_optimality(self):
        result = optimize.optimise(self.model, budget_minor=120_000_000,
                                   max_actions=4, exact=True)
        self.assertTrue(result.optimal)
        self.assertEqual(result.method, "exact")

    def test_heuristic_search_is_flagged_as_best_effort(self):
        result = optimize.optimise(self.model, budget_minor=120_000_000,
                                   max_actions=4, exact=False)
        self.assertFalse(result.optimal)
        self.assertEqual(result.method, "heuristic")
        self.assertLessEqual(result.cost_minor, 120_000_000)

    def test_exact_is_at_least_as_good_as_heuristic(self):
        exact = optimize.optimise(self.model, budget_minor=300_000_000,
                                  max_actions=6, exact=True)
        heuristic = optimize.optimise(self.model, budget_minor=300_000_000,
                                      max_actions=6, exact=False)
        self.assertLessEqual(exact.plan_eal_minor, heuristic.plan_eal_minor)

    def test_optimise_returns_serialisable_dict(self):
        payload = optimize.optimise(self.model, budget_minor=250_000_000,
                                    max_actions=5).as_dict()
        for key in ("selected", "cost_minor", "baseline_eal_minor",
                    "plan_eal_minor", "reduction_pct", "rosi", "method",
                    "optimal", "candidates", "selected_detail"):
            self.assertIn(key, payload)
        self.assertEqual(payload["selected_detail"][0]["marginal_reduction_minor"] > 0, True)


class TestMarginals(EngineTestCase):
    def _reduction(self, subset):
        """The contract optimize.optimise() uses: reduction vs baseline."""
        return risk.assess(self.model).eal_minor - risk.assess(self.model, subset).eal_minor

    def test_marginal_reductions_are_positive_for_selected_actions(self):
        candidates = candidates_for(self.model)
        result = optimize.optimise(self.model, budget_minor=250_000_000,
                                   max_actions=5)
        rows = optimize.marginal_contributions(result.selected, candidates,
                                                self._reduction)
        self.assertEqual({r["action_code"] for r in rows}, set(result.selected))
        for row in rows:
            self.assertGreater(row["marginal_reduction_minor"], 0,
                               f"{row['action_code']} has a non-positive marginal")
            # The optimiser maximises risk reduction, not ROSI, so a selected
            # action can still have a negative marginal ROSI. The number must
            # at least be arithmetically consistent.
            expected = (row["marginal_reduction_minor"] - row["cost_minor"]) \
                / row["cost_minor"]
            self.assertAlmostEqual(row["marginal_rosi"], expected, places=4)
            self.assertGreaterEqual(row["standalone_reduction_minor"],
                                    row["marginal_reduction_minor"])

    def test_selected_detail_marginals_match_recomputed_values(self):
        candidates = candidates_for(self.model)
        payload = optimize.optimise(self.model, budget_minor=250_000_000,
                                    max_actions=4).as_dict()
        computed = {r["action_code"]: r["marginal_reduction_minor"] for r in
                    optimize.marginal_contributions(payload["selected"], candidates,
                                                    self._reduction)}
        self.assertEqual({d["action_code"] for d in payload["selected_detail"]},
                         set(payload["selected"]))
        for detail in payload["selected_detail"]:
            self.assertAlmostEqual(
                detail["marginal_reduction_minor"],
                computed[detail["action_code"]], delta=1)

    def test_removing_a_selected_action_never_helps(self):
        candidates = candidates_for(self.model)
        result = optimize.optimise(self.model, budget_minor=250_000_000,
                                   max_actions=5)
        full = self._reduction(set(result.selected))
        for code in result.selected:
            with self.subTest(action=code):
                self.assertLess(self._reduction(set(result.selected) - {code}), full)

    def test_rosi_is_reduction_minus_cost_over_cost(self):
        result = optimize.optimise(self.model, budget_minor=250_000_000,
                                   max_actions=5)
        self.assertGreater(result.cost_minor, 0)
        self.assertAlmostEqual(
            result.rosi,
            (result.reduction_minor - result.cost_minor) / result.cost_minor,
            places=6)

    def test_rejection_reasons_explain_unselected_actions(self):
        candidates = candidates_for(self.model)
        result = optimize.optimise(self.model, budget_minor=10_000_000,
                                   max_actions=2)
        rejected = optimize.rejection_reasons(result.selected, candidates,
                                              10_000_000, 2)
        self.assertTrue(rejected)


class TestFrontier(EngineTestCase):
    def test_frontier_is_monotonic_in_budget_and_within_budget(self):
        points = optimize.frontier(self.model, budget_max=400_000_000,
                                   max_actions=6, steps=5)
        self.assertGreaterEqual(len(points), 3)
        eals = [p["plan_eal_minor"] for p in points]
        self.assertEqual(eals, sorted(eals, reverse=True))
        for point in points:
            self.assertLessEqual(point["cost_minor"], point["budget_minor"])

    def test_frontier_first_point_is_the_untreated_baseline(self):
        points = optimize.frontier(self.model, budget_max=100_000_000,
                                   max_actions=4, steps=4)
        self.assertEqual(points[0]["selected"], [])
        self.assertEqual(points[0]["cost_minor"], 0)

    def test_frontier_last_point_does_not_exceed_budget_max(self):
        points = optimize.frontier(self.model, budget_max=250_000_000,
                                   max_actions=5, steps=6)
        self.assertLessEqual(points[-1]["budget_minor"], 250_000_000)


class TestMoneyConsistency(EngineTestCase):
    def test_candidate_costs_are_positive_integers(self):
        for candidate in candidates_for(self.model).values():
            self.assertIsInstance(candidate.cost, int)
            self.assertGreater(candidate.cost, 0)

    def test_exact_search_limit_is_configured(self):
        self.assertGreaterEqual(config.EXACT_SEARCH_MAX_ACTIONS, 1)


if __name__ == "__main__":
    unittest.main()
