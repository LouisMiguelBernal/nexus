"""ops.logging - JSON file sink, request correlation; and the lint_excepts guard."""

import importlib.util
import json
import logging
from pathlib import Path

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.ops.logging import RequestIdMiddleware, bind_service, configure_logging, log_path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


@pytest.fixture
def isolated_logging():
    """Restore the root logger afterwards so one test cannot reconfigure the suite."""
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    yield
    structlog.contextvars.clear_contextvars()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    for handler in saved_handlers:
        root.addHandler(handler)
    root.setLevel(saved_level)


def _read_json_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_existing_stdlib_loggers_become_json_without_touching_call_sites(tmp_path, isolated_logging):
    configure_logging(level="INFO", data_dir=tmp_path, force=True)
    # Exactly how the ~120 existing call sites log today.
    logging.getLogger("nexus.somewhere").warning("funding poll failed for %s: %s", "BTCUSDT", "timeout")

    records = _read_json_lines(log_path(tmp_path))
    assert len(records) == 1
    record = records[0]
    assert record["event"] == "funding poll failed for BTCUSDT: timeout"
    assert record["level"] == "warning"
    assert record["logger"] == "nexus.somewhere"
    assert record["timestamp"].endswith("Z") or "T" in record["timestamp"]


def test_exception_tracebacks_reach_the_file(tmp_path, isolated_logging):
    configure_logging(level="INFO", data_dir=tmp_path, force=True)
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("nexus.x").exception("persist failed")

    record = _read_json_lines(log_path(tmp_path))[0]
    assert record["level"] == "error"
    assert "ValueError: boom" in json.dumps(record)


def test_debug_is_filtered_at_info_level(tmp_path, isolated_logging):
    """The reason LOG001 matters: at INFO, a DEBUG line is written nowhere."""
    configure_logging(level="INFO", data_dir=tmp_path, force=True)
    logging.getLogger("nexus.x").debug("invisible")
    logging.getLogger("nexus.x").warning("visible")
    events = [r["event"] for r in _read_json_lines(log_path(tmp_path))]
    assert events == ["visible"]


def test_bound_service_name_is_attached_to_every_record(tmp_path, isolated_logging):
    configure_logging(level="INFO", data_dir=tmp_path, force=True)
    bind_service("trade_ingest")
    logging.getLogger("nexus.x").warning("tick failed")
    assert _read_json_lines(log_path(tmp_path))[0]["service"] == "trade_ingest"


def test_unwritable_log_dir_degrades_to_console(tmp_path, isolated_logging, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(Path, "mkdir", boom)
    configure_logging(level="INFO", data_dir=tmp_path / "nope", force=True)
    logging.getLogger("nexus.x").warning("still works")  # must not raise


def test_request_id_is_echoed_and_bound(tmp_path, isolated_logging):
    configure_logging(level="INFO", data_dir=tmp_path, force=True)
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/thing")
    async def thing() -> dict:
        logging.getLogger("nexus.route").warning("something odd")
        return {"ok": True}

    client = TestClient(app)

    generated = client.get("/thing")
    assert generated.status_code == 200
    assert len(generated.headers["x-request-id"]) == 16

    supplied = client.get("/thing", headers={"X-Request-ID": "caller-supplied-id"})
    assert supplied.headers["x-request-id"] == "caller-supplied-id"

    records = _read_json_lines(log_path(tmp_path))
    assert records[0]["request_id"] == generated.headers["x-request-id"]
    assert records[1]["request_id"] == "caller-supplied-id"
    assert records[1]["path"] == "/thing" and records[1]["method"] == "GET"


def test_context_does_not_leak_between_requests(tmp_path, isolated_logging):
    configure_logging(level="INFO", data_dir=tmp_path, force=True)
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/a")
    async def a() -> dict:
        return {}

    TestClient(app).get("/a", headers={"X-Request-ID": "first"})
    logging.getLogger("nexus.background").warning("after the request")
    assert "request_id" not in _read_json_lines(log_path(tmp_path))[-1]


# ---------------------------------------------------------------------------
# the guard that keeps this from rotting
# ---------------------------------------------------------------------------


def _load_linter():
    spec = importlib.util.spec_from_file_location("lint_excepts", SCRIPTS / "lint_excepts.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lint_excepts_flags_debug_in_handler_and_honours_noqa(tmp_path):
    linter = _load_linter()
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import logging\n"
        "logger = logging.getLogger('x')\n"
        "def f():\n"
        "    try:\n"
        "        pass\n"
        "    except Exception as e:\n"
        "        logger.debug('swallowed: %s', e)\n"
        "def g():\n"
        "    try:\n"
        "        pass\n"
        "    except Exception as e:\n"
        "        logger.debug('fine: %s', e)  # noqa: LOG001\n"
        "def h():\n"
        "    try:\n"
        "        pass\n"
        "    except Exception as e:\n"
        "        logger.warning('seen: %s', e)\n",
        encoding="utf-8",
    )
    codes = [(f.code, f.line) for f in linter.check_file(sample)]
    assert ("LOG001", 7) in codes
    assert not any(c == "LOG001" and ln == 12 for c, ln in codes), "noqa must suppress"
    assert not any(c == "LOG001" and ln == 17 for c, ln in codes)


def test_lint_excepts_flags_silent_handler_but_not_a_reraise(tmp_path):
    linter = _load_linter()
    sample = tmp_path / "silent.py"
    sample.write_text(
        "def f():\n"
        "    try:\n"
        "        pass\n"
        "    except Exception:\n"
        "        pass\n"
        "def g():\n"
        "    try:\n"
        "        pass\n"
        "    except Exception:\n"
        "        raise\n",
        encoding="utf-8",
    )
    codes = {(f.code, f.line) for f in linter.check_file(sample)}
    assert ("LOG002", 4) in codes
    assert not any(c == "LOG002" and ln == 9 for c, ln in codes), "re-raising is not silent"


def test_backend_has_no_invisible_failures():
    """The real guard: backend/ must stay free of LOG001."""
    linter = _load_linter()
    backend = Path(__file__).resolve().parents[1]
    fatal = [
        f
        for path in linter.iter_python_files([backend])
        for f in linter.check_file(path)
        if f.code in ("LOG000", "LOG001")
    ]
    assert not fatal, "\n".join(str(f) for f in fatal)
