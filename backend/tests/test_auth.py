"""Local API token middleware (backend/ops/auth.py)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.ops.auth import TokenAuthMiddleware, ensure_token, is_protected, load_token, token_path


def _app(token: str | None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(TokenAuthMiddleware, token=token)

    @app.get("/api/thing")
    async def thing() -> dict:
        return {"ok": True}

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    return app


def test_protected_routes_require_the_token():
    client = TestClient(_app("s3cret"))
    assert client.get("/api/thing").status_code == 401
    assert client.get("/api/thing", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/thing", headers={"Authorization": "Bearer s3cret"}).json() == {"ok": True}
    assert client.get("/api/thing", headers={"X-Nexus-Token": "s3cret"}).status_code == 200
    assert client.get("/api/thing?token=s3cret").status_code == 200


def test_open_paths_and_cors_preflight_bypass_auth():
    client = TestClient(_app("s3cret"))
    assert client.get("/healthz").status_code == 200
    assert client.options("/api/thing").status_code != 401


def test_401_is_explicit():
    response = TestClient(_app("s3cret")).get("/api/thing")
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"] == "unauthorized"


def test_no_token_configured_means_no_enforcement():
    assert TestClient(_app(None)).get("/api/thing").status_code == 200


def test_is_protected():
    assert is_protected("/api/health")
    assert is_protected("/ws/stream")
    assert not is_protected("/healthz")
    assert not is_protected("/docs")


def test_ensure_and_load_token(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUS_API_TOKEN", raising=False)
    assert load_token(tmp_path) is None
    token = ensure_token(tmp_path)
    assert len(token) >= 32
    assert token_path(tmp_path).is_file()
    assert load_token(tmp_path) == token
    assert ensure_token(tmp_path) == token  # idempotent
    monkeypatch.setenv("NEXUS_API_TOKEN", "from-env")
    assert load_token(tmp_path) == "from-env"
