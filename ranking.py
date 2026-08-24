"""Ranking, explanation, and a way to find out whether the ranking is any good.

cost.py measures workflows. This module orders them, says why one beat another,
and measures the ordering against a human preference ordering so the cost model
can be shown to be wrong.

That last part matters more than the ranking. Any set of weights produces an
order. The question a reviewer should ask is whether the order agrees with
what an analyst would choose, and nothing in a cost model answers that by
itself. agreement() answers it with Kendall's tau over a reference ordering,
and disagreements() names the specific pairs where the model and the human part
company, which is the only useful output when tau comes back low.

Ties are kept as ties. Two workflows with identical cost vectors are not put in
an arbitrary order and then reported as if the order meant something; rank()
gives them the same rank and the caller can see that it did.
"""

from dataclasses import dataclass
from itertools import combinations
from typing import Optional, Sequence

from cost import CostModel, CostVector


@dataclass(frozen=True)
class Scored:
    """One workflow with its cost, its rank, and a stable identity."""

    workflow: object
    cost: CostVector
    total: float
    rank: int

    @property
    def expression(self) -> str:
        return self.workflow.expression()

    def __str__(self) -> str:
        return "{0:>3}. {1:8.3f}  {2}".format(self.rank, self.total, self.expression)


def rank(workflows: Sequence, model: Optional[CostModel] = None) -> list:
    """Workflows cheapest first, with equal costs sharing a rank.

    Sorting is by total cost and then by expression, so a run is reproducible.
    Rank numbers are competition style: two workflows tied at rank 1 are
    followed by rank 3, because reporting the next one as rank 2 would hide
    that a tie happened.
    """
    engine = model if model is not None else CostModel()
    scored = []
    for workflow in workflows:
        vector = engine.cost(workflow)
        scored.append((vector.total(engine.weights), workflow.expression(), workflow, vector))
    scored.sort(key=lambda row: (row[0], row[1]))

    out = []
    previous_total = None
    current_rank = 0
    for position, (total, _expression, workflow, vector) in enumerate(scored, start=1):
        if previous_total is None or total > previous_total:
            current_rank = position
            previous_total = total
        out.append(Scored(workflow=workflow, cost=vector, total=total, rank=current_rank))
    return out


def explain(
    better: object,
    worse: object,
    model: Optional[CostModel] = None,
) -> str:
    """Why one workflow outranks another, component by component.

    Written to be pasted into a review, not parsed. The component table is the
    substance; the closing line names the single largest contributor, because
    that is the part a reader will argue with.
    """
    engine = model if model is not None else CostModel()
    a, b = engine.cost(better), engine.cost(worse)
    a_total, b_total = a.total(engine.weights), b.total(engine.weights)
    a_parts, b_parts = a.components(engine.weights), b.components(engine.weights)

    lines = [
        "A  {0}".format(better.expression()),
        "B  {0}".format(worse.expression()),
        "",
        "{0:<16}{1:>10}{2:>10}{3:>12}".format("component", "A", "B", "A minus B"),
    ]
    gaps = {}
    for key in ("scale_loss", "support_loss", "concept_shift", "length", "source",
                "redundancy"):
        difference = round(a_parts[key] - b_parts[key], 6)
        gaps[key] = difference
        lines.append(
            "{0:<16}{1:>10.3f}{2:>10.3f}{3:>12.3f}".format(
                key.replace("_", " "), a_parts[key], b_parts[key], difference
            )
        )
    lines.append(
        "{0:<16}{1:>10.3f}{2:>10.3f}{3:>12.3f}".format(
            "total", a_total, b_total, round(a_total - b_total, 6)
        )
    )

    if a_total == b_total:
        lines.append("")
        lines.append("Tied. The cost model does not separate these two.")
        return "\n".join(lines)

    decisive = min(gaps, key=lambda k: gaps[k])
    if gaps[decisive] >= 0:
        lines.append("")
        lines.append("B is the cheaper of the two under this weighting.")
        return "\n".join(lines)

    lines.append("")
    lines.append(
        "A wins mainly on {0}, by {1:.3f} of the {2:.3f} total gap."
        .format(decisive.replace("_", " "), -gaps[decisive], b_total - a_total)
    )
    for step in a.steps:
        if step.scale_loss or step.support_loss or step.concept_shift:
            lines.append("  A  {0}".format(step))
    for step in b.steps:
        if step.scale_loss or step.support_loss or step.concept_shift:
            lines.append("  B  {0}".format(step))
    return "\n".join(lines)


def sharing(workflow) -> dict:
    """Intermediates this workflow computes once and consumes more than once.

    Worth reporting because Workflow.expression flattens a directed acyclic
    graph into a tree, so a shared intermediate is printed once per consumer
    and the workflow reads as though it does the work twice. Of the 176
    workflows the noise question produces at depth four, 45 share an
    intermediate and are misread this way; 2 genuinely recompute, which is what
    the redundancy term in cost.py charges for. The two cases look identical in
    an expression string and are not the same thing at all.
    """
    source_names = {source.name for source in workflow.sources}
    consumers = {}
    for step in workflow.steps:
        for name in step.inputs:
            if name not in source_names:
                consumers[name] = consumers.get(name, 0) + 1
    shared = {name: count for name, count in consumers.items() if count > 1}
    produced_by = {step.output: step.transformation for step in workflow.steps}
    return {
        "shared": tuple(
            sorted((produced_by.get(name, name), count) for name, count in shared.items())
        ),
        "count": len(shared),
    }


