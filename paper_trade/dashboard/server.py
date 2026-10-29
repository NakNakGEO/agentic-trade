"""Tiny local web server: the page, its code files, JSON endpoints, and a live push stream."""

from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from paper_trade.dashboard import stream
from paper_trade.dashboard.routes import ROUTES, list_runs, mode_of  # noqa: F401  (list_runs is part of the public API)

STATIC = Path(__file__).parent / "static"
KINDS = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
STATIC_NAME = re.compile(r"^[A-Za-z0-9_]+\.(html|js|css)$")


def make_handler(default_run: str):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _static(self, name: str) -> None:
            path = STATIC / name
            if STATIC_NAME.match(name) and path.is_file():
                self._send(200, path.read_bytes(), KINDS[path.suffix])
            else:
                self._send(404, b"not found", "text/plain")

        def _stream(self, run: str, mode: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            stream.serve(self.wfile, run, mode)

        def do_GET(self) -> None:                                  # noqa: N802
            url = urlparse(self.path)
            query = parse_qs(url.query)
            run = query.get("run", [default_run])[0]
            if url.path == "/":
                self._static("index.html")
            elif url.path == "/charts":
                self._static("charts.html")
            elif url.path.startswith("/static/"):
                self._static(url.path[len("/static/"):])
            elif url.path == "/api/stream":
                self._stream(run, mode_of(query))
            elif url.path in ROUTES:
                try:
                    payload = {"ok": True, "data": ROUTES[url.path](run, query)}
                except Exception as exc:                           # keep the page alive on bad reads
                    payload = {"ok": False, "error": str(exc)[:300]}
                self._send(200, json.dumps(payload, default=str).encode(), "application/json")
            else:
                self._send(404, b"not found", "text/plain")

        def log_message(self, *args) -> None:                      # keep the console quiet
            pass

    return Handler


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="paper_trade.dashboard")
    parser.add_argument("--run", default="replay2")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(args.run))
    print(f"dashboard for run '{args.run}' on http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()
