"""Test package for the typed workflow layer.

The package root is put on sys.path here so that `python3 -m unittest discover
-s tests` works from the project directory without an installation step and
without a -t argument.

subexpressions() lives here because test_analysis and test_cost both need it
and had a verbatim copy each, under two different names, which is one copy too
many for a function that defines what "the minimum number of steps" means.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def subexpressions(expression):
    """Every distinct non-source call in an expression, as a set of strings.

    The minimum number of steps a workflow with that expression can have, so
    comparing it against len(workflow.steps) detects both a dead step and a
    subexpression computed twice.
    """
    found, depth, start = set(), 0, 0
    for index, character in enumerate(expression):
        if character == "(":
            if depth == 0:
                start = index
                while start > 0 and (expression[start - 1].isalnum()
                                     or expression[start - 1] == "_"):
                    start -= 1
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                span = expression[start:index + 1]
                found.add(span)
                found |= subexpressions(span[span.index("(") + 1:-1])
    return found
