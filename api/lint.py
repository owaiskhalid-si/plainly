"""The live demo's endpoint: POST {"text": "...", "fix": true} -> the report as JSON.

Runs as a Vercel Python function in production and under site/dev.py locally; both call
`respond()`, so the two never drift. The package is imported from ../src so no install step
is needed on Vercel (vercel.json includes src/ in the function's bundle).
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from plainly import __version__
from plainly.engine import lint_text

MAX_CHARS = 60_000


def respond(body: bytes) -> tuple[int, dict[str, Any]]:
    """Status and JSON for a request body."""
    try:
        data = json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 400, {"error": "Body must be JSON."}
    text = data.get("text") if isinstance(data, dict) else None
    if not isinstance(text, str):
        return 400, {"error": 'Send {"text": "..."}.'}
    if len(text) > MAX_CHARS:
        return 413, {"error": f"Text is over {MAX_CHARS:,} characters."}
    select = data.get("select") if isinstance(data.get("select"), list) else None
    report = lint_text(text, "demo.md", select=select, fix=bool(data.get("fix")))
    out = report.to_dict()
    out["version"] = __version__
    if report.fixed_text is not None:
        out["fixedText"] = report.fixed_text
    return 200, out


def cors(h: BaseHTTPRequestHandler) -> None:
    h.send_header("Access-Control-Allow-Origin", "*")
    h.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    h.send_header("Access-Control-Allow-Headers", "Content-Type")


def send_json(h: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    h.send_response(status)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    h.send_header("Cache-Control", "no-store")
    cors(h)
    h.end_headers()
    h.wfile.write(body)


INFO = {"name": "plainly", "version": __version__, "usage": 'POST {"text": "..."}'}


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        status, payload = respond(self.rfile.read(length))
        send_json(self, status, payload)

    def do_GET(self) -> None:
        send_json(self, 200, INFO)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        cors(self)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return