def plan(workflow) -> str:
    """The workflow as a sequence of bindings rather than a nested call.

    This is the rendering to put in front of a person. Each step is named once
    and referred to afterwards, so a shared intermediate appears once and the
    reader can see that it is computed once. The nested expression stays as the
    workflow's identity, because it is stable and comparable; it is simply not
    a good way to read a graph.
    """
    source_names = {source.name for source in workflow.sources}
    labels = {}
    lines = []
    for index, step in enumerate(workflow.steps):
        label = chr(ord("a") + index) if index < 26 else "t{0}".format(index)
        labels[step.output] = label
        arguments = ", ".join(
            name if name in source_names else labels.get(name, name)
            for name in step.inputs
        )
        binding = "{0} = {1}({2})".format(label, step.transformation, arguments)
        lines.append(
            "  {0:<34}{1}".format(binding, step.output_type)
        )
    if workflow.steps:
        lines.append("  result: {0}".format(labels[workflow.steps[-1].output]))
    return "\n".join(lines)


def _concordance(model_order: Sequence[str], reference: Sequence[str]) -> tuple:
    """Concordant, discordant and tied pairs between two orderings."""
    position = {name: index for index, name in enumerate(model_order)}
    reference_position = {name: index for index, name in enumerate(reference)}
    shared = [name for name in reference if name in position]
    concordant = discordant = 0
    tied = []
    for first, second in combinations(shared, 2):
        model_gap = position[first] - position[second]
        reference_gap = reference_position[first] - reference_position[second]
        product = model_gap * reference_gap
        if product > 0:
            concordant += 1
        elif product < 0:
            discordant += 1
            tied.append((first, second))
    return concordant, discordant, tuple(tied)


def agreement(scored: Sequence[Scored], reference: Sequence[str]) -> dict:
    """Kendall's tau between the model's order and a reference order.

    reference is a sequence of workflow expressions, best first, as an analyst
    would order them. Only expressions present in both are compared, so a
    reference covering a subset is fine and the returned n says how much of it
    was used.

    tau of 1.0 is perfect agreement, 0.0 is no better than chance, and negative
    means the model is ordering against the reference, which is a more useful
    finding than a middling positive number.
    """
    model_order = [item.expression for item in scored]
    concordant, discordant, _ = _concordance(model_order, reference)
    pairs = concordant + discordant
    if pairs == 0:
        return {"tau": None, "pairs": 0, "n": 0, "note": "fewer than two shared workflows"}
    tau = (concordant - discordant) / float(pairs)
    shared = len([name for name in reference if name in set(model_order)])
    return {
        "tau": round(tau, 4),
        "pairs": pairs,
        "concordant": concordant,
        "discordant": discordant,
        "n": shared,
    }


def disagreements(scored: Sequence[Scored], reference: Sequence[str]) -> tuple:
    """The pairs the model ordered against the reference, worst gap first.

    This is the output to look at when tau is low. A single tau tells you the
    model is wrong; these tell you where, and every entry is a candidate
    counterexample to argue about or a missing term in the cost model.
    """
    model_order = [item.expression for item in scored]
    _concordant, _discordant, flipped = _concordance(model_order, reference)
    by_expression = {item.expression: item for item in scored}
    rows = []
    for first, second in flipped:
        rows.append(
            {
                "reference_prefers": first,
                "model_prefers": second,
                "cost_gap": round(
                    by_expression[first].total - by_expression[second].total, 6
                ),
            }
        )
    rows.sort(key=lambda row: -row["cost_gap"])
    return tuple(rows)


def stability(
    workflows: Sequence,
    model: Optional[CostModel] = None,
    factor: float = 2.0,
) -> dict:
    """How much of the top ordering survives a wide change in weights.

    Each weight is taken up and down by the given factor, one at a time, and
    the winner under each variant is recorded. A winner that holds across every
    variant is a result about the workflows. A winner that changes is a result
    about the weights, and should be reported as such rather than quoted as if
    the model had settled the question.
    """
    engine = model if model is not None else CostModel()
    baseline = rank(workflows, engine)
    if not baseline:
        return {"winner": None, "variants": 0, "held": 0, "stable": True, "alternatives": ()}

    winner = baseline[0].expression
    held = 0
    variants = 0
    alternatives = set()
    for name in engine.weights.as_dict():
        for scale in (factor, 1.0 / factor):
            current = getattr(engine.weights, name) * scale
            variant = engine.with_weights(**{name: current})
            top = rank(workflows, variant)[0].expression
            variants += 1
            if top == winner:
                held += 1
            else:
                alternatives.add(top)
    return {
        "winner": winner,
        "variants": variants,
        "held": held,
        "stable": held == variants,
        "alternatives": tuple(sorted(alternatives)),
    }
