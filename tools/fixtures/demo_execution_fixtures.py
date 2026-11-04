"""Bounded synthetic demo-dispatch inputs; no broker connection or order capability."""

import re
from pathlib import Path

from fx_talanta.demo.projection import project
from fx_talanta.demo.wire import encode_request
from fx_talanta.domain.ea_protocol import Envelope, ExecutionRequest
from fx_talanta.shadow.work import scope_for
from tools.fixtures.disabled_integration_fixtures import packet
from tools.fixtures.shadow_fixtures import CLIENT, KEY, POLICY, RELEASE, work

ACCOUNT = work()[0].payload.account.model_copy(update={"venue": "BROKER_DEMO"})


def example(action="ENTER", sequence=1):
    e, s = work(sequence)
    data = e.payload.model_dump() | {"account": ACCOUNT, "action": action}
    if action != "ENTER":
        data.update(
            max_risk="0",
            side=None,
            stop="1.099" if action == "TIGHTEN_STOP" else None,
            target=None,
            position_id=None if action == "CANCEL" else "700",
            order_id="500" if action == "CANCEL" else None,
            expected_state_version=4 if sequence == 2 else 3,
        )
    return Envelope.seal(ExecutionRequest.model_validate(data)), s


def export(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for action, sequence in [
        ("ENTER", 1),
        ("CLOSE", 1),
        ("TIGHTEN_STOP", 1),
        ("CANCEL", 1),
        ("ENTER", 2),
        ("CLOSE", 2),
        ("TIGHTEN_STOP", 2),
        ("CANCEL", 2),
    ]:
        e, s = example(action, sequence)
        frame = encode_request(e)
        risk = project(e, s)
        disabled = packet(risk)
        payload = "demo-execution/1\t" + frame.encode().hex() + "\t" + disabled.encode().hex()
        rows.append(
            "\t".join([action, frame.encode().hex(), risk.encode().hex(), payload.encode().hex()])
        )
    (folder / "demo-cases.tsv").write_text("\n".join(rows) + "\n", encoding="ascii")
    (folder / "demo-binding.tsv").write_text(
        "\t".join([scope_for(ACCOUNT), CLIENT, RELEASE, POLICY, KEY.decode()]) + "\n",
        encoding="ascii",
    )


def compare(folder, *, required_checks=None):
    """Verify a predeclared check set, never infer completeness from row count."""
    if required_checks is None:
        raise ValueError("REQUIRED_CHECK_MANIFEST_MISSING")
    if isinstance(required_checks, (str, bytes)):
        raise ValueError("INVALID_REQUIRED_CHECK_MANIFEST")
    required = tuple(required_checks)
    if (
        not required
        or any(
            not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9_-]+", name) is None
            for name in required
        )
        or len(set(required)) != len(required)
    ):
        raise ValueError("INVALID_REQUIRED_CHECK_MANIFEST")
    checks = {}
    for line in (Path(folder) / "demo-checks.tsv").read_text(encoding="ascii").splitlines():
        fields = line.split("\t")
        if len(fields) != 2 or re.fullmatch(r"[A-Za-z0-9_-]+", fields[0]) is None:
            raise ValueError("MALFORMED_NATIVE_CHECK")
        name, value = fields
        if name in checks:
            raise ValueError("DUPLICATE_NATIVE_CHECK:" + name)
        if value not in {"0", "1"}:
            raise ValueError("INVALID_NATIVE_CHECK_VALUE:" + name)
        checks[name] = value
    if set(checks) != set(required):
        raise ValueError(
            "NATIVE_CHECK_SET_MISMATCH:missing="
            + str(sorted(set(required) - checks.keys()))
            + ";unexpected="
            + str(sorted(checks.keys() - set(required)))
        )
    failures = [name for name, value in checks.items() if value != "1"]
    if failures:
        raise ValueError("NATIVE_FAILURE:" + str(failures))
    return dict(
        checks=checks,
        required_check_count=len(required),
        check_set_complete=True,
        synthetic=True,
        execution_enabled=False,
        broker_orders_sent=0,
        demo_order_acceptance=False,
    )
