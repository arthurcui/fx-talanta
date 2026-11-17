"""Fixed-origin HistData acquisition and immutable, streamed index preparation."""

import http.cookiejar
import json
import re
import sqlite3
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fx_talanta.research.historical import MAX_ARCHIVE
from fx_talanta.research.replay import digest
from fx_talanta.research.spool import file_hash
from fx_talanta.research.tick_index import TickIndex, build_index, milliseconds

ORIGIN = "https://www.histdata.com"


class FixedOrigin(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme != "https" or parsed.netloc != "www.histdata.com":
            raise ValueError("historical download redirected outside trusted origin")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(symbol, month, destination):
    if symbol not in {"EURUSD", "USDJPY"} or not re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])", month):
        raise ValueError("unsupported historical request")
    destination = Path(destination)
    receipt = destination.with_suffix(".json")
    if destination.exists():
        saved = json.loads(receipt.read_text(encoding="utf8"))
        if (saved["symbol"], saved["month"]) != (symbol, month) or saved["sha256"] != file_hash(
            destination
        ):
            raise ValueError("cached history changed")
        return saved
    url = (
        f"{ORIGIN}/download-free-forex-historical-data/?/ascii/tick-data-quotes/"
        f"{symbol.lower()}/{month[:4]}/{int(month[4:])}"
    )
    opener = urllib.request.build_opener(
        FixedOrigin(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    with opener.open(url, timeout=30) as response:
        raw = response.read(200001)
    if len(raw) > 200000:
        raise ValueError("download page too large")
    form = re.search(r'<form id="file_down".*?</form>', raw.decode("utf8"), re.S)
    if not form:
        raise ValueError("historical month unavailable")
    fields = dict(re.findall(r'name="([^"]+)"[^>]*value="([^"]*)"', form[0]))
    expected = dict(date=month[:4], datemonth=month, platform="ASCII", timeframe="T", fxpair=symbol)
    if any(fields.get(k) != v for k, v in expected.items()) or not fields.get("tk"):
        raise ValueError("download form identity mismatch")
    request = urllib.request.Request(
        ORIGIN + "/get.php",
        data=urllib.parse.urlencode(dict(expected, tk=fields["tk"])).encode(),
        headers={"Referer": url},
    )
    partial = destination.with_suffix(".partial")
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with opener.open(request, timeout=30) as response, partial.open("wb") as target:
        while chunk := response.read(65536):
            count += len(chunk)
            if count > MAX_ARCHIVE:
                raise ValueError("archive exceeds byte bound")
            target.write(chunk)
    with partial.open("rb") as stream:
        if stream.read(4) != b"PK\x03\x04":
            raise ValueError("download is not a ZIP archive")
    saved = dict(
        provider="HistData",
        symbol=symbol,
        month=month,
        bytes=count,
        sha256=file_hash(partial),
        source_url=url,
    )
    receipt.write_text(json.dumps(saved), encoding="utf8")
    partial.replace(destination)
    return saved


def months(start, end):
    at = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    result = []
    while at < end:
        result.append(at.strftime("%Y%m"))
        at = (at.replace(day=28) + timedelta(days=4)).replace(day=1)
    if len(result) > 14:
        raise ValueError("research acquisition exceeds fourteen-month bound")
    return result


def prepare(root, symbol, start, end, warmup_hours, progress, fetch=download):
    """Fetch exact months, validate source rows, and assemble an unqualified index."""
    root = Path(root)
    warm_start = start - timedelta(days=max(14, (warmup_hours // 24 + 1) * 2))
    identity = digest(
        dict(
            symbol=symbol,
            start=start.isoformat(),
            end=end.isoformat(),
            warm_start=warm_start.isoformat(),
            version=1,
        )
    )
    target = root / identity
    receipt = target / "prepared.json"
    if receipt.exists():
        saved = json.loads(receipt.read_text(encoding="utf8"))
        if file_hash(target / "ticks.sqlite") != saved["index_sha256"]:
            raise ValueError("prepared historical index changed")
        return target, saved
    if target.exists():
        raise ValueError("interrupted preparation retained; no blind overwrite")
    sources = []
    for month in months(warm_start, end):
        progress(dict(symbol=symbol, phase="acquisition", status="DOWNLOADING", month=month))
        suffix = "-" + end.strftime("%Y%m%d") if month == datetime.now(UTC).strftime("%Y%m") else ""
        archive = root / "cache" / f"{symbol}-{month}{suffix}.zip"
        source = fetch(symbol, month, archive)
        index_dir = root / "indexes" / (source["sha256"] + "-normalized")
        if not index_dir.exists():
            index_dir.parent.mkdir(parents=True, exist_ok=True)
            build_index(archive, symbol, index_dir, normalize_timestamps=True)
        check = json.loads((index_dir / "receipt.json").read_text(encoding="utf8"))
        if file_hash(index_dir / "ticks.sqlite") != check["index_sha256"]:
            raise ValueError("source index changed")
        sources.append((index_dir, source))
    progress(dict(symbol=symbol, phase="acquisition", status="PREPARING"))
    target.mkdir(parents=True)
    db = sqlite3.connect(target / "ticks.sqlite")
    count, first, last, bars, previous = 0, None, None, {}, None
    active_days, large_gaps = set(), 0
    try:
        db.execute("CREATE TABLE ticks(seq INTEGER PRIMARY KEY,at_ms INTEGER,bid TEXT,ask TEXT)")
        db.execute("CREATE TABLE metadata(value TEXT)")
        for path, _ in sources:
            index = TickIndex(path / "ticks.sqlite")
            try:
                for bar in index.metadata["bars"]:
                    if warm_start <= datetime.fromisoformat(bar["close_at"]) <= end:
                        key = bar["timeframe"], bar["close_at"]
                        if key in bars and bars[key] != bar:
                            raise ValueError("conflicting source bars")
                        bars[key] = bar
                cursor = index.db.execute(
                    "SELECT at_ms,bid,ask FROM ticks WHERE at_ms>=? AND at_ms<? ORDER BY at_ms,seq",
                    (milliseconds(warm_start), milliseconds(end)),
                )
                while batch := cursor.fetchmany(5000):
                    rows = []
                    for at, bid, ask in batch:
                        if previous is not None and at < previous:
                            raise ValueError("source month overlap or reversed time")
                        if at >= milliseconds(start):
                            active_days.add(at // 86400000)
                            large_gaps += previous is not None and at - previous > 3600000
                        previous = at
                        first = at if first is None else first
                        last = at
                        rows.append((count, at, bid, ask))
                        count += 1
                        if count > 50_000_000:
                            raise ValueError("prepared tick bound exceeded")
                    db.executemany("INSERT INTO ticks VALUES(?,?,?,?)", rows)
            finally:
                index.close()
        if not count:
            raise ValueError("no historical ticks in requested window")
        metadata = dict(
            schema="historical-tick-index/1",
            status="COMPLETE",
            symbol=symbol,
            archive_sha256=digest([s for _, s in sources]),
            rows=count,
            bars=list(bars.values()),
            receipt_times="UNKNOWN",
            m1_qualified=False,
        )
        db.execute("INSERT INTO metadata VALUES(?)", (json.dumps(metadata),))
        db.execute("CREATE INDEX ticks_time ON ticks(at_ms,seq)")
        db.commit()
    finally:
        db.close()
    saved = dict(
        symbol=symbol,
        index_sha256=file_hash(target / "ticks.sqlite"),
        rows=count,
        sources=[s for _, s in sources],
        start=start.isoformat(),
        end=end.isoformat(),
        observed_days=len(active_days),
        gaps_over_one_hour=large_gaps,
        end_lag_seconds=max(0, (milliseconds(end) - last) / 1000),
        timestamp_order="STABLE_SORT_WITH_SOURCE_ORDER_RETAINED",
        missing_weekdays=[
            (start + timedelta(days=i)).date().isoformat()
            for i in range((end.date() - start.date()).days)
            if (start + timedelta(days=i)).weekday() < 5
            and milliseconds(
                start.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=i)
            )
            // 86400000
            not in active_days
        ],
        first_ms=first,
        last_ms=last,
        qualification="UNQUALIFIED_RESEARCH_ONLY",
        calendar_news="NOT_ACQUIRED",
        broker_costs="UNCALIBRATED",
    )
    receipt.write_text(json.dumps(saved, indent=2), encoding="utf8")
    return target, saved
