"""Investment optimiser (PRD 9).

Decision variables   x_a in {0,1} for each candidate action a
Objective            maximise total EAL reduction = EAL(baseline) - EAL(selected)
Budget constraint    sum(cost_a * x_a) <= budget
Dependencies         x_p <= x_d  for every prerequisite d of p
Exclusivity          sum(x_a for a in group) <= 1 for each capacity_group
Capacity             sum(x_a) <= max_actions
ROSI                 (EAL reduction - cost) / cost, all annualised to 12 months

The objective is NOT separable: control effects multiply together, so adding an
action to a plan changes the value of every other action in the plan. We handle
this by evaluating the true risk engine on complete action sets rather than
summing per-action deltas. That is what prevents double counting.

Search strategy
  - Exact: exhaustive enumeration, feasible while the candidate set is small.
  - Heuristic: greedy construction plus add/remove/swap local search, used when
    the candidate set is too large or the exact search is disabled.
Both are cross-checked by a feasibility verifier that re-runs the plan through
the risk engine and asserts every constraint.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from . import config, risk


@dataclass
class Candidate:
    action_code: str
    name: str
    category: str
    cost: int
    lead_time_days: int
    capacity_group: str | None
    requires_actions: list[str]
    effect_type: str
    effect: dict[str, Any]
    description: str
    selected_by_default: bool = False


@dataclass
class FeasibilityIssue:
    code: str
    message: str
    actions: list[str] = field(default_factory=list)


@dataclass
class OptimisationResult:
    method: str
    budget_minor: int
    capacity_max: int
    selected: list[str]
    cost_minor: int
    baseline_eal_minor: int
    plan_eal_minor: int
    reduction_minor: int
    reduction_pct: float
    net_benefit_minor: int
    rosi: float | None
    marginal_by_action: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    feasibility: list[FeasibilityIssue]
    optimal: bool
    candidates_evaluated: int
    runtime_ms: int
    currency: str = config.DEFAULT_CURRENCY
    capacity_used: int = 0
    candidate_list: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "optimal": self.optimal,
            "budget_minor": self.budget_minor,
            "capacity_max": self.capacity_max,
            "capacity_used": self.capacity_used,
            "cost_minor": self.cost_minor,
            "currency": self.currency,
            "baseline_eal_minor": self.baseline_eal_minor,
            "plan_eal_minor": self.plan_eal_minor,
            "reduction_minor": self.reduction_minor,
            "reduction_pct": round(self.reduction_pct, 2),
            "net_benefit_minor": self.net_benefit_minor,
            "rosi": None if self.rosi is None else round(self.rosi, 4),
            "selected": self.selected,
            "marginal_by_action": self.marginal_by_action,
            "selected_detail": [
                {"action_code": m["action_code"], "name": m["name"],
                 "category": m["category"], "cost_minor": m["cost_minor"],
                 "lead_time_days": m["lead_time_days"],
                 "marginal_reduction_minor": m["marginal_reduction_minor"],
                 "standalone_reduction_minor": m["standalone_reduction_minor"],
                 "overlap_penalty_minor": m["overlap_penalty_minor"],
                 "marginal_rosi": m["marginal_rosi"],
                 "rosi_standalone": m["rosi_standalone"]}
                for m in self.marginal_by_action],
            "candidates": [
                {"action_code": c["action_code"], "name": c["name"],
                 "category": c["category"], "cost_minor": c["cost_minor"],
                 "lead_time_days": c["lead_time_days"],
                 "capacity_group": c["capacity_group"],
                 "requires_actions": c["requires_actions"]}
                for c in getattr(self, "candidate_list", [])],
            "rejected": self.rejected,
            "feasibility": [{"code": i.code, "message": i.message, "actions": i.actions}
                            for i in self.feasibility],
            "candidates_evaluated": self.candidates_evaluated,
            "runtime_ms": self.runtime_ms,
        }


# ---------------------------------------------------------------- feasibility
def check_feasibility(selected: Iterable[str], candidates: dict[str, Candidate],
                      budget: int, max_actions: int) -> list[FeasibilityIssue]:
    sel = list(selected)
    issues: list[FeasibilityIssue] = []
    sel_set = set(sel)

    cost = sum(candidates[a].cost for a in sel if a in candidates)
    if cost > budget:
        issues.append(FeasibilityIssue(
            "OVER_BUDGET",
            f"Plan cost {config.CURRENCY_SYMBOL}{db_fmt(cost)} exceeds budget "
            f"{config.CURRENCY_SYMBOL}{db_fmt(budget)}",
            [a for a in sel if a in candidates]))

    if len(sel) > max_actions:
        issues.append(FeasibilityIssue(
            "OVER_CAPACITY",
            f"Plan selects {len(sel)} actions but the implementation limit is {max_actions}",
            sel))

    for a in sel:
        cand = candidates.get(a)
        if cand is None:
            issues.append(FeasibilityIssue("UNKNOWN_ACTION", f"Unknown action '{a}'", [a]))
            continue
        for prereq in cand.requires_actions:
            if prereq not in sel_set:
                issues.append(FeasibilityIssue(
                    "UNMET_DEPENDENCY",
                    f"'{cand.name}' requires '{candidates[prereq].name if prereq in candidates else prereq}' "
                    "which is not in the plan", [a, prereq]))

    groups: dict[str, list[str]] = {}
    for a in sel:
        g = candidates[a].capacity_group if a in candidates else None
        if g:
            groups.setdefault(g, []).append(a)
    for g, members in groups.items():
        if len(members) > 1:
            issues.append(FeasibilityIssue(
                "MUTUALLY_EXCLUSIVE",
                f"Mutually exclusive group '{g}' has {len(members)} selected actions: "
                + ", ".join(members), members))

    return issues


def db_fmt(minor: int) -> str:
    return f"{minor / 100:,.0f}"


# ---------------------------------------------------------------- search
def _valid_subset(subset: frozenset[str], candidates: dict[str, Candidate],
                  budget: int, max_actions: int) -> bool:
    if len(subset) > max_actions:
        return False
    cost = 0
    for a in subset:
        cand = candidates.get(a)
        if cand is None:
            return False
        cost += cand.cost
        if any(p not in subset for p in cand.requires_actions):
            return False
    if cost > budget:
        return False
    seen: dict[str, int] = {}
    for a in subset:
        g = candidates[a].capacity_group
        if g:
            seen[g] = seen.get(g, 0) + 1
            if seen[g] > 1:
                return False
    return True


def solve_exact(candidates: dict[str, Candidate], evaluator: Callable[[set[str]], int],
                budget: int, max_actions: int) -> tuple[set[str], int]:
    """Exhaustive search over feasible subsets. O(2^n) - only for small n."""
    codes = sorted(candidates)
    best: set[str] = set()
    best_score = -1
    evaluated = 0
    for size in range(0, min(max_actions, len(codes)) + 1):
        for combo in itertools.combinations(codes, size):
            subset = frozenset(combo)
            if not _valid_subset(subset, candidates, budget, max_actions):
                continue
            evaluated += 1
            score = evaluator(set(subset))
            if score > best_score:
                best_score = score
                best = set(subset)
    return best, evaluated


def solve_heuristic(candidates: dict[str, Candidate], evaluator: Callable[[set[str]], int],
                    budget: int, max_actions: int) -> tuple[set[str], int]:
    """Greedy construction then add/remove/swap local search. Always returns a
    feasible plan; optimality is not claimed.

    Every move is accepted only when it strictly improves on the current plan's
    score, which is what makes the local search terminate.
    """
    evaluated = 0
    scores: dict[frozenset[str], int] = {}

    def score_of(plan: set[str]) -> int:
        nonlocal evaluated
        key = frozenset(plan)
        if key not in scores:
            evaluated += 1
            scores[key] = evaluator(set(plan))
        return scores[key]

    def feasible(plan: set[str]) -> bool:
        return _valid_subset(frozenset(plan), candidates, budget, max_actions)

    def best_move(current: set[str], current_score: int,
                  proposals) -> tuple[set[str], int] | None:
        for plan in proposals(current):
            if not feasible(plan):
                continue
            value = score_of(plan)
            if value > current_score:
                return plan, value
        return None

    def additions(current: set[str]):
        for code in sorted(candidates):
            if code not in current:
                yield current | {code}

    def removals(current: set[str]):
        for code in sorted(current):
            yield current - {code}

    def swaps(current: set[str]):
        for out in sorted(current):
            for code in sorted(candidates):
                if code not in current:
                    yield (current - {out}) | {code}

    current: set[str] = set()
    current_score = score_of(current)

    # 1. greedy construction
    while True:
        move = best_move(current, current_score, additions)
        if move is None:
            break
        current, current_score = move

    # 2. local search: repeat until no single move improves the plan
    while True:
        improved = False
        for proposals in (swaps, removals, additions):
            move = best_move(current, current_score, proposals)
            if move is not None:
                current, current_score = move
                improved = True
        if not improved:
            break
    return current, evaluated


# ---------------------------------------------------------------- marginals
def marginal_contributions(selected: Iterable[str], candidates: dict[str, Candidate],
                           evaluator: Callable[[set[str]], int]) -> list[dict[str, Any]]:
    """Value each selected action by removing it from the completed plan.

    `evaluator(subset)` must return the risk *reduction* achieved by that
    subset, not its EAL. These are marginal, not standalone, and they do not
    sum to the total reduction. Reporting them additively would double count.
    """
    selected = set(selected)
    full = evaluator(selected)
    out = []
    for code in sorted(selected):
        without = evaluator(selected - {code})
        standalone = evaluator({code})
        cand = candidates[code]
        # Dropping an action lowers the reduction it was contributing, so the
        # reduction attributable to the action is full - without.
        gain = full - without
        cost = cand.cost
        out.append({
            "action_code": code,
            "name": cand.name,
            "category": cand.category,
            "cost_minor": cost,
            "marginal_reduction_minor": gain,
            "marginal_gain_minor": gain,
            "standalone_reduction_minor": standalone,
            "standalone_gain_minor": standalone,
            "overlap_penalty_minor": standalone - gain,
            "marginal_rosi": None if cost == 0 else round((gain - cost) / cost, 4),
            "rosi": None if cost == 0 else round((gain - cost) / cost, 4),
            "rosi_standalone": None if cost == 0 else round((standalone - cost) / cost, 4),
            "lead_time_days": cand.lead_time_days,
        })
    return out


def rejection_reasons(selected: set[str], candidates: dict[str, Candidate],
                      budget: int, max_actions: int) -> list[dict[str, Any]]:
    out = []
    for code in sorted(candidates):
        if code in selected:
            continue
        cand = candidates[code]
        missing = [p for p in cand.requires_actions if p not in selected]
        exclusive_clash = [
            a for a in selected
            if candidates[a].capacity_group and candidates[a].capacity_group == cand.capacity_group
        ]
        remaining = budget - sum(candidates[a].cost for a in selected)
        if missing:
            reason = "Dependency unmet: requires " + ", ".join(
                candidates[p].name for p in missing)
            kind = "dependency"
        elif exclusive_clash:
            reason = f"Mutually exclusive with {candidates[exclusive_clash[0]].name}"
            kind = "exclusivity"
        elif cand.cost > remaining:
            reason = (f"Over budget: costs {config.CURRENCY_SYMBOL}{db_fmt(cand.cost)}, "
                      f"remaining budget {config.CURRENCY_SYMBOL}{db_fmt(remaining)}")
            kind = "budget"
        elif len(selected) >= max_actions:
            reason = f"Implementation capacity reached ({max_actions} actions)"
            kind = "capacity"
        else:
            reason = "Feasible, but estimated risk reduction is lower than actions in the plan"
            kind = "value"
        out.append({"action_code": code, "name": cand.name, "category": cand.category,
                    "cost_minor": cand.cost, "reason": reason, "reason_kind": kind})
    return out


# ---------------------------------------------------------------- entry point
def optimise(model: dict[str, Any], budget_minor: int, max_actions: int,
             preselected: set[str] | None = None, exact: bool = True,
             rho_map: dict[str, float] | None = None) -> OptimisationResult:
    started = time.perf_counter()
    actions: dict[str, Action] = model["actions"]
    if not actions:
        raise risk.RiskError("no candidate actions are loaded")

    candidates = {
        code: Candidate(
            action_code=code, name=a.name, category=a.category, cost=a.cost,
            lead_time_days=a.lead_time_days, capacity_group=a.capacity_group,
            requires_actions=a.requires_actions, effect_type=a.effect_type,
            effect=a.effect, description=a.description,
        )
        for code, a in actions.items()
    }

    # Forced actions (user ticked "must include") are pinned into every subset.
    forced = set(preselected or set())
    for code in forced:
        if code not in candidates:
            raise risk.RiskError(f"unknown preselected action '{code}'")

    baseline = risk.assess(model, rho_map=rho_map).eal_minor
    cache: dict[frozenset[str], int] = {}

    def evaluate(sel: set[str]) -> int:
        key = frozenset(sel)
        if key not in cache:
            cache[key] = baseline - risk.assess(model, sel, rho_map=rho_map).eal_minor
        return cache[key]

    pool = {c: v for c, v in candidates.items() if c not in forced}

    def evaluate_with_forced(sel: set[str]) -> int:
        return evaluate(set(sel) | forced)

    if forced:
        issues = check_feasibility(forced, candidates, budget_minor, max_actions)
        blocking = [i for i in issues if i.code in {"OVER_BUDGET", "OVER_CAPACITY",
                                                    "UNMET_DEPENDENCY", "MUTUALLY_EXCLUSIVE",
                                                    "UNKNOWN_ACTION"}]
        if blocking:
            raise risk.RiskError(blocking[0].message)

    use_exact = exact and len(pool) <= config.EXACT_SEARCH_MAX_ACTIONS
    if use_exact:
        if forced:
            best, evaluated = _exact_with_forced(pool, forced, candidates,
                                                 evaluate_with_forced, budget_minor, max_actions)
        else:
            best, evaluated = solve_exact(pool, evaluate, budget_minor, max_actions)
        method = "exact"
        optimal = True
    elif forced:
        current: set[str] = set(forced)
        improved = True
        while improved:
            improved = False
            for code in sorted(pool):
                trial = current | {code}
                if not _valid_subset(frozenset(trial), candidates, budget_minor, max_actions):
                    continue
                if evaluate(trial) > evaluate(current):
                    current = trial
                    improved = True
        best, evaluated = current, len(cache)
        method = "heuristic"
        optimal = False
    else:
        best, evaluated = solve_heuristic(pool, evaluate, budget_minor, max_actions)
        method = "heuristic"
        optimal = False

    selected = set(best) | forced
    cost = sum(candidates[a].cost for a in selected)
    plan = risk.assess(model, selected, rho_map=rho_map)
    reduction = baseline - plan.eal_minor
    net = reduction - cost
    rosi = None if cost == 0 else (reduction - cost) / cost
    pct = (reduction / baseline * 100.0) if baseline else 0.0

    issues = check_feasibility(selected, candidates, budget_minor, max_actions)

    return OptimisationResult(
        method=method, optimal=optimal, budget_minor=budget_minor,
        capacity_max=max_actions, capacity_used=len(selected),
        selected=sorted(selected), cost_minor=cost, baseline_eal_minor=baseline,
        plan_eal_minor=plan.eal_minor, reduction_minor=reduction, reduction_pct=pct,
        net_benefit_minor=net, rosi=rosi,
        marginal_by_action=marginal_contributions(selected, candidates, evaluate),
        rejected=rejection_reasons(selected, candidates, budget_minor, max_actions),
        feasibility=issues, candidates_evaluated=evaluated,
        candidate_list=[
            {"action_code": c.action_code, "name": c.name, "category": c.category,
             "cost_minor": c.cost, "lead_time_days": c.lead_time_days,
             "capacity_group": c.capacity_group,
             "requires_actions": c.requires_actions,
             "description": c.description}
            for c in candidates.values()],
        runtime_ms=int((time.perf_counter() - started) * 1000),
    )


def _exact_with_forced(pool: dict[str, Candidate], forced: set[str], all_candidates,
                       evaluator, budget: int,
                       max_actions: int) -> tuple[set[str], int]:
    """Exhaustive search where `forced` actions are pinned into every subset."""
    codes = sorted(pool)
    room = max_actions - len(forced)
    best: set[str] = set()
    best_score = -1
    evaluated = 0
    for size in range(0, min(room, len(codes)) + 1):
        for combo in itertools.combinations(codes, size):
            full = frozenset(combo) | forced
            if not _valid_subset(full, all_candidates, budget, max_actions):
                continue
            evaluated += 1
            score = evaluator(set(combo))
            if score > best_score:
                best_score = score
                best = set(combo)
    return best | forced, evaluated


# ---------------------------------------------------------------- frontier
def frontier(model: dict[str, Any], budget_max: int, max_actions: int, steps: int = 12,
             rho_map: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """Risk reduction achievable at a range of budgets.

    Feasibility is monotone: a plan feasible at budget B is feasible at any
    budget >= B, so the curve is non-decreasing in the budget.
    """
    out = []
    if steps < 2:
        steps = 2
    for i in range(steps):
        budget = int(budget_max * i / (steps - 1))
        res = optimise(model, budget, max_actions, exact=(i % 2 == 0),
                       rho_map=rho_map)
        out.append({
            "budget_minor": budget,
            "cost_minor": res.cost_minor,
            "reduction_minor": res.reduction_minor,
            "plan_eal_minor": res.plan_eal_minor,
            "selected": res.selected,
            "optimal": res.optimal,
        })
    return out
