"""Fail the build when a failure is logged where nobody will see it.

Phase 0 swept 22 sites in ``main.py`` that logged a caught exception at DEBUG
level while the configured level was INFO - the failure was recorded in a
place that never printed. Ruff's BLE001 catches the blind ``except``; nothing
catches the invisible log. This does.

    LOG001  logger.debug(...) inside an except handler
    LOG002  except handler with no logging and no re-raise (reported, not fatal)

Escape hatch: put ``# noqa: LOG001`` on the offending line when DEBUG really is
right - a probe whose failure is expected and already surfaced elsewhere.

    python scripts/lint_excepts.py [paths...]
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGETS = [ROOT / "backend"]
SKIP_PARTS = {"tests", "__pycache__", ".venv", "node_modules"}


class Finding:
    __slots__ = ("code", "col", "line", "message", "path")

    def __init__(self, path: Path, line: int, col: int, code: str, message: str) -> None:
        self.path = path
        self.line = line
        self.col = col
        self.code = code
        self.message = message

    def __str__(self) -> str:
        rel = self.path.relative_to(ROOT) if self.path.is_relative_to(ROOT) else self.path
        return f"{rel}:{self.line}:{self.col}: {self.code} {self.message}"


def _is_logger_call(node: ast.AST, method: str) -> bool:
    """True for `<something log-ish>.<method>(...)`."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr != method:
        return False
    target = node.func.value
    name = ""
    if isinstance(target, ast.Name):
        name = target.id
    elif isinstance(target, ast.Attribute):
        name = target.attr
    return "log" in name.lower()


def _reraises(handler: ast.ExceptHandler) -> bool:
    return any(isinstance(n, ast.Raise) for n in ast.walk(handler))


def _logs_visibly(handler: ast.ExceptHandler) -> bool:
    return any(
        _is_logger_call(n, m)
        for n in ast.walk(handler)
        for m in ("info", "warning", "error", "exception", "critical")
    )


def check_file(path: Path) -> list[Finding]:
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [Finding(path, exc.lineno or 1, exc.offset or 1, "LOG000", f"syntax error: {exc.msg}")]

    lines = source.splitlines()
    findings: list[Finding] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue

        for inner in ast.walk(node):
            if not _is_logger_call(inner, "debug"):
                continue
            line_text = lines[inner.lineno - 1] if 0 < inner.lineno <= len(lines) else ""
            if "noqa: LOG001" in line_text:
                continue
            findings.append(
                Finding(
                    path,
                    inner.lineno,
                    inner.col_offset + 1,
                    "LOG001",
                    "caught exception logged at DEBUG - invisible at the configured level; "
                    "use warning/exception, or add `# noqa: LOG001` with a reason",
                )
            )

        if not _logs_visibly(node) and not _reraises(node):
            handler_line = lines[node.lineno - 1] if 0 < node.lineno <= len(lines) else ""
            if "noqa: LOG002" not in handler_line:
                findings.append(
                    Finding(
                        path,
                        node.lineno,
                        node.col_offset + 1,
                        "LOG002",
                        "except handler neither logs nor re-raises",
                    )
                )

    return findings


def iter_python_files(targets: list[Path]) -> list[Path]:
    files: list[Path] = []
    for target in targets:
        if target.is_file() and target.suffix == ".py":
            files.append(target)
        elif target.is_dir():
            files.extend(p for p in sorted(target.rglob("*.py")) if not SKIP_PARTS.intersection(p.parts))
    return files


def main(argv: list[str]) -> int:
    targets = [Path(a).resolve() for a in argv[1:]] or DEFAULT_TARGETS
    findings = [f for path in iter_python_files(targets) for f in check_file(path)]

    fatal = [f for f in findings if f.code in ("LOG000", "LOG001")]
    advisory = [f for f in findings if f.code == "LOG002"]

    for finding in fatal:
        print(finding)
    if advisory:
        print(f"\n{len(advisory)} silent except handler(s) (LOG002, advisory):")
        for finding in advisory[:15]:
            print(f"  {finding}")
        if len(advisory) > 15:
            print(f"  ... and {len(advisory) - 15} more")

    if fatal:
        print(f"\n{len(fatal)} error(s): a caught failure must be visible at the configured log level.")
        return 1
    print(f"lint_excepts: clean ({len(advisory)} advisory)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
