"""Core concept data types for geo-analytical question answering.

A core concept data type is a triple: a core concept (after Kuhn's core
concepts of spatial information), a measurement or quality level, and a
support. Each axis is a small subsumption lattice. A dataset is admissible in
a transformation slot when the type declared for the slot subsumes the type of
the dataset.

Where the hierarchy lives. Not here. `ontology/ccd.ttl` is an OWL ontology and
this module reads it at import through `owl.py`, building one parent map per
axis from the rdfs:subClassOf axioms. Nothing below hard-codes a parent, so
editing the lattice means editing the ontology, and the same file can be handed
to a reasoner. The modelling arguments that used to sit in comments here are
rdfs:comment annotations there, next to the axiom each one justifies.

Design note on the shape of the model. The three axes are kept independent and
compared componentwise, rather than flattened into one hierarchy of named
composite types such as PointMeasures or ExistenceRaster. Componentwise
comparison is weaker: it cannot express that some combinations of concept,
quality and support are meaningless. It is enough to reject the chains this
package is about. The cost is a constraint the loader enforces rather than
assumes: each axis must be a single chain, so a class declaring two
superclasses raises at import instead of quietly changing what subsumes what.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import owl

ONTOLOGY = owl.Ontology(owl.load())

# The three axis roots, identified by the ccd:axis annotation rather than by
# name, so renaming a root in the ontology is caught here instead of producing
# an empty axis.
_AXIS_PROPERTY = "https://daudee.com/ns/ccd#axis"
_ROOTS = {}
for _subject, _predicate, _object in ONTOLOGY.triples:
    if _predicate == _AXIS_PROPERTY:
        _ROOTS[_object.strip('"')] = _subject
if set(_ROOTS) != {"core concept", "quality", "support"}:
    raise owl.OntologyError(
        "expected three ccd:axis roots, found {0!r}".format(sorted(_ROOTS)))

# Term names, read back from the ontology so a typo here fails at import.
ANY_CONCEPT = "AnyConcept"
FIELD = "Field"
OBJECT = "Object"
NETWORK = "Network"
EVENT = "Event"

ANY_QUALITY = "AnyQuality"
NOMINAL = "Nominal"
ORDINAL = "Ordinal"
INTERVAL = "Interval"
RATIO = "Ratio"
EXTENSIVE = "ExtensiveQuantity"
INTENSIVE = "IntensiveQuantity"
COUNT = "Count"

ANY_SUPPORT = "AnySupport"
POINT_SUPPORT = "PointSupport"
REGION_SUPPORT = "RegionSupport"
LATTICE_SUPPORT = "LatticeSupport"

# One parent map per axis, derived from the rdfs:subClassOf axioms. The names
# below are the same ones the ontology declares; single_parent_map raises if a
# class under a root has anything other than exactly one superclass.
CONCEPT_PARENT = ONTOLOGY.single_parent_map(_ROOTS["core concept"])
QUALITY_PARENT = ONTOLOGY.single_parent_map(_ROOTS["quality"])
SUPPORT_PARENT = ONTOLOGY.single_parent_map(_ROOTS["support"])

# Every constant this module exports must be a term the ontology declares.
# Without this check a renamed class in the ontology would leave a constant
# pointing at nothing, and the failure would surface as an unrelated
# ValueError deep inside a type check rather than here.
for _axis_map, _expected in (
    (CONCEPT_PARENT, (ANY_CONCEPT, FIELD, OBJECT, NETWORK, EVENT)),
    (QUALITY_PARENT, (ANY_QUALITY, NOMINAL, ORDINAL, INTERVAL, RATIO,
                      EXTENSIVE, INTENSIVE, COUNT)),
    (SUPPORT_PARENT, (ANY_SUPPORT, POINT_SUPPORT, REGION_SUPPORT,
                      LATTICE_SUPPORT)),
):
    _missing = [term for term in _expected if term not in _axis_map]
    if _missing:
        raise owl.OntologyError(
            "the ontology does not declare {0}".format(", ".join(_missing)))
    _extra = sorted(set(_axis_map) - set(_expected))
    if _extra:
        raise owl.OntologyError(
            "the ontology declares {0}, which this module does not export. Add "
            "a constant for it or remove it".format(", ".join(_extra)))

# (readable axis label, attribute name on CCDType, parent map)
_AXES = (
    ("core concept", "concept", CONCEPT_PARENT),
    ("quality", "quality", QUALITY_PARENT),
    ("support", "support", SUPPORT_PARENT),
)


def _subsumes(parents: dict, general: str, specific: str) -> bool:
    """True when general is specific, or an ancestor of it, in one axis."""
    node = specific
    while node is not None:
        if node == general:
            return True
        node = parents[node]
    return False


@dataclass(frozen=True)
class AxisMismatch:
    """One axis on which a required type fails to subsume an actual type."""

    axis: str
    required: str
    actual: str

    def __str__(self) -> str:
        return (
            "{0:<14}{1} required, {2} given. {1} does not subsume {2}."
            .format(self.axis + ":", self.required, self.actual)
        )


@dataclass(frozen=True)
class CCDType:
    """An immutable, hashable core concept data type.

    Unspecified axes default to their top element, which acts as a wildcard in
    a transformation signature.
    """

    concept: str = ANY_CONCEPT
    quality: str = ANY_QUALITY
    support: str = ANY_SUPPORT

    def __post_init__(self) -> None:
        for label, attr, parents in _AXES:
            value = getattr(self, attr)
            if value not in parents:
                raise ValueError("unknown {0} term: {1!r}".format(label, value))

    def __str__(self) -> str:
        return "{0}({1}, {2})".format(self.concept, self.quality, self.support)

    def subsumes(self, other: "CCDType") -> bool:
        """True when self is other, or more general than other, on every axis."""
        return all(
            _subsumes(parents, getattr(self, attr), getattr(other, attr))
            for _, attr, parents in _AXES
        )

    def mismatches(self, other: "CCDType") -> tuple:
        """The axes on which self, read as a requirement, rejects other."""
        found = []
        for label, attr, parents in _AXES:
            required = getattr(self, attr)
            actual = getattr(other, attr)
            if not _subsumes(parents, required, actual):
                found.append(AxisMismatch(label, required, actual))
        return tuple(found)

    def unify(self, other: "CCDType") -> Optional["CCDType"]:
        """The more specific of two comparable types, or None if incompatible.

        Returns None as soon as one axis holds two terms neither of which
        subsumes the other, for example Field against Object. That is the check
        the whole package rests on: no unifier means no workflow.
        """
        parts = []
        for _, attr, parents in _AXES:
            a = getattr(self, attr)
            b = getattr(other, attr)
            if _subsumes(parents, a, b):
                parts.append(b)
            elif _subsumes(parents, b, a):
                parts.append(a)
            else:
                return None
        return CCDType(*parts)

    def with_axes(
        self,
        concept: Optional[str] = None,
        quality: Optional[str] = None,
        support: Optional[str] = None,
    ) -> "CCDType":
        """A copy with the named axes replaced. Used for inherited axes."""
        return CCDType(
            concept if concept is not None else self.concept,
            quality if quality is not None else self.quality,
            support if support is not None else self.support,
        )

    # Serialisation is the same string a person reads, rather than a nested
    # object with one key per axis. A provenance record is meant to be opened
    # and understood, and three keys per type turns a small graph into pages.
    def serialise(self) -> str:
        return str(self)

    @staticmethod
    def parse(text: str) -> "CCDType":
        """Read back what serialise wrote. Raises ValueError on anything else."""
        cleaned = text.strip()
        if not cleaned.endswith(")") or "(" not in cleaned:
            raise ValueError("not a core concept data type: {0!r}".format(text))
        concept, _, tail = cleaned[:-1].partition("(")
        parts = [item.strip() for item in tail.split(",")]
        if len(parts) != 2:
            raise ValueError("not a core concept data type: {0!r}".format(text))
        return CCDType(concept.strip(), parts[0], parts[1])
