"""Local API token for the backend.

Single operator, single machine - this is not user management. The point is
that the backend serves signed Binance account reads and (in Phase 3) paper
orders, and it used to listen on 0.0.0.0 with no check at all. A random
token on disk, presented by the Electron shell and the dev tooling, keeps
anything else on the LAN out.

Token discovery order: ``NEXUS_API_TOKEN`` env, then ``<NEXUS_DATA_DIR>/api_token``.
When neither exists the middleware is not installed and the backend logs a
warning, so an older launcher keeps working until it is rebuilt.

Accepted on protected routes: ``Authorization: Bearer <token>``,
``X-Nexus-Token: <token>``, or ``?token=<token>`` (for WebSocket clients).
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
from collections.abc import Awaitable, Callable, MutableMapping
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

logger = logging.getLogger("nexus.auth")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

TOKEN_FILE = "api_token"
PROTECTED_PREFIXES: tuple[str, ...] = ("/api/", "/ws/")
OPEN_PATHS: frozenset[str] = frozenset({"/healthz", "/readyz"})


def token_path(data_dir: Path) -> Path:
    return data_dir / TOKEN_FILE


def load_token(data_dir: Path) -> str | None:
    env = os.getenv("NEXUS_API_TOKEN", "").strip()
    if env:
        return env
    path = token_path(data_dir)
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip() or None
    except OSError as exc:
        logger.warning("could not read %s: %s", path, exc)
    return None


def describe_source(data_dir: Path) -> str:
    if os.getenv("NEXUS_API_TOKEN", "").strip():
        return "env NEXUS_API_TOKEN"
    return str(token_path(data_dir))


def ensure_token(data_dir: Path) -> str:
    """Return the configured token, generating and persisting one if none exists."""
    existing = load_token(data_dir)
    if existing:
        return existing
    data_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    path = token_path(data_dir)
    path.write_text(token + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass  # Windows ACLs; the directory is per-user anyway
    logger.info("generated API token at %s", path)
    return token


def is_protected(path: str) -> bool:
    return path not in OPEN_PATHS and path.startswith(PROTECTED_PREFIXES)


def _presented_token(scope: Scope) -> str | None:
    headers: dict[str, str] = {
        k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
    }
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    custom = headers.get("x-nexus-token", "").strip()
    if custom:
        return custom
    query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
    values = query.get("token")
    return values[0] if values else None


class TokenAuthMiddleware:
    """Pure-ASGI bearer-token gate for ``/api/*`` and ``/ws/*``.

    Installed inside CORS so a rejected browser request still receives CORS
    headers and the UI can read the 401 instead of a network error.
    """

    def __init__(self, app: ASGIApp, token: str | None) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            not self.token
            or scope["type"] not in ("http", "websocket")
            or not is_protected(scope.get("path", ""))
            or scope.get("method") == "OPTIONS"
        ):
            await self.app(scope, receive, send)
            return

        presented = _presented_token(scope)
        if presented is not None and hmac.compare_digest(presented, self.token):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401})
            return

        body = (
            b'{"error":"unauthorized","hint":"send Authorization: Bearer <token>; '
            b'the token lives in NEXUS_DATA_DIR/api_token"}'
        )
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


if __name__ == "__main__":
    from backend.config import NEXUS_DATA_DIR

    ensure_token(NEXUS_DATA_DIR)
    print(f"API token ready at {token_path(NEXUS_DATA_DIR)}")
