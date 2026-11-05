"""Offline, sample-scoped cost measurements from ONE saved demo history snapshot.

No prices, tickets, account IDs or paths are emitted. No replay profile is produced.
"""

import argparse
import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path


def number(value, *, positive=False):
    result = Decimal(str(value))
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError("invalid numeric evidence")
    return result


def assess(data):
    if data["account"]["trade_mode"] != 0 or data["account"]["currency"] != "CAD":
        raise ValueError("expected retained CAD demo population")
    trades = [d for d in data["deals"] if d["type"] in (0, 1)]
    if not trades or len({d["ticket"] for d in trades}) != len(trades):
        raise ValueError("empty or duplicate trade population")
    groups = defaultdict(list)
    for d in trades:
        if d["symbol"] != "EURUSD." or d["entry"] not in (0, 1):
            raise ValueError("unsupported symbol or reversal")
        if not d["position_id"] or number(d["volume"], positive=True) != Decimal("0.01"):
            raise ValueError("unexpected position or volume")
        if isinstance(d["time_msc"], bool) or not isinstance(d["time_msc"], int):
            raise ValueError("integer native timestamp required")
        groups[d["position_id"]].append(d)
    durations = []
    for deals in groups.values():
        entries = [d for d in deals if d["entry"] == 0]
        exits = [d for d in deals if d["entry"] == 1]
        if len(entries) != 1 or len(exits) != 1:
            raise ValueError("incomplete or unsupported partial position history")
        opened, closed = entries[0], exits[0]
        elapsed = closed["time_msc"] - opened["time_msc"]
        if elapsed < 0 or opened["type"] == closed["type"]:
            raise ValueError("invalid round trip chronology or direction")
        durations.append(elapsed)
    volume = sum((number(d["volume"]) for d in trades), Decimal(0))
    charges = {
        k: sum((number(d[k]) for d in trades), Decimal(0)) for k in ("commission", "fee", "swap")
    }
    return {
        "schema": "retained-cost-calibration/1",
        "scope": "FOREX.com MT5 saved CAD demo EURUSD sample only",
        "trade_deals": len(trades),
        "matched_closed_positions": len(groups),
        "filled_lots_across_both_legs": str(volume),
        "native_elapsed_ms_sorted": sorted(durations),
        "native_elapsed_is_verified_utc_interval": False,
        "recorded_trade_charges_cad": {k: str(v) for k, v in charges.items()},
        "observed_commission_and_fee_cad_per_filled_lot": str(
            (charges["commission"] + charges["fee"]) / volume
        ),
        "measurement_status": "OBSERVED_SAMPLE_ONLY",
        "nontrade_deals_excluded": len(data["deals"]) - len(trades),
        "complete_account_charge_audit": False,
        "account_tariff": "UNKNOWN",
        "historical_2025_applicability": "UNPROVEN",
        "financing_rate": "NOT_IDENTIFIABLE_FROM_ZERO_RECORDED_SWAP",
        "slippage": "NO_VALIDATED_SUBMISSION_BENCHMARK",
        "cad_to_usd_conversion": "NO_DATED_CONVERSION_EVIDENCE",
        "broker_costs_qualified": False,
        "replay_profile_created": False,
        "b01_verdict": "REJECT_FOR_PROMOTION_UNCHANGED",
        "execution_enabled": False,
    }


def run(source, output):
    raw = source.read_bytes()
    result = assess(json.loads(raw))
    if source.read_bytes() != raw:
        raise ValueError("source changed during assessment")
    result["source_sha256"] = hashlib.sha256(raw).hexdigest()
    result["assessor_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result["source_unchanged"] = True
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.output)


if __name__ == "__main__":
    main()
