import http.client
import json
import ssl
import threading
from datetime import timedelta

import pytest
from test_dashboard_service import build, certificates

from fx_talanta.dashboard.server import make_server
from fx_talanta.dashboard.sessions import Owner, Sessions, cookie_token

PASSWORD = "fixture-only-long-passphrase"


def test_session_expiry_revocation_binding_and_rate(tmp_path):
    app = build(tmp_path)
    try:
        owner = Owner.create("owner", PASSWORD)
        assert PASSWORD not in owner.model_dump_json()
        sessions = Sessions(app, owner)

        def login():
            return sessions.login(
                {"username": "owner", "password": PASSWORD}, peer="a", secure=True
            )

        token, result = login()
        assert sessions.verify(token, peer="a")["authenticated"]
        with pytest.raises(PermissionError):
            sessions.verify(token, peer="a", mutation=True, csrf="wrong")
        assert sessions.verify(token, peer="a", mutation=True, csrf=result["csrf"])
        with pytest.raises(PermissionError):
            Sessions(app, owner).verify(token, peer="a")
        sessions.logout(token)
        with pytest.raises(PermissionError):
            sessions.verify(token, peer="a")
        token, _ = login()
        with pytest.raises(PermissionError):
            sessions.verify(token, peer="different-certificate")
        token, _ = login()
        app.clock.advance(timedelta(minutes=30))
        with pytest.raises(PermissionError):
            sessions.verify(token, peer="a")
        token, _ = login()
        app.clock._now -= timedelta(seconds=1)  # Inject a rollback, never adjust host time.
        with pytest.raises(PermissionError):
            sessions.verify(token, peer="a")
        for _ in range(5):
            with pytest.raises(PermissionError):
                sessions.login({"bootstrap": app.token}, peer="a", secure=True)
        with pytest.raises(PermissionError, match="temporarily"):
            login()
        app.clock.advance(timedelta(hours=9))
        with pytest.raises(PermissionError):
            Sessions(app, owner).login(
                {"username": "owner", "password": PASSWORD}, peer="a", secure=True
            )
    finally:
        app.close()


def test_owner_requires_tls_before_bind(tmp_path):
    app = build(tmp_path)
    try:
        with pytest.raises(ValueError, match="HTTPS"):
            make_server(app, owner=Owner.create("owner", PASSWORD))
        assert cookie_token("sid=a; sid=b", "sid") == ""
    finally:
        app.close()


def test_real_https_owner_session_csrf_logout_and_no_bearer_bypass(tmp_path):
    certificates(tmp_path)
    app = build(tmp_path / "state")
    server = make_server(
        app,
        owner=Owner.create("owner", PASSWORD),
        remote_cert=tmp_path / "server.pem",
        remote_key=tmp_path / "server.key",
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    origin = f"https://127.0.0.1:{server.server_port}"
    cookie = ""
    csrf = ""

    def call(path, method="GET", data=None, **headers):
        conn = http.client.HTTPSConnection(
            "127.0.0.1",
            server.server_port,
            context=ssl.create_default_context(cafile=str(tmp_path / "ca.pem")),
            timeout=3,
        )
        try:
            conn.request(
                method,
                path,
                body=json.dumps(data) if data is not None else None,
                headers={
                    "Origin": origin,
                    "Cookie": cookie,
                    "X-FX-CSRF": csrf,
                    "Content-Type": "application/json",
                    **headers,
                },
            )
            response = conn.getresponse()
            return response.status, json.loads(response.read()), response.getheader("Set-Cookie")
        finally:
            conn.close()

    try:
        assert call("/api/overview", Authorization="Bearer " + app.token)[0] == 403
        assert call("/api/session")[1] == {"authenticated": False, "mode": "OWNER"}
        data = {"username": "owner", "password": PASSWORD}
        assert call("/api/session", "POST", data)[0] == 403
        assert (
            call(
                "/api/session",
                "POST",
                data,
                **{"X-FX-Session": "1", "Origin": "https://evil.invalid"},
            )[0]
            == 403
        )
        status, result, header = call("/api/session", "POST", data, **{"X-FX-Session": "1"})
        assert status == 200 and result["execution_enabled"] is False
        assert all(
            x in header for x in ("__Host-", "Secure", "HttpOnly", "SameSite=Strict", "Path=/")
        )
        assert "Domain=" not in header
        cookie = header.split(";")[0]
        csrf = result["csrf"]
        assert call("/api/overview")[0] == 200
        assert call("/api/session")[1]["csrf"] == csrf
        assert call("/api/operator/state")[0] == 403
        assert call("/api/session/logout", "POST", **{"X-FX-CSRF": "wrong"})[0] == 403
        assert call("/api/session/logout", "POST", Origin="https://evil.invalid")[0] == 403
        assert call("/api/session/logout", "POST")[0] == 200
        assert call("/api/overview")[0] == 403
        assert call("/api/overview", Authorization="Bearer " + app.token)[0] == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        app.close()
