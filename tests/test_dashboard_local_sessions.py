import hashlib
import http.client
import json
import threading
from datetime import timedelta

import pytest
from test_dashboard_service import build

from fx_talanta.dashboard.local_sessions import LocalSessions
from fx_talanta.dashboard.server import make_server

PASSWORD = "fixture-passphrase-never-use"


def test_durable_session_revocation_and_internal_expiry(tmp_path):
    app = build(tmp_path)
    try:
        sessions = LocalSessions(app)
        assert sessions.mode() == "LOCAL_SETUP"
        token, result = sessions.login(
            dict(username="owner", password=PASSWORD), peer="a", secure=False
        )
        assert sessions.mode() == "LOCAL_OWNER"
        app.clock.advance(timedelta(days=2))
        restarted = LocalSessions(app)
        assert restarted.verify(token, peer="a")["authenticated"]
        app.authorize(app.token)  # No legacy eight-hour lockout after verified sign-in.
        assert token.encode() not in sessions.path.read_bytes()
        assert PASSWORD.encode() not in sessions.path.read_bytes()
        with pytest.raises(PermissionError):
            restarted.verify(token, peer="a", mutation=True, csrf="wrong")
        assert restarted.verify(token, peer="a", mutation=True, csrf=result["csrf"])
        restarted.logout_all()
        with pytest.raises(PermissionError):
            sessions.verify(token, peer="a")
        token, _ = sessions.login(dict(username="owner", password=PASSWORD), peer="a", secure=False)
        app.clock.advance(timedelta(days=7))
        with pytest.raises(PermissionError):
            sessions.verify(token, peer="a")
    finally:
        app.close()


def test_restart_does_not_reset_failure_limit_or_allow_replacement_owner(tmp_path):
    app = build(tmp_path)
    try:
        sessions = LocalSessions(app)
        sessions.login(dict(username="owner", password=PASSWORD), peer="a", secure=False)
        for _ in range(5):
            with pytest.raises(PermissionError):
                LocalSessions(app).login(
                    dict(username="attacker", password=PASSWORD), peer="a", secure=False
                )
        with pytest.raises(PermissionError, match="temporarily"):
            LocalSessions(app).login(
                dict(username="owner", password=PASSWORD), peer="a", secure=False
            )
    finally:
        app.close()


def test_persistent_mode_cannot_be_exposed_remotely(tmp_path):
    app = build(tmp_path)
    try:
        for options in [dict(bind="0.0.0.0"), dict(origin="https://example.com")]:
            with pytest.raises(ValueError, match="loopback"):
                make_server(app, local_signin=True, **options)
    finally:
        app.close()


def test_http_setup_login_restart_and_revoke(tmp_path):
    app = build(tmp_path)
    server = make_server(app, local_signin=True)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"

    def request(method, path, data=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        conn.request(method, path, json.dumps(data) if data else None, headers or {})
        response = conn.getresponse()
        result = (response.status, json.loads(response.read()), response.getheader("Set-Cookie"))
        conn.close()
        return result

    try:
        assert request("GET", "/api/session")[1]["mode"] == "LOCAL_SETUP"
        assert (
            request("GET", "/api/strategies", headers={"Authorization": "Bearer " + app.token})[0]
            == 403
        )
        credentials = dict(username="owner", password=PASSWORD)
        headers = {"Origin": origin, "Content-Type": "application/json", "X-FX-Session": "1"}
        assert (
            request(
                "POST", "/api/session", credentials, {**headers, "Origin": "https://evil.example"}
            )[0]
            == 403
        )
        bad, details, _ = request(
            "POST", "/api/session", dict(username="name with spaces", password=PASSWORD), headers
        )
        assert bad == 400 and "no spaces" in details["error"]
        assert PASSWORD not in json.dumps(details)
        status, body, cookie = request("POST", "/api/session", credentials, headers)
        assert status == 200 and "HttpOnly" in cookie and "Max-Age=2592000" in cookie
        auth = {"Cookie": cookie.split(";")[0], "Origin": origin, "X-FX-CSRF": body["csrf"]}
        assert request("GET", "/api/strategies", headers=auth)[0] == 200
        token = cookie.split(";", 1)[0].split("=", 1)[1]
        assert LocalSessions(app).verify(token, peer=hashlib.sha256(b"").hexdigest())
        assert (
            request(
                "POST",
                "/api/session/logout-all",
                headers={"Cookie": auth["Cookie"], "Origin": origin},
            )[0]
            == 403
        )
        assert request("POST", "/api/session/logout-all", headers=auth)[0] == 200
        assert request("GET", "/api/strategies", headers=auth)[0] == 403
        assert request("GET", "/api/session")[1]["mode"] == "LOCAL_OWNER"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
        app.close()


def test_setup_validation_is_explicit_and_email_username_works(tmp_path):
    from fx_talanta.dashboard.local_sessions import SetupValidationError

    app = build(tmp_path)
    try:
        sessions = LocalSessions(app)
        for data, message in [
            (dict(username="name with spaces", password=PASSWORD), "no spaces"),
            (dict(username="owner", password="short"), "16–256"),
        ]:
            with pytest.raises(SetupValidationError, match=message):
                sessions.login(data, peer="a", secure=False)
            assert sessions.mode() == "LOCAL_SETUP"
        token, _ = sessions.login(
            dict(username="owner@example.test", password=PASSWORD), peer="a", secure=False
        )
        assert sessions.verify(token, peer="a")["authenticated"]
    finally:
        app.close()
