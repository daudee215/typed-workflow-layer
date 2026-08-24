"""Measuring the search instead of asserting things about it.

synthesis.py carries three search restrictions and a workflow cap. Each was
introduced with a comment explaining why it was harmless. This module exists
because a comment is not evidence, and because one of those comments turned out
to be wrong.

Four questions, each answered by running the thing rather than reasoning about
it:

Soundness
    Is every workflow the enumerator returns actually type correct? It is by
    construction, but "by construction" is exactly the claim that stops being
    true after a refactor nobody re-checked. why_rejected is an independent
    checker written for a different purpose, so re-verifying every enumerated
    workflow through it is a real cross-check and not a tautology.

Growth
    How does the space grow with the depth bound, and where does the workflow
    cap start truncating? Without this the default max_depth is a guess, and a
    caller has no way to know whether raising it is free or ruinous.

The price of each restriction
    Turn one off, enumerate again, and look at what appears. Anything that
    appears is something the restriction was removing. The interesting part is
    not how many but which kind: a workflow that reduces to one already in the
    set costs nothing, and a workflow with no equivalent in the set is a real
    loss of expressiveness being taken silently.

Redundancy of the restrictions with each other
    A restriction that removes only things the deduplication already removes is
    doing no work on the result, whatever it saves in search time. That is
    worth knowing before anyone treats it as load bearing.

Standard library only. Run: python3 analysis.py
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import ccd
from ccd import CCDType
from synthesis import (Dataset, Restrictions, Workflow, enumerate_workflows,
                       why_rejected)

# The scenario from demo.py: a noise field over regions, district boundaries,
# and a question whose answer is an intensive quantity borne by the districts.
# Reused rather than invented so the numbers below describe the example the
# rest of the package is documented against.
SOURCES = (
    Dataset("noise", CCDType(ccd.FIELD, ccd.INTERVAL, ccd.REGION_SUPPORT)),
    Dataset("district", CCDType(ccd.OBJECT, ccd.NOMINAL, ccd.REGION_SUPPORT)),
)
TARGET = CCDType(ccd.OBJECT, ccd.INTENSIVE, ccd.REGION_SUPPORT)


def to_chain(workflow: Workflow) -> tuple:
    """A Workflow in the reference form why_rejected accepts.

    Step outputs are named step1, step2 and so on in application order, so
    stepN is the output of index N-1 and becomes $(N-1).
    """
    chain = []
    for step in workflow.steps:
        references = tuple(
            "$%d" % (int(ref[4:]) - 1) if ref.startswith("step") else ref
            for ref in step.inputs
        )
        chain.append((step.transformation, references))
    return tuple(chain)


@dataclass
class SoundnessReport:
    checked: int = 0
    rejected: List[Tuple[str, str]] = field(default_factory=list)
    type_mismatches: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def sound(self) -> bool:
        return not self.rejected and not self.type_mismatches

    def __str__(self) -> str:
        if self.sound:
            return ("  {0} workflow(s) re-verified through why_rejected, "
                    "0 rejected, 0 type mismatches.".format(self.checked))
        lines = ["  {0} workflow(s) checked, {1} UNSOUND.".format(
            self.checked, len(self.rejected) + len(self.type_mismatches))]
        for expression, reason in self.rejected + self.type_mismatches:
            lines.append("    {0}\n      {1}".format(expression, reason))
        return "\n".join(lines)


def soundness(workflows: Sequence[Workflow],
              sources: Sequence[Dataset],
              target: Optional[CCDType] = None) -> SoundnessReport:
    """Re-verify every enumerated workflow through the independent checker.

    Two properties, not one. The chain must type check, and the result type
    must actually satisfy the target that was asked for. A search that returned
    a well typed workflow answering a different question would pass the first
    test and fail the second.
    """
    report = SoundnessReport()
    for workflow in workflows:
        report.checked += 1
        rejection = why_rejected(to_chain(workflow), sources)
        if rejection is not None:
            report.rejected.append(
                (workflow.expression(), rejection.explain().split("\n")[0]))
            continue
        if target is not None and not target.subsumes(workflow.result.type):
            report.type_mismatches.append((
                workflow.expression(),
                "result is {0}, which {1} does not subsume".format(
                    workflow.result.type, target)))
    return report


@dataclass
class GrowthRow:
    depth: int
    candidates: int
    type_checks: int
    admissible: int
    workflows: int
    truncated: bool
    seconds: float


def growth(sources: Sequence[Dataset], target: CCDType,
           depths: Sequence[int] = (1, 2, 3, 4, 5),
           max_workflows: int = 100000) -> List[GrowthRow]:
    """How the search space grows with the depth bound.

    The cap is raised well above the default here on purpose. The point is to
    see the real shape of the space, and a run that truncates measures the cap
    instead.
    """
    rows = []
    for depth in depths:
        started = time.perf_counter()
        result = enumerate_workflows(sources, target, max_depth=depth,
                                     max_workflows=max_workflows)
        elapsed = time.perf_counter() - started
        stats = result.stats
        rows.append(GrowthRow(
            depth=depth, candidates=stats.candidates_examined,
            type_checks=stats.type_checks,
            admissible=stats.admissible_applications,
            workflows=len(result), truncated=stats.truncated,
            seconds=round(elapsed, 3)))
    return rows


def growth_report(rows: Sequence[GrowthRow]) -> str:
    lines = ["  {0:>5}  {1:>12}  {2:>12}  {3:>11}  {4:>9}  {5:>8}".format(
        "depth", "candidates", "type checks", "admissible", "workflows",
        "seconds")]
    previous = None
    for row in rows:
        factor = ""
        if previous and previous.candidates:
            factor = "  x{0:.1f}".format(row.candidates / float(previous.candidates))
        lines.append("  {0:>5}  {1:>12,}  {2:>12,}  {3:>11,}  {4:>9,}  "
                     "{5:>8.3f}{6}{7}".format(
                         row.depth, row.candidates, row.type_checks,
                         row.admissible, row.workflows, row.seconds, factor,
                         "  TRUNCATED" if row.truncated else ""))
        previous = row
    return "\n".join(lines)


@dataclass
class AblationRow:
    """One restriction turned off, and what came back."""

    restriction: str
    workflows: int
    gained: int
    candidates: int
    seconds: float
    reduces_to_kept: int = 0
    type_equivalent: int = 0
    no_equivalent: int = 0
    examples: List[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if self.gained == 0:
            return "removes nothing the deduplication does not already remove"
        if self.no_equivalent:
            return "removes {0} workflow(s) with no equivalent kept".format(
                self.no_equivalent)
        return "removes only workflows equivalent to ones already kept"


def _classify(kept: Sequence[Workflow], gained: Sequence[Workflow]) -> Dict:
    """Sort gained workflows by how much they actually add.

    reduces_to_kept
        The expression is already present. Costs nothing.
    type_equivalent
        A kept workflow reaches the same result type from the same sources.
        The type system cannot tell them apart, so nothing downstream of the
        types can either. Reported separately from redundant because the two
        are not the same claim: these may differ semantically, and saying so
        is the point.
    no_equivalent
        Nothing kept reaches that type from those sources. A real loss.
    """
    kept_expressions = {w.expression() for w in kept}
    kept_signatures = {
        (str(w.result.type), frozenset(s.name for s in w.sources_consumed()))
        for w in kept
    }
    counts = {"reduces_to_kept": 0, "type_equivalent": 0, "no_equivalent": 0}
    examples = []
    for workflow in gained:
        if workflow.expression() in kept_expressions:
            counts["reduces_to_kept"] += 1
            continue
        signature = (str(workflow.result.type),
                     frozenset(s.name for s in workflow.sources_consumed()))
        if signature in kept_signatures:
            counts["type_equivalent"] += 1
            if len(examples) < 3:
                examples.append("type-equivalent: " + workflow.expression())
        else:
            counts["no_equivalent"] += 1
            examples.insert(0, "NO EQUIVALENT: " + workflow.expression())
    return {"counts": counts, "examples": examples[:4]}


def ablation(sources: Sequence[Dataset], target: CCDType, depth: int = 3,
             max_workflows: int = 100000) -> List[AblationRow]:
    """Price each restriction by turning it off on its own."""
    started = time.perf_counter()
    baseline = enumerate_workflows(sources, target, max_depth=depth,
                                   max_workflows=max_workflows)
    base_seconds = time.perf_counter() - started
    rows = [AblationRow("all three on (default)", len(baseline), 0,
                        baseline.stats.candidates_examined,
                        round(base_seconds, 3))]

    baseline_expressions = {w.expression() for w in baseline}
    for name in ("connected", "no_immediate_repeat", "distinct_slots"):
        rules = Restrictions(**{name: False})
        started = time.perf_counter()
        relaxed = enumerate_workflows(sources, target, max_depth=depth,
                                      max_workflows=max_workflows,
                                      restrictions=rules)
        elapsed = time.perf_counter() - started
        gained = [w for w in relaxed
                  if w.expression() not in baseline_expressions]
        classified = _classify(baseline, gained)
        rows.append(AblationRow(
            restriction=name + " off",
            workflows=len(relaxed), gained=len(gained),
            candidates=relaxed.stats.candidates_examined,
            seconds=round(elapsed, 3),
            reduces_to_kept=classified["counts"]["reduces_to_kept"],
            type_equivalent=classified["counts"]["type_equivalent"],
            no_equivalent=classified["counts"]["no_equivalent"],
            examples=classified["examples"]))
    return rows


def ablation_report(rows: Sequence[AblationRow]) -> str:
    lines = ["  {0:<28}{1:>10}{2:>9}{3:>13}{4:>9}".format(
        "configuration", "workflows", "gained", "candidates", "seconds")]
    for row in rows:
        lines.append("  {0:<28}{1:>10,}{2:>9,}{3:>13,}{4:>9.3f}".format(
            row.restriction, row.workflows, row.gained, row.candidates,
            row.seconds))
    lines.append("")
    for row in rows[1:]:
        lines.append("  {0}".format(row.restriction))
        lines.append("      {0}".format(row.verdict))
        if row.gained:
            lines.append("      {0} reduce to a kept workflow, {1} are type "
                         "equivalent, {2} have no equivalent".format(
                             row.reduces_to_kept, row.type_equivalent,
                             row.no_equivalent))
        for example in row.examples:
            lines.append("        " + example)
    return "\n".join(lines)


def truncation_point(sources: Sequence[Dataset], target: CCDType,
                     depth: int = 4,
                     caps: Sequence[int] = (10, 50, 100, 500, 1000)) -> List[Tuple[int, int, bool]]:
    """Where the workflow cap starts silently cutting the answer off.

    The default cap is 500. This says whether that is generous or binding for
    the scenario in front of it, which is a question the old signature could
    not even express.
    """
    rows = []
    for cap in caps:
        result = enumerate_workflows(sources, target, max_depth=depth,
                                     max_workflows=cap)
        rows.append((cap, len(result), result.stats.truncated))
    return rows


@dataclass
class ClosureRound:
    round: int
    reachable: int
    added: int
    new_types: List[str] = field(default_factory=list)


def type_closure(sources: Sequence[Dataset],
                 max_rounds: int = 12) -> Tuple[List[ClosureRound], set]:
    """Which core concept data types are reachable at all, and how fast.

    This is the structure underneath the growth table. Workflows are sequences
    and there are combinatorially many of them; types are a set and there are
    few. Iterating the catalogue over the reachable type set to a fixpoint says
    how much of the type space the sources can actually reach, and after which
    round nothing new appears.

    The gap between the two is the real justification for a depth bound. Once
    the type closure has saturated, a longer workflow is not reaching anything
    new. It is reaching an already reachable type by a longer route, which the
    cost model then has to be trusted to penalise.
    """
    from itertools import product as _product

    from catalogue import CATALOGUE

    reachable = {s.type for s in sources}
    rounds: List[ClosureRound] = []
    for number in range(1, max_rounds + 1):
        produced = set()
        for transformation in CATALOGUE.values():
            for assignment in _product(reachable, repeat=transformation.arity):
                if transformation.accepts(list(assignment)):
                    produced.add(transformation.output_type(list(assignment)))
        added = produced - reachable
        rounds.append(ClosureRound(
            round=number, reachable=len(reachable), added=len(added),
            new_types=sorted(str(t) for t in added)))
        if not added:
            break
        reachable |= added
    return rounds, reachable


def closure_report(rounds: Sequence[ClosureRound], reachable: set) -> str:
    lines = ["  {0:>6}  {1:>10}  {2:>7}  {3}".format(
        "round", "reachable", "new", "types added")]
    for row in rounds:
        shown = ", ".join(row.new_types[:2])
        if len(row.new_types) > 2:
            shown += ", ... (+{0})".format(len(row.new_types) - 2)
        lines.append("  {0:>6}  {1:>10}  {2:>7}  {3}".format(
            row.round, row.reachable, row.added, shown or "none, fixpoint"))
    lines.append("")
    lines.append("  {0} distinct types reachable in total.".format(len(reachable)))
    return "\n".join(lines)


def unreachable_transformations(sources: Sequence[Dataset], target: CCDType,
                                depth: int = 4,
                                max_workflows: int = 200000) -> Tuple[set, set]:
    """Catalogue entries that never appear in any workflow reaching the target.

    Not a defect in the catalogue. It is a fact about this question: an entry
    that cannot contribute to this target is dead weight for this search, and
    saying which are dead is more useful than reporting a catalogue size.
    """
    from catalogue import CATALOGUE

    result = enumerate_workflows(sources, target, max_depth=depth,
                                 max_workflows=max_workflows)
    used = set()
    for workflow in result:
        used |= set(workflow.transformations_used())
    return used, set(CATALOGUE) - used


@dataclass
class RankingReport:
    workflows: int = 0
    distinct_scores: int = 0
    largest_tie: int = 0
    best: float = 0.0
    worst: float = 0.0
    top_expression: str = ""
    tied_at_top: int = 0

    @property
    def discrimination(self) -> float:
        """Distinct scores per workflow. 1.0 means it separates everything."""
        if not self.workflows:
            return 0.0
        return round(self.distinct_scores / float(self.workflows), 3)

    def __str__(self) -> str:
        return "\n".join([
            "  workflows ranked   {0}".format(self.workflows),
            "  distinct scores    {0}".format(self.distinct_scores),
            "  discrimination     {0}  (1.0 would separate every workflow)".format(
                self.discrimination),
            "  largest tie group  {0}".format(self.largest_tie),
            "  score range        {0:.3f} to {1:.3f}".format(self.best, self.worst),
            "  tied at rank 1     {0}".format(self.tied_at_top),
            "  top                {0}".format(self.top_expression),
        ])


def ranking_analysis(workflows: Sequence[Workflow], model=None) -> RankingReport:
    """Does the cost model actually separate these workflows, or mostly tie?

    A ranking over 176 workflows that produces 8 distinct scores is not
    ordering them, it is bucketing them, and reporting a rank-1 out of a tie of
    thirty as though it were a winner would be misleading.
    """
    import ranking as ranking_module

    scored = ranking_module.rank(list(workflows), model)
    report = RankingReport(workflows=len(scored))
    if not scored:
        return report
    totals = [s.total for s in scored]
    counts: Dict[float, int] = {}
    for total in totals:
        counts[total] = counts.get(total, 0) + 1
    report.distinct_scores = len(counts)
    report.largest_tie = max(counts.values())
    report.best, report.worst = min(totals), max(totals)
    report.top_expression = scored[0].expression
    report.tied_at_top = sum(1 for s in scored if s.rank == 1)
    return report


@dataclass
class ComponentSpread:
    """One cost component across the whole workflow set."""

    name: str
    low: float
    high: float
    distinct: int

    @property
    def inert(self) -> bool:
        """Constant across every workflow, so its weight cannot order anything.

        This is a stronger statement than a low sensitivity. A weight on a
        component that never varies is not weakly influential, it is incapable
        of influencing the order at any value, and tuning it to fix a ranking
        is wasted effort. Worth knowing before anyone tries.
        """
        return self.low == self.high


def component_spread(workflows: Sequence[Workflow],
                     model=None) -> List[ComponentSpread]:
    """How much each cost component actually varies over the candidates."""
    from cost import CostModel

    engine = model if model is not None else CostModel()
    # Raw components, not weighted. A weight cannot rescue a component that
    # does not vary, and multiplying by the weight first would hide that.
    names = ("scale_loss", "support_loss", "concept_shift", "length",
             "source", "redundancy")
    values: Dict[str, List[float]] = {name: [] for name in names}
    for workflow in workflows:
        vector = engine.cost(workflow)
        for name in names:
            values[name].append(float(getattr(vector, name)))
    return [ComponentSpread(name=name, low=min(series), high=max(series),
                            distinct=len(set(series)))
            for name, series in sorted(values.items())]


def spread_report(rows: Sequence[ComponentSpread]) -> str:
    lines = ["  {0:<16}{1:>8}{2:>8}{3:>10}  {4}".format(
        "component", "low", "high", "distinct", "")]
    for row in rows:
        lines.append("  {0:<16}{1:>8.2f}{2:>8.2f}{3:>10}  {4}".format(
            row.name, row.low, row.high, row.distinct,
            "INERT, cannot affect the order" if row.inert else ""))
    return "\n".join(lines)


@dataclass
class SensitivityRow:
    weight: str
    top_unchanged: bool
    top_five_unchanged: bool
    tau: Optional[float]
    new_top: str = ""


def weight_sensitivity(workflows: Sequence[Workflow],
                       perturbation: float = 0.25) -> List[SensitivityRow]:
    """Does the ordering survive a change to each weight on its own?

    Any set of weights produces an order, and the weights in cost.py were set
    by judgement rather than fitted to anything. If moving one by a quarter
    reorders the result, the order is a property of the weight and not a
    finding about the workflows.

    Three measures, because the first one alone is misleading here. Rank 1 is a
    two-way tie in this scenario and rank() breaks ties on the expression
    string, so "the top did not change" can mean the tie-break did not change
    rather than that the model did not move. The top-five set is insensitive to
    tie-break order, and Kendall's tau over the full ranking sees movement
    anywhere in it, not just at the front.
    """
    import ranking as ranking_module

    from cost import CostModel

    baseline_model = CostModel()
    baseline = ranking_module.rank(list(workflows), baseline_model)
    baseline_order = [item.expression for item in baseline]
    baseline_top = baseline_order[0]
    baseline_five = set(baseline_order[:5])

    rows = []
    for name, value in baseline_model.weights.as_dict().items():
        for direction, factor in (("up", 1.0 + perturbation),
                                  ("down", 1.0 - perturbation)):
            model = baseline_model.with_weights(**{name: value * factor})
            scored = ranking_module.rank(list(workflows), model)
            order = [item.expression for item in scored]
            result = ranking_module.agreement(scored, baseline_order)
            rows.append(SensitivityRow(
                weight="{0} {1}".format(name, direction),
                top_unchanged=order[0] == baseline_top,
                top_five_unchanged=set(order[:5]) == baseline_five,
                tau=result.get("tau"),
                new_top="" if order[0] == baseline_top else order[0]))
    return rows


def sensitivity_report(rows: Sequence[SensitivityRow]) -> str:
    lines = ["  {0:<22}{1:>8}{2:>12}{3:>9}".format(
        "weight moved", "top 1", "top 5 set", "tau")]
    for row in rows:
        lines.append("  {0:<22}{1:>8}{2:>12}{3:>9}".format(
            row.weight,
            "same" if row.top_unchanged else "moved",
            "same" if row.top_five_unchanged else "moved",
            "{0:.3f}".format(row.tau) if row.tau is not None else "-"))
    return "\n".join(lines)


def main() -> None:
    print("=" * 78)
    print("Search analysis: noise field and districts, target {0}".format(TARGET))
    print("=" * 78)

    print()
    print("1. Soundness of the enumeration")
    print()
    result = enumerate_workflows(SOURCES, TARGET, max_depth=4,
                                 max_workflows=100000)
    print(soundness(result, SOURCES, TARGET))
    print()
    print("  why_rejected is an independent checker written to explain refusals")
    print("  to a person, not to validate the search. Passing every enumerated")
    print("  workflow back through it tests the enumerator against something")
    print("  that does not share its code path.")

    print()
    print("2. How the space grows with the depth bound")
    print()
    print(growth_report(growth(SOURCES, TARGET, depths=(1, 2, 3, 4, 5))))
    print()
    print("  The workflow column is what a caller sees. The candidate column is")
    print("  what it cost to produce, and it is the one that decides whether")
    print("  raising max_depth is affordable.")

    print()
    print("3. What each search restriction actually removes")
    print()
    print(ablation_report(ablation(SOURCES, TARGET, depth=3)))

    print()
    print("4. Where the default workflow cap starts truncating")
    print()
    for cap, returned, truncated in truncation_point(SOURCES, TARGET, depth=4):
        print("  cap {0:>5}   returned {1:>5}   {2}".format(
            cap, returned, "TRUNCATED" if truncated else "complete"))
    print()
    print("  Before .stats.truncated existed, every row above returned a plain")
    print("  list and the truncated ones were indistinguishable from the")
    print("  complete ones. A caller ranking those workflows would have been")
    print("  ranking an arbitrary prefix of the space while believing it had")
    print("  the whole of it.")

    print()
    print("5. The type space underneath the workflow space")
    print()
    rounds, reachable = type_closure(SOURCES)
    print(closure_report(rounds, reachable))
    print()
    print("  This is the shape of the problem. The type closure saturates after")
    print("  a small number of rounds while the workflow count in section 2 is")
    print("  still multiplying, which means almost everything a deeper search")
    print("  finds is another route to a type that was already reachable.")
    print()
    print("  That is the argument for a depth bound, and it is also the argument")
    print("  for the cost model: past the fixpoint the search stops adding")
    print("  capability and starts adding alternatives, so something has to")
    print("  order them.")

    used, dead = unreachable_transformations(SOURCES, TARGET)
    print()
    print("  Of the catalogue, {0} entries appear in some workflow reaching this".format(len(used)))
    print("  target and {0} never do: {1}".format(
        len(dead), ", ".join(sorted(dead)) or "none"))
    print("  Not a fault in the catalogue. A fact about this question.")

    print()
    print("6. Whether the ranking is doing any work")
    print()
    workflows = enumerate_workflows(SOURCES, TARGET, max_depth=4,
                                    max_workflows=100000)
    print(ranking_analysis(workflows))
    print()
    print("  Discrimination is the number the ranking lives or dies on. A model")
    print("  that collapses the space into a handful of scores is bucketing")
    print("  rather than ordering, and a rank of 1 drawn from a large tie is")
    print("  not a winner.")

    print()
    print("7. Whether the winner survives the weights being wrong")
    print()
    spread = component_spread(workflows)
    print(spread_report(spread))
    inert = [row.name for row in spread if row.inert]
    print()
    print("  {0} of {1} components never vary over these {2} workflows: {3}.".format(
        len(inert), len(spread), len(workflows), ", ".join(inert) or "none"))
    print("  Their weights are inert here whatever value they are given, so the")
    print("  order is decided by the {0} that do vary.".format(
        len(spread) - len(inert)))
    print()
    print("  redundancy is inert for a specific reason worth stating: the")
    print("  enumerator can no longer emit a workflow that recomputes anything,")
    print("  so the term is zero on every candidate. It still earns its place,")
    print("  because build_chain accepts chains from outside the search and")
    print("  those are exactly where recomputation arrives.")
    print()

    rows = weight_sensitivity(workflows)
    print(sensitivity_report(rows))
    taus = [r.tau for r in rows if r.tau is not None]
    print()
    print("  top 1 held in {0} of {1}, the top five set in {2}, and Kendall's".format(
        sum(1 for r in rows if r.top_unchanged), len(rows),
        sum(1 for r in rows if r.top_five_unchanged)))
    if taus:
        print("  tau against the unperturbed order ranges {0:.3f} to {1:.3f}.".format(
            min(taus), max(taus)))
    print()
    print("  The first column on its own would have been misleading. Rank 1 is")
    print("  a two-way tie here and rank() breaks ties on the expression, so an")
    print("  unchanged top can mean the tie-break did not move rather than the")
    print("  model did not. Tau sees movement anywhere in the order.")
    print()
    print("  The weights in cost.py were set by judgement, not fitted to")
    print("  anything, and that is stated where they are defined. This is the")
    print("  test of whether that matters.")


if __name__ == "__main__":
    main()
