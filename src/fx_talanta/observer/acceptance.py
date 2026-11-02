"""Version-two slot-based evidence. Never re-score legacy campaigns."""

from collections import Counter
from datetime import timedelta
from math import ceil
from statistics import median


class SeparatedEvidence:
    def __init__(self):
        self.records = {}

    @property
    def ids(self):
        return self.records.keys()

    def add(self, record):
        if record.body.health is None:
            raise ValueError("v2 acceptance requires v2 observations")
        self.records.setdefault(record.record_id, record)

    def summary(self, started, now, plan, phase):
        duration = plan.duration_seconds
        elapsed = max(0, (now - started).total_seconds())
        slots_total = ceil(duration / plan.interval_seconds)
        slots_due = min(slots_total, int(min(elapsed, duration) // plan.interval_seconds) + 1)
        records = sorted(self.records.values(), key=lambda r: r.recorded_at)
        scheduled, final = [], []
        slots = {}
        for record in records:
            health = record.body.health
            if record.recorded_at > now:
                continue
            offset = (health.collection_started_at - started).total_seconds()
            if health.final_verification:
                if (
                    duration <= offset <= duration + plan.final_verification_seconds
                    and record.recorded_at
                    <= started + timedelta(seconds=duration + plan.final_verification_seconds)
                ):
                    final.append(record)
                continue
            if 0 <= offset < duration and record.recorded_at <= started + timedelta(
                seconds=duration
            ):
                slot = int(offset // plan.interval_seconds)
                # First committed attempt owns the slot: later bursts cannot
                # replace a failed/stale attempt with a cherry-picked success.
                if slot not in slots:
                    slots[slot] = record
                    scheduled.append(record)
        complete = [r for r in scheduled if r.body.health.complete_read]
        fresh = [r for r in complete if r.body.reason == "CURRENT"]
        end = min(elapsed, duration)

        def gaps(items):
            times = [0.0] + [(r.recorded_at - started).total_seconds() for r in items] + [end]
            return max((b - a for a, b in zip(times, times[1:], strict=False)), default=end)

        span = (
            (scheduled[-1].recorded_at - scheduled[0].recorded_at).total_seconds()
            if scheduled
            else 0
        )
        final_count = sum(r.body.health.final_verification for r in records)
        last = final[0] if len(final) == final_count == 1 else None
        final_complete = bool(
            last and last.body.health.complete_read and last.body.state != "HALTED"
        )
        final_fresh = bool(final_complete and last.body.reason == "CURRENT")
        collector = {
            "valid_timestamps": not any(r.recorded_at > now for r in records),
            "duration": elapsed >= duration,
            "minimum_24_hours": duration >= 86400,
            "sample_span": span >= duration - 2 * plan.interval_seconds,
            "coverage": len(scheduled) / slots_due >= plan.minimum_coverage_fraction,
            "complete_reads": len(complete) / slots_due >= plan.minimum_healthy_fraction,
            "attempt_gaps": gaps(scheduled) <= plan.max_gap_seconds,
            "complete_read_gaps": gaps(complete) <= plan.max_gap_seconds,
            "final_read": final_complete,
            "no_halt": not any(r.body.state == "HALTED" for r in records),
        }
        quotes = {
            "fresh_slot_fraction": len(fresh) / slots_due >= plan.minimum_healthy_fraction,
            "final_fresh": final_fresh,
        }
        symbols = sorted({s for r in scheduled for s in r.body.health.quote_quality})
        quality_summary = {}
        for symbol in symbols:
            ages = sorted(
                r.body.health.quote_ages_seconds[symbol]
                for r in scheduled
                if symbol in r.body.health.quote_ages_seconds
            )
            longest = streak = 0
            previous_slot = -2
            for slot, record in sorted(slots.items()):
                stale = record.body.health.quote_quality.get(symbol) == "STALE"
                streak = (streak + 1 if slot == previous_slot + 1 else 1) if stale else 0
                longest = max(longest, streak)
                previous_slot = slot
            quality_summary[symbol] = {
                "age_samples": len(ages),
                "median_age_seconds": median(ages) if ages else None,
                "p95_age_seconds": ages[ceil(0.95 * len(ages)) - 1] if ages else None,
                "max_age_seconds": max(ages) if ages else None,
                "longest_consecutive_stale_sample_slots": longest,
            }
        collector_passed = phase == "COMPLETE" and all(collector.values())
        quote_passed = (
            phase == "COMPLETE"
            and all(quotes.values())
            and collector["duration"]
            and collector["minimum_24_hours"]
        )
        return {
            "policy_version": 2,
            "last_state": records[-1].body.state if records else None,
            "last_reason": records[-1].body.reason if records else None,
            "last_committed_at": records[-1].recorded_at.isoformat() if records else None,
            "last_successful_committed_read_at": max(
                (r.recorded_at for r in records if r.body.health.complete_read), default=None
            ).isoformat()
            if any(r.body.health.complete_read for r in records)
            else None,
            "observations": len(scheduled),
            "scheduled_slots": slots_total,
            "slots_due": slots_due,
            "complete_reads": len(complete),
            "healthy": len(fresh),
            "reasons": dict(Counter(r.body.reason for r in scheduled)),
            "coverage_fraction": len(scheduled) / slots_due,
            "healthy_fraction": len(fresh) / slots_due,
            "legacy_fresh_per_committed_fraction": len(fresh) / len(scheduled) if scheduled else 0,
            "per_symbol_fresh_fraction": {
                s: sum(
                    r.body.health.quote_quality.get(s) == "FRESH" and r.body.health.complete_read
                    for r in scheduled
                )
                / slots_due
                for s in symbols
            },
            "per_symbol_quote_quality": quality_summary,
            "elapsed_seconds": elapsed,
            "observed_span_seconds": span,
            "max_gap_seconds": gaps(scheduled),
            "max_complete_read_gap_seconds": gaps(complete),
            "collector_gates": collector,
            "quote_gates": quotes,
            "collector_accepted": collector_passed,
            "quote_readiness_accepted": quote_passed,
            "accepted": collector_passed and quote_passed,
            "final_verification_records": final_count,
            "timely_final_verification_records": len(final),
            "final_verification_duration_seconds": (
                last.recorded_at - last.body.health.collection_started_at
            ).total_seconds()
            if last
            else None,
            "final_verification_after_deadline_seconds": (
                last.recorded_at - started
            ).total_seconds()
            - duration
            if last
            else None,
            "entry_authorized": False,
        }
