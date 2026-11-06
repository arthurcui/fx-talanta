"""Loopback-only UI. Exact Host/Origin, bearer capability, no CORS or execution routes."""

import argparse
import hmac
import json
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from fx_talanta.clock import SystemClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import demo
from fx_talanta.dashboard.models import Snapshot
from fx_talanta.provider_pipeline import status_lock

LIMIT = 2 * 1024 * 1024


def make_server(app, port=0):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log credentials, queries or account data.

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def reply(self, status, body, mime="application/json"):
            raw = json.dumps(body).encode() if mime == "application/json" else body
            self.send_response(status)
            for key, value in {
                "Content-Type": mime,
                "Content-Length": str(len(raw)),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": (
                    "default-src 'none'; script-src 'self'; style-src 'self'; "
                    "connect-src 'self'; img-src 'self'; frame-ancestors 'none'; "
                    "base-uri 'none'; form-action 'none'"
                ),
            }.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(raw)

        def allowed(self, private=False):
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != origin.removeprefix("http://"):
                return False
            if self.headers.get("Origin") not in (None, origin):
                return False
            if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
                return False
            if private:
                supplied = self.headers.get("Authorization", "")
                if not supplied.isascii() or not hmac.compare_digest(
                    supplied, "Bearer " + app.token
                ):
                    return False
                try:
                    app.authorize(app.token)
                except PermissionError:
                    return False
            return True

        def do_GET(self):
            if not self.allowed(private=self.path.startswith("/api/")):
                return self.reply(403, {"error": "Access denied or session expired"})
            assets = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript"),
                "/style.css": ("style.css", "text/css"),
            }
            if self.path in assets:
                name, mime = assets[self.path]
                return self.reply(
                    200, files("fx_talanta.dashboard").joinpath("static", name).read_bytes(), mime
                )
            route = urlsplit(self.path)
            if route.path in (
                "/api/overview",
                "/api/history",
                "/api/report",
                "/api/incidents",
            ) or route.path.startswith("/api/trace/"):
                try:
                    query = parse_qs(route.query, keep_blank_values=True, strict_parsing=True)
                    if len(self.path) > 1024 or any(len(v) != 1 for v in query.values()):
                        raise ValueError("invalid query")
                    if route.path != "/api/incidents" and query:
                        raise ValueError("unexpected query")
                    if route.path == "/api/incidents":
                        if set(query) - {"q", "before"}:
                            raise ValueError("invalid filter")
                        result = app.incidents(
                            query.get("q", [""])[0],
                            int(query["before"][0]) if "before" in query else None,
                        )
                    elif route.path.startswith("/api/trace/"):
                        result = app.trace(route.path.removeprefix("/api/trace/"))
                    else:
                        result = {
                            "/api/overview": app.overview,
                            "/api/history": app.history,
                            "/api/report": app.report,
                        }[route.path]()
                    return self.reply(200, result)
                except ValueError:
                    return self.reply(400, {"error": "Invalid inspection request"})
                except Exception:
                    return self.reply(503, {"error": "Snapshot unavailable; readiness unknown"})
            return self.reply(404, {"error": "Unknown read-only route"})

        def do_POST(self):
            if not self.allowed(private=True):
                return self.reply(403, {"error": "Access denied or session expired"})
            if self.path not in ("/api/chat", "/api/calendar"):
                return self.reply(404, {"error": "No execution route"})
            try:
                size = int(self.headers.get("Content-Length", "-1"))
                maximum = 4096 if self.path == "/api/chat" else LIMIT
                if not 0 < size <= maximum or self.headers.get("Transfer-Encoding"):
                    # Drain only bounded rejected bodies so Windows can deliver the error.
                    if maximum < size <= LIMIT and not self.headers.get("Transfer-Encoding"):
                        self.rfile.read(size)
                    return self.reply(413, {"error": "Invalid request size"})
                mime = "application/json" if self.path == "/api/chat" else "text/calendar"
                if self.headers.get("Content-Type") != mime:
                    return self.reply(415, {"error": "Unsupported content type"})
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError("short request")
                result = (
                    app.chat(json.loads(raw))
                    if self.path == "/api/chat"
                    else app.upload_calendar(raw)
                )
                return self.reply(200, result)
            except (ValueError, KeyError, TypeError, UnicodeError):
                return self.reply(
                    400,
                    {"error": "Invalid input or conflicting request; no trading action performed"},
                )
            except Exception:
                return self.reply(
                    503, {"error": "Inspection unavailable; no trading action performed"}
                )

    return HTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot",
        type=Path,
        help="Immutable dashboard-snapshot/1 JSON; default is synthetic tour",
    )
    parser.add_argument(
        "--state",
        type=Path,
        required=True,
        help="NEW isolated directory for inspection receipts and uploads",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--resume", action="store_true", help="Resume the same inspection state and binding"
    )
    parser.add_argument(
        "--telemetry", type=Path, help="Explicit dashboard-telemetry/1 file; never auto-discovered"
    )
    parser.add_argument("--telemetry-run", type=UUID, help="Exact producer run binding")
    parser.add_argument(
        "--session-file", type=Path, help="Write private local launch URL instead of printing"
    )
    args = parser.parse_args()
    if args.snapshot:
        with args.snapshot.open("rb") as f:
            raw = f.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            parser.error("snapshot exceeds 8 MiB")
        snapshot = Snapshot.model_validate_json(raw)
    else:
        snapshot = demo()
    if args.resume:
        if not (args.state / "inspection.sqlite").is_file():
            parser.error("resume requires an existing inspection journal")
    else:
        args.state.mkdir(parents=True, exist_ok=False)
    with status_lock(args.state / "dashboard.lock"):
        serve(snapshot, args)


def serve(snapshot, args):
    app = Dashboard(
        snapshot,
        args.state,
        secrets.token_urlsafe(32),
        SystemClock(),
        telemetry=args.telemetry,
        telemetry_run=args.telemetry_run,
    )
    server = make_server(app, args.port)
    url = f"http://127.0.0.1:{server.server_port}/#token={app.token}"
    if args.session_file:
        with args.session_file.open("x", encoding="utf-8") as f:
            f.write(url)
    else:
        print("Private local dashboard URL (do not share): " + url, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()


if __name__ == "__main__":
    main()
