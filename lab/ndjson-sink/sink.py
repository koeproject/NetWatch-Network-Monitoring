"""Phase-0 receiver for the engine's Connector push (CLAUDE.md §3).

Lab tool, not product code. It proves the push path works end to end and
keeps the first raw batches on disk, so connector_schema.py is written from
real payloads instead of from the docs.

Runs inside the engine's Docker network. Stdlib only, so the container
needs nothing installed.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

TOKEN = os.environ["SINK_TOKEN"]
PORT = int(os.environ.get("SINK_PORT", "8099"))
KEEP = int(os.environ.get("SINK_KEEP", "20"))  # batches saved per path; the rest are only counted
OUT = Path(__file__).resolve().parent / "captured"

_batches: Counter[str] = Counter()
_lock = Lock()


def _read_body(handler: BaseHTTPRequestHandler) -> bytes:
    length = handler.headers.get("Content-Length")
    if length is not None:
        return handler.rfile.read(int(length))
    # Transfer-Encoding: chunked
    body = bytearray()
    while True:
        size = int(handler.rfile.readline().split(b";")[0].strip(), 16)
        if size == 0:
            handler.rfile.readline()
            return bytes(body)
        body += handler.rfile.read(size)
        handler.rfile.readline()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        body = _read_body(self)

        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            print(f"401 {self.path}: bad or missing Bearer token", flush=True)
            self._reply(401)
            return

        name = re.sub(r"[^A-Za-z0-9_-]", "_", self.path.strip("/")) or "root"
        with _lock:
            _batches[name] += 1
            n = _batches[name]

        lines = len(body.splitlines())
        print(
            f"[{name}] batch {n}: {lines} lines, {len(body)} bytes, "
            f"Content-Type={self.headers.get('Content-Type')}",
            flush=True,
        )

        if n <= KEEP:
            folder = OUT / name
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{n:04d}.ndjson").write_bytes(body)

        self._reply(200)

    def _reply(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass  # the one line per batch above is enough


if __name__ == "__main__":
    print(f"ndjson-sink on :{PORT}, saving first {KEEP} batches per path to {OUT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
