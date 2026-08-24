"""A cost model over admissible workflows.

Type checking answers whether a workflow may run. It does not answer which of
the admissible workflows anyone should run. On the noise exposure question the
synthesiser returns 176 workflows at depth four, 24 of which honour the 70 dB
constraint, and until this module existed those 24 came back in an arbitrary
order with no way to say that one was better than another.

The model here is deliberately not a bag of tuned constants. Every component is
read off the same core concept data type axes the type checker already uses, so
a cost is a statement about what a workflow does to the data rather than a
preference expressed in numbers:

  scale loss     descent through Stevens' measurement scales. Ratio to Ordinal
                 to Nominal is monotone loss of structure, and the quality
                 lattice in ccd.py already orders it.
  support loss   coarsening of the geometry a value is defined over. Points
                 carry more than a lattice, a lattice more than a region.
  concept shift  a change of core concept, which is a modelling decision rather
                 than a computation, and worth flagging as such.
  length         number of steps, as a tiebreaker only.
  source         a penalty read from declared metadata about the inputs.
  redundancy     the same computation performed twice in one workflow. The
                 enumerator can no longer emit one, so this charges chains
                 that arrive through build_chain from outside the search.

Two decisions in here are worth arguing with rather than accepting.

The first is position weighting. A loss at the first step costs more than the
same loss at the last, because everything downstream is computed from what
survived. Reclassifying to classes and then computing zonal statistics is not
the same workflow as computing zonal statistics and then reclassifying, and the
second is better, because the statistics saw the values. Both type check
identically. Position weighting is what separates them.

The second is the weight vector. Weights are policy, not fact, so they live in
a dataclass with defaults that are stated rather than hidden, and ranking.py
can measure any weighting against a human preference ordering. A cost model
that cannot be shown to be wrong is not worth having.
"""

from dataclasses import dataclass, field, replace
from math import log2
from typing import Dict, Optional, Sequence

from ccd import (
    ANY_QUALITY,
    ANY_SUPPORT,
    CCDType,
    LATTICE_SUPPORT,
    POINT_SUPPORT,
    QUALITY_PARENT,
    REGION_SUPPORT,
)


def _depth(parents: dict, term: str) -> int:
    """Distance from the root of one axis. The root is 0."""
    depth = 0
    node = term
    while parents[node] is not None:
        depth += 1
        node = parents[node]
    return depth


QUALITY_DEPTH = {term: _depth(QUALITY_PARENT, term) for term in QUALITY_PARENT}

# Granularity of a support, finest first. This is an ordering the type system
# does not impose, because subsumption between supports is not a granularity
# claim: a region is not a coarse point in the type lattice, the two are simply
# siblings. Ranking needs the ordering anyway, so it is declared here and kept
# out of ccd.py, where it would wrongly imply subtyping.
SUPPORT_GRANULARITY = {
    POINT_SUPPORT: 3,
    LATTICE_SUPPORT: 2,
    REGION_SUPPORT: 1,
    ANY_SUPPORT: 2,
}


@dataclass(frozen=True)
class Weights:
    """The policy half of the model, separated from the measurement half.

    Defaults were chosen so that one full scale descent early in a workflow
    outranks any plausible difference in length, because a workflow that throws
    away the interval structure of its input is answering a different question,
    while a workflow with one extra step is answering the same question at
    slightly more expense.
    """

    scale_loss: float = 4.0
    support_loss: float = 2.5
    concept_shift: float = 1.5
    length: float = 0.5
    source: float = 1.0
    redundancy: float = 3.0

    def as_dict(self) -> dict:
        return {
            "scale_loss": self.scale_loss,
            "support_loss": self.support_loss,
            "concept_shift": self.concept_shift,
            "length": self.length,
            "source": self.source,
            "redundancy": self.redundancy,
        }


