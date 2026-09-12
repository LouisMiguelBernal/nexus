"""Structured logging.

The backend logs through stdlib ``logging.getLogger("nexus.*")`` in ~120
places. Rather than rewrite those call sites, this wires structlog's
``ProcessorFormatter`` underneath the stdlib root logger, so every existing
``logger.warning("...", exc_info=True)`` becomes a JSON line with no change
at the call site.

Two handlers:

- **console** - human-readable, for ``just dev-backend`` and the Electron
  console, which is where the operator actually watches the app;
- **file** - JSON lines at ``NEXUS_DATA_DIR/logs/backend.jsonl``, rotated at
  20 MB x 5, so a failure at 3am is still there in the morning.

Every record carries the request id of the HTTP request that caused it (or
the name of the background service), which is the part that was missing: a
warning from a shared helper used to be unattributable.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from pathlib import Path
from typing import Any

import structlog

LOG_FILENAME = "backend.jsonl"
MAX_BYTES = 20 * 1024 * 1024
BACKUP_COUNT = 5
REQUEST_ID_HEADER = b"x-request-id"

# Libraries that are informative at WARNING and noise at INFO.
NOISY_LOGGERS = {
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "websockets.client": logging.WARNING,
    "websockets.server": logging.WARNING,
    "urllib3": logging.WARNING,
    "asyncio": logging.WARNING,
    "aiosqlite": logging.WARNING,
    "transformers": logging.WARNING,
    "filelock": logging.WARNING,
}

_configured = False


def _shared_processors() -> list[Any]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]


def configure_logging(
    *,
    level: str | int = "INFO",
    data_dir: Path | None = None,
    console_json: bool = False,
    force: bool = False,
) -> None:
    """Install the console + rotating-JSON handlers on the root logger.

    Idempotent unless ``force``; safe to call from tests.
    """
    global _configured
    if _configured and not force:
        return

    shared = _shared_processors()

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # `foreign_pre_chain` is what makes plain stdlib records (every existing
    # logger.warning in the codebase) pass through the same processors.
    #
    # `format_exc_info` is needed for the JSON renderer and must NOT be used
    # with ConsoleRenderer, which formats exceptions itself: without it a
    # logger.exception() reached the console with its traceback and the log
    # file with none, which is the sink that matters at 3am.
    def formatter(renderer: Any, *, render_exceptions: bool) -> structlog.stdlib.ProcessorFormatter:
        processors: list[Any] = [structlog.stdlib.ProcessorFormatter.remove_processors_meta]
        if render_exceptions:
            processors.append(structlog.processors.format_exc_info)
        processors.append(renderer)
        return structlog.stdlib.ProcessorFormatter(foreign_pre_chain=shared, processors=processors)

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    console = logging.StreamHandler(stream=sys.stdout)
    console.setFormatter(
        formatter(structlog.processors.JSONRenderer(), render_exceptions=True)
        if console_json
        else formatter(structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty()), render_exceptions=False)
    )
    root.addHandler(console)

    if data_dir is not None:
        log_dir = data_dir / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_dir / LOG_FILENAME,
                maxBytes=MAX_BYTES,
                backupCount=BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setFormatter(
                formatter(structlog.processors.JSONRenderer(sort_keys=True), render_exceptions=True),
            )
            root.addHandler(file_handler)
        except OSError as exc:
            # A read-only data dir must degrade to console logging, never
            # prevent the backend from starting.
            root.warning("file logging disabled: %s", exc)

    root.setLevel(level)
    for name, lvl in NOISY_LOGGERS.items():
        logging.getLogger(name).setLevel(lvl)

    _configured = True


def log_path(data_dir: Path) -> Path:
    return data_dir / "logs" / LOG_FILENAME


# ---------------------------------------------------------------------------
# Request correlation
# ---------------------------------------------------------------------------


def bind_request_id(request_id: str) -> None:
    structlog.contextvars.bind_contextvars(request_id=request_id)


def bind_service(name: str) -> None:
    """Called by a supervised service so its log lines are attributable."""
    structlog.contextvars.bind_contextvars(service=name)


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()


Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class RequestIdMiddleware:
    """Bind a request id to the logging context and echo it back.

    Pure ASGI (like the auth middleware) so it also covers WebSocket scopes,
    which BaseHTTPMiddleware does not.
    """

    def __init__(self, app: ASGIApp, header: bytes = REQUEST_ID_HEADER) -> None:
        self.app = app
        self.header = header

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        incoming = None
        for key, value in scope.get("headers", []):
            if key == self.header:
                incoming = value.decode("latin-1")
                break
        request_id = incoming or uuid.uuid4().hex[:16]

        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            path=scope.get("path", ""),
            method=scope.get("method", scope["type"]),
        )

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((self.header, request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            structlog.contextvars.clear_contextvars()
