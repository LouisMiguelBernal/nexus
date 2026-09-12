"""The HTTP contract, recorded so the extraction can be proved not to change it.

Splitting a 3,400-line module into routers is only safe if "the API did not
change" is a command rather than an opinion. This records the surface before
anything moves and diffs against it afterwards.

    python -m backend.ops.contract snapshot   # record the baseline
    python -m backend.ops.contract check      # diff the live app against it
    python -m backend.ops.contract live       # record/diff response key sets

What is recorded and why:

- ``routes.json`` - method, path, declaration index, and the path/query
  parameter signature of every route. **Declaration order is part of the
  contract**: ``/api/zones/watchlist`` is only reachable because it is
  declared before ``/api/zones/{symbol}``; swap them and "watchlist" is
  matched as ``symbol="WATCHLIST"``. An extraction that regroups routes into
  routers reorders them by construction, so order is asserted, not assumed.
- ``openapi.json`` - the full generated document, for eyeballing a diff.
  Not asserted by the test: it moves with FastAPI's version, and a dependency
  bump failing CI teaches people to ignore the check.
- ``response_keys.json`` - top-level response keys per route, recorded from a
  running instance. This is the half a static tool cannot see, and it is what
  catches a handler that silently starts returning a different shape.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DIR = ROOT / "docs" / "contract"
ROUTES_FILE = CONTRACT_DIR / "routes.json"
OPENAPI_FILE = CONTRACT_DIR / "openapi.json"
RESPONSE_KEYS_FILE = CONTRACT_DIR / "response_keys.json"

# Routes with side effects or an unbounded cost - never probed by `live`.
LIVE_SKIP: frozenset[str] = frozenset(
    {
        "/api/ai/brief",
        "/api/zones/alert",
        "/api/macro/sentinel-update",
        "/api/alerts/telegram/test",
        "/api/blofin/order",
        "/api/risk/kelly",
        "/api/risk/simulate",
        "/api/sentiment/brief-save",
        "/api/sentiment/brief-clear",
    }
)


def _param_spec(param: Any) -> dict[str, Any]:
    """Name, requiredness, default and numeric bounds of one parameter.

    Query validation is part of the wire contract: ``limit=Query(500, ge=30,
    le=1500)`` rejecting 2000 is behaviour a caller depends on.
    """
    info = getattr(param, "field_info", None)
    spec: dict[str, Any] = {"name": param.name, "required": bool(getattr(param, "required", False))}

    default = getattr(info, "default", None)
    if default is not None and type(default).__name__ != "PydanticUndefinedType":
        spec["default"] = default if isinstance(default, str | int | float | bool) else repr(default)

    for bound in ("ge", "le", "gt", "lt"):
        value = getattr(info, bound, None)
        if value is None:
            for meta in getattr(info, "metadata", None) or []:
                value = getattr(meta, bound, None)
                if value is not None:
                    break
        if value is not None:
            spec[bound] = value
    return spec


def _walk(routes: Any, prefix: str = "") -> Any:
    """Flatten ``app.routes`` in matching order, descending into mounted routers.

    FastAPI 0.141 does not flatten ``include_router`` into ``app.routes``: it
    inserts one ``_IncludedRouter`` that holds the sub-router and expands at
    match time. Iterating ``app.routes`` and keeping only ``APIRoute`` - the
    obvious implementation, and the one this file shipped first - therefore saw
    52 of 79 routes and cheerfully reported "contract holds" while journal (10),
    matrix (1), world (9) and sentiment (7) went unchecked. Descending keeps
    the expansion in place, so declaration order stays the order Starlette
    matches in.
    """
    from fastapi.routing import APIRoute

    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
            continue
        included = getattr(route, "original_router", None)
        if included is not None:
            context = getattr(route, "include_context", None)
            yield from _walk(included.routes, prefix + (getattr(context, "prefix", "") or ""))
        elif hasattr(route, "routes"):  # Mount, or an older FastAPI's flattening
            yield from _walk(route.routes, prefix + (getattr(route, "path", "") or ""))


def describe_routes(app: Any) -> list[dict[str, Any]]:
    """Every route in declaration order, with its parameter signature."""
    out: list[dict[str, Any]] = []
    for index, (path, route) in enumerate(_walk(app.routes)):
        dependant = route.dependant
        for method in sorted(set(route.methods or ()) - {"HEAD", "OPTIONS"}):
            out.append(
                {
                    "index": index,
                    "method": method,
                    "path": path,
                    "name": route.name,
                    "path_params": [_param_spec(p) for p in dependant.path_params],
                    "query_params": sorted(
                        (_param_spec(p) for p in dependant.query_params), key=lambda p: str(p["name"])
                    ),
                }
            )
    return out


def load_app() -> Any:
    from backend.main import app

    return app


def snapshot() -> int:
    app = load_app()
    CONTRACT_DIR.mkdir(parents=True, exist_ok=True)
    routes = describe_routes(app)
    ROUTES_FILE.write_text(json.dumps(routes, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    OPENAPI_FILE.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"recorded {len(routes)} route entries -> {ROUTES_FILE.relative_to(ROOT)}")
    print(f"recorded openapi          -> {OPENAPI_FILE.relative_to(ROOT)}")
    return 0


def diff_routes(baseline: list[dict[str, Any]], current: list[dict[str, Any]]) -> list[str]:
    """Human-readable differences. Empty list means the contract holds."""
    problems: list[str] = []

    def key(entry: dict[str, Any]) -> str:
        return f"{entry['method']} {entry['path']}"

    base_by_key = {key(e): e for e in baseline}
    cur_by_key = {key(e): e for e in current}

    for missing in sorted(set(base_by_key) - set(cur_by_key)):
        problems.append(f"REMOVED  {missing}")
    for added in sorted(set(cur_by_key) - set(base_by_key)):
        problems.append(f"ADDED    {added}")

    for k in sorted(set(base_by_key) & set(cur_by_key)):
        before, after = base_by_key[k], cur_by_key[k]
        for field in ("path_params", "query_params"):
            if before[field] != after[field]:
                problems.append(f"PARAMS   {k}: {field} {before[field]} -> {after[field]}")

    # Relative declaration order, restricted to routes present in both.
    shared = [k for k in (key(e) for e in baseline) if k in cur_by_key]
    current_order = [k for k in (key(e) for e in current) if k in base_by_key]
    if shared != current_order:
        for position, (was, now) in enumerate(zip(shared, current_order, strict=False)):
            if was != now:
                problems.append(f"ORDER    position {position}: expected {was!r}, found {now!r}")
                break
    return problems


def check() -> int:
    if not ROUTES_FILE.exists():
        print(f"no baseline at {ROUTES_FILE} - run `python -m backend.ops.contract snapshot` first")
        return 1
    baseline = json.loads(ROUTES_FILE.read_text(encoding="utf-8"))
    current = describe_routes(load_app())
    problems = diff_routes(baseline, current)
    if problems:
        print(f"CONTRACT BROKEN ({len(problems)} difference(s)):")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(f"contract holds: {len(current)} route entries unchanged, declaration order intact")
    return 0


# ---------------------------------------------------------------------------
# live response shapes
# ---------------------------------------------------------------------------


# Routes with a REQUIRED query parameter: without these they answer 422 and the
# shape is never recorded.
REQUIRED_QUERY: dict[str, str] = {
    "/api/world/search": "q=BTC",
    "/api/metrics/history/{symbol}": "metric=obi",
}

# Binance answers 418 (IP ban) after repeated limit breaches, and several routes
# fan out to it - /api/crypto/strip alone fires ten concurrent calls. Probing 66
# routes back-to-back rate-limited the machine and then recorded the degraded
# shapes it had just caused, so the probe paces itself and retries once.
RETRY_STATUSES = frozenset({418, 429, 500, 502, 503, 504})


def _sample_path(path: str, symbol: str) -> str | None:
    """Fill path parameters with something real, or skip the route."""
    filled = (
        path.replace("{symbol}", symbol).replace("{currency}", "BTC").replace("{instrument}", "BTC-PERPETUAL")
    )
    if "{" in filled:
        return None
    query = REQUIRED_QUERY.get(path)
    return f"{filled}?{query}" if query else filled


def _probe(url: str, token: str | None, timeout: float) -> Any:
    request = urllib.request.Request(url)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def live(
    base_url: str,
    symbol: str,
    token: str | None,
    record: bool,
    *,
    delay_s: float = 0.75,
    retry_pause_s: float = 8.0,
) -> int:
    app = load_app()
    entries = [e for e in describe_routes(app) if e["method"] == "GET" and e["path"] not in LIVE_SKIP]

    observed: dict[str, list[str]] = {}
    failures: list[str] = []
    retried: list[str] = []
    for entry in entries:
        url_path = _sample_path(entry["path"], symbol)
        if url_path is None:
            continue
        url = base_url.rstrip("/") + url_path
        payload: Any = None
        try:
            payload = _probe(url, token, 60.0)
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRY_STATUSES:
                failures.append(f"{entry['path']}: HTTP {exc.code}")
                continue
            time.sleep(retry_pause_s)
            try:
                payload = _probe(url, token, 60.0)
                retried.append(entry["path"])
            except (urllib.error.URLError, OSError, ValueError) as retry_exc:
                failures.append(f"{entry['path']}: {retry_exc} (after retry)")
                continue
        except (urllib.error.URLError, OSError, ValueError) as exc:
            failures.append(f"{entry['path']}: {exc}")
            continue
        observed[entry["path"]] = sorted(payload.keys()) if isinstance(payload, dict) else ["<non-object>"]
        time.sleep(delay_s)

    if retried:
        print(f"  recovered on retry ({len(retried)}): {', '.join(retried)}")
    for failure in failures:
        print(f"  unreachable: {failure}")
    if failures and record:
        print("  NOTE: unreachable routes are simply absent from the baseline, never recorded as degraded.")

    if record:
        CONTRACT_DIR.mkdir(parents=True, exist_ok=True)
        RESPONSE_KEYS_FILE.write_text(json.dumps(observed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"recorded {len(observed)} response shapes -> {RESPONSE_KEYS_FILE.relative_to(ROOT)}")
        return 0

    if not RESPONSE_KEYS_FILE.exists():
        print(f"no baseline at {RESPONSE_KEYS_FILE} - run with --record first")
        return 1
    baseline = json.loads(RESPONSE_KEYS_FILE.read_text(encoding="utf-8"))
    problems: list[str] = []
    for path, keys in sorted(observed.items()):
        expected = baseline.get(path)
        if expected is None:
            problems.append(f"NEW     {path}: {keys}")
        elif expected != keys:
            gone = sorted(set(expected) - set(keys))
            new = sorted(set(keys) - set(expected))
            problems.append(f"SHAPE   {path}: -{gone} +{new}")
    for path in sorted(set(baseline) - set(observed)):
        problems.append(f"UNCHECKED {path} (unreachable this run)")

    if problems:
        print(f"RESPONSE SHAPES CHANGED ({len(problems)}):")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(f"response shapes hold: {len(observed)} routes unchanged")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record and check the Nexus HTTP contract")
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("snapshot", help="record the route baseline")
    sub.add_parser("check", help="diff the live app against the baseline")
    live_parser = sub.add_parser("live", help="record/diff top-level response keys from a running instance")
    live_parser.add_argument("--url", default="http://127.0.0.1:8001")
    live_parser.add_argument("--symbol", default="BTCUSDT")
    live_parser.add_argument("--record", action="store_true")
    live_parser.add_argument("--delay", type=float, default=0.75, help="seconds between probes")

    args = parser.parse_args(argv)
    if args.mode == "snapshot":
        return snapshot()
    if args.mode == "check":
        return check()

    from backend.config import NEXUS_DATA_DIR
    from backend.ops.auth import load_token

    return live(args.url, args.symbol, load_token(NEXUS_DATA_DIR), args.record, delay_s=args.delay)


if __name__ == "__main__":
    sys.exit(main())
