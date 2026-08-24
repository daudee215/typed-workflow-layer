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
finite and free of workflows that are formally distinct but practically the
same. They are search heuristics, not claims about geography, and each is
marked below.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from typing import Optional, Sequence

import catalogue
from catalogue import CATALOGUE, SlotMismatch
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
) -> list:
    """Every admissible workflow from sources to target, up to max_depth steps.

    must_use names transformations that have to appear, which is how a
    constraint carried by a request narrows the space: a question that asks
    about values above a threshold is not answered by a workflow that never
    thresholds anything, even though such a workflow type checks.

    Results are ordered by depth and then by expression, so the output is
    stable between runs.
    """
    required = frozenset(must_use)
    for name in required:
        catalogue.get(name)
    found = {}

    def expand(available: tuple, steps: tuple) -> None:
        if len(found) >= max_workflows or len(steps) >= max_depth:
            return
        for name, transformation in CATALOGUE.items():
            # Search restriction: distinct datasets across slots. Every
            # two-slot entry in this catalogue combines things of different
            # kinds, so a repeated argument is always degenerate here.
            for assignment in permutations(available, transformation.arity):
                # Checked here rather than only on entry, because the loop
                # continues after a nested call returns and would otherwise
                # add one more workflow per stack frame as it unwinds.
                if len(found) >= max_workflows:
                    return
                # Search restriction: a transformation is never applied to a
                # dataset it produced itself. Aggregate of an aggregate and
                # buffer of a buffer are the cases this removes, and they
                # would otherwise fill the depth bound with noise.
                if any(item.origin == name for item in assignment):
                    continue
                types = [item.type for item in assignment]
                if transformation.check(types):
                    continue
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
                    and _is_connected(extended)
                ):
                    workflow = Workflow(extended, tuple(sources), output)
                    found.setdefault(workflow.expression(), workflow)
                expand(available + (output,), extended)

    expand(tuple(sources), ())
    return sorted(found.values(), key=lambda w: (w.depth, w.expression()))


@dataclass(frozen=True)
class Rejection:
    """Why one step of a candidate chain could not be built.

    kind is one of unknown_transformation, arity, unknown_input or type. Only
    the last carries slot and axis detail.
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
    known = {source.name: source for source in sources}
    produced = []

    for index, (name, references) in enumerate(chain):
        try:
            transformation = catalogue.get(name)
        except KeyError as error:
            return Rejection(index, name, "unknown_transformation", str(error))

        arguments = []
        for reference in references:
            if reference.startswith("$"):
                position = int(reference[1:])
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
            first: SlotMismatch = failures[0]
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
