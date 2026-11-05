"""Bounded, offline HistData ASCII tick import. No network or broker access."""

import argparse
import csv
import io
import json
import re
import zipfile
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from fx_talanta.domain.offline import Instrument, Market, Quote
from fx_talanta.research.baseline import Bar
from fx_talanta.research.replay import Dataset, Event

EST = timezone(timedelta(hours=-5))  # Source specifies fixed EST, including summer.
MAX_ARCHIVE = 32 * 1024 * 1024
MAX_CSV = 256 * 1024 * 1024


def parse_row(row):
    if len(row) != 4 or not re.fullmatch(r"\d{8} \d{9}", row[0]):
        raise ValueError("expected HistData ASCII tick row")
    at = datetime.strptime(row[0], "%Y%m%d %H%M%S%f").replace(tzinfo=EST).astimezone(UTC)
    bid, ask, volume = map(Decimal, row[1:])
    if not all(x.is_finite() for x in (bid, ask, volume)) or not 0 < bid <= ask or volume < 0:
        raise ValueError("invalid historical quote")
    return at, bid, ask


def import_zip(path, symbol, start, end, *, latency_ms=250, assume_inputs=False):
    """Construct BID bars and preserve every selected tick, including timestamp ties.

    assume_inputs is a counterfactual research scenario, never an M1 attestation.
    Original receipt times and provider revisions are not present in this format.
    """
    if symbol not in {"EURUSD", "USDJPY"}:
        raise ValueError("unsupported pair")
    if start.tzinfo is None or end.tzinfo is None or not start < end:
        raise ValueError("ordered, timezone-aware interval required")
    if not isinstance(latency_ms, int) or not 0 <= latency_ms <= 10000:
        raise ValueError("explicit modeled latency must be 0..10000 ms")
    path = Path(path)
    if path.stat().st_size > MAX_ARCHIVE:
        raise ValueError("archive size bound")
    archive_hash = sha256(path.read_bytes()).hexdigest()
    latency = timedelta(milliseconds=latency_ms)
    pip = Decimal("0.0001" if symbol == "EURUSD" else "0.01")
    spec = Instrument(
        symbol=symbol,
        base=symbol[:3],
        quote=symbol[3:],
        minimum_stop=pip / 2,
        maximum_spread=pip * 3,
        maximum_adverse_move=pip * 5,
    )
    groups, events = {}, []
    first = previous = last = None
    rows = ties = exact_duplicates = large_gaps = 0
    max_gap = 0.0
    previous_quote = None
    gaps = []
    with zipfile.ZipFile(path) as archive:
        names = [
            i
            for i in archive.infolist()
            if re.fullmatch(rf"DAT_ASCII_{symbol}_T_\d{{6}}\.csv", i.filename)
        ]
        if len(names) != 1 or len(archive.infolist()) > 10:
            raise ValueError("expected one matching tick CSV")
        member = names[0]
        if member.file_size > MAX_CSV or member.flag_bits & 1:
            raise ValueError("oversized or encrypted CSV")
        with archive.open(member) as raw:
            stream = io.TextIOWrapper(raw, encoding="ascii", newline="")
            for sequence, row in enumerate(csv.reader(stream)):
                if len(row) == 1 and not row[0].strip():
                    continue
                at, bid, ask = parse_row(row)
                if previous is not None and at < previous:
                    raise ValueError("source timestamps moved backwards; do not sort away evidence")
                if previous == at:
                    ties += 1
                    exact_duplicates += previous_quote == (bid, ask)
                if previous is not None:
                    gap = (at - previous).total_seconds()
                    max_gap = max(max_gap, gap)
                    if gap > 180:
                        large_gaps += 1
                        if len(gaps) < 100:
                            gaps.append(
                                {"from": previous.isoformat(), "to": at.isoformat(), "seconds": gap}
                            )
                first = first or at
                previous, previous_quote, last = at, (bid, ask), at
                rows += 1
                if rows > 5_000_000:
                    raise ValueError("row bound")
                # Later source rows are validated, but cannot affect selected bars or trades.
                if at < end:
                    for minutes in (15, 60):
                        bucket = at.replace(
                            minute=(at.minute // minutes) * minutes, second=0, microsecond=0
                        )
                        key = minutes, bucket
                        if key not in groups:
                            groups[key] = [bid, bid, bid, bid]
                        else:
                            values = groups[key]
                            values[1], values[2], values[3] = (
                                max(values[1], bid),
                                min(values[2], bid),
                                bid,
                            )
                available = at + latency
                if start <= available < end:
                    conversion = {"USD": Decimal(1)}
                    conversion["EUR" if symbol == "EURUSD" else "JPY"] = (
                        bid if symbol == "EURUSD" else Decimal(1) / ask
                    )
                    events.append(
                        Event(
                            available_at=available,
                            source_sequence=sequence,
                            market=Market(
                                at=at,
                                quotes=(Quote(symbol=symbol, bid=bid, ask=ask, at=at),),
                                instruments=(spec,),
                                conversion=conversion,
                                calendar_ok=assume_inputs,
                                news_ok=assume_inputs,
                            ),
                        )
                    )
                    if len(events) > 50000:
                        raise ValueError(
                            "pilot event bound exceeded; never silently downsample ticks"
                        )
    if first is None:
        raise ValueError("empty tick archive")
    bars = []
    for (minutes, bucket), (opened, high, low, closed) in sorted(groups.items()):
        close = bucket + timedelta(minutes=minutes)
        if bucket < first or close > min(last, end):
            continue  # Never publish a partially bounded edge bar.
        bars.append(
            Bar(
                symbol=symbol,
                timeframe="H1" if minutes == 60 else "M15",
                close_at=close,
                available_at=close + latency,
                revision=1,
                open=opened,
                high=high,
                low=low,
                close=closed,
            )
        )
    assumptions = {
        "receipt_time": "UNKNOWN",
        "modeled_latency_ms": latency_ms,
        "source_revisions": "UNKNOWN",
        "session_calendar": "UNRECONCILED",
        "research_inputs_assumed": assume_inputs,
        "calendar_news_qualified": False,
        "history_qualified": False,
        "conversion": "USD account; EUR valued at bid, JPY at inverse ask",
        "execution_enabled": False,
    }
    report = {
        "schema": "histdata-import/1",
        "symbol": symbol,
        "archive_sha256": archive_hash,
        "source_timezone": "fixed UTC-05:00; no DST",
        "rows": rows,
        "timestamp_ties": ties,
        "exact_duplicate_rows_retained": exact_duplicates,
        "first": first.isoformat(),
        "last": last.isoformat(),
        "selected_events": len(events),
        "bars": len(bars),
        "gaps_over_180s": large_gaps,
        "maximum_gap_seconds": max_gap,
        "gap_examples": gaps,
        "assumptions": assumptions,
    }
    data = Dataset(
        provenance="HISTORICAL_UNQUALIFIED",
        source=f"HistData {symbol} SHA256 {archive_hash}",
        session_calendar="Unreconciled; optional input completeness is a counterfactual assumption",
        bar_price_basis="BID",
        history_complete=assume_inputs,
        bars=tuple(bars),
        events=tuple(events),
    )
    return data, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--symbol", choices=("EURUSD", "USDJPY"), required=True)
    parser.add_argument("--start", type=datetime.fromisoformat, required=True)
    parser.add_argument("--end", type=datetime.fromisoformat, required=True)
    parser.add_argument("--latency-ms", type=int, default=250)
    parser.add_argument("--assume-research-inputs", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=False)
    try:
        data, report = import_zip(
            args.archive,
            args.symbol,
            args.start,
            args.end,
            latency_ms=args.latency_ms,
            assume_inputs=args.assume_research_inputs,
        )
        payload = data.model_dump_json()
        if len(payload.encode()) > 32 * 1024 * 1024:
            raise ValueError("replay input size bound")
        (args.output / "dataset.json").write_text(payload + "\n", encoding="utf-8", newline="\n")
        (args.output / "quality.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        print(
            json.dumps(
                {k: report[k] for k in ("symbol", "rows", "selected_events", "timestamp_ties")}
            )
        )
        return 0
    except Exception:
        (args.output / "failed.json").write_text('{"status":"FAILED"}\n', encoding="utf-8")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
