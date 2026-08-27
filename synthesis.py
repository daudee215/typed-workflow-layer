"""Enumeration of the valid workflows that reach a target type.

Two facilities live here.

enumerate_workflows returns every admissible workflow up to a depth bound, not
the first one found. The project this package was written for describes its own
goal as producing the set of possible valid ways to address a given question,
so returning a single plan would miss the point. A chain that does not type
check is never built, never executed and never returned.

why_rejected takes a candidate chain that a person or a language model has
proposed and says exactly which step failed, which slot, which axis, and which
transformation would have repaired it. Enumeration is the easy half. Saying why
something was refused, in terms a reader can act on, is the half that decides
whether anyone trusts the refusal.

Design note on the search restrictions. Three restrictions keep the space
finite and remove workflows that are, in most cases, formally distinct but
practically the same. They are search heuristics, not claims about geography,
and each is marked below.

They are also switchable, because an unmeasured heuristic is an assumption.
analysis.py turns each one off in turn and reports what it costs. That exercise
corrected this docstring once already: the no immediate repeat restriction was
described here as removing noise, and it does not. It also removes multi-level
aggregation, which is a real workflow. See Restrictions.no_immediate_repeat.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations, product
from typing import Optional, Sequence

import catalogue
from catalogue import CATALOGUE, CrossSlotMismatch, SlotMismatch
from ccd import CCDType


@dataclass(frozen=True)
class Dataset:
    """A named dataset carrying a core concept data type.

    origin is None for a source and the transformation name for anything
    derived, which is what the no immediate repeat restriction reads.
    """

    name: str
    type: CCDType
    origin: Optional[str] = None

    def __str__(self) -> str:
        return "{0}: {1}".format(self.name, self.type)


@dataclass(frozen=True)
class Step:
    """One application of a transformation inside a workflow."""

    transformation: str
    inputs: tuple
    output: str
    output_type: CCDType


@dataclass(frozen=True)
class Workflow:
    """A sequence of steps ending in a dataset of the target type."""

    steps: tuple
    sources: tuple
    result: Dataset

    @property
    def depth(self) -> int:
        return len(self.steps)

    def dataset(self, name: str) -> Dataset:
        for source in self.sources:
            if source.name == name:
                return source
        for step in self.steps:
            if step.output == name:
                return Dataset(step.output, step.output_type, step.transformation)
        raise KeyError("no dataset named {0!r} in this workflow".format(name))

    def expression(self, name: Optional[str] = None) -> str:
        """The workflow as a nested call, which also serves as its identity."""
        target = name if name is not None else self.result.name
        for step in self.steps:
            if step.output == target:
                args = ", ".join(self.expression(ref) for ref in step.inputs)
                return "{0}({1})".format(step.transformation, args)
        return target

    def sources_consumed(self) -> tuple:
        used = set()
        source_names = {source.name for source in self.sources}
        for step in self.steps:
            used.update(ref for ref in step.inputs if ref in source_names)
        return tuple(s for s in self.sources if s.name in used)

    def transformations_used(self) -> frozenset:
        return frozenset(step.transformation for step in self.steps)


@dataclass(frozen=True)
class Restrictions:
    """Which search restrictions are in force.

    All three default to on, which is the behaviour the rest of the package
    relies on. They exist as flags so analysis.py can price each one instead of
    the docstring asserting they are free.

    connected
        Drop a workflow containing a step that does not feed the result.

        Now a no-op, and measurably so. expression() renders only the steps
        reachable from the result, so a disconnected workflow always collapses
        onto the expression of its connected core, and that core is itself
        enumerated. It used to still matter for the stored object, because
        turning it off left 28 of 176 workflows carrying a step that fed
        nothing. Keeping the shortest realisation of an expression removed that
        too: a workflow with a dead step is strictly longer than the same
        expression without one, so it can no longer win the key.

        Kept as a flag rather than deleted, so the claim stays measurable and
        is re-checked by the suite instead of resting on this paragraph.

    no_immediate_repeat
        Never apply a transformation to a dataset it produced itself. This one
        is not free. It removes Aggregate(Aggregate(x)), and aggregating to
        districts and then to regions is a real two-level workflow, not noise.
        It is kept on by default because the same rule removes a much larger
        number of genuinely degenerate chains, and because the type system
        here cannot tell the two apart: both have identical input and output
        types, so nothing in the signature distinguishes a second meaningful
        grouping from a pointless re-sum. Turning it off is the honest way to
        see multi-level workflows, and analysis.py reports how many appear.

    distinct_slots
        Never pass one dataset to two slots of the same transformation. Safe
        for every entry whose slots take different core concepts. Overlay is
        the exception, taking two nominal fields, so this rule does exclude
        Overlay(x, x). That is degenerate on any reasonable reading of overlay,
        but it is an exclusion on semantic grounds and not on the structural
        grounds the other cases rest on, so it is named here rather than
        waved through.
    """

    connected: bool = True
    no_immediate_repeat: bool = True
    distinct_slots: bool = True


@dataclass
class SearchStats:
    """What the search did, as opposed to what it returned.

    truncated is the field that matters. Before it existed the search stopped
    at max_workflows and returned a plain list, so a caller could not tell a
    complete enumeration from a capped one. A result that silently looks
    complete is the same failure as a load test that cannot see its own queue:
    the arithmetic is right and the subject is wrong.
    """

    candidates_examined: int = 0
    type_checks: int = 0
    admissible_applications: int = 0
    workflows_found: int = 0
    truncated: bool = False
    max_depth_reached: int = 0

    def __str__(self) -> str:
        return (
            "{0} workflow(s) from {1} candidate application(s), "
            "{2} type check(s){3}".format(
                self.workflows_found,
                self.candidates_examined,
                self.type_checks,
                ", TRUNCATED at the workflow cap" if self.truncated else "",
            )
        )


class WorkflowSet(list):
    """The enumeration result, carrying how it was produced.

    A list subclass so every existing caller keeps working unchanged, while
    `.stats.truncated` gives the one thing a plain list could never say.
    """

    def __init__(self, workflows=(), stats: Optional[SearchStats] = None):
        super().__init__(workflows)
        self.stats = stats if stats is not None else SearchStats()

    @property
    def complete(self) -> bool:
        """True when the whole space up to the depth bound was enumerated."""
        return not self.stats.truncated


def _is_connected(steps: Sequence[Step]) -> bool:
    """True when every step contributes to the last step's output.

    Search restriction, not a semantic rule. Without it, a workflow that
    reaches the target and also computes something irrelevant on the side
    would be returned as a separate answer from the same workflow without the
    detour. Steps are in topological order, so one backward pass is enough.
    """
    needed = {steps[-1].output}
    for step in reversed(steps):
        if step.output not in needed:
            return False
        needed.update(step.inputs)
    return True


def enumerate_workflows(
    sources: Sequence[Dataset],
    target: CCDType,
    max_depth: int = 3,
    must_use: Sequence[str] = (),
    max_workflows: int = 500,
    restrictions: Optional[Restrictions] = None,
) -> WorkflowSet:
    """Every admissible workflow from sources to target, up to max_depth steps.

    must_use names transformations that have to appear, which is how a
    constraint carried by a request narrows the space: a question that asks
    about values above a threshold is not answered by a workflow that never
    thresholds anything, even though such a workflow type checks.

    Results are ordered by depth and then by expression, so the output is
    stable between runs. The return is a list carrying `.stats`, so a caller
    that needs to know whether the cap was hit can ask instead of guessing.
    """
    if max_depth < 0:
        raise ValueError("max_depth cannot be negative")
    if max_workflows < 0:
        raise ValueError("max_workflows cannot be negative")
    source_names = [source.name for source in sources]
    if len(source_names) != len(set(source_names)):
        raise ValueError("source names must be unique")
    rules = restrictions if restrictions is not None else Restrictions()
    required = frozenset(must_use)
    for name in required:
        catalogue.get(name)
    found = {}
    stats = SearchStats()

    def combinations(available: tuple, arity: int):
        """Argument assignments for one transformation.

        permutations draws without replacement, which is the distinct_slots
        restriction. product draws with replacement, which is what the search
        looks like without it.
        """
        if rules.distinct_slots:
            return permutations(available, arity)
        return product(available, repeat=arity)

    def expand(available: tuple, steps: tuple) -> None:
        if len(found) >= max_workflows or len(steps) >= max_depth:
            return
        stats.max_depth_reached = max(stats.max_depth_reached, len(steps))
        for name, transformation in CATALOGUE.items():
            for assignment in combinations(available, transformation.arity):
                # Checked here rather than only on entry, because the loop
                # continues after a nested call returns and would otherwise
                # add one more workflow per stack frame as it unwinds.
                if len(found) >= max_workflows:
                    stats.truncated = True
                    return
                stats.candidates_examined += 1
                # Search restriction: a transformation is never applied to a
                # dataset it produced itself. See Restrictions for what this
                # costs, which is more than the first version of this comment
                # claimed.
                if rules.no_immediate_repeat and any(
                    item.origin == name for item in assignment
                ):
                    continue
                types = [item.type for item in assignment]
                stats.type_checks += 1
                if transformation.check(types):
                    continue
                stats.admissible_applications += 1
                output = Dataset(
                    "step%d" % (len(steps) + 1),
                    transformation.output_type(types),
                    name,
                )
                step = Step(
                    name,
                    tuple(item.name for item in assignment),
                    output.name,
                    output.type,
                )
                extended = steps + (step,)
                if (
                    target.subsumes(output.type)
                    and required.issubset(s.transformation for s in extended)
                    and (not rules.connected or _is_connected(extended))
                ):
                    workflow = Workflow(extended, tuple(sources), output)
                    expression = workflow.expression()
                    # Keep the shortest realisation of an expression, not the
                    # first one reached.
                    #
                    # expression() renders the workflow as a tree while the
                    # workflow is a DAG, so a step feeding two later steps is
                    # printed twice. Two different step lists can therefore
                    # render identically: one that computes a shared
                    # subexpression once, and one that computes it twice. Both
                    # are correct and one is a step longer.
                    #
                    # setdefault kept whichever the search happened to reach
                    # first, which was the longer one for 2 of the 176
                    # workflows in the demo scenario. That is not cosmetic:
                    # cost.py charges length as len(workflow.steps), so those
                    # two were ranked worse for steps they did not need.
                    existing = found.get(expression)
                    if existing is None or len(extended) < len(existing.steps):
                        found[expression] = workflow
                expand(available + (output,), extended)

    expand(tuple(sources), ())
    stats.workflows_found = len(found)
    return WorkflowSet(
        sorted(found.values(), key=lambda w: (w.depth, w.expression())), stats
    )


@dataclass(frozen=True)
class Rejection:
    """Why one step of a candidate chain could not be built.

    kind is one of unknown_transformation, arity, unknown_input, malformed_step,
    type or cross_slot. The type and cross_slot cases carry structured detail.
    """

    step_index: int
    transformation: str
    kind: str
    detail: str
    slot: Optional[int] = None
    required: Optional[CCDType] = None
    actual: Optional[CCDType] = None
    actual_dataset: Optional[str] = None
    axis_mismatches: tuple = ()
    cross_slot_mismatches: tuple = ()

    def explain(self) -> str:
        """A readable account of the failure, and of what would repair it."""
        head = "Step {0} of the chain, {1}, was refused.".format(
            self.step_index + 1, self.transformation
        )
        if self.kind != "type":
            return head + "\n  " + self.detail

        lines = [
            head,
            "  {0:<18}{1}".format(
                "slot {0} requires".format(self.slot), self.required
            ),
            "  {0:<18}{1}    [{2}]".format(
                "but receives", self.actual, self.actual_dataset
            ),
        ]
        for mismatch in self.axis_mismatches:
            lines.append("  " + str(mismatch))

        concept_failed = any(
            mismatch.axis == "core concept" for mismatch in self.axis_mismatches
        )
        repairs = catalogue.producing(self.required, self.actual)
        if repairs:
            lines.append(
                "  reaching {0} from {1} is possible with: {2}".format(
                    self.required, self.actual, ", ".join(repairs)
                )
            )
        else:
            lines.append(
                "  nothing in the catalogue reaches {0} from {1}".format(
                    self.required, self.actual
                )
            )
        if concept_failed:
            lines.append(
                "  the chain contains no step that moves the value from one"
            )
            lines.append(
                "  core concept to another, so the quantity never becomes a"
            )
            lines.append(
                "  property of the thing the question asks about."
            )
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.explain()


def why_rejected(chain: Sequence, sources: Sequence[Dataset]) -> Optional[Rejection]:
    """Walk a candidate chain and report the first step that cannot be built.

    A chain is a sequence of pairs, each a transformation name and a tuple of
    references. A reference is either the name of a source or "$k" for the
    output of step k, counting from zero.

    Returns None when the whole chain type checks, which is the only way this
    package ever says yes to a chain it did not build itself.
    """
    if not isinstance(chain, Sequence) or isinstance(chain, (str, bytes)):
        raise ValueError("chain must be a sequence of workflow steps")
    known = {}
    for source in sources:
        if source.name in known:
            raise ValueError("source names must be unique")
        known[source.name] = source
    produced = []

    for index, item in enumerate(chain):
        if (not isinstance(item, (tuple, list)) or len(item) != 2):
            return Rejection(
                index,
                "<malformed>",
                "malformed_step",
                "each step must be (transformation name, input references)",
            )
        name, references = item
        if (not isinstance(name, str) or not isinstance(references, Sequence)
                or isinstance(references, (str, bytes))):
            return Rejection(
                index,
                str(name),
                "malformed_step",
                "each step must be (transformation name, input references)",
            )
        try:
            transformation = catalogue.get(name)
        except KeyError as error:
            return Rejection(index, name, "unknown_transformation", str(error))

        arguments = []
        for reference in references:
            if not isinstance(reference, str):
                return Rejection(
                    index,
                    name,
                    "unknown_input",
                    "input references must be strings, got {0!r}".format(
                        reference
                    ),
                )
            if reference.startswith("$"):
                suffix = reference[1:]
                if not suffix.isdigit():
                    return Rejection(
                        index,
                        name,
                        "unknown_input",
                        "reference {0} is not a non-negative step index".format(
                            reference
                        ),
                    )
                position = int(suffix)
                if position >= len(produced):
                    return Rejection(
                        index,
                        name,
                        "unknown_input",
                        "reference {0} points at a step that has not run "
                        "yet".format(reference),
                    )
                arguments.append(produced[position])
            elif reference in known:
                arguments.append(known[reference])
            else:
                return Rejection(
                    index,
                    name,
                    "unknown_input",
                    "no source named {0!r}. Known sources: {1}".format(
                        reference, ", ".join(sorted(known))
                    ),
                )

        if len(arguments) != transformation.arity:
            return Rejection(
                index,
                name,
                "arity",
                "{0} takes {1} input(s), {2} given".format(
                    name, transformation.arity, len(arguments)
                ),
            )

        types = [argument.type for argument in arguments]
        failures = transformation.check(types)
        if failures:
            first = failures[0]
            if isinstance(first, SlotMismatch):
                return Rejection(
                    index,
                    name,
                    "type",
                    "slot {0} does not unify".format(first.slot),
                    slot=first.slot,
                    required=first.required,
                    actual=first.actual,
                    actual_dataset=_describe(arguments[first.slot]),
                    axis_mismatches=first.axis_mismatches,
                )
            if isinstance(first, CrossSlotMismatch):
                return Rejection(
                    index,
                    name,
                    "cross_slot",
                    str(first),
                    cross_slot_mismatches=(first,),
                )
            raise TypeError("catalogue returned an unknown mismatch type")

        produced.append(
            Dataset(
                "$%d" % index, transformation.output_type(types), name
            )
        )

    return None


def build_chain(chain: Sequence, sources: Sequence[Dataset]) -> Workflow:
    """Turn a type checking chain into a Workflow, or raise.

    Kept separate from why_rejected so that construction has one entry point
    that cannot succeed on a chain the checker would refuse.
    """
    if not chain:
        raise ValueError("a workflow chain must contain at least one step")
    rejection = why_rejected(chain, sources)
    if rejection is not None:
        raise TypeError(rejection.explain())

    known = {source.name: source for source in sources}
    steps = []
    outputs = []
    for index, (name, references) in enumerate(chain):
        transformation = catalogue.get(name)
        resolved = [
            outputs[int(ref[1:])] if ref.startswith("$") else known[ref]
            for ref in references
        ]
        output = Dataset(
            "step%d" % (index + 1),
            transformation.output_type([item.type for item in resolved]),
            name,
        )
        steps.append(
            Step(
                name,
                tuple(item.name for item in resolved),
                output.name,
                output.type,
            )
        )
        outputs.append(output)
    return Workflow(tuple(steps), tuple(sources), outputs[-1])


def _describe(dataset: Dataset) -> str:
    if dataset.origin is None:
        return "source {0}".format(dataset.name)
    return "{0}, produced by {1}".format(dataset.name, dataset.origin)
