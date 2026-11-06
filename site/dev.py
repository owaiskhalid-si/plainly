"""Serve the site locally with the same /api/lint handler Vercel runs.

python site/dev.py            # http://localhost:3900
python site/dev.py 8000
"""

from __future__ import annotations

import importlib.util
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

spec = importlib.util.spec_from_file_location("lint_api", ROOT / "api" / "lint.py")
assert spec is not None and spec.loader is not None
lint_api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lint_api)


class Handler(SimpleHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path.split("?")[0] == "/api/lint":
            length = int(self.headers.get("content-length") or 0)
            status, payload = lint_api.respond(self.rfile.read(length))
            lint_api.send_json(self, status, payload)
            return
        self.send_error(404)

    def do_GET(self) -> None:
        if self.path.split("?")[0] == "/api/lint":
            lint_api.send_json(self, 200, lint_api.INFO)
            return
        super().do_GET()

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3900
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(SITE)))
    print(f"plainly site at http://localhost:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
