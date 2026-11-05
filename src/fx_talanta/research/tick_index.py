"""Private immutable SQLite tick index, built offline from a pinned HistData ZIP."""

import csv
import io
import json
import re
import sqlite3
import zipfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path

from fx_talanta.domain.offline import Instrument, Market, Quote
from fx_talanta.research.baseline import Bar
from fx_talanta.research.historical import EST, MAX_ARCHIVE, MAX_CSV, parse_row
from fx_talanta.research.replay import Event
from fx_talanta.research.spool import file_hash

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
MILLISECOND = timedelta(milliseconds=1)
MAX_TICKS = 5_000_000
MAX_BARS = 20000


def milliseconds(at):
    if at.tzinfo is None:
        raise ValueError("timezone required")
    return (at - EPOCH) // MILLISECOND


def build_index(archive_path, symbol, output):
    archive_path, output = Path(archive_path), Path(output)
    if symbol not in {"EURUSD", "USDJPY"} or archive_path.stat().st_size > MAX_ARCHIVE:
        raise ValueError("unsupported source or archive bound")
    output.mkdir(parents=True, exist_ok=False)
    db = sqlite3.connect(output / "ticks.sqlite")
    try:
        db.execute("PRAGMA cache_size=-8192")
        db.execute(
            "CREATE TABLE ticks(seq INTEGER PRIMARY KEY, at_ms INTEGER NOT NULL, "
            "bid TEXT NOT NULL, ask TEXT NOT NULL)"
        )
        db.execute("CREATE TABLE metadata(value TEXT NOT NULL)")
        groups, batch = {}, []
        first = last = None
        count = ties = 0
        with zipfile.ZipFile(archive_path) as archive:
            members = [
                i
                for i in archive.infolist()
                if re.fullmatch(rf"DAT_ASCII_{symbol}_T_\d{{6}}\.csv", i.filename)
            ]
            if len(members) != 1 or len(archive.infolist()) > 10:
                raise ValueError("one matching CSV required")
            member = members[0]
            month = member.filename[-10:-4]
            if member.file_size > MAX_CSV or member.flag_bits & 1:
                raise ValueError("CSV bound or encryption")
            with archive.open(member) as stream:
                for seq, row in enumerate(
                    csv.reader(io.TextIOWrapper(stream, encoding="ascii", newline=""))
                ):
                    at, bid, ask = parse_row(row)
                    if at.astimezone(EST).strftime("%Y%m") != month:
                        raise ValueError("row outside named source month")
                    if last is not None and at < last:
                        raise ValueError("source timestamps reversed")
                    ties += at == last
                    first = first or at
                    last = at
                    count += 1
                    if count > MAX_TICKS:
                        raise ValueError("tick count bound")
                    batch.append((seq, milliseconds(at), str(bid), str(ask)))
                    if len(batch) == 5000:
                        db.executemany("INSERT INTO ticks VALUES(?,?,?,?)", batch)
                        batch.clear()
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
                    if len(groups) > MAX_BARS:
                        raise ValueError("bar bound")
        if not count:
            raise ValueError("empty archive")
        db.executemany("INSERT INTO ticks VALUES(?,?,?,?)", batch)
        bars = []
        for (minutes, bucket), prices in sorted(groups.items()):
            close = bucket + timedelta(minutes=minutes)
            if bucket < first or close > last:
                continue
            bars.append(
                Bar(
                    symbol=symbol,
                    timeframe="H1" if minutes == 60 else "M15",
                    close_at=close,
                    available_at=close,
                    revision=1,
                    open=prices[0],
                    high=prices[1],
                    low=prices[2],
                    close=prices[3],
                ).model_dump(mode="json")
            )
        metadata = {
            "schema": "historical-tick-index/1",
            "status": "COMPLETE",
            "symbol": symbol,
            "archive_sha256": file_hash(archive_path),
            "rows": count,
            "timestamp_ties": ties,
            "first": first.isoformat(),
            "last": last.isoformat(),
            "bars": bars,
            "receipt_times": "UNKNOWN",
            "source_revisions": "UNKNOWN",
            "m1_qualified": False,
        }
        db.execute("INSERT INTO metadata VALUES(?)", (json.dumps(metadata),))
        db.execute("CREATE INDEX ticks_time ON ticks(at_ms,seq)")
        db.commit()
    except Exception as error:
        db.rollback()
        (output / "failed.json").write_text(
            json.dumps(
                {"status": "FAILED", "error_type": type(error).__name__, "reason": str(error)[:500]}
            ),
            encoding="utf-8",
        )
        raise
    finally:
        db.close()
    receipt = {
        "schema": "historical-tick-index-receipt/1",
        "archive_sha256": metadata["archive_sha256"],
        "index_sha256": file_hash(output / "ticks.sqlite"),
        "rows": count,
        "symbol": symbol,
    }
    (output / "receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return receipt


class TickIndex:
    def __init__(self, path):
        self.path = Path(path)
        self.db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
        self.db.execute("PRAGMA cache_size=-8192")
        try:
            self.metadata = json.loads(self.db.execute("SELECT value FROM metadata").fetchone()[0])
            if (
                self.metadata["schema"] != "historical-tick-index/1"
                or self.metadata["status"] != "COMPLETE"
            ):
                raise ValueError("incomplete tick index")
        except Exception:
            self.close()
            raise

    def close(self):
        self.db.close()

    def bars(self, latency_ms):
        return tuple(
            Bar.model_validate(b).model_copy(
                update={
                    "available_at": datetime.fromisoformat(b["close_at"])
                    + timedelta(milliseconds=latency_ms)
                }
            )
            for b in self.metadata["bars"]
        )

    def events(self, start, end, latency_ms, assume_inputs):
        symbol = self.metadata["symbol"]
        pip = Decimal("0.0001" if symbol == "EURUSD" else "0.01")
        spec = Instrument(
            symbol=symbol,
            base=symbol[:3],
            quote=symbol[3:],
            minimum_stop=pip / 2,
            maximum_spread=pip * 3,
            maximum_adverse_move=pip * 5,
        )
        cursor = self.db.execute(
            "SELECT seq,at_ms,bid,ask FROM ticks WHERE at_ms>=? AND at_ms<? ORDER BY at_ms,seq",
            (milliseconds(start) - latency_ms, milliseconds(end) - latency_ms),
        )
        previous = None
        while batch := cursor.fetchmany(512):
            for seq, at_ms, bid, ask in batch:
                if previous is not None and (at_ms, seq) <= previous:
                    raise ValueError("indexed event ordering invalid")
                previous = at_ms, seq
                at = EPOCH + at_ms * MILLISECOND
                bid, ask = Decimal(bid), Decimal(ask)
                with localcontext() as context:
                    context.prec = 28  # Same conversion convention as the original importer.
                    conversion = {
                        "USD": Decimal(1),
                        "EUR" if symbol == "EURUSD" else "JPY": bid
                        if symbol == "EURUSD"
                        else Decimal(1) / ask,
                    }
                yield Event(
                    available_at=at + timedelta(milliseconds=latency_ms),
                    source_sequence=seq,
                    market=Market(
                        at=at,
                        quotes=(Quote(symbol=symbol, bid=bid, ask=ask, at=at),),
                        instruments=(spec,),
                        conversion=conversion,
                        calendar_ok=assume_inputs,
                        news_ok=assume_inputs,
                    ),
                )
