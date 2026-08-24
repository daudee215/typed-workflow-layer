"""Test package for the typed workflow layer.

The package root is put on sys.path here so that `python3 -m unittest discover
-s tests` works from the project directory without an installation step and
without a -t argument.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
