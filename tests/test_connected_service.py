import io
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from fx_talanta.connected_shadow.authority import Authority, backend_checkpoint
from fx_talanta.connected_shadow.host_clock import HostClock
from fx_talanta.connected_shadow.service import (
    ConnectedApplication,
    Service,
    hold_receipt,
    validate_receipt,
)
from fx_talanta.shadow.store import SQLiteStore
from fx_talanta.shadow.wire import Frame, digest
from tests.test_connected_inputs import NOW, binding, capture

CLIENT, INC, KEY = "c" * 64, "d" * 64, b"local-fixture-key-" * 2


@pytest.fixture
def service(tmp_path):
    at = [NOW]
    account = binding().account
    authority = Authority(
        SQLiteStore(tmp_path / "authority.db", bootstrap=True), account, bootstrap=True
    )
    authority.claim(CLIENT, INC, NOW)
    s = Service(
        SQLiteStore(tmp_path / "backend.db", bootstrap=True),
        authority,
        account,
        CLIENT,
        INC,
        1,
        KEY,
        lambda: (at[0], 10),
        bootstrap=True,
    )
    s.publish(capture(), "EURUSD")
    return s, at


def call(s, at, op="PULL", receipt="", nonce="a" * 64):
    payload = f"connected/1\t{op}\t{INC}\t1"
    if receipt:
        payload += "\t" + receipt.encode().hex()
    raw = Frame(
        "C2S",
        s.scope,
        CLIENT,
        nonce,
        at,
        at + 5000,
        "REPORT" if op == "REPORT" else "PULL",
        payload,
    ).encode(KEY)
    result = s.exchange(raw)
    return Frame.decode(
        result, KEY, direction="S2C", scope=s.scope, client=CLIENT, now=at, nonce=nonce
    )


def test_native_hold_retained_across_lost_ack_restart_and_lease_expiry(service):
    s, at = service
    assert call(s, NOW, "SYNC", nonce="0" * 64).payload == f"connected/1\tCLOCK\t{NOW}\t10"
    work = call(s, NOW).payload
    receipt = hold_receipt(work, NOW, 40, NOW - 400)
    assert receipt.split("\t")[9] == "REQUIRED_INPUTS"
    assert call(s, NOW, "REPORT", receipt, "b" * 64).payload == digest(receipt)
    at[0] += 20000
    resumed = Service(s.store, s.authority, s.account, CLIENT, INC, 1, KEY, s.clock)
    assert call(resumed, at[0], "REPORT", receipt, "c" * 64).payload == digest(receipt)
    assert resumed.status()["receipt_count"] == 1
    with pytest.raises(ValueError, match="LEASE_EXPIRED"):
        call(resumed, at[0], nonce="d" * 64)
    checkpoint = backend_checkpoint(s.store, s.scope)
    assert checkpoint.sequence == 1 and checkpoint.receipt_hash == digest(receipt)


def test_real_quote_age_boundary_missing_native_data_and_forged_verdict(service):
    s, at = service
    work = call(s, NOW).payload
    # Captured quote is 500 ms old; 40 ms receiver bound leaves 1,460 ms.
    assert hold_receipt(work, NOW + 1460, 40, NOW + 1000).split("\t")[9] == "REQUIRED_INPUTS"
    assert hold_receipt(work, NOW + 1461, 40, NOW + 1000).split("\t")[9] == "QUOTE_STALE"
    missing = hold_receipt(work, NOW, 40, 0)
    assert missing.split("\t")[8:10] == ["-1", "NATIVE_DATA_UNAVAILABLE"]
    good = hold_receipt(work, NOW, 40, NOW - 100)
    with pytest.raises(ValueError, match="NATIVE_RECEIPT_MISMATCH"):
        validate_receipt(good.replace("REQUIRED_INPUTS", "ACCEPTED"), work, NOW)
    with pytest.raises(ValueError, match="CLOCK"):
        hold_receipt(work, NOW, 101, NOW - 100)


def test_receipt_causality_compares_both_clock_intervals_without_quote_credit(service):
    s, _ = service
    work = call(s, NOW).payload
    receipt = hold_receipt(work, NOW + 100, 50, NOW - 100)
    assert validate_receipt(receipt, work, NOW + 40, 20)[9] == "REQUIRED_INPUTS"
    with pytest.raises(ValueError, match="NATIVE_RECEIPT_MISMATCH"):
        validate_receipt(receipt, work, NOW + 20, 20)
    stale = hold_receipt(work, NOW + 1451, 50, NOW + 1000)
    assert validate_receipt(stale, work, NOW + 1500, 20)[9] == "QUOTE_STALE"


