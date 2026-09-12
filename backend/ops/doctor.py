"""Environment doctor: ``just doctor`` / ``python -m backend.ops.doctor``.

Replaces ``scripts/health_check.py``, which imported a config key that had
been deleted months earlier and had raised ImportError ever since. Every
check here reads a real thing; nothing is inferred from configuration.

Exit code 1 when a critical check fails (Python too old, data dir unusable).
Degraded-but-runnable states (Ollama down, no token, sources unreachable)
are reported, not fatal - the app degrades the same way.
"""

from __future__ import annotations

import argparse
import json
import socket
import sqlite3
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from backend.config import DB_PATH, NEXUS_DATA_DIR, OLLAMA_CONFIG, PROJECT_ROOT
from backend.data.http import HttpStatusError, fetch_json, tls_downgrade_counts
from backend.ops.auth import load_token, token_path
from backend.ops.version import build_info


@dataclass
class Check:
    name: str
    status: str  # "ok" | "warn" | "fail" | "skip"
    detail: str


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def _http_json(url: str, timeout: float = 4.0) -> Any:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def check_python() -> Check:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 12)
    return Check("python", "ok" if ok else "fail", f"{v.major}.{v.minor}.{v.micro} at {sys.executable}")


def check_version() -> Check:
    info = build_info()
    return Check("build", "ok", f"v{info['version']} {info['git_sha']}")


def check_data_dir() -> Check:
    try:
        NEXUS_DATA_DIR.mkdir(parents=True, exist_ok=True)
        probe = NEXUS_DATA_DIR / ".doctor_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return Check("data_dir", "fail", f"{NEXUS_DATA_DIR} not writable: {exc}")
    return Check("data_dir", "ok", str(NEXUS_DATA_DIR))


def check_database() -> Check:
    if not DB_PATH.exists():
        return Check("sqlite", "warn", f"{DB_PATH} does not exist yet (created on first backend start)")
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return Check("sqlite", "fail", f"{DB_PATH}: {exc}")
    size_mb = DB_PATH.stat().st_size / 1e6
    return Check("sqlite", "ok", f"{DB_PATH} ({size_mb:.1f} MB, {len(tables)} tables)")


def check_token() -> Check:
    if load_token(NEXUS_DATA_DIR):
        return Check("api_token", "ok", "configured - /api/* requires a bearer token")
    return Check("api_token", "warn", f"none at {token_path(NEXUS_DATA_DIR)} - API auth DISABLED")


def check_env_file() -> Check:
    present = (PROJECT_ROOT / ".env").exists()
    return Check(
        "env_file",
        "ok" if present else "warn",
        ".env present" if present else ".env missing (copy .env.example)",
    )


def check_backend() -> Check:
    if not _port_open(8001):
        return Check("backend", "warn", "port 8001 closed - backend not running")
    data = _http_json("http://127.0.0.1:8001/healthz")
    if isinstance(data, dict):
        return Check("backend", "ok", f"/healthz v{data.get('version')} {data.get('git_sha')}")
    return Check("backend", "warn", "port 8001 open but /healthz did not answer")


def check_frontend() -> Check:
    return Check(
        "frontend",
        "ok" if _port_open(3000) else "warn",
        "port 3000 " + ("open" if _port_open(3000) else "closed"),
    )


def check_ollama() -> Check:
    tags_url = str(OLLAMA_CONFIG.get("tags_endpoint", "http://localhost:11434/api/tags"))
    data = _http_json(tags_url)
    if not isinstance(data, dict):
        return Check("ollama", "warn", "server not reachable on 11434 - AI briefs will fail (see RUNBOOK)")
    names = [m.get("name", "") for m in data.get("models", []) if isinstance(m, dict)]
    want = str(OLLAMA_CONFIG["model"])
    if any(want.split(":")[0] in n for n in names):
        return Check("ollama", "ok", f"up, {want} installed")
    return Check("ollama", "warn", f"up but {want} missing - run: ollama pull {want}")


def check_ai_deps() -> Check:
    parts: list[str] = []
    try:
        import torch

        parts.append(f"torch {torch.__version__} cuda={'yes' if torch.cuda.is_available() else 'no'}")
    except ImportError:
        parts.append("torch missing (FinBERT unavailable; `just setup-ai`)")
    try:
        import transformers

        parts.append(f"transformers {transformers.__version__}")
    except ImportError:
        parts.append("transformers missing")
    status = "ok" if "missing" not in " ".join(parts) else "warn"
    return Check("ai_deps", status, "; ".join(parts))


def check_sources() -> list[Check]:
    probes = {
        "binance_fapi": "https://fapi.binance.com/fapi/v1/ping",
        "fred_csv": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10",
    }
    out: list[Check] = []
    for name, url in probes.items():
        try:
            if name == "fred_csv":
                from backend.data.http import fetch_bytes

                fetch_bytes(url, timeout=8.0)
            else:
                fetch_json(url, timeout=8.0)
            out.append(Check(f"source:{name}", "ok", "reachable"))
        except HttpStatusError as exc:
            out.append(Check(f"source:{name}", "warn", f"HTTP {exc.status}"))
        except Exception as exc:  # noqa: BLE001  # reason: any failure is the finding we report
            out.append(Check(f"source:{name}", "warn", f"unreachable: {exc}"))
    downgrades = tls_downgrade_counts()
    if downgrades:
        out.append(Check("tls", "warn", f"permissive TLS fallback used for: {', '.join(sorted(downgrades))}"))
    else:
        out.append(Check("tls", "ok", "strict TLS succeeded for every probed host"))
    return out


def run(offline: bool = False) -> list[Check]:
    checks = [
        check_python(),
        check_version(),
        check_data_dir(),
        check_database(),
        check_token(),
        check_env_file(),
        check_backend(),
        check_frontend(),
        check_ollama(),
        check_ai_deps(),
    ]
    if offline:
        checks.append(Check("sources", "skip", "--offline"))
    else:
        checks.extend(check_sources())
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Nexus environment doctor")
    parser.add_argument("--offline", action="store_true", help="skip external source probes")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    checks = run(offline=args.offline)
    if args.json:
        print(json.dumps([c.__dict__ for c in checks], indent=2))
    else:
        width = max(len(c.name) for c in checks)
        for c in checks:
            marker = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}[c.status]
            print(f"[{marker}] {c.name.ljust(width)}  {c.detail}")
    failed = [c for c in checks if c.status == "fail"]
    warned = [c for c in checks if c.status == "warn"]
    print(f"\n{len(failed)} failed, {len(warned)} warnings, {len(checks) - len(failed) - len(warned)} ok")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
