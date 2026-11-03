"""Verify and sanitize actual native M2B artifacts; does not run MT5 or trade."""

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from fx_talanta.domain.ea_protocol import ChannelTelemetry
from fx_talanta.execution_contracts.ea_journal import read_journal

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(native, compiler_run="05", service_run="02"):
    sources = {}
    for source in sorted((ROOT / "mql5/gateway").iterdir()):
        copied = (
            native / "MQL5/Services/FXTalantaBootstrap.mq5"
            if source.name == "BootstrapSynthetic.mq5"
            else native / "MQL5/Experts/FXTalanta" / source.name
        )
        if source.read_bytes() != copied.read_bytes():
            raise ValueError(f"native source mismatch: {source.name}")
        sources[source.relative_to(ROOT).as_posix()] = digest(source)
    builds = {}
    for unit in ("NativeTests", "FixedGateway", "GatewayTester", "FXTalantaBootstrap"):
        service = unit == "FXTalantaBootstrap"
        logfile = native / (
            f"bootstrap-service-compile-{service_run}.log"
            if service
            else f"{unit}-compile-{compiler_run}.log"
        )
        results = re.findall(r"Result: (\d+) errors, (\d+) warnings", logfile.read_text("utf-16"))
        if results != [("0", "0")]:
            raise ValueError(f"compile did not pass cleanly: {unit}")
        binary = native / ("MQL5/Services" if service else "MQL5/Experts/FXTalanta") / f"{unit}.ex5"
        builds[unit] = {
            "errors": 0,
            "warnings": 0,
            "ex5_sha256": digest(binary),
            "compile_log_sha256": digest(logfile),
        }
    agent = native / "Tester/Agent-127.0.0.1-3001"
    log = sorted((agent / "logs").glob("*.log"))[-1]
    text = log.read_text("utf-16")
    start = text.rfind("FX_M2B_CHECK python_native_canonical_hash")
    if start < 0:
        raise ValueError("no native test start")
    session = text[start:]
    checks = re.findall(r"FX_M2B_CHECK (\w+) (PASS|FAIL)", session)
    match = re.search(
        r"FX_M2B_ORDER_RESULT checks=(\d+) failures=(\d+) sends=(\d+) "
        r"callbacks=(\d+) final_positions=(\d+) final_orders=(\d+)",
        session,
    )
    if match is None:
        raise ValueError("no completed native order result")
    count, failures, sends, callbacks, positions, orders = map(int, match.groups())
    if len(checks) != count or len(dict(checks)) != count or failures or positions or orders:
        raise ValueError("native run incomplete/failed")
    if any(result != "PASS" for _, result in checks) or sends != 7 or callbacks < 1:
        raise ValueError("native execution checks failed")
    journal = max(
        (agent / "MQL5/Files/fx-m2b-tests").glob("native-orders-*.journal"),
        key=lambda p: p.stat().st_mtime_ns,
    )
    records = read_journal(journal.read_bytes())
    latest = {r.envelope.payload.message_id: r for r in records}
    if len(latest) != 7 or any(r.state != "CLOSED" or r.remaining_units for r in latest.values()):
        raise ValueError("independent journal reconstruction disagrees")
    telemetry_file = agent / "MQL5/Files/fx-m2b/ea-quote.json"
    telemetry = ChannelTelemetry.model_validate_json(telemetry_file.read_bytes())
    terminal_log = sorted((native / "MQL5/logs").glob("*.log"))[-1]
    if "FX_M2B_CONNECTED_EXECUTION_DISABLED" not in terminal_log.read_text("utf-16"):
        raise ValueError("non-Tester rejection evidence missing")
    platform_log = sorted((native / "logs").glob("20*.log"))[-1]
    builds_seen = re.findall(r"MetaTrader 5 x64 build (\d+)", platform_log.read_text("utf-16"))
    if not builds_seen:
        raise ValueError("terminal build evidence missing")
    isolation = json.loads((native / "isolation-check.json").read_text("utf-8-sig"))
    required = (
        "original_profile_unchanged",
        "private_terminal_stopped",
        "temporary_account_cache_removed",
        "loopback_proxy_configured",
        "allow_live_trading_disabled",
    )
    if any(isolation.get(key) is not True for key in required):
        raise ValueError("host isolation verification incomplete")
    return dict(
        schema="m2b-native-evidence/1",
        verified_at=datetime.now(UTC).isoformat(),
        scope="Offline native Strategy Tester using synthetic custom-symbol data only",
        terminal_build=int(builds_seen[-1]),
        source_sha256=sources,
        builds=builds,
        native_checks={
            "count": count,
            "failures": failures,
            "checks": dict(checks),
            "simulated_order_calls": sends,
            "trade_callbacks": callbacks,
            "final_positions": positions,
            "final_orders": orders,
            "agent_log_sha256": digest(log),
        },
        journal={
            "independently_verified_rows": len(records),
            "requests": len(latest),
            "all_closed": True,
            "remaining_reserved_units": 0,
            "sha256": digest(journal),
        },
        telemetry={
            "python_schema_valid": True,
            "channel": telemetry.channel,
            "capability": telemetry.capability,
            "fresh_at_measurement": telemetry.quote_fresh(telemetry.measured_at),
            "delivery_latency_measured": telemetry.samples > 0,
            "sha256": digest(telemetry_file),
        },
        connected_mode_refused=True,
        connected_trading_enabled=False,
        new_broker_campaign_started=False,
        host_verification=isolation,
        earlier_attempts=[
            "OnTesterInit bootstrap timed out before its body ran; not a test pass.",
            "Initial service bootstrap reported error 5308; later setup produced 7200 bars.",
            "Credential-free full Tester startup refused: account not specified.",
            "Earlier core math: 51 passed; earlier orders: 72 passed/5 simulated sends.",
        ],
        isolation=[
            "Separate portable terminal; no M2B files installed into broker terminals.",
            "Temporary copy of existing demo profile used with unreachable loopback proxy.",
            "Tester account is synthetic 42. Original profile hashes verified unchanged.",
            "Isolated terminal stopped; temporary accounts.dat copy removed afterward.",
            "Raw logs remain private; only sanitized results and hashes are published.",
        ],
        limitations=[
            "Not broker execution, sustained qualification, or production deployment approval.",
            "USD synthetic custom-symbol economics; native USD/CAD risk parity remains M2C.",
            "Partial fill/lost acknowledgement/corruption are core fixtures, not broker faults.",
            "No qualified transport, loss ledger, protection deadlines, or broker failover.",
            "Telemetry is simulated; source clock and delivery latency remain unproven.",
        ],
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compiler-run", default="05")
    parser.add_argument("--service-run", default="02")
    args = parser.parse_args()
    report = verify(args.native_root, args.compiler_run, args.service_run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "native_checks": report["native_checks"]["count"],
                "independent_journal_rows": report["journal"]["independently_verified_rows"],
            }
        )
    )
