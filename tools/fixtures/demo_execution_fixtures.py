"""Bounded synthetic demo-dispatch inputs; no broker connection or order capability."""

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


def compare(folder):
    checks = dict(
        line.split("\t") for line in (Path(folder) / "demo-checks.tsv").read_text().splitlines()
    )
    if len(checks) < 20 or any(value != "1" for value in checks.values()):
        raise ValueError("NATIVE_FAILURE:" + str([k for k, v in checks.items() if v != "1"]))
    return dict(
        checks=checks,
        synthetic=True,
        execution_enabled=False,
        broker_orders_sent=0,
        demo_order_acceptance=False,
    )
