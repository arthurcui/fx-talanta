"""Loopback-only UI. Exact Host/Origin, bearer capability, no CORS or execution routes."""

import argparse
import hmac
import json
import secrets
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
            origin = (
                f"{getattr(self.server, 'scheme', 'http')}://127.0.0.1:{self.server.server_port}"
            )
            if self.headers.get("Host") != origin.split("://", 1)[1]:
                return False
            if self.headers.get("Origin") not in (None, origin):
                return False
            if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
                return False
            if private and self.path.startswith("/api/operator/"):
                if app.operator is None:
                    return False
                try:
                    app.operator.authorize(
                        self.headers.get("Authorization", "").removeprefix("Bearer ")
                    )
                except PermissionError:
                    return False
                return True
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
            if self.path == "/api/operator/state":
                try:
                    result = app.operator.status(
                        self.headers.get("Authorization", "").removeprefix("Bearer ")
                    )
                    return self.reply(200, result)
                except Exception:
                    return self.reply(503, {"error": "Simulator state unavailable"})
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
                "/api/broker",
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
                            "/api/broker": app.broker,
                        }[route.path]()
                    if not self.allowed(private=True):
                        return self.reply(403, {"error": "Session expired"})
                    return self.reply(200, result)
                except ValueError:
                    return self.reply(400, {"error": "Invalid inspection request"})
                except Exception:
                    return self.reply(503, {"error": "Snapshot unavailable; readiness unknown"})
            return self.reply(404, {"error": "Unknown read-only route"})

        def do_POST(self):
            if not self.allowed(private=True):
                return self.reply(403, {"error": "Access denied or session expired"})
            if self.path in (
                "/api/operator/preview",
                "/api/operator/confirm",
                "/api/operator/revoke",
            ):
                try:
                    size = int(self.headers.get("Content-Length", "-1"))
                    if not 0 < size <= 4096 or self.headers.get("Transfer-Encoding"):
                        return self.reply(413, {"error": "Invalid request size"})
                    if self.headers.get("Content-Type") != "application/json":
                        return self.reply(415, {"error": "JSON required"})
                    raw = self.rfile.read(size)
                    data = json.loads(raw)
                    token = self.headers.get("Authorization", "").removeprefix("Bearer ")
                    method = self.path.rsplit("/", 1)[1]
                    result = (
                        app.operator.revoke(token)
                        if method == "revoke"
                        else getattr(app.operator, method)(token, data)
                    )
                    return self.reply(200, result)
                except PermissionError:
                    return self.reply(403, {"error": "Operator denied"})
                except (ValueError, TypeError, KeyError):
                    return self.reply(400, {"error": "Invalid or stale simulator command"})
                except Exception:
                    return self.reply(
                        503, {"error": "Outcome unknown; inspect the same request, never resend"}
                    )
            if self.path not in ("/api/chat", "/api/calendar", "/api/explain", "/api/study"):
                return self.reply(404, {"error": "No execution route"})
            try:
                size = int(self.headers.get("Content-Length", "-1"))
                maximum = (
                    4096
                    if self.path in ("/api/chat", "/api/explain")
                    else 16 * 1024 * 1024
                    if self.path == "/api/study"
                    else LIMIT
                )
                if not 0 < size <= maximum or self.headers.get("Transfer-Encoding"):
                    # Drain only bounded rejected bodies so Windows can deliver the error.
                    if maximum < size <= LIMIT and not self.headers.get("Transfer-Encoding"):
                        self.rfile.read(size)
                    return self.reply(413, {"error": "Invalid request size"})
                mime = "text/calendar" if self.path == "/api/calendar" else "application/json"
                if self.headers.get("Content-Type") != mime:
                    return self.reply(415, {"error": "Unsupported content type"})
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError("short request")
                if self.path == "/api/chat":
                    result = app.chat(json.loads(raw))
                elif self.path == "/api/explain":
                    result = app.explain(json.loads(raw))
                elif self.path == "/api/study":
                    result = app.upload_study(raw)
                else:
                    result = app.upload_calendar(raw)
                # Access may expire while an external model is working.
                if not self.allowed(private=True):
                    return self.reply(403, {"error": "Session expired"})
                return self.reply(200, result)
            except PermissionError:
                return self.reply(403, {"error": "Capability unavailable or session expired"})
            except (ValueError, KeyError, TypeError, UnicodeError):
                return self.reply(
                    400,
                    {"error": "Invalid input or conflicting request; no trading action performed"},
                )
            except Exception:
                return self.reply(
                    503, {"error": "Inspection unavailable; no trading action performed"}
                )

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def configure_tls(server, certificate=None, key=None):
    scheme = "http"
    if bool(certificate) != bool(key):
        raise ValueError("TLS certificate and key required together")
    if certificate:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certificate, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        scheme = "https"
    server.scheme = scheme
    return scheme


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
    parser.add_argument("--model-key-file", type=Path, help="Optional ignored OpenAI env file")
    parser.add_argument(
        "--model-budget-file", type=Path, help="Explicit immutable ProviderBudget JSON"
    )
    parser.add_argument("--tls-cert", type=Path, help="Optional server certificate chain")
    parser.add_argument("--tls-key", type=Path, help="Private key for optional loopback TLS")
    parser.add_argument(
        "--broker-config", type=Path, help="Exact private broker journal/run binding JSON"
    )
    parser.add_argument(
        "--broker-env-file", type=Path, help="Ignored file containing BROKER_READ_DSN"
    )
    parser.add_argument(
        "--simulator-env", type=Path, help="Explicit disabled PAPER/SIMULATOR database settings"
    )
    parser.add_argument("--simulator-run", type=UUID)
    parser.add_argument(
        "--simulator-market",
        type=Path,
        help="Original timestamped Market JSON; never refreshed by UI",
    )
    parser.add_argument(
        "--operator-token-file",
        type=Path,
        help="Private file containing separate operator capability",
    )
    args = parser.parse_args()
    if any(
        (args.simulator_env, args.simulator_run, args.simulator_market, args.operator_token_file)
    ) and not all(
        (args.simulator_env, args.simulator_run, args.simulator_market, args.operator_token_file)
    ):
        parser.error("all four simulator/operator options required")
    if bool(args.broker_config) != bool(args.broker_env_file):
        parser.error("broker config and private DSN file required together")
    if bool(args.tls_cert) != bool(args.tls_key):
        parser.error("TLS certificate and key must be supplied together")
    if bool(args.model_key_file) != bool(args.model_budget_file):
        parser.error("model key and budget files must be supplied together")
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
    budget = transport = None
    if args.model_key_file:
        from dotenv import dotenv_values

        from fx_talanta.advisor.provider import OpenAITransport
        from fx_talanta.advisor.provider_ledger import ProviderBudget

        budget = ProviderBudget.model_validate_json(args.model_budget_file.read_bytes())
        transport = OpenAITransport(dotenv_values(args.model_key_file).get("OPENAI_API_KEY", ""))
    broker_view = None
    if args.broker_config:
        from dotenv import dotenv_values

        from fx_talanta.dashboard.broker_view import BrokerView, BrokerViewConfig

        config = BrokerViewConfig.model_validate_json(args.broker_config.read_bytes())
        dsn = dotenv_values(args.broker_env_file).get("BROKER_READ_DSN", "")
        if not dsn:
            raise ValueError("broker read DSN missing")
        broker_view = BrokerView(config, dsn)
    gateway = market_source = operator_token = None
    if args.simulator_env:
        from fx_talanta.domain.models import Environment
        from fx_talanta.domain.offline import Market
        from fx_talanta.gateway.offline import Gateway
        from fx_talanta.storage.config import Settings

        if snapshot.account.venue != "SIMULATOR" or snapshot.account.environment != "PAPER":
            raise ValueError("operator requires explicit simulator snapshot")
        if (args.state / "restored-inspection-only.json").exists():
            raise PermissionError("restored workspace cannot acquire simulator authority")
        operator_token = args.operator_token_file.read_text().strip()
        if len(operator_token) < 32 or not operator_token.isascii():
            raise ValueError("invalid operator capability")

        def market_source():
            with args.simulator_market.open("rb") as stream:
                raw = stream.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("market file too large")
            return Market.model_validate_json(raw)

        # Existing database only: no bootstrap, account adoption, terminal or entry path.
        settings = Settings.load(args.simulator_env, runtime=Environment.PAPER)
        import psycopg

        from fx_talanta.domain.offline import GatewayBook

        dsn = settings.runtime_dsn(Environment.PAPER)
        with psycopg.connect(
            dsn,
            connect_timeout=3,
            options="-c default_transaction_read_only=on -c statement_timeout=3000",
        ) as conn:
            binding = conn.execute(
                "SELECT identity,execution_enabled FROM fx.account_binding"
            ).fetchone()
            if not binding or binding[0] != snapshot.account.model_dump(mode="json") or binding[1]:
                raise PermissionError("disabled simulator binding required")
            row = conn.execute(
                "SELECT payload FROM fx.offline_journal WHERE run_id=%s AND stream='gateway' "
                "ORDER BY revision DESC LIMIT 1",
                (args.simulator_run,),
            ).fetchone()
            if not row:
                raise ValueError("existing simulator run required")
            book = GatewayBook.model_validate(row[0])
        gateway = Gateway(dsn, snapshot.account, args.simulator_run, SystemClock(), book.policy)
    app = server = None
    try:
        app = Dashboard(
            snapshot,
            args.state,
            secrets.token_urlsafe(32),
            SystemClock(),
            telemetry=args.telemetry,
            telemetry_run=args.telemetry_run,
            model_budget=budget,
            model_transport=transport,
            broker_view=broker_view,
            operator_gateway=gateway,
            operator_market=market_source,
            operator_token=operator_token,
        )
        server = make_server(app, args.port)
        scheme = configure_tls(server, args.tls_cert, args.tls_key)
        url = f"{scheme}://127.0.0.1:{server.server_port}/#token={app.token}"
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
        if server is not None:
            server.server_close()
        if app is not None:
            app.close()
        if gateway is not None:
            gateway.close()


if __name__ == "__main__":
    main()
