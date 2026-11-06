"""Short actual demo quote-inspection acceptance; file faults only, no broker faults/orders."""

import argparse
import http.client
import json
import secrets
import threading
import time
from pathlib import Path
from uuid import uuid4

from fx_talanta.clock import SystemClock
from fx_talanta.dashboard.app import Dashboard
from fx_talanta.dashboard.current_broker import CurrentBrokerView, CurrentConfig
from fx_talanta.dashboard.demo import demo
from fx_talanta.dashboard.quote_clock import QuoteClock
from fx_talanta.dashboard.server import make_server
from fx_talanta.dashboard.service import InspectionService
from fx_talanta.observer.contracts import Binding
from tools.qualification.current_broker_capture import bounded_capture, existing_terminal


def run(binding, proof, out):
    pid = existing_terminal(binding)
    run_id = uuid4()
    latest = out / "latest.json"
    config = CurrentConfig(
        label="FOREX demo verified quote-age inspection",
        run_id=run_id,
        binding_hash=binding.fingerprint(),
        receipt_file=latest,
        quote_clock=proof,
    )
    (out / "view.json").write_text(config.model_dump_json(indent=2), encoding="utf-8")
    app = Dashboard(
        demo(),
        out / "state",
        secrets.token_urlsafe(32),
        SystemClock(),
        broker_view=CurrentBrokerView(config),
    )
    worker = InspectionService(app, 1)
    app.service = worker
    server = make_server(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    observations = []
    try:
        worker.start()
        thread.start()

        def get():
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                conn.request("GET", "/api/broker", headers={"Authorization": "Bearer " + app.token})
                response = conn.getresponse()
                return response.status, json.loads(response.read())
            finally:
                conn.close()

        def collect(sequence):
            if existing_terminal(binding) != pid:
                raise ValueError("terminal changed")
            r = bounded_capture(binding, run_id, sequence, proof)
            if existing_terminal(binding) != pid:
                raise ValueError("terminal changed")
            raw = r.model_dump_json(indent=2)
            (out / f"receipt-{sequence:04}.json").write_text(raw, encoding="utf-8")
            temp = out / "next.json"
            temp.write_text(raw, encoding="utf-8")
            temp.replace(latest)
            worker.sample()
            status, value = get()
            if status != 200 or value["quote_clock"] != "VERIFIED_BOUNDED":
                raise ValueError("current quote view not verified")
            observations.append(value["quote_observation"])
            if value["entry_ready"] or value["execution_enabled"]:
                raise ValueError("authority violation")
            return r

        for seq in range(1, 4):
            collect(seq)
        time.sleep(3)
        worker.sample()
        status, stale = get()
        stale_pass = status == 200 and stale["quote_freshness"] == "NOT_FRESH"
        original = latest.read_bytes()
        latest.rename(out / "retained-before-loss.json")
        worker.sample()
        missing_pass = get()[0] == 503
        # Actual new samples after the file fault, never restamp an old tick.
        for seq in range(4, 7):
            r = collect(seq)
        raw = latest.read_bytes()
        latest.write_text(r.model_copy(update={"quote_clock_hash": "0" * 64}).model_dump_json())
        worker.sample()
        mismatch_pass = get()[0] != 200
        latest.write_bytes(raw)
        worker.sample()
        recovery_pass = get()[0] == 200
        quotes = [q for observation in observations for q in observation["quotes"]]
        fresh = sum(q["state"] == "FRESH" for q in quotes)
        recovery_fresh = any(q["state"] == "FRESH" for o in observations[3:] for q in o["quotes"])
        ages = [q["age_seconds"] for q in quotes if q["age_seconds"] is not None]
        result = dict(
            schema="verified-quote-inspection-acceptance/1",
            result="PASS"
            if all((stale_pass, missing_pass, mismatch_pass, recovery_pass, fresh, recovery_fresh))
            else "INCOMPLETE",
            samples=6,
            quotes=len(quotes),
            fresh_quotes=fresh,
            clock_error_bound_ms=proof.initial_error_ms,
            server_offset_seconds=proof.server_offset_seconds,
            quote_age_min_seconds=min(ages) if ages else None,
            quote_age_max_seconds=max(ages) if ages else None,
            real_elapsed_stale=stale_pass,
            isolated_file_missing_503=missing_pass,
            wrong_clock_hash_rejected=mismatch_pass,
            recovered_file_readable=recovery_pass,
            actual_fresh_quote_after_recovery=recovery_fresh,
            original_pre_loss_receipt_preserved=(out / "retained-before-loss.json").read_bytes()
            == original,
            local_notifications_undelivered=app.notifications.summary()["undelivered"],
            evidence_hash=proof.evidence_hash,
            entry_ceiling_seconds=2,
            trading_enabled=False,
            orders_submitted=0,
            terminal_settings_changed=False,
            full_M5_qualified=False,
            broker_disconnect_qualified=False,
            limitation=(
                "Bounded quote-age inspection, not network latency, sustained broker "
                "qualification or execution authority."
            ),
        )
        return result
    finally:
        if thread.is_alive():
            server.shutdown()
        server.server_close()
        thread.join(5)
        worker.stop()
        app.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("binding", "clock", "output", "report"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    if a.report.exists():
        raise ValueError("report already exists")
    a.output.mkdir(parents=True, exist_ok=False)
    try:
        report = run(
            Binding.model_validate_json(a.binding.read_bytes()),
            QuoteClock.model_validate_json(a.clock.read_bytes()),
            a.output.resolve(),
        )
    except Exception:
        (a.output / "failed.json").write_text('{"status":"ACCEPTANCE_FAILED"}')
        raise RuntimeError("acceptance failed; original private evidence retained") from None
    with a.report.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
