import json
import urllib.error
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from fx_talanta.advisor.provider import (
    MODEL,
    NoRedirect,
    OpenAITransport,
    parse_selection,
    payload_for,
    render_selection,
    run_once,
)
from tools.qualification.provider_smoke import fixture

NOW = datetime(2026, 11, 5, tzinfo=UTC)


def response(evidence):
    return {
        "status": "completed",
        "model": MODEL,
        "usage": {"input_tokens": 200, "output_tokens": 50},
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {
                                "decision": "EXPLAIN",
                                "citation_ids": [str(evidence.citations[0].record_id)],
                                "reason": "EVIDENCE_SELECTED",
                            }
                        ),
                    }
                ],
            }
        ],
    }


def test_request_no_account_or_tools_and_exact_schema():
    payload = payload_for(fixture(NOW), "Which record?")
    data = json.loads(payload)
    assert data["store"] is False and data["tools"] == []
    assert data["text"]["format"]["strict"] is True
    assert b"no-broker" not in payload and b"offline-smoke" not in payload
    assert b"Synthetic fixture; no orders" not in payload


def test_one_call_and_restart_no_resend(tmp_path):
    e = fixture(NOW)
    calls = []

    def transport(payload):
        calls.append(payload)
        return json.dumps(response(e)).encode()

    args = (e, "Which record?", tmp_path / "reservation.json", transport)
    kw = dict(expires_at=NOW + timedelta(seconds=10), now=lambda: NOW)
    r = run_once(*args, **kw)
    assert r.status == "EXPLAIN"
    assert "approved=False" in render_selection(e, r)
    assert "交易已禁用" in render_selection(e, r, "zh")
    assert run_once(*args, **kw).reason == "RESERVATION_CONSUMED_NO_RESEND"
    assert len(calls) == 1
    with pytest.raises(ValueError):
        render_selection(fixture(NOW + timedelta(seconds=1)), r)


@pytest.mark.parametrize(
    "change",
    [
        "unknown",
        "duplicate",
        "incomplete",
        "refusal",
        "tool",
        "model",
        "usage",
        "extra",
        "hold",
        "empty",
    ],
)
def test_bad_responses_hold_without_repair_retry(tmp_path, change):
    e, raw = fixture(NOW), response(fixture(NOW))
    selection = json.loads(raw["output"][0]["content"][0]["text"])
    if change == "unknown":
        selection["citation_ids"] = [str(uuid4())]
    if change == "duplicate":
        selection["citation_ids"] *= 2
    if change == "extra":
        selection["execute"] = True
    if change == "hold":
        selection["decision"] = "HOLD"
    if change == "empty":
        selection["citation_ids"] = []
    raw["output"][0]["content"][0]["text"] = json.dumps(selection)
    if change == "incomplete":
        raw["status"] = "incomplete"
    if change == "refusal":
        raw["output"][0]["content"][0]["type"] = "refusal"
    if change == "tool":
        raw["output"][0]["type"] = "function_call"
    if change == "model":
        raw["model"] = "unexpected"
    if change == "usage":
        raw["usage"]["input_tokens"] = True
    result = run_once(
        e,
        "Which record?",
        tmp_path / "reservation.json",
        lambda _: json.dumps(raw).encode(),
        expires_at=NOW + timedelta(seconds=10),
        now=lambda: NOW,
    )
    assert result.status == "HOLD"
    assert result.reason == "PROVIDER_FAILURE_HOLD"
    assert not result.execution_enabled


def test_timeout_expiry_and_storage_failure(tmp_path):
    e = fixture(NOW)
    calls = []

    def transport(_):
        calls.append(1)
        raise TimeoutError("secret-bearing provider error must not escape")

    kw = dict(expires_at=NOW + timedelta(seconds=10), now=lambda: NOW)
    r = run_once(e, "Which record?", tmp_path / "reservation.json", transport, **kw)
    assert "secret" not in r.model_dump_json()
    assert r.status == "HOLD"
    assert (
        run_once(e, "Which record?", tmp_path / "reservation.json", transport, **kw).status
        == "HOLD"
    )
    assert len(calls) == 1
    with pytest.raises(OSError):
        run_once(e, "Which record?", tmp_path / "missing/reservation.json", transport, **kw)
    assert len(calls) == 1


def test_late_response_never_accepted(tmp_path):
    e = fixture(NOW)
    ticks = iter([0, 16])
    r = run_once(
        e,
        "Which record?",
        tmp_path / "reservation.json",
        lambda _: json.dumps(response(e)).encode(),
        expires_at=NOW + timedelta(seconds=30),
        now=lambda: NOW,
        monotonic=lambda: next(ticks),
    )
    assert r.reason == "EXPIRED" and r.status == "HOLD"


def test_network_policy():
    assert NoRedirect().redirect_request(None, None, 302, None, None, "https://evil.test") is None
    transport = OpenAITransport("secret-placeholder")
    assert "secret-placeholder" not in repr(transport)


def test_model_cannot_add_prose_or_trade_command():
    e = fixture(NOW)
    raw = response(e)
    raw["output"][0]["content"][0]["text"] = json.dumps({"decision": "ENTER", "rationale": "trade"})
    with pytest.raises(ValueError):
        parse_selection(json.dumps(raw).encode(), e)


def test_concurrent_reservation_only_one_sender(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    e = fixture(NOW)
    calls = []

    def call(_):
        def transport(payload):
            calls.append(1)
            return json.dumps(response(e)).encode()

        return run_once(
            e,
            "Which record?",
            tmp_path / "reservation.json",
            transport,
            expires_at=NOW + timedelta(seconds=10),
            now=lambda: NOW,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(call, (0, 1)))
    assert len(calls) == 1
    assert sorted(r.status for r in results) == ["EXPLAIN", "HOLD"]


def test_http_error_sanitized_and_never_retried(tmp_path):
    def transport(_):
        raise urllib.error.HTTPError("https://api.openai.com", 429, "SECRET", {}, None)

    e = fixture(NOW)
    result = run_once(
        e,
        "Which record?",
        tmp_path / "reservation.json",
        transport,
        expires_at=NOW + timedelta(seconds=10),
        now=lambda: NOW,
    )
    assert result.reason == "HTTP_429"
    assert "SECRET" not in result.model_dump_json()


def test_expired_request_no_network_or_reservation(tmp_path):
    def transport(_):
        pytest.fail("must not send")

    path = tmp_path / "reservation.json"
    r = run_once(fixture(NOW), "Which record?", path, transport, expires_at=NOW, now=lambda: NOW)
    assert r.reason == "EXPIRED"
    assert not path.exists()
