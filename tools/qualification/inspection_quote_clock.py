"""Corroborate a short inspection clock using saved BLS, native MCP and NTP.

Creates a NEW private binding. Never edits an old policy or changes host/terminal time.
This deliberately supports only an exact Employment Situation anchor on the same UTC day.
"""

import argparse
import json
import ntpath
import subprocess
import time
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from fx_talanta.acceptance.clock_probe import probe
from fx_talanta.bls_calendar import parse_ics
from fx_talanta.dashboard.quote_clock import QuoteClock, host_identity
from fx_talanta.mcp_client import Client, validate_endpoint
from fx_talanta.observer.contracts import Binding, windows_path
from tools.qualification.current_broker_capture import existing_terminal


def endpoint_from_export(path):
    raw = path.read_bytes()
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("export too large")
    text = raw.decode("utf-8-sig")
    for i, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = json.JSONDecoder().raw_decode(text[i:])
        except ValueError:
            continue
        if isinstance(value, dict) and "mcpServers" in value:
            return validate_endpoint(value["mcpServers"]["terminal"]["url"])
    raise ValueError("terminal export required")


def check_owner(endpoint, binding):
    port = urlsplit(endpoint).port
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            f"Get-NetTCPConnection -State Listen -LocalPort {port} -ErrorAction Stop | "
            "ForEach-Object { (Get-Process -Id $_.OwningProcess -ErrorAction Stop).Path } | "
            "ConvertTo-Json -Compress",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise ValueError("MCP listener unavailable")
    paths = json.loads(result.stdout)
    paths = paths if isinstance(paths, list) else [paths]
    if not paths or any(windows_path(p) != windows_path(binding.terminal_path) for p in paths):
        raise ValueError("MCP owner mismatch")


def anchor_offset(events, values, scheduled):
    expected = {"840030015": "unemployment-rate", "840030016": "nonfarm-payrolls"}
    catalog = {str(e["id"]): e for e in events}
    for eid, code in expected.items():
        e = catalog[eid]
        if e["event_code"] != code or urlsplit(e["source_url"]).hostname not in {
            "bls.gov",
            "www.bls.gov",
        }:
            raise ValueError("official BLS event required")
    rows = [v for v in values if str(v["event_id"]) in expected]
    if len(rows) != 2 or {str(v["event_id"]) for v in rows} != set(expected):
        raise ValueError("two exact employment anchors required")
    offsets = set()
    for row in rows:
        native = datetime.fromisoformat(row["time"])
        if row["time_unknown"] is not False or native.tzinfo is not None:
            raise ValueError("exact server-wall-clock anchor required")
        offsets.add((native - scheduled.replace(tzinfo=None)).total_seconds())
    if len(offsets) != 1:
        raise ValueError("calendar anchors disagree")
    offset = offsets.pop()
    if offset % 900 or not -50400 <= offset <= 50400:
        raise ValueError("unsupported offset")
    return int(offset), rows


