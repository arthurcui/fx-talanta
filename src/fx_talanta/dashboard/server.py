"""Inspection UI; optional mutual-TLS access, simulator operator restricted to loopback."""

import argparse
import hashlib
import hmac
import ipaddress
import json
import secrets
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from fx_talanta.clock import SystemClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.demo import demo
from fx_talanta.dashboard.models import Snapshot
from fx_talanta.dashboard.sessions import Owner, Sessions, cookie_header, cookie_token
from fx_talanta.provider_pipeline import status_lock

LIMIT = 2 * 1024 * 1024


class BoundedServer(ThreadingHTTPServer):
    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(8)
        self.tls_context = None
        super().__init__(*args, **kwargs)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        if self.tls_context:
            connection = self.tls_context.wrap_socket(
                connection, server_side=True, do_handshake_on_connect=False
            )
        return connection, address

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


def validate_access(bind, origin, certificate, key, client_ca, operator=False):
    address = ipaddress.ip_address(bind)
    if address.version != 4:
        raise ValueError("IPv4 bind required")
    if bool(certificate) != bool(key):
        raise ValueError("TLS pair required")
    remote = not address.is_loopback
    if operator and (remote or origin or client_ca):
        raise ValueError("simulator operator requires local-only configuration")
    if remote and (not all((origin, certificate, key, client_ca)) or operator):
        raise ValueError("remote inspection requires mutual TLS, exact origin, and no operator")
    if client_ca and not certificate:
        raise ValueError("client CA requires TLS")
    if origin:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.netloc != parsed.netloc.lower()
        ):
            raise ValueError("canonical HTTPS origin required")
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("invalid origin port")
        if not certificate:
            raise ValueError("explicit HTTPS origin requires TLS")
    return remote


