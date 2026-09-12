"""The HTTP surface must not move while main.py is decomposed.

Importing ``backend.main`` here is deliberate: this is the one test that has to
see the real application exactly as uvicorn does, mounted routers included.
"""

import json
from pathlib import Path

import pytest

from backend.ops.contract import ROUTES_FILE, describe_routes, diff_routes

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def routes() -> list[dict]:
    from backend.main import app

    return describe_routes(app)


@pytest.fixture(scope="module")
def baseline() -> list[dict]:
    assert ROUTES_FILE.exists(), "run: uv run python -m backend.ops.contract snapshot"
    return json.loads(ROUTES_FILE.read_text(encoding="utf-8"))


def paths_in_order(entries: list[dict]) -> list[str]:
    return [e["path"] for e in entries]


# ---------------------------------------------------------------------------
# the whole surface
# ---------------------------------------------------------------------------


def test_route_surface_is_unchanged(routes, baseline):
    problems = diff_routes(baseline, routes)
    assert not problems, "\n".join(problems)


def test_every_mounted_router_is_represented(routes):
    """The walker bug this guards against: FastAPI 0.141 keeps an included
    router as a single _IncludedRouter in app.routes instead of flattening it,
    so a naive `isinstance(r, APIRoute)` scan saw 52 of 79 routes and reported
    the contract intact while 27 went unchecked."""
    counts = {
        prefix: sum(1 for p in paths_in_order(routes) if p.startswith(prefix))
        for prefix in ("/api/journal/", "/api/matrix/", "/api/world/", "/api/sentiment/")
    }
    assert counts == {
        "/api/journal/": 10,
        "/api/matrix/": 1,
        "/api/world/": 9,
        "/api/sentiment/": 7,
    }, counts
    assert len(routes) == 79, f"expected 79 route entries, found {len(routes)}"


# ---------------------------------------------------------------------------
# declaration order: the part a reorganisation silently breaks
# ---------------------------------------------------------------------------


def test_zones_watchlist_is_declared_before_the_parameterised_route(routes):
    """Register /api/zones/{symbol} first and 'watchlist' is swallowed as
    symbol='WATCHLIST' - a 200 with the wrong body, not an error."""
    order = paths_in_order(routes)
    assert order.index("/api/zones/watchlist") < order.index("/api/zones/{symbol}")


def test_symbols_search_is_declared_before_any_symbol_parameter_route(routes):
    """Latent today (no /api/symbols/{x} exists). If one is ever added to
    api/market.py or api/chart.py, search must still win."""
    order = paths_in_order(routes)
    search = order.index("/api/symbols/search")
    shadows = [i for i, p in enumerate(order) if p.startswith("/api/symbols/{")]
    assert all(search < i for i in shadows), order[search : max(shadows or [search]) + 1]


def test_bare_sentiment_route_coexists_with_the_router_children(routes):
    order = paths_in_order(routes)
    assert "/api/sentiment" in order
    children = [p for p in order if p.startswith("/api/sentiment/")]
    assert len(children) == 7, children
    # The children are literal paths, so the bare route cannot shadow them
    # wherever it sits - but assert the relationship that makes that true.
    assert all("{" not in p for p in children)


# ---------------------------------------------------------------------------
# query validation is part of the wire contract
# ---------------------------------------------------------------------------


def test_query_bounds_are_recorded_for_the_routes_that_have_them(routes):
    by_path = {(e["method"], e["path"]): e for e in routes}

    merged = by_path[("GET", "/api/book/merged/{symbol}")]
    depth = next(p for p in merged["query_params"] if p["name"] == "depth")
    assert depth["default"] == 20 and depth["ge"] == 1 and depth["le"] == 100

    derivatives = by_path[("GET", "/api/derivatives/{symbol}")]
    limit = next(p for p in derivatives["query_params"] if p["name"] == "limit")
    assert limit["default"] == 500 and limit["ge"] == 30 and limit["le"] == 1500


def test_open_paths_are_exactly_the_unauthenticated_ones(routes):
    """ops.auth guards /api/ and /ws/ only; /healthz must keep its path or the
    unauthenticated liveness probe starts 401ing."""
    from backend.ops.auth import OPEN_PATHS, is_protected

    order = paths_in_order(routes)
    assert "/healthz" in order
    assert not is_protected("/healthz")
    for path in order:
        if path.startswith("/api/"):
            assert is_protected(path), path
    assert "/readyz" in OPEN_PATHS, "reserved for the readiness probe added in step 12"