def verify(binding, export, reference, out):
    def stage(name):
        (out / "stage.json").write_text(json.dumps({"stage": name}), encoding="utf-8")

    stage("OWNER_CHECK")
    original_pid = existing_terminal(binding)
    endpoint = endpoint_from_export(export)
    check_owner(endpoint, binding)  # Before credential transmission.
    client = Client(export, endpoint, timeout=5)
    stage("MCP_IDENTITY")
    client.start()
    terminal = client.tool("terminal_get_info", {})["terminal"]
    if (
        windows_path(terminal["terminal_path"])
        not in {
            windows_path(binding.terminal_path),
            windows_path(ntpath.dirname(binding.terminal_path)),
        }
        or windows_path(terminal["data_path"]) != windows_path(binding.data_path)
        or terminal["build"] != binding.expected_build
    ):
        raise ValueError("terminal identity mismatch")
    now = datetime.now(UTC)
    stage("SAVED_BLS_ANCHOR")
    raw = reference.read_bytes()
    anchors = [
        e
        for e in parse_ics(raw)
        if e.release_id == 50 and e.scheduled_at.date() == now.date() and e.status == "CONFIRMED"
    ]
    if len(anchors) != 1:
        raise ValueError("same-day saved Employment Situation schedule required")
    events = client.tool("economic_calendar_list_events_by_currency", {"currency_code": "USD"})
    stage("NATIVE_CALENDAR")
    day = now.date().isoformat()
    values = client.tool(
        "economic_calendar_list_values",
        {"datetime_from": day + "T00:00:00", "datetime_to": day + "T23:59:59", "limit": 1000},
    )
    (out / "calendar.private.json").write_text(
        json.dumps({"events": events, "values": values}), encoding="utf-8"
    )
    if values.get("truncated") or len(values["values"]) >= 1000:
        raise ValueError("calendar response incomplete")
    offset, rows = anchor_offset(events["events"], values["values"], anchors[0].scheduled_at)
    times = client.tool("get_time_information", {})
    stage("CURRENT_SERVER_TIME")
    (out / "time.json").write_text(json.dumps(times), encoding="utf-8")
    utc = datetime.fromisoformat(times["utc_time"])
    server = datetime.fromisoformat(times["trade_server_last_known_time"]).replace(tzinfo=UTC)
    if (
        abs((datetime.now(UTC) - utc).total_seconds()) > 2
        or abs((server - timedelta(seconds=offset) - utc).total_seconds()) > 5
    ):
        raise ValueError("current terminal time disagrees with calendar mapping")
    stage("HOST_CLOCK")
    ntp = probe()
    (out / "ntp.json").write_text(json.dumps(ntp), encoding="utf-8")
    verified = datetime.now(UTC)
    mono = time.monotonic()
    if (
        not ntp["passed"]
        or (verified - datetime.fromisoformat(ntp["checked_at"])).total_seconds() > 1
    ):
        raise ValueError("fresh bounded host clock required")
    if existing_terminal(binding) != original_pid:
        raise ValueError("terminal changed during clock verification")
    evidence = dict(
        reference_sha256=sha256(raw).hexdigest(),
        reference_scheduled_utc=anchors[0].scheduled_at.isoformat(),
        anchors=rows,
        terminal_time=times,
        ntp=ntp,
        terminal_identity_verified=True,
        source_binding_hash=binding.fingerprint(),
    )
    encoded = json.dumps(evidence, sort_keys=True).encode()
    evidence_hash = sha256(encoded).hexdigest()
    until = verified + timedelta(minutes=5)
    new = Binding.model_validate(
        binding.model_copy(
            update={
                "sdk_time_offset_seconds": offset,
                "time_policy_from": verified,
                "time_policy_until": until,
                "time_policy_evidence": evidence_hash,
            }
        ).model_dump(mode="json")
    )
    clock = QuoteClock(
        binding_hash=new.fingerprint(),
        host_hash=host_identity(),
        verified_at=verified,
        verified_monotonic=mono,
        valid_until=until,
        server_offset_seconds=offset,
        initial_error_ms=ntp["error_bound_ms"],
        evidence_hash=evidence_hash,
        symbols=binding.symbols,
    )
    if clock.status(datetime.now(UTC), time.monotonic(), host_identity())[0] != "VERIFIED_BOUNDED":
        raise ValueError("clock uncertainty exhausted before publication")
    (out / "evidence.private.json").write_bytes(encoded)
    (out / "binding.private.json").write_text(new.model_dump_json(indent=2), encoding="utf-8")
    (out / "clock.json").write_text(clock.model_dump_json(indent=2), encoding="utf-8")
    stage("COMPLETE")
    return clock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binding", "export", "reference", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    try:
        clock = verify(
            Binding.model_validate_json(args.binding.read_bytes()),
            args.export,
            args.reference,
            args.output,
        )
        print(
            json.dumps(
                dict(
                    status="VERIFIED_BOUNDED",
                    valid_until=clock.valid_until.isoformat(),
                    server_offset_seconds=clock.server_offset_seconds,
                    error_bound_ms=clock.initial_error_ms,
                    trading_enabled=False,
                )
            )
        )
    except Exception:
        (args.output / "failure.json").write_text('{"status":"CLOCK_VERIFICATION_FAILED"}')
        raise RuntimeError("clock verification failed; no authority issued") from None


if __name__ == "__main__":
    main()
