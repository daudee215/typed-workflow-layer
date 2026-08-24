"""A deliberately tiny parser from a controlled phrasing to a target type.

This is not a natural language interface and is not a step towards one. It
recognises three fixed phrasings, listed in GRAMMAR below, and turns each into
a target core concept data type plus any constraints the phrasing carries.
Anything else raises. Writing a real question interface is a research problem
in its own right, and pretending otherwise here would misrepresent what the
package does.

The small part that is worth keeping is the split between the target type and
the constraints. The type says what kind of thing the answer is, which is what
synthesis searches for. The constraints say which transformations must appear
whatever route is taken, which is what stops a type correct workflow from
answering a different question.

Design note on why the target of a proportion is intensive. The proportion of a
district's area above a threshold is a share, and shares do not add up when
districts are merged, so the target quality is IntensiveQuantity and not
ExtensiveQuantity. The covered area itself is extensive. A workflow that stops
at the covered area has answered a different question, and giving the two
questions different target types is what keeps them apart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ccd import CCDType, EXTENSIVE, INTENSIVE, OBJECT, REGION_SUPPORT

GRAMMAR = (
    "proportion of area where <field> <op> <value> [<unit>] for each <object>",
    "total area where <field> <op> <value> [<unit>] for each <object>",
    "mean <field> for each <object>",
)

_OPERATORS = (">=", "<=", "==", ">", "<")

_TERM = r"[A-Za-z_][A-Za-z0-9_]*"
_VALUE = r"-?\d+(?:\.\d+)?"
_OP = r">=|<=|==|>|<"
_UNIT = r"[A-Za-z%]+"

_THRESHOLD_PATTERNS = (
    (
        INTENSIVE,
        re.compile(
            r"^proportion\s+of\s+area\s+where\s+(?P<field>{term})\s*"
            r"(?P<op>{op})\s*(?P<value>{value})\s*(?P<unit>{unit})?\s+"
            r"for\s+each\s+(?P<object>{term})$".format(
                term=_TERM, op=_OP, value=_VALUE, unit=_UNIT
            ),
            re.IGNORECASE,
        ),
    ),
    (
        EXTENSIVE,
        re.compile(
            r"^total\s+area\s+where\s+(?P<field>{term})\s*"
            r"(?P<op>{op})\s*(?P<value>{value})\s*(?P<unit>{unit})?\s+"
            r"for\s+each\s+(?P<object>{term})$".format(
                term=_TERM, op=_OP, value=_VALUE, unit=_UNIT
            ),
            re.IGNORECASE,
        ),
    ),
)

_MEAN_PATTERN = re.compile(
    r"^mean\s+(?P<field>{term})\s+for\s+each\s+(?P<object>{term})$".format(
        term=_TERM
    ),
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Constraint:
    """A condition on a field that the answer must respect."""

    field_term: str
    operator: str
    value: float
    unit: str = ""

    def __str__(self) -> str:
        rendered = self.value
        if float(self.value).is_integer():
            rendered = int(self.value)
        tail = " {0}".format(self.unit) if self.unit else ""
        return "{0} {1} {2}{3}".format(
            self.field_term, self.operator, rendered, tail
        )


@dataclass(frozen=True)
class TransformationRequest:
    """What a question asks for: a target type and the constraints on it."""

    phrasing: str
    target: CCDType
    field_term: str
    object_term: str
    constraints: tuple = ()

    def required_transformations(self) -> frozenset:
        """Transformations that any answering workflow must contain.

        A threshold in the phrasing forces a Constrain step. Without this,
        enumeration happily returns workflows that compute a share of total
        area and never look at the threshold, because those workflows do type
        check.
        """
        if self.constraints:
            return frozenset({"Constrain"})
        return frozenset()

    def describe(self) -> str:
        lines = [
            "phrasing:    " + self.phrasing,
            "target type: " + str(self.target),
            "field term:  " + self.field_term,
            "object term: " + self.object_term,
        ]
        if self.constraints:
            lines.append(
                "constraints: "
                + "; ".join(str(item) for item in self.constraints)
            )
            lines.append(
                "implies:     "
                + ", ".join(sorted(self.required_transformations()))
                + " must appear in any answering workflow"
            )
        else:
            lines.append("constraints: none")
        return "\n".join(lines)


def parse(phrasing: str) -> TransformationRequest:
    """Parse one of the phrasings in GRAMMAR, or raise ValueError."""
    text = " ".join(phrasing.strip().split())
    if text.endswith("?"):
        text = text[:-1].rstrip()

    for quality, pattern in _THRESHOLD_PATTERNS:
        match = pattern.match(text)
        if match is None:
            continue
        unit = match.group("unit") or ""
        constraint = Constraint(
            match.group("field"),
            match.group("op"),
            float(match.group("value")),
            unit,
        )
        return TransformationRequest(
            phrasing=text,
            target=CCDType(OBJECT, quality, REGION_SUPPORT),
            field_term=match.group("field"),
            object_term=match.group("object"),
            constraints=(constraint,),
        )

    match = _MEAN_PATTERN.match(text)
    if match is not None:
        return TransformationRequest(
            phrasing=text,
            # A mean over a zone is intensive for the same reason a proportion
            # is: merging two zones does not let you add their means.
            target=CCDType(OBJECT, INTENSIVE, REGION_SUPPORT),
            field_term=match.group("field"),
            object_term=match.group("object"),
        )

    raise ValueError(
        "cannot parse {0!r}. This parser recognises only:\n  {1}".format(
            phrasing, "\n  ".join(GRAMMAR)
        )
    )
