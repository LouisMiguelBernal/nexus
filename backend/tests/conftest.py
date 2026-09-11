"""Pytest bootstrap - add the repo root to sys.path so `backend.*` imports resolve.

Run from `E:/nexus` with:

    pytest backend/tests/ -q
"""

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