def make_server(
    app,
    port=0,
    *,
    bind="127.0.0.1",
    origin=None,
    remote_cert=None,
    remote_key=None,
    remote_ca=None,
    owner=None,
):
    if owner is not None and not (remote_cert and remote_key):
        raise ValueError("owner sign-in requires HTTPS")
    sessions = Sessions(app, owner)
    remote = not ipaddress.ip_address(bind).is_loopback
    if app.operator is not None and (origin or remote_ca):
        raise ValueError("simulator operator cannot use public-origin/client-CA mode")
    validate_access(bind, origin, remote_cert, remote_key, remote_ca, app.operator is not None)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log credentials, queries or account data.

        def setup(self):
            super().setup()
            self.connection.settimeout(5)
            if isinstance(self.connection, ssl.SSLSocket):
                self.connection.do_handshake()

        def reply(self, status, body, mime="application/json", headers=None):
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
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(raw)

        def origin(self):
            return getattr(self.server, "public_origin", None) or (
                f"{getattr(self.server, 'scheme', 'http')}://127.0.0.1:{self.server.server_port}"
            )

        def cookie_name(self):
            prefix = "__Host-" if self.server.tls_context else ""
            return f"{prefix}fx_session_{self.server.server_port}"

        def session_token(self):
            return cookie_token(self.headers.get("Cookie", ""), self.cookie_name())

        def session(self, mutation=False):
            if mutation and self.headers.get("Origin") != self.origin():
                raise PermissionError("origin required")
            cert = (
                self.connection.getpeercert(binary_form=True)
                if isinstance(self.connection, ssl.SSLSocket)
                else None
            )
            return sessions.verify(
                self.session_token(),
                peer=hashlib.sha256(cert or b"").hexdigest(),
                csrf=self.headers.get("X-FX-CSRF"),
                mutation=mutation,
            )

        def session_request(self):
            if (
                not self.allowed()
                or self.headers.get("Origin") != self.origin()
                or self.headers.get("X-FX-Session") != "1"
            ):
                return self.reply(403, {"error": "Sign-in denied"})
            try:
                size = int(self.headers.get("Content-Length", "-1"))
                if not 0 < size <= 8192 or self.headers.get("Transfer-Encoding"):
                    return self.reply(413, {"error": "Invalid request size"})
                if self.headers.get("Content-Type") != "application/json":
                    return self.reply(415, {"error": "JSON required"})
                raw = self.rfile.read(size)
                data = json.loads(raw)
                if len(raw) != size or not isinstance(data, dict):
                    raise ValueError("invalid input")
                cert = (
                    self.connection.getpeercert(binary_form=True)
                    if isinstance(self.connection, ssl.SSLSocket)
                    else None
                )
                token, result = sessions.login(
                    data,
                    peer=hashlib.sha256(cert or b"").hexdigest(),
                    secure=bool(self.server.tls_context),
                )
                return self.reply(
                    200,
                    result,
                    headers={
                        "Set-Cookie": cookie_header(
                            self.cookie_name(), token, bool(self.server.tls_context)
                        )
                    },
                )
            except (ValueError, TypeError, PermissionError, UnicodeError):
                return self.reply(403, {"error": "Sign-in denied or temporarily unavailable"})

        def allowed(self, private=False):
            origin = getattr(self.server, "public_origin", None) or (
                f"{getattr(self.server, 'scheme', 'http')}://127.0.0.1:{self.server.server_port}"
            )
            if self.headers.get("Host") != origin.split("://", 1)[1]:
                return False
            if self.headers.get("Origin") not in (None, origin):
                return False
            if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
                return False
            browser = False
            if private and (owner is not None or self.session_token()):
                try:
                    self.session(mutation=self.command == "POST")
                    browser = True
                except PermissionError:
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
            if private and not browser:
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
            if self.path == "/api/session":
                if not self.allowed():
                    return self.reply(403, {"error": "Access denied"})
                try:
                    result = self.session()
                except PermissionError:
                    result = {"authenticated": False, "mode": "OWNER" if owner else "LOCAL_LAUNCH"}
                return self.reply(200, result)
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
                "/api/notifications",
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
                            "/api/notifications": app.notifications.summary,
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
            if self.path == "/api/session":
                return self.session_request()
            if self.path == "/api/session/logout":
                try:
                    if not self.allowed():
                        raise PermissionError("access denied")
                    self.session(mutation=True)
                    sessions.logout(self.session_token())
                    return self.reply(
                        200,
                        {"authenticated": False},
                        headers={
                            "Set-Cookie": cookie_header(
                                self.cookie_name(), "", bool(self.server.tls_context), clear=True
                            )
                        },
                    )
                except PermissionError:
                    return self.reply(403, {"error": "Session denied"})
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
            if self.path not in (
                "/api/chat",
                "/api/calendar",
                "/api/explain",
                "/api/study",
                "/api/notifications/ack",
            ):
                return self.reply(404, {"error": "No execution route"})
            try:
                size = int(self.headers.get("Content-Length", "-1"))
                maximum = (
                    4096
                    if self.path in ("/api/chat", "/api/explain", "/api/notifications/ack")
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
                if self.path == "/api/notifications/ack":
                    result = app.notifications.acknowledge(json.loads(raw))
                elif self.path == "/api/chat":
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

    server = BoundedServer((bind, port), Handler)
    server.public_origin = origin
    if remote or remote_cert:
        try:
            configure_tls(server, remote_cert, remote_key, remote_ca)
        except BaseException:
            server.server_close()
            raise
    return server


def configure_tls(server, certificate=None, key=None, client_ca=None):
    scheme = "http"
    if client_ca and not certificate:
        raise ValueError("client CA requires TLS")
    if bool(certificate) != bool(key):
        raise ValueError("TLS certificate and key required together")
    if certificate:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certificate, key)
        if client_ca:
            context.load_verify_locations(cafile=client_ca)
            context.verify_mode = ssl.CERT_REQUIRED
        server.tls_context = context
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
    parser.add_argument(
        "--owner-file", type=Path, help="Private single-owner verifier; requires HTTPS"
    )
    parser.add_argument(
        "--study-journal-config", type=Path, help="Read-only exact matched-receipt journal binding"
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
        "--broker-receipt-config",
        type=Path,
        help="Isolated current demo inspection view.json (no terminal attachment by UI)",
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
    parser.add_argument(
        "--bind", default="127.0.0.1", help="Explicit IPv4 listener; remote requires mutual TLS"
    )
    parser.add_argument(
        "--public-origin", help="Exact canonical HTTPS origin; forwarded headers never trusted"
    )
    parser.add_argument(
        "--tls-client-ca", type=Path, help="Required client-certificate CA for remote inspection"
    )
    parser.add_argument(
        "--monitor-interval", type=int, default=5, help="Inspection sampling cadence, 1..60 seconds"
    )
    args = parser.parse_args()
    try:
        validate_access(
            args.bind,
            args.public_origin,
            args.tls_cert,
            args.tls_key,
            args.tls_client_ca,
            bool(args.simulator_env),
        )
        if args.owner_file and not args.tls_cert:
            raise ValueError("owner sign-in requires HTTPS")
        if not 1 <= args.monitor_interval <= 60:
            raise ValueError("invalid monitor interval")
    except ValueError as error:
        parser.error(str(error))
    if any(
        (args.simulator_env, args.simulator_run, args.simulator_market, args.operator_token_file)
    ) and not all(
        (args.simulator_env, args.simulator_run, args.simulator_market, args.operator_token_file)
    ):
        parser.error("all four simulator/operator options required")
    if bool(args.broker_config) != bool(args.broker_env_file):
        parser.error("broker config and private DSN file required together")
    if args.broker_receipt_config and args.broker_config:
        parser.error("choose a broker journal or inspection receipts, not both")
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
    if args.broker_receipt_config:
        from fx_talanta.dashboard.current_broker import CurrentBrokerView, CurrentConfig

        broker_view = CurrentBrokerView(
            CurrentConfig.model_validate_json(args.broker_receipt_config.read_bytes())
        )
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
    from fx_talanta.dashboard.workflow import WorkflowView

    workflow_view = (
        WorkflowView.from_file(args.study_journal_config) if args.study_journal_config else None
    )
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
            workflow_view=workflow_view,
        )
        server = make_server(
            app,
            args.port,
            bind=args.bind,
            origin=args.public_origin,
            remote_cert=args.tls_cert,
            remote_key=args.tls_key,
            remote_ca=args.tls_client_ca,
            owner=Owner.model_validate_json(args.owner_file.read_bytes())
            if args.owner_file
            else None,
        )
        scheme = configure_tls(server, args.tls_cert, args.tls_key, args.tls_client_ca)
        origin = args.public_origin or f"{scheme}://{args.bind}:{server.server_port}"
        url = f"{origin}/" if args.owner_file else f"{origin}/#token={app.token}"
        if args.session_file:
            with args.session_file.open("x", encoding="utf-8") as f:
                f.write(url)
        else:
            print("Private local dashboard URL (do not share): " + url, flush=True)
        from fx_talanta.dashboard.service import InspectionService

        app.service = InspectionService(app, args.monitor_interval)
        app.service.start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    finally:
        if server is not None:
            server.server_close()
        if app is not None:
            if app.service is not None:
                app.service.stop()
            app.close()
        if gateway is not None:
            gateway.close()


if __name__ == "__main__":
    main()