@dataclass(frozen=True)
class SourceProfile:
    """Declared metadata about one source dataset.

    Nothing here is inferred. A source with no profile contributes no penalty,
    which keeps an unprofiled catalogue usable rather than silently penalising
    every source equally.
    """

    name: str
    resolution_m: Optional[float] = None
    year: Optional[int] = None
    authority: Optional[str] = None

    def penalty(self, reference_year: int = 2026) -> float:
        """A small, bounded penalty. Bounded because source quality should
        never dominate a ranking that is otherwise about what the workflow does.
        """
        total = 0.0
        if self.resolution_m is not None and self.resolution_m > 0:
            # Halving resolution costs one unit, so 10 m to 20 m and 20 m to
            # 40 m cost the same, which is how resolution is usually discussed.
            total += max(0.0, log2(self.resolution_m / 10.0))
        if self.year is not None:
            total += max(0, reference_year - self.year) / 10.0
        return round(min(total, 5.0), 4)


@dataclass(frozen=True)
class StepCost:
    """What one step in a workflow costs, and why."""

    index: int
    transformation: str
    position_weight: float
    scale_loss: float
    support_loss: float
    concept_shift: float
    note: str = ""

    @property
    def weighted(self) -> dict:
        return {
            "scale_loss": self.scale_loss * self.position_weight,
            "support_loss": self.support_loss * self.position_weight,
            "concept_shift": self.concept_shift * self.position_weight,
        }

    def __str__(self) -> str:
        parts = []
        if self.scale_loss:
            parts.append("scale -{0:g}".format(self.scale_loss))
        if self.support_loss:
            parts.append("support -{0:g}".format(self.support_loss))
        if self.concept_shift:
            parts.append("concept shift")
        detail = ", ".join(parts) if parts else "no loss"
        return "step {0} {1}: {2} (position weight {3:.2f})".format(
            self.index, self.transformation, detail, self.position_weight
        )


@dataclass(frozen=True)
class CostVector:
    """The cost of a whole workflow, kept per component rather than collapsed.

    Keeping the components apart is what lets ranking.py say why one workflow
    beat another instead of only that it did.
    """

    scale_loss: float = 0.0
    support_loss: float = 0.0
    concept_shift: float = 0.0
    length: float = 0.0
    source: float = 0.0
    redundancy: float = 0.0
    steps: tuple = ()

    def total(self, weights: Weights) -> float:
        w = weights
        return round(
            self.scale_loss * w.scale_loss
            + self.support_loss * w.support_loss
            + self.concept_shift * w.concept_shift
            + self.length * w.length
            + self.source * w.source
            + self.redundancy * w.redundancy,
            6,
        )

    def components(self, weights: Weights) -> dict:
        w = weights.as_dict()
        raw = {
            "scale_loss": self.scale_loss,
            "support_loss": self.support_loss,
            "concept_shift": self.concept_shift,
            "length": self.length,
            "source": self.source,
            "redundancy": self.redundancy,
        }
        return {k: round(v * w[k], 6) for k, v in raw.items()}


def _scale_loss(before: CCDType, after: CCDType) -> float:
    """Descent through the quality lattice, in lattice levels.

    Only descent counts. A transformation that moves up the lattice is not
    creating information out of nothing, it is asserting structure the modeller
    believes is there, and charging for that would penalise the interpolation
    of a continuous surface from points, which is a legitimate thing to do.
    """
    if before.quality == ANY_QUALITY or after.quality == ANY_QUALITY:
        return 0.0
    drop = QUALITY_DEPTH[before.quality] - QUALITY_DEPTH[after.quality]
    return float(max(0, drop))


def _support_loss(before: CCDType, after: CCDType) -> float:
    """Coarsening of the geometry, in granularity levels."""
    if before.support == ANY_SUPPORT or after.support == ANY_SUPPORT:
        return 0.0
    drop = SUPPORT_GRANULARITY[before.support] - SUPPORT_GRANULARITY[after.support]
    return float(max(0, drop))


def _concept_shift(before: CCDType, after: CCDType) -> float:
    return 1.0 if before.concept != after.concept else 0.0


def _redundancy(workflow) -> float:
    """Computations performed more than once in the same workflow.

    Found while testing the model against its own output: two workflows that
    computed Clip(noise, district) twice were tying with the one that computed
    it once, because nothing in the model looked at repetition. A synthesiser
    that enumerates rather than plans will produce these, and an analyst
    reading the ranked list will discard them on sight, so the model has to as
    well.

    A step is a repeat when the same transformation is applied to inputs whose
    expressions match, which catches recomputation under different output names
    rather than only literal duplicates.
    """
    seen = set()
    repeats = 0
    for step in workflow.steps:
        signature = (
            step.transformation,
            tuple(workflow.expression(name) for name in step.inputs),
        )
        if signature in seen:
            repeats += 1
        else:
            seen.add(signature)
    return float(repeats)


