"""backend.data.http - strict-first fetch, HTTP errors never downgrade TLS, downgrades are logged once."""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from backend.data import http as nexus_http


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        if self.path == "/ok":
            body = json.dumps({"hello": "world"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        else:
            body = b"nope"
            self.send_response(404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # silence
        pass


@pytest.fixture(scope="module")
def server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_fetch_json_over_plain_http(server):
    assert nexus_http.fetch_json(f"{server}/ok") == {"hello": "world"}


def test_http_error_is_a_status_error_and_never_a_downgrade(server):
    before = dict(nexus_http.tls_downgrade_counts())
    with pytest.raises(nexus_http.HttpStatusError) as exc_info:
        nexus_http.fetch_json(f"{server}/missing")
    assert exc_info.value.status == 404
    assert exc_info.value.body == "nope"
    assert nexus_http.tls_downgrade_counts() == before


def test_transport_failure_propagates_when_permissive_retry_is_forbidden():
    with pytest.raises(OSError):  # URLError / timeout are OSError subclasses
        nexus_http.fetch_json("http://127.0.0.1:9/", timeout=0.5, permissive_ok=False)


def test_downgrade_is_logged_once_per_host_and_counted_every_time(caplog):
    host = "example.invalid"
    before = nexus_http.tls_downgrade_counts().get(host, 0)
    with caplog.at_level(logging.DEBUG, logger="nexus.http"):
        nexus_http._note_downgrade(host, RuntimeError("certificate verify failed"))
        nexus_http._note_downgrade(host, RuntimeError("certificate verify failed"))
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and host in r.getMessage()]
    assert len(warnings) == 1
    assert nexus_http.tls_downgrade_counts()[host] == before + 2
