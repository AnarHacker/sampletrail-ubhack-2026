"""Serve the interactive local demo or the public synthetic showcase."""

import argparse
import base64
import binascii
import hmac
import json
import os
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from .engine import LABEL
from .fixtures import DIRECTORY, REPORTS, seed_demo
from .store import Store, digest


WEB = Path(__file__).with_name("web")
STATIC = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
FIXTURE_NAMES = {"manifest.csv", "rules.json", "v1.csv", "v1.pdf", "v2.csv", "v2.pdf",
                 "SIM-CERT-A.pdf", "SIM-CERT-B.pdf"}
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8", ".csv": "text/csv; charset=utf-8",
                 ".json": "application/json; charset=utf-8", ".pdf": "application/pdf"}
MAX_BODY = 8 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, raw, content_type, code=200, download=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; "
                         "object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.end_headers()
        self.wfile.write(raw)

    def send_json(self, data, code=200):
        self.send_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"), CONTENT_TYPES[".json"], code)

    def local_host(self):
        return self.headers.get("Host") in ("127.0.0.1", f"127.0.0.1:{self.server.server_port}")

    def do_GET(self):
        if not self.server.hosted and not self.local_host():
            return self.send_json({"error": "Use the local loopback URL from the console."}, 403)
        path = urlsplit(self.path).path
        if path == "/healthz":
            return self.send_json({"ok": True})
        if path == "/favicon.ico":
            return self.send_bytes(b"", "image/x-icon", 204)
        if path in STATIC:
            file = WEB / STATIC[path]
            return self.send_bytes(file.read_bytes(), CONTENT_TYPES[file.suffix])
        if path == "/api/dashboard":
            return self.send_json(dict(self.server.store.dashboard(), label=LABEL, hosted=self.server.hosted))
        if path == "/api/fixture-meta":
            return self.send_json(REPORTS)
        if path.startswith("/fixtures/"):
            name = path.removeprefix("/fixtures/")
            file = DIRECTORY / name
            if name in FIXTURE_NAMES and file.is_file():
                return self.send_bytes(file.read_bytes(), CONTENT_TYPES[file.suffix])
        if path == "/api/source/manifest":
            return self.download("manifest", None)
        if match := re.fullmatch(r"/api/source/(\d+)/(assay|pdf)", path):
            return self.download(match[2], int(match[1]))
        return self.send_json({"error": "File or route not found."}, 404)

    def download(self, kind, report_id):
        raw = self.server.store.attachment(kind, report_id)
        if raw is None:
            return self.send_json({"error": "Source file not found."}, 404)
        suffix = ".pdf" if kind == "pdf" else ".csv"
        base = "manifest" if report_id is None else f"report-{report_id}-{kind}"
        return self.send_bytes(raw, CONTENT_TYPES[suffix], download=base + suffix)

    def do_POST(self):
        if self.server.hosted:
            return self.send_json({"error": "The hosted showcase is read-only. Use the local demo to make changes."}, 403)
        origin = self.headers.get("Origin")
        if not self.local_host() or (origin is not None and origin != f"http://127.0.0.1:{self.server.server_port}"):
            return self.send_json({"error": "Use the application from its loopback URL."}, 403)
        try:
            body = self.read_json()
            result = self.mutate(urlsplit(self.path).path, body)
        except PermissionError as error:
            return self.send_json({"error": str(error)}, 403)
        except (ValueError, KeyError, TypeError) as error:
            return self.send_json({"error": str(error)}, 400)
        return self.send_json(result)

    def read_json(self):
        if self.headers.get_content_type() != CONTENT_TYPES[".json"].split(";")[0]:
            raise ValueError("Expected a JSON request.")
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > MAX_BODY:
            raise ValueError("Request size is outside the demo limit.")
        body = json.loads(self.rfile.read(length))
        if not isinstance(body, dict):
            raise ValueError("Expected a JSON object.")
        return body

    def mutate(self, path, body):
        store = self.server.store
        if path == "/api/rules":
            code = body.get("code")
            if not isinstance(code, str) or not hmac.compare_digest(code.encode("utf-8"), self.server.operator_code):
                raise PermissionError("Enter the local rule editor code from the console.")
            store.configure(body["rules"])
        elif path == "/api/manifest":
            store.import_manifest(file_bytes(body, "file"))
        elif path == "/api/report":
            report = store.import_report(body, file_bytes(body, "csv"), file_bytes(body, "pdf"))
            return {"ok": True, "id": report}
        elif path == "/api/review":
            store.record_review(int(body["id"]), body)
        elif path == "/api/verify":
            kind = body["kind"]
            if kind not in {"manifest", "assay", "pdf"}:
                raise ValueError("Select a registered source type.")
            registered = store.attachment(kind, int(body.get("id") or 0))
            if registered is None:
                raise ValueError("Registered source file was not found.")
            expected, supplied = digest(registered), digest(file_bytes(body, "file"))
            return {"match": hmac.compare_digest(expected, supplied), "expected": expected, "supplied": supplied}
        else:
            raise ValueError("Unknown action.")
        return {"ok": True}


def file_bytes(body, key):
    try:
        raw = base64.b64decode(body[key], validate=True)
    except (ValueError, TypeError, binascii.Error, KeyError) as error:
        raise ValueError(f"Select a valid {key} file.") from error
    if not raw or len(raw) > 3 * 1024 * 1024:
        raise ValueError("Each selected file must be between 1 byte and 3 MB.")
    return raw


def create_server(db, port=8000, operator_code=None, *, hosted=False):
    store = Store(db)
    if hosted:
        seed_demo(store)
    server = ThreadingHTTPServer(("0.0.0.0" if hosted else "127.0.0.1", port), Handler)
    server.store = store
    server.hosted = hosted
    if not hosted:
        server.operator_code = (operator_code or secrets.token_urlsafe(9)).encode("utf-8")
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, help="SQLite path for the interactive local demo.")
    parser.add_argument("--port", type=int, default=os.environ.get("PORT", "8000"))
    parser.add_argument("--hosted", action="store_true", help="Serve a read-only synthetic showcase on all interfaces.")
    args = parser.parse_args()
    if args.hosted:
        if args.db is not None:
            parser.error("--hosted creates its own temporary database; omit --db.")
        with TemporaryDirectory(prefix="sampletrail-") as folder:
            serve(Path(folder) / "showcase.sqlite3", args.port, hosted=True)
    else:
        serve(args.db or Path("sampletrail.sqlite3"), args.port)


def serve(db, port, *, hosted=False):
    with create_server(db, port, hosted=hosted) as server:
        print(f"SampleTrail: http://{server.server_address[0]}:{server.server_port}", flush=True)
        if not hosted:
            print(f"Rule editor code: {server.operator_code.decode()}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
