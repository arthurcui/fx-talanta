import json
from uuid import uuid4

import pytest
import test_candidate_research as fixtures
from test_candidate_research import registration, response


@pytest.fixture
def app(tmp_path):
    yield from fixtures.app.__wrapped__(tmp_path)


def answer(rules):
    value = json.loads(response())
    value["output"][0]["content"][0]["text"] = json.dumps(
        dict(
            explanation="The supplied sample is too small to infer performance.",
            hypothesis="A shorter signal lookback may alter entry timing.",
            proposed_change="Change only signal_period to test entry sensitivity.",
            falsification="Reject if losses or risk halts persist; validate independently later.",
            uncertainty="This is a hypothesis on reused data, not a profit claim.",
            recommendation="REVISE_RULES",
            rules=rules,
        )
    )
    return json.dumps(value).encode()


def baseline(app):
    reg = app.research.register(registration(app))
    result = app.research.execute(dict(registration_id=reg["id"], partition="training"))
    return reg, result


def diagnose(app, result):
    rules = dict(result["payload"]["rules"], signal_period=19)
    calls = []
    app.research.transport = lambda raw: (calls.append(raw), answer(rules))[1]
    req = dict(request_id=str(uuid4()), result_id=result["id"])
    receipt = app.research.diagnose(req)
    assert app.research.diagnose(req) == receipt
    assert len(calls) == 1
    sent = json.loads(calls[0])
    assert json.loads(sent["input"])["evidence"]["baseline_id"] == result["id"]
    assert json.loads(sent["input"])["evidence"]["session_results"]["version"] == "fx-sessions/1"
    return receipt


def test_diagnosis_revision_comparison_preserves_inputs_and_authority(app):
    reg, original = baseline(app)
    diagnosis = diagnose(app, original)
    revision = app.research.revise_diagnosis(dict(diagnosis_id=diagnosis["id"], reviewed=True))
    assert (
        app.research.revise_diagnosis(dict(diagnosis_id=diagnosis["id"], reviewed=True)) == revision
    )
    comparison = app.research.compare_revision(dict(revision_id=revision["id"], reviewed=True))
    assert comparison["kind"] == "COMPARISON"
    p = comparison["payload"]
    assert p["risk_limits_unchanged"] and p["inputs_identical"]
    assert not p["execution_enabled"] and not p["qualified_for_paper"]
    assert (
        app.research.compare_revision(dict(revision_id=revision["id"], reviewed=True)) == comparison
    )
    updated = app.research.item(p["registration_id"])["payload"]
    for key in (
        "experiment",
        "dataset",
        "minimum_closed_trades",
        "maximum_drawdown_fraction",
        "engine_sha256",
    ):
        assert updated[key] == reg["payload"][key]
    assert app.research.item(original["id"]) == original
    assert updated["rules"]["signal_period"] == 19
    assert app.research.improvement_status(dict(comparison_id=p["comparison_id"])) == comparison


def test_no_holdout_diagnosis_or_unreviewed_revision(app):
    _, original = baseline(app)
    altered = dict(original["payload"], partition="holdout")
    item = app.research.retain("BACKTEST", altered)
    with pytest.raises(ValueError, match="training results only"):
        app.research.diagnose(dict(request_id=str(uuid4()), result_id=item["id"]))
    d = diagnose(app, original)
    with pytest.raises(ValueError):
        app.research.revise_diagnosis(dict(diagnosis_id=d["id"], reviewed=False))


def test_multiple_rule_changes_rejected_and_no_strategy_written(app):
    _, original = baseline(app)
    d = diagnose(app, original)
    p = json.loads(json.dumps(d["payload"]))
    p["proposal"]["rules"]["hold_bars"] = 8
    item = app.research.retain("AI_DIAGNOSIS", p)
    before = app.strategies.read()
    with pytest.raises(ValueError, match="one rule change"):
        app.research.revise_diagnosis(dict(diagnosis_id=item["id"], reviewed=True))
    assert app.strategies.read() == before


def test_provider_failure_is_retained_without_resend(app):
    _, original = baseline(app)
    calls = []

    def fail(raw):
        calls.append(raw)
        raise OSError("private error must not be exposed")

    app.research.transport = fail
    req = dict(request_id=str(uuid4()), result_id=original["id"])
    first = app.research.diagnose(req)
    assert first["status"] == "FAILED_OR_UNCERTAIN_NO_RESEND"
    assert app.research.diagnose(req) == first
    assert len(calls) == 1 and "private" not in json.dumps(first)


def test_investigation_only_cannot_create_revision(app):
    _, original = baseline(app)
    d = diagnose(app, original)
    p = json.loads(json.dumps(d["payload"]))
    p["proposal"]["recommendation"] = "INVESTIGATE_DATA_OR_POLICY"
    item = app.research.retain("AI_DIAGNOSIS", p)
    with pytest.raises(ValueError, match="requires investigation"):
        app.research.revise_diagnosis(dict(diagnosis_id=item["id"], reviewed=True))


def test_comparison_failure_is_not_reported_as_completed(app, monkeypatch):
    _, original = baseline(app)
    d = diagnose(app, original)
    revision = app.research.revise_diagnosis(dict(diagnosis_id=d["id"], reviewed=True))
    monkeypatch.setattr(app.research, "execute", lambda _: None)
    monkeypatch.setattr(
        app.research,
        "run_status",
        lambda _: {"status": "COMPLETED", "outcome": {"status": "FAILED_NO_RESEND"}},
    )
    result = app.research.compare_revision(dict(revision_id=revision["id"], reviewed=True))
    assert result["status"] == "FAILED_NO_RESEND"
    assert result["kind"] == "COMPARISON_PENDING"


def test_halt_diagnosis_requires_measured_training_halt(app):
    _, original = baseline(app)
    with pytest.raises(ValueError, match="measured aggregate-risk"):
        app.research.investigate_halt(dict(result_id=original["id"]))
    held = app.research.retain("BACKTEST", dict(original["payload"], partition="holdout"))
    with pytest.raises(ValueError, match="training backtest"):
        app.research.investigate_halt(dict(result_id=held["id"]))
