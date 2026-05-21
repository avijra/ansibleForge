"""Lightweight threaded HTTP health server.

Runs on ``port + 1`` in a daemon thread so Tauri can always check backend
liveness even when the asyncio event loop is saturated by agent work.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from ansible_forge import __version__

logger = logging.getLogger(__name__)

_status: dict[str, object] = {
    "status": "starting",
    "version": __version__,
    "updated_at": time.time(),
}
_status_lock = threading.Lock()


def update_status(new_status: str) -> None:
    with _status_lock:
        _status["status"] = new_status
        _status["updated_at"] = time.time()


def get_status() -> dict[str, object]:
    with _status_lock:
        return dict(_status)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in ("/health", "/"):
            body = json.dumps(get_status()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        pass


def start(port: int) -> threading.Thread:
    health_port = port + 1

    def _serve() -> None:
        try:
            server = HTTPServer(("127.0.0.1", health_port), _Handler)
            server.timeout = 1
            logger.info("health_thread_started port=%d", health_port)
            server.serve_forever()
        except OSError:
            logger.warning("health_thread_port_conflict port=%d", health_port)

    t = threading.Thread(target=_serve, name="health-thread", daemon=True)
    t.start()
    return t
