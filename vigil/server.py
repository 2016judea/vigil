"""VIGIL daemon -- polls the fleet, serves the Face and the CLI.

Localhost only. No egress. The corpus never leaves the machine.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .engine import Engine

HOST, PORT = "127.0.0.1", 7717
POLL_SECONDS = 3.0
HERE = Path(__file__).parent

_engine = Engine()
_state: dict = {"at": 0, "lamp": False, "headline": "Starting up.", "focus": None,
                "sessions": [], "repos": []}
_version = 0
_cv = threading.Condition()


def _poller() -> None:
    global _state, _version
    while True:
        try:
            snap = _engine.snapshot()
        except Exception as exc:  # a poll must never kill the daemon
            snap = {"at": time.time(), "lamp": False,
                    "headline": "Cannot read the fleet.",
                    "error": f"{type(exc).__name__}: {exc}",
                    "focus": None, "sessions": [], "repos": []}
        # only wake the surfaces when something a human would notice changed
        sig = json.dumps([snap.get("headline"), snap.get("lamp"),
                          [(s["id"], s["state"], int(s["quiet_s"] // 5)) for s in snap["sessions"]]],
                         sort_keys=True)
        with _cv:
            changed = sig != _state.get("_sig")
            snap["_sig"] = sig
            _state = snap
            if changed:
                _version += 1
                _cv.notify_all()
        time.sleep(POLL_SECONDS)


def _public(state: dict) -> dict:
    return {k: v for k, v in state.items() if not k.startswith("_")}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # keep the terminal quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]

        if path in ("/", "/index.html"):
            html = (HERE / "face.html").read_bytes()
            return self._send(200, html, "text/html; charset=utf-8")

        if path == "/api/state":
            with _cv:
                body = json.dumps(_public(_state)).encode()
            return self._send(200, body, "application/json; charset=utf-8")

        if path == "/api/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            seen = -1
            try:
                while True:
                    with _cv:
                        if _version == seen:
                            _cv.wait(timeout=20)
                        seen = _version
                        payload = json.dumps(_public(_state))
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            return

        self._send(404, b"not found", "text/plain; charset=utf-8")


def serve() -> None:
    threading.Thread(target=_poller, daemon=True).start()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    httpd.daemon_threads = True
    print(f"vigil -- http://{HOST}:{PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nvigil -- stopped")


if __name__ == "__main__":
    serve()
