"""A small catalogue of typed transformations.

Each entry is a name, a typed input signature, a typed output signature and one
line of prose. Nothing here executes: a transformation is a claim about which
core concept data types go in and what comes out, and that claim is all the
synthesis and rejection machinery ever consults.

Design note on inherited axes. Several transformations preserve an axis of
their input rather than fixing it. Clip does not change the quality or the
support of the field it clips; Constrain changes the quality to nominal but
keeps the support. Rather than introduce type variables, a transformation may
name the input slot from which the output copies its quality or its support.
That is less general than unification with variables and much easier to read.

Design note on honesty. Some of these signatures are debatable, and the
debatable ones carry a comment saying why. A catalogue that hides its
judgement calls is worse than a small one that shows them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from ccd import (
    ANY_QUALITY,
    CCDType,
    EXTENSIVE,
    FIELD,
    INTENSIVE,
    INTERVAL,
    NOMINAL,
    OBJECT,
    ORDINAL,
    POINT_SUPPORT,
    REGION_SUPPORT,
)


@dataclass(frozen=True)
class SlotMismatch:
    """A rejected argument: which slot, what it wanted, what it got."""

    slot: int
    required: CCDType
    actual: CCDType
    axis_mismatches: tuple


@dataclass(frozen=True)
class CrossSlotMismatch:
    """A relation between slots that componentwise typing cannot express."""

    slots: tuple
    axis: str
    actual: tuple

    def __str__(self) -> str:
        rendered = ", ".join(str(item) for item in self.actual)
        return (
            "slots {0} must agree on {1}; received {2}".format(
                ", ".join(str(item) for item in self.slots),
                self.axis,
                rendered,
            )
        )


@dataclass(frozen=True)
class Transformation:
    """A typed transformation signature."""

    name: str
    inputs: tuple
    output: CCDType
    description: str
    inherit_quality_from: Optional[int] = None
    inherit_support_from: Optional[int] = None
    same_support_slots: tuple = ()

    @property
    def arity(self) -> int:
        return len(self.inputs)

    def check(self, actual: Sequence[CCDType]) -> tuple:
        """Every slot that rejects its argument, in slot order.

        An empty result means the application is admissible. Arity is the
        caller's problem and is checked before this is reached.
        """
        found = []
        for index, (required, given) in enumerate(zip(self.inputs, actual)):
            axis_mismatches = required.mismatches(given)
            if axis_mismatches:
                found.append(
                    SlotMismatch(index, required, given, axis_mismatches)
                )
        for slots in self.same_support_slots:
            if len(slots) < 2:
                raise ValueError("a cross-slot constraint needs two slots")
            supports = tuple(actual[index].support for index in slots)
            if len(set(supports)) > 1:
                found.append(CrossSlotMismatch(slots, "support", supports))
        return tuple(found)

    def accepts(self, actual: Sequence[CCDType]) -> bool:
        return len(actual) == self.arity and not self.check(actual)

    def output_type(self, actual: Sequence[CCDType]) -> CCDType:
        """The concrete output type for a given set of admissible inputs."""
        result = self.output
        if self.inherit_quality_from is not None:
            result = result.with_axes(
                quality=actual[self.inherit_quality_from].quality
            )
        if self.inherit_support_from is not None:
            result = result.with_axes(
                support=actual[self.inherit_support_from].support
            )
        return result

    def signature(self) -> str:
        """A one-line rendering of the signature, for printing."""
        given = ", ".join(str(t) for t in self.inputs)
        out = str(self.output)
        inherited = []
        if self.inherit_quality_from is not None:
            inherited.append("quality from slot %d" % self.inherit_quality_from)
        if self.inherit_support_from is not None:
            inherited.append("support from slot %d" % self.inherit_support_from)
        if inherited:
            out += " with " + " and ".join(inherited)
        if self.same_support_slots:
            out += "; slots {0} share support".format(
                ", ".join(",".join(str(item) for item in slots)
                            for slots in self.same_support_slots)
            )
        return "{0}: {1} -> {2}".format(self.name, given, out)


_ENTRIES = (
    Transformation(
        name="Constrain",
        # Ordinal, not Ratio: a threshold needs an ordered scale and nothing
        # more. Requiring Ratio here would wrongly refuse an ordinal noise
        # class map, and requiring Interval would refuse ordinal data that a
        # comparison handles perfectly well.
        inputs=(CCDType(FIELD, ORDINAL),),
        output=CCDType(FIELD, NOMINAL),
        inherit_support_from=0,
        description=(
            "Threshold a field, giving a field of where the condition holds."
        ),
    ),
    Transformation(
        name="Interpolate",
        # Interval and not Nominal: interpolating a nominal field is not
        # meaningful. The output is declared Interval rather than inheriting
        # the input quality, because interpolation invents values between
        # observations and a ratio claim would not survive that.
        inputs=(CCDType(FIELD, INTERVAL, POINT_SUPPORT),),
        output=CCDType(FIELD, INTERVAL, REGION_SUPPORT),
        description=(
            "Estimate a continuous field over regions from point observations."
        ),
    ),
    Transformation(
        name="Clip",
        inputs=(CCDType(FIELD), CCDType(OBJECT, ANY_QUALITY, REGION_SUPPORT)),
        output=CCDType(FIELD),
        inherit_quality_from=0,
        inherit_support_from=0,
        description="Restrict a field to the extent of an object.",
    ),
    Transformation(
        name="Coverage",
        # The one that matters. Measuring how much of a field falls inside an
        # object moves the value from the field to the object and makes it
        # extensive: covered areas over disjoint districts add up. The field
        # slot asks for Nominal, which by the scale ordering also accepts
        # interval and ratio fields, so coverage per distinct value is
        # admissible as well as coverage of a thresholded field.
        inputs=(
            CCDType(FIELD, NOMINAL),
            CCDType(OBJECT, ANY_QUALITY, REGION_SUPPORT),
        ),
        output=CCDType(OBJECT, EXTENSIVE, REGION_SUPPORT),
        description=(
            "Measure the extent of a field inside each object, as an "
            "extensive quantity borne by the object."
        ),
    ),
    Transformation(
        name="ZonalStatistics",
        # The contrast with Coverage. A mean or a maximum per zone is
        # intensive: it does not add up when zones are merged. Same shape of
        # signature, different output quality, and that difference is what
        # stops Aggregate being applied to it.
        inputs=(
            CCDType(FIELD, INTERVAL),
            CCDType(OBJECT, ANY_QUALITY, REGION_SUPPORT),
        ),
        output=CCDType(OBJECT, INTENSIVE, REGION_SUPPORT),
        description=(
            "Summarise a field within each object as an intensive quantity."
        ),
    ),
    Transformation(
        name="Aggregate",
        # Debatable, and stated as such. A real signature would take a second
        # object as the grouping, and would then also have to check that the
        # grouping partitions the input. Kept to one slot because the brief
        # asks for object to object, and because the interesting constraint is
        # the quality: only extensive quantities may be summed across objects.
        inputs=(CCDType(OBJECT, EXTENSIVE),),
        output=CCDType(OBJECT, EXTENSIVE, REGION_SUPPORT),
        description=(
            "Sum an extensive quantity over a coarser set of objects."
        ),
    ),
    Transformation(
        name="Proportion",
        # The step that turns a quantity into a share of something. Covered
        # area is extensive, the proportion of a district's area that it
        # occupies is intensive, and a workflow that stops before this step
        # answers a different question from the one asked.
        inputs=(CCDType(OBJECT, EXTENSIVE),),
        output=CCDType(OBJECT, INTENSIVE),
        inherit_support_from=0,
        description=(
            "Normalise an extensive quantity by the size of its object, "
            "giving an intensive quantity such as a proportion."
        ),
    ),
    Transformation(
        name="Reclassify",
        inputs=(CCDType(FIELD, NOMINAL),),
        output=CCDType(FIELD, NOMINAL),
        inherit_support_from=0,
        description="Map the values of a field onto a set of classes.",
    ),
    Transformation(
        name="Buffer",
        # Debatable in two ways. The output quality is declared Nominal
        # because a buffer carries identity and not measurement, which
        # discards any attribute the input object had. The support is fixed to
        # regions because buffering a point or a line yields a region.
        inputs=(CCDType(OBJECT),),
        output=CCDType(OBJECT, NOMINAL, REGION_SUPPORT),
        description="Grow an object by a distance, giving a region object.",
    ),
    Transformation(
        name="Overlay",
        # Two fields are combined only if they share a support. This is a
        # relation between inputs rather than a componentwise requirement, so
        # it is declared explicitly instead of being hidden in the executor.
        inputs=(CCDType(FIELD, NOMINAL), CCDType(FIELD, NOMINAL)),
        output=CCDType(FIELD, NOMINAL),
        inherit_support_from=0,
        same_support_slots=((0, 1),),
        description="Combine two classified fields into one classified field.",
    ),
)

CATALOGUE = {entry.name: entry for entry in _ENTRIES}


def get(name: str) -> Transformation:
    """Look a transformation up by name, raising KeyError with a useful list."""
    try:
        return CATALOGUE[name]
    except KeyError:
        raise KeyError(
            "no transformation named {0!r}. Known: {1}".format(
                name, ", ".join(sorted(CATALOGUE))
            )
        ) from None


def producing(required: CCDType, from_type: Optional[CCDType] = None) -> tuple:
    """Transformations that would produce required, given from_type to work on.

    This is what turns a rejection into advice, so it has to answer on every
    axis and not only on the core concept. A transformation qualifies when some
    slot accepts from_type and the output computed for that argument satisfies
    required, which matters for the entries that inherit an axis: Constrain
    declares its output support as the top term and only fixes it once it knows
    its input.

    The remaining slots are filled with the types they declare, which is an
    approximation: it assumes an input of exactly the declared type is
    available. It over-reports only when a slot could not in fact be filled.
    """
    found = []
    for entry in _ENTRIES:
        if from_type is None:
            if required.subsumes(entry.output):
                found.append(entry.name)
            continue
        slot = next(
            (
                index
                for index, declared in enumerate(entry.inputs)
                if declared.subsumes(from_type)
            ),
            None,
        )
        if slot is None:
            continue
        arguments = list(entry.inputs)
        arguments[slot] = from_type
        if required.subsumes(entry.output_type(arguments)):
            found.append(entry.name)
    return tuple(found)
