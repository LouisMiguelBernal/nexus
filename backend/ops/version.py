"""The running build's identity: VERSION file + git SHA + process start time.

Every place that used to carry a literal "0.3.0" reads from here (or, for the
frontend, from the same VERSION file at build time), so a version can only be
bumped in one place and a frontend/backend mismatch can be detected.
"""

from __future__ import annotations

import os
import subprocess
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
_STARTED_AT = time.time()


@lru_cache(maxsize=1)
def version() -> str:
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


@lru_cache(maxsize=1)
def git_sha() -> str:
    """Short commit SHA. ``NEXUS_GIT_SHA`` wins (the packaged app has no git)."""
    env = os.getenv("NEXUS_GIT_SHA", "").strip()
    if env:
        return env[:12]
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--short=7", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    sha = proc.stdout.strip()
    return sha if proc.returncode == 0 and sha else "unknown"


@lru_cache(maxsize=1)
def frontend_sha() -> str:
    """Short SHA of the last commit that touched frontend/. The status bar compares
    the bundle's build stamp against this, so a backend-only commit does not raise
    a false BUILD MISMATCH. ``NEXUS_FRONTEND_SHA`` overrides (packaged app)."""
    env = os.getenv("NEXUS_FRONTEND_SHA", "").strip()
    if env:
        return env[:12]
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "log", "-1", "--format=%h", "--abbrev=7", "--", "frontend"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    sha = proc.stdout.strip()
    return sha if proc.returncode == 0 and sha else "unknown"


def started_at() -> float:
    return _STARTED_AT


def uptime_s() -> float:
    return time.time() - _STARTED_AT


def build_info() -> dict[str, Any]:
    return {
        "version": version(),
        "git_sha": git_sha(),
        "frontend_sha": frontend_sha(),
        "started_at": round(_STARTED_AT, 3),
        "uptime_s": round(uptime_s(), 1),
    }