def _position_weight(index: int, total_steps: int) -> float:
    """Later steps count for less.

    Linear rather than exponential, because the claim being made is only that
    an early loss is unavailable downstream, not that it compounds. A
    single-step workflow gets weight 1.0.
    """
    if total_steps <= 1:
        return 1.0
    return (total_steps - index) / float(total_steps)


def _governing_input(workflow, step) -> Optional[CCDType]:
    """The input a step's loss should be measured against.

    A transformation with several inputs is compared against the input that
    carries the most measurement structure, because that is the one whose
    information a lossy step is discarding. Comparing against the coarsest
    input would report no loss for exactly the workflows that lose the most.

    An unresolvable reference is refused rather than skipped. It cannot happen
    on an enumerated workflow, but build_chain accepts chains from outside the
    search, and a step whose inputs all failed to resolve used to score zero on
    scale, support and concept, so a hand-built workflow naming a dataset that
    does not exist came back as the cheapest thing in the list.
    """
    best = None
    for name in step.inputs:
        try:
            candidate = workflow.dataset(name).type
        except KeyError:
            raise ValueError(
                "step {0} of this workflow consumes {1!r}, which is neither a "
                "source nor the output of an earlier step".format(
                    step.transformation, name
                )
            ) from None
        if candidate.quality == ANY_QUALITY:
            continue
        if best is None or QUALITY_DEPTH[candidate.quality] > QUALITY_DEPTH[best.quality]:
            best = candidate
    return best


class CostModel:
    """Scores workflows. Holds no state beyond its weights and source profiles."""

    def __init__(
        self,
        weights: Optional[Weights] = None,
        profiles: Optional[Sequence[SourceProfile]] = None,
        reference_year: int = 2026,
    ) -> None:
        self.weights = weights if weights is not None else Weights()
        self.profiles: Dict[str, SourceProfile] = {
            profile.name: profile for profile in (profiles or ())
        }
        self.reference_year = reference_year

    def step_costs(self, workflow) -> tuple:
        total_steps = len(workflow.steps)
        costs = []
        for index, step in enumerate(workflow.steps):
            governing = _governing_input(workflow, step)
            after = step.output_type
            if governing is None:
                scale = support = shift = 0.0
                note = "no typed input to compare against"
            else:
                scale = _scale_loss(governing, after)
                support = _support_loss(governing, after)
                shift = _concept_shift(governing, after)
                note = "{0} -> {1}".format(governing, after)
            costs.append(
                StepCost(
                    index=index,
                    transformation=step.transformation,
                    position_weight=_position_weight(index, total_steps),
                    scale_loss=scale,
                    support_loss=support,
                    concept_shift=shift,
                    note=note,
                )
            )
        return tuple(costs)

    def source_penalty(self, workflow) -> float:
        total = 0.0
        for source in workflow.sources_consumed():
            profile = self.profiles.get(source.name)
            if profile is not None:
                total += profile.penalty(self.reference_year)
        return round(total, 6)

    def cost(self, workflow) -> CostVector:
        steps = self.step_costs(workflow)
        scale = sum(s.weighted["scale_loss"] for s in steps)
        support = sum(s.weighted["support_loss"] for s in steps)
        shift = sum(s.weighted["concept_shift"] for s in steps)
        return CostVector(
            scale_loss=round(scale, 6),
            support_loss=round(support, 6),
            concept_shift=round(shift, 6),
            length=float(len(workflow.steps)),
            source=self.source_penalty(workflow),
            redundancy=_redundancy(workflow),
            steps=steps,
        )

    def total(self, workflow) -> float:
        return self.cost(workflow).total(self.weights)

    def with_weights(self, **overrides) -> "CostModel":
        """A copy under different weights, for sensitivity analysis.

        Sensitivity is the point: a ranking that survives a wide range of
        weightings is a claim about the workflows, and one that flips under a
        small change is a claim about the weights.
        """
        return CostModel(
            weights=replace(self.weights, **overrides),
            profiles=tuple(self.profiles.values()),
            reference_year=self.reference_year,
        )