def test_snapshot_hash_idempotency_scope_and_native_route(service):
    s, at = service
    assert not s.publish(capture(), "EURUSD")
    raw = deepcopy(capture())
    raw["account"]["equity"] = "1"
    with pytest.raises(ValueError, match="CAPTURE_HASH"):
        s.publish(raw, "EURUSD")
    app, codes = ConnectedApplication(s), []
    assert app({"PATH_INFO": "/v1/shadow"}, lambda status, _: codes.append(status)) == [b""]
    assert codes == ["404 Not Found"]
    body = Frame(
        "C2S", s.scope, CLIENT, "e" * 64, NOW, NOW + 5000, "PULL", f"connected/1\tSYNC\t{INC}\t1"
    ).encode(KEY)
    result = app(
        dict(
            PATH_INFO="/v1/connected-shadow",
            REQUEST_METHOD="POST",
            **{
                "wsgi.url_scheme": "https",
                "wsgi.input": io.BytesIO(body),
                "CONTENT_TYPE": "application/octet-stream",
                "CONTENT_LENGTH": str(len(body)),
            },
        ),
        lambda status, _: codes.append(status),
    )
    assert codes[-1] == "200 OK" and result


def test_host_clock_expires_and_detects_actual_wall_monotonic_divergence():
    wall, mono = [NOW], [1000]
    report = dict(
        passed=True,
        error_bound_ms=10,
        checked_at=datetime.fromtimestamp(NOW / 1000, UTC).isoformat(),
    )
    clock = HostClock(report, wall=lambda: wall[0] * 1000000, monotonic=lambda: mono[0] * 1000000)
    assert clock.read() == (NOW, 15)
    wall[0] += 7
    with pytest.raises(ValueError, match="CHANGED"):
        clock.read()
    wall[0] = NOW
    clock = HostClock(report, wall=lambda: wall[0] * 1000000, monotonic=lambda: mono[0] * 1000000)
    wall[0] = NOW + 60000
    mono[0] = 61000
    with pytest.raises(ValueError, match="EXPIRED"):
        clock.read()


def test_sync_is_authorized_durable_and_cannot_reuse_a_clock_sample(service):
    s, at = service
    call(s, NOW, "SYNC")
    with pytest.raises(ValueError, match="SYNC_NONCE_REPLAY"):
        call(s, NOW, "SYNC")
    with pytest.raises(ValueError, match="NONCE_CONFLICT"):
        call(s, NOW, "PULL")
    with s.store.transaction() as events:
        assert sum(e["kind"] == "exchange" for e in events.records) == 1
    # Expired, unreplaced peer may synchronize to upload its old receipt, but
    # synchronization alone does not renew its lease or permit more work.
    at[0] += 20000
    call(s, at[0], "SYNC", nonce="b" * 64)
    with pytest.raises(ValueError, match="LEASE_EXPIRED"):
        call(s, at[0], "PULL", nonce="c" * 64)
    # An unavailable durable journal also denies SYNC.
    s.store.path = s.store.path.with_name("missing.db")
    with pytest.raises(ValueError, match="MISSING_JOURNAL"):
        call(s, at[0], "SYNC", nonce="d" * 64)


def test_upper_clock_bound_enforces_lease_and_cross_account_binding(service, tmp_path):
    s, at = service
    at[0] += 14990  # Midpoint is still inside the lease, upper bound is not.
    with pytest.raises(ValueError, match="LEASE_EXPIRED"):
        call(s, at[0])
    other = s.account.model_copy(update={"login": "other-demo"})
    with pytest.raises(ValueError, match="AUTHORITY_OR_STORE_ACCOUNT_MISMATCH"):
        Service(
            SQLiteStore(tmp_path / "other.db", bootstrap=True),
            s.authority,
            other,
            CLIENT,
            INC,
            1,
            KEY,
            s.clock,
            bootstrap=True,
        )


def test_narrower_clock_interval_does_not_reverse_authority_time(service):
    s, at = service
    clock = [NOW, 90]
    s.clock = lambda: tuple(clock)
    assert s.clock_upper() == NOW + 90
    clock[:] = [NOW + 10, 20]
    assert s.clock_upper() == NOW + 90
    clock[:] = [NOW + 100, 20]
    assert s.clock_upper() == NOW + 120


@pytest.mark.parametrize("receipt", ["", "connected-hold/1", "bad\tfield"])
def test_malformed_report_is_client_error_without_journal_mutation(service, receipt):
    s, at = service
    raw = Frame(
        "C2S",
        s.scope,
        CLIENT,
        "e" * 64,
        NOW,
        NOW + 5000,
        "REPORT",
        f"connected/1\tREPORT\t{INC}\t1\t" + receipt.encode().hex(),
    ).encode(KEY)
    codes = []
    result = ConnectedApplication(s)(
        {
            "PATH_INFO": "/v1/connected-shadow",
            "REQUEST_METHOD": "POST",
            "wsgi.url_scheme": "https",
            "wsgi.input": io.BytesIO(raw),
            "CONTENT_TYPE": "application/octet-stream",
            "CONTENT_LENGTH": str(len(raw)),
        },
        lambda status, _: codes.append(status),
    )
    assert codes == ["400 Bad Request"] and result
    with s.store.transaction() as events:
        assert not any(e["kind"] in {"receipt", "exchange"} for e in events.records)
