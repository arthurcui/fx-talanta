"""Descriptive report from committed observations; no SDK or acceptance promotion."""

from collections import Counter
from hashlib import sha256
from math import ceil

from fx_talanta.domain.models import TerminalObservation


def distribution(values):
    values = sorted(values)
    if not values:
        return {"samples": 0, "p50": None, "p95": None, "max": None}
    return {
        "samples": len(values),
        "p50": values[ceil(len(values) * 0.50) - 1],
        "p95": values[ceil(len(values) * 0.95) - 1],
        "max": values[-1],
    }


def summarize(records):
    """No prices/IDs in output. UTC-hour bins are descriptive, not session labels."""
    records = list(records)
    if not records:
        raise ValueError("no committed observations")
    first = records[0]
    if any(
        not isinstance(r.body, TerminalObservation)
        or r.account != first.account
        or r.correlation_id != first.correlation_id
        or r.body.binding_hash != first.body.binding_hash
        for r in records
    ):
        raise ValueError("mixed observation scope")
    if len({r.record_id for r in records}) != len(records):
        raise ValueError("duplicate record")
    if any(a.recorded_at > b.recorded_at for a, b in zip(records, records[1:])):
        raise ValueError("records out of commit order")
    reasons = Counter()
    diagnostics = Counter()
    ages, repeated, previous_ticks, stale_streak, longest_streak = {}, {}, {}, {}, {}
    durations, hours = [], {}
    missing_health = 0
    for record in records:
        body = record.body
        reasons[body.reason] += 1
        if body.diagnostic:
            diagnostics[body.diagnostic.rule] += 1
        hour = record.recorded_at.strftime("%Y-%m-%dT%H:00:00Z")
        bucket = hours.setdefault(hour, {"records": 0, "complete": 0, "fresh": 0})
        bucket["records"] += 1
        if body.health:
            h = body.health
            durations.append((record.recorded_at - h.collection_started_at).total_seconds())
            bucket["complete"] += int(h.complete_read)
            bucket["fresh"] += int(
                h.complete_read and all(quality == "FRESH" for quality in h.quote_quality.values())
            )
            for symbol, age in h.quote_ages_seconds.items():
                ages.setdefault(symbol, []).append(age)
            for symbol, quality in h.quote_quality.items():
                stale_streak[symbol] = stale_streak.get(symbol, 0) + 1 if quality == "STALE" else 0
                longest_streak[symbol] = max(longest_streak.get(symbol, 0), stale_streak[symbol])
        else:
            missing_health += 1
        if not body.snapshot:
            previous_ticks.clear()
            stale_streak.clear()
            continue
        current = {t.symbol: t.at for t in body.snapshot.ticks}
        for symbol, at in current.items():
            repeated[symbol] = repeated.get(symbol, 0) + int(previous_ticks.get(symbol) == at)
        previous_ticks = current
    return {
        "schema": "observation-description/1",
        "records": len(records),
        "records_sha256": sha256(
            "\n".join(r.model_dump_json() for r in records).encode()
        ).hexdigest(),
        "first_record_at": first.recorded_at.isoformat(),
        "last_record_at": records[-1].recorded_at.isoformat(),
        "reasons": dict(sorted(reasons.items())),
        "diagnostics": dict(sorted(diagnostics.items())),
        "missing_health_records": missing_health,
        "collection_to_record_seconds": distribution(durations),
        "inter_record_seconds": distribution(
            [(b.recorded_at - a.recorded_at).total_seconds() for a, b in zip(records, records[1:])]
        ),
        "symbols": {
            s: {
                "sampled_age_seconds": distribution(values),
                "age_le_2_seconds": sum(0 <= v <= 2 for v in values),
                "age_gt_2_le_5_seconds": sum(2 < v <= 5 for v in values),
                "age_gt_5_seconds": sum(v > 5 for v in values),
                "negative_age": sum(v < 0 for v in values),
                "repeated_timestamp_adjacent_reads": repeated.get(s, 0),
                "longest_consecutive_stale_samples": longest_streak.get(s, 0),
            }
            for s, values in sorted(ages.items())
        },
        "utc_hours": hours,
        "limitations": [
            "Descriptive committed samples only; no acceptance verdict or entry authorization.",
            "Collection-to-record excludes database commit latency; no SDK-call stage timings.",
            "Per-sample independent clock uncertainty is absent from legacy records.",
            "UTC hours are not inferred market sessions; no continuous-freshness claim.",
            "Missing slots and absent ticks are not imputed; old failed snapshots stay missing.",
        ],
    }
