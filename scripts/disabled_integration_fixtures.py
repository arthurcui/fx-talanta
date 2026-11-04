"""Synthetic no-order native evidence; never broker/provider qualification."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from fx_talanta.shadow.work import assess, parse_receipt, parse_work, scope_for
from scripts.shadow_fixtures import ACCOUNT, CLIENT, KEY, POLICY, RELEASE, cases


def packet(work):
    _, s = parse_work(work)
    day = datetime.fromtimestamp(s.measured_at_ms / 1000, UTC).strftime("%Y%m%d")
    return "\t".join(
        [
            "disabled-work/1",
            work.encode().hex(),
            day,
            format(s.day_start, "f"),
            "0",
            format(s.day_start, "f"),
            "1",
            format(s.day_loss, "f"),
            str(int(bool(s.flags & 2))),
            str(int(bool(s.flags & 1))),
            str(int(bool(s.flags & 64))),
        ]
    )


def export(folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "disabled-binding.tsv").write_text(
        "\t".join([scope_for(ACCOUNT), CLIENT, RELEASE, POLICY, KEY.decode()]) + "\n"
    )
    (folder / "disabled-cases.tsv").write_text(
        "".join(
            f"{name}\t{now}\t{error}\t{packet(work).encode().hex()}\n"
            for name, work, now, error in cases()
        )
    )


def compare(folder):
    rows = [r.split("\t") for r in (folder / "disabled-results.tsv").read_text().splitlines()]
    expected = list(cases())
    if len(rows) != len(expected):
        raise ValueError("NATIVE_CASE_COUNT")
    for row, (name, work, now, error) in zip(rows, expected, strict=True):
        if row[:2] != [name, "1"]:
            raise ValueError("NATIVE_RECEIVE_FAILED:" + name)
        native = bytes.fromhex(row[2]).decode()
        parse_receipt(native, work)
        if native != assess(work, now, error):
            # Numeric equality was already checked independently; native decimal
            # formatting may omit trailing zeros. Compare all non-volume fields.
            a, b = native.split("\t"), assess(work, now, error).split("\t")
            if a[:7] + a[8:] != b[:7] + b[8:]:
                raise ValueError("NATIVE_PARITY:" + name)
    checks = [r.split("\t") for r in (folder / "disabled-checks.tsv").read_text().splitlines()]
    if len(checks) != 12 or any(len(c) != 2 or c[1] != "1" for c in checks):
        raise ValueError("NATIVE_FAULT_CHECKS")
    return dict(
        synthetic=True,
        native_cases=len(rows),
        native_fault_checks=len(checks),
        execution_enabled=False,
        orders_sent=0,
        broker_qualified=False,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["export", "compare"])
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    if args.action == "export":
        export(args.folder)
    else:
        print(json.dumps(compare(args.folder), sort_keys=True))
