"""Propagate the root VERSION file to every place that carries a version literal.

    python scripts/sync_versions.py          # write
    python scripts/sync_versions.py --check  # exit 1 if anything is out of sync (CI)

Targets: frontend/package.json ("version") and pyproject.toml ([project] version).
The backend reads VERSION at runtime (backend/ops/version.py); the frontend
reads it at build time (frontend/next.config.ts).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_version() -> str:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
        raise SystemExit(f"VERSION is not a semantic version: {version!r}")
    return version


def sync_package_json(version: str, check: bool) -> bool:
    path = ROOT / "frontend" / "package.json"
    text = path.read_text(encoding="utf-8")
    current = json.loads(text)["version"]
    if current == version:
        return True
    if check:
        print(f"package.json version {current} != VERSION {version}")
        return False
    new_text = re.sub(r'("version":\s*")[^"]+(")', rf"\g<1>{version}\g<2>", text, count=1)
    path.write_text(new_text, encoding="utf-8")
    print(f"package.json: {current} -> {version}")
    return True


def sync_pyproject(version: str, check: bool) -> bool:
    path = ROOT / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    if not match:
        raise SystemExit("pyproject.toml has no [project] version line")
    current = match.group(1)
    if current == version:
        return True
    if check:
        print(f"pyproject.toml version {current} != VERSION {version}")
        return False
    new_text = text[: match.start(1)] + version + text[match.end(1) :]
    path.write_text(new_text, encoding="utf-8")
    print(f"pyproject.toml: {current} -> {version}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    version = read_version()
    ok = sync_package_json(version, args.check) & sync_pyproject(version, args.check)
    if ok:
        print(f"versions in sync at {version}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
