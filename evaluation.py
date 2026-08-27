"""Reference-based correctness checks for executed workflow outputs."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class Mismatch:
    """One reference value that was missing, unexpected, or numerically wrong."""

    path: str
    expected: Any
    actual: Any
    absolute_error: Optional[float] = None
    relative_error: Optional[float] = None
    reason: str = "value mismatch"

    def __str__(self) -> str:
        return "{0}: expected {1!r}, got {2!r} ({3})".format(
            self.path, self.expected, self.actual, self.reason
        )


@dataclass(frozen=True)
class EvaluationReport:
    """A compact, serialisable correctness report."""

    passed: bool
    compared: int
    max_absolute_error: float
    max_relative_error: float
    mismatches: tuple = ()

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "compared": self.compared,
            "max_absolute_error": self.max_absolute_error,
            "max_relative_error": self.max_relative_error,
            "mismatches": [
                {
                    "path": item.path,
                    "expected": item.expected,
                    "actual": item.actual,
                    "absolute_error": item.absolute_error,
                    "relative_error": item.relative_error,
                    "reason": item.reason,
                }
                for item in self.mismatches
            ],
        }

    def assert_passed(self) -> None:
        if not self.passed:
            details = "; ".join(str(item) for item in self.mismatches[:3])
            raise AssertionError(
                "reference comparison failed ({0} mismatch(es)): {1}".format(
                    len(self.mismatches), details
                )
            )


def compare(expected: Any, actual: Any, absolute_tolerance: float = 1e-9,
            relative_tolerance: float = 1e-9) -> EvaluationReport:
    """Compare scalars, mappings, and sequences without hiding missing keys.

    The result separates type-valid execution from empirical correctness. A
    workflow can pass the first and fail this comparison, which is precisely
    the distinction a reproducible PhD evaluation needs.
    """
    if absolute_tolerance < 0 or relative_tolerance < 0:
        raise ValueError("tolerances cannot be negative")
    mismatches = []
    compared = 0
    max_absolute = 0.0
    max_relative = 0.0

    def visit(reference: Any, value: Any, path: str) -> None:
        nonlocal compared, max_absolute, max_relative
        if isinstance(reference, Mapping) or isinstance(value, Mapping):
            if not isinstance(reference, Mapping) or not isinstance(value, Mapping):
                mismatches.append(Mismatch(path, reference, value, reason="shape mismatch"))
                return
            keys = sorted(set(reference) | set(value), key=str)
            for key in keys:
                child = "{0}[{1!r}]".format(path, key) if path else repr(key)
                if key not in reference:
                    mismatches.append(Mismatch(child, "<missing>", value[key], reason="unexpected key"))
                elif key not in value:
                    mismatches.append(Mismatch(child, reference[key], "<missing>", reason="missing key"))
                else:
                    visit(reference[key], value[key], child)
            return
        if isinstance(reference, (tuple, list)) or isinstance(value, (tuple, list)):
            if not isinstance(reference, (tuple, list)) or not isinstance(value, (tuple, list)):
                mismatches.append(Mismatch(path, reference, value, reason="shape mismatch"))
                return
            if len(reference) != len(value):
                mismatches.append(Mismatch(path, len(reference), len(value), reason="sequence length mismatch"))
            for index, (left, right) in enumerate(zip(reference, value)):
                visit(left, right, "{0}[{1}]".format(path, index))
            return
        compared += 1
        if (isinstance(reference, (int, float)) and not isinstance(reference, bool)
                and isinstance(value, (int, float)) and not isinstance(value, bool)):
            absolute = abs(float(reference) - float(value))
            scale = max(abs(float(reference)), abs(float(value)), 1e-12)
            relative = absolute / scale
            max_absolute = max(max_absolute, absolute)
            max_relative = max(max_relative, relative)
            if (not math.isfinite(absolute) or
                    absolute > absolute_tolerance and relative > relative_tolerance):
                mismatches.append(Mismatch(path, reference, value, absolute, relative))
            return
        if reference != value:
            mismatches.append(Mismatch(path, reference, value))

    visit(expected, actual, "")
    return EvaluationReport(
        not mismatches, compared, max_absolute, max_relative, tuple(mismatches)
    )

