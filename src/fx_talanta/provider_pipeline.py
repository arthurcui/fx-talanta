"""Durable metadata-only provider collection and point-in-time shadow filtering."""

import argparse
import json
import multiprocessing
import os
import sqlite3
import ssl
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values

from fx_talanta import bls_calendar as bls
from fx_talanta import fred_calendar as fred
from fx_talanta.domain.models import NewsRevision, utc
from fx_talanta.news_filter import (
    CalendarRevision,
    FeedCheck,
    FilterInputs,
    FilterPolicy,
    NewsEvidence,
    SourceRule,
    assess,
)

SOURCES = {
    "fed": ("https://www.federalreserve.gov/feeds/press_monetary.xml", "USD"),
    "ecb": ("https://www.ecb.europa.eu/rss/press.html", "EUR"),
    "boj": ("https://www.boj.or.jp/en/rss/whatsnew.xml", "JPY"),
    "bls": (bls.URL, "USD"),
}
LIMIT = 2 * 1024 * 1024


@contextmanager
def status_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def policy():
    return FilterPolicy(
        version="provider-shadow/2",
        sources=(
            SourceRule(source="calendar_inventory", role="CALENDAR", required=True),
            SourceRule(source="news_inventory", role="NEWS", required=True),
            *(
                SourceRule(
                    source=s,
                    role="CALENDAR" if s == "bls" else "NEWS",
                    required=False,
                    currencies=(currency,),
                )
                for s, (_, currency) in SOURCES.items()
            ),
            SourceRule(source="fred", role="CALENDAR", required=False, currencies=("USD",)),
            SourceRule(source="mt5_calendar", role="CALENDAR", required=False),
        ),
    )


def parse_news(source, raw, observed):
    if len(raw) > LIMIT:
        raise ValueError("body bound")
    text = raw.decode("utf-8-sig")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("entity declaration")
    root = ET.fromstring(text)
    if root.tag.split("}")[-1] not in {"rss", "RDF", "feed"}:
        raise ValueError("feed root")
    rows, identities = [], set()
    for item in root.iter():
        if item.tag.split("}")[-1] not in {"item", "entry"}:
            continue
        fields = {e.tag.split("}")[-1]: e.text for e in item}
        url = fields.get("link") or next(
            (e.attrib.get("href") for e in item if e.tag.split("}")[-1] == "link"), None
        )
        parsed = urllib.parse.urlsplit(url or "")
        host = urllib.parse.urlsplit(SOURCES[source][0]).hostname
        original_url = url
        # BOJ publishes HTTP attribution links inside its HTTPS feed. Retain
        # the original metadata, but expose a canonical HTTPS link; never fetch it.
        if source == "boj" and parsed.scheme == "http" and parsed.hostname == host:
            parsed = parsed._replace(scheme="https")
            url = urllib.parse.urlunsplit(parsed)
        if (
            parsed.scheme != "https"
            or parsed.hostname != host
            or parsed.username
            or parsed.password
            or parsed.port
        ):
            raise ValueError("unapproved attribution URL")
        identity = digest(fields.get("guid") or fields.get("id") or url)
        stamp = fields.get("pubDate") or fields.get("published") or fields.get("date")
        published = utc(
            parsedate_to_datetime(stamp) if fields.get("pubDate") else datetime.fromisoformat(stamp)
        )
        if published > observed or identity in identities:
            raise ValueError("future timestamp or duplicate identity")
        identities.add(identity)
        rows.append(
            dict(
                item_id=identity,
                url=url,
                original_url=original_url,
                published_at=published.isoformat(),
                content_hash=sha256(ET.tostring(item)).hexdigest(),
            )
        )
        if len(rows) > 1000:
            raise ValueError("item bound")
    return rows


def _worker(sender, source, tls, fred_key, start, end):
    try:
        if source == "fred":
            snapshot = fred.collect(fred_key, start, end)
            result = {"status": snapshot.status, "payload": snapshot.model_dump(mode="json")}
        else:
            context = ssl.create_default_context()
            if tls == "native":
                import truststore

                context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
                raise ValueError("TLS verification required")
            request = urllib.request.Request(
                SOURCES[source][0],
                headers={
                    "User-Agent": "FX-Talanta-Shadow/1",
                    "Accept": "application/rss+xml, application/xml, text/calendar",
                },
            )
            opener = urllib.request.build_opener(
                fred.NoRedirect(), urllib.request.HTTPSHandler(context=context)
            )
            with opener.open(request, timeout=15) as response:
                if response.status != 200:
                    raise ValueError("unexpected status")
                raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise ValueError("body bound")
            observed = datetime.now(UTC)
            payload = (
                bls.import_calendar(raw, fetched_at=observed).model_dump(mode="json")
                if source == "bls"
                else parse_news(source, raw, observed)
            )
            result = {"status": "OK", "payload": payload, "response_hash": sha256(raw).hexdigest()}
    except urllib.error.HTTPError as exc:
        result = {
            "status": "THROTTLED" if exc.code == 429 else "FAILED",
            "error": f"HTTP_{exc.code}",
        }
    except Exception:
        result = {"status": "FAILED", "error": "TRANSPORT_OR_SCHEMA_FAILURE"}
    try:
        sender.send_bytes(json.dumps(result).encode())
    finally:
        sender.close()


def fetch(source, *, tls="default", fred_key="", start=None, end=None, timeout=45):
    if source not in {*SOURCES, "fred"} or tls not in {"default", "native"}:
        raise ValueError("unapproved source or TLS backend")
    ctx = multiprocessing.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    process = ctx.Process(
        target=_worker, args=(sender, source, tls, fred_key, start, end), daemon=True
    )
    try:
        process.start()
        sender.close()
        if not receiver.poll(timeout):
            return {"status": "FAILED", "error": "DEADLINE_EXCEEDED"}
        return json.loads(receiver.recv_bytes(2 * LIMIT))
    except (EOFError, OSError, ValueError):
        return {"status": "FAILED", "error": "WORKER_FAILED"}
    finally:
        receiver.close()
        sender.close()
        if process.pid:
            process.join(0.1)
            if process.is_alive():
                process.terminate()
                process.join(1)
            if process.is_alive():
                process.kill()
                process.join(1)
            if process.is_alive():
                raise RuntimeError("collector worker did not stop")
            process.close()


class Journal:
    def __init__(self, path, *, create=False):
        self.path = Path(path).resolve()
        self.conn = sqlite3.connect(
            self.path.as_uri() + ("?mode=rwc" if create else "?mode=rw"), uri=True, timeout=5
        )
        self.conn.execute("PRAGMA foreign_keys=ON")
        if create:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS metadata(id TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts(
                    id TEXT PRIMARY KEY, source TEXT NOT NULL, started TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS outcomes(
                    attempt TEXT PRIMARY KEY REFERENCES attempts(id), available TEXT NOT NULL,
                    status TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions(
                    source TEXT NOT NULL, identity TEXT NOT NULL, revision INTEGER NOT NULL,
                    available TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(source, identity, revision));
                CREATE TABLE IF NOT EXISTS assessments(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            """)
            with self.conn:
                self.conn.execute(
                    "INSERT OR IGNORE INTO metadata VALUES ('journal_id', ?)", (str(uuid4()),)
                )
            for table in ("metadata", "attempts", "outcomes", "revisions", "assessments"):
                for action in ("UPDATE", "DELETE"):
                    self.conn.execute(
                        f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action} "
                        f"BEFORE {action} ON {table} "
                        "BEGIN SELECT RAISE(ABORT, 'immutable evidence'); END"
                    )
            self.conn.commit()
        self.identity = self.conn.execute(
            "SELECT value FROM metadata WHERE id='journal_id'"
        ).fetchone()[0]

    def close(self):
        self.conn.close()

    def begin(self, source, now):
        if source not in {*SOURCES, "fred", "mt5_calendar"}:
            raise ValueError("unapproved source")
        latest = self.conn.execute(
            "SELECT max(stamp) FROM (SELECT started AS stamp FROM attempts "
            "UNION ALL SELECT available AS stamp FROM outcomes)"
        ).fetchone()[0]
        if latest and utc(now) < datetime.fromisoformat(latest):
            raise ValueError("collection clock rollback")
        identity = str(uuid4())
        with self.conn:
            self.conn.execute(
                "INSERT INTO attempts VALUES (?, ?, ?)", (identity, source, utc(now).isoformat())
            )
        return identity

    def finish(self, attempt, result, now):
        now = utc(now)
        source, started = self.conn.execute(
            "SELECT source, started FROM attempts WHERE id=?", (attempt,)
        ).fetchone()
        if now < datetime.fromisoformat(started):
            raise ValueError("clock rollback")
        with self.conn:
            if result["status"] == "OK":
                candidates = []
                if source == "mt5_calendar":
                    normalized = result["payload"]
                    if (
                        normalized["provenance"] != "MT5_CALENDAR_EXPORT"
                        or normalized["available_at"] != now.isoformat()
                    ):
                        raise ValueError("invalid bridge availability or provenance")
                    prior = self.conn.execute(
                        "SELECT o.payload FROM attempts a JOIN outcomes o ON a.id=o.attempt "
                        "WHERE a.source='mt5_calendar' AND o.status='OK' "
                        "ORDER BY a.rowid DESC LIMIT 1"
                    ).fetchone()
                    if prior:
                        previous_snapshot = json.loads(prior[0])["payload"]
                        if any(
                            normalized[k] != previous_snapshot[k]
                            for k in ("bridge_id", "clock_policy_hash")
                        ):
                            raise ValueError("new bridge/clock policy requires a separate journal")
                        if normalized["exported_at"] < previous_snapshot["exported_at"]:
                            raise ValueError("export timeline regressed")
                        if (
                            normalized["exported_at"] == previous_snapshot["exported_at"]
                            and normalized["source_hash"] != previous_snapshot["source_hash"]
                        ):
                            raise ValueError("conflicting export at same producer time")
                    candidates = [(v["value_id"], v) for v in normalized["events"]]
                elif source == "bls":
                    snapshot = bls.BlsSnapshot.model_validate(result["payload"])
                    if snapshot.imported_at > now:
                        raise ValueError("future import")
                    for event in snapshot.events:
                        candidates.append(
                            (
                                digest(event.uid),
                                {
                                    "scheduled_at": event.scheduled_at.isoformat(),
                                    "status": "CANCELLED"
                                    if event.status == "CANCELLED"
                                    else "SCHEDULED",
                                    "sequence": event.sequence,
                                    "impact": "HIGH" if event.status == "CONFIRMED" else "UNKNOWN",
                                },
                            )
                        )
                elif source in {"fed", "ecb", "boj"}:
                    candidates = [(item["item_id"], item) for item in result["payload"]]
                for identity, candidate in candidates:
                    previous = self.conn.execute(
                        "SELECT revision, payload FROM revisions WHERE source=? AND identity=? "
                        "ORDER BY revision DESC LIMIT 1",
                        (source, identity),
                    ).fetchone()
                    old = json.loads(previous[1]) if previous else None
                    if (
                        old
                        and source == "mt5_calendar"
                        and (
                            candidate["source_revision"] < old["value"]["source_revision"]
                            or any(
                                candidate[k] != old["value"][k] for k in ("event_id", "currency")
                            )
                        )
                    ):
                        raise ValueError("calendar value identity or revision regressed")
                    if (
                        old
                        and source == "bls"
                        and (
                            candidate["sequence"] < old["value"]["sequence"]
                            or (
                                candidate["sequence"] == old["value"]["sequence"]
                                and candidate != old["value"]
                            )
                        )
                    ):
                        raise ValueError("calendar revision regressed or conflicts")
                    if (
                        old
                        and source not in {"bls", "mt5_calendar"}
                        and candidate["published_at"] != old["value"]["published_at"]
                    ):
                        raise ValueError("publication time changed")
                    if old and candidate == old["value"]:
                        continue
                    payload = {
                        "value": candidate,
                        "first_observed_at": old["first_observed_at"] if old else now.isoformat(),
                    }
                    self.conn.execute(
                        "INSERT INTO revisions VALUES (?, ?, ?, ?, ?)",
                        (
                            source,
                            identity,
                            previous[0] + 1 if previous else 1,
                            now.isoformat(),
                            json.dumps(payload),
                        ),
                    )
            self.conn.execute(
                "INSERT INTO outcomes VALUES (?, ?, ?, ?)",
                (attempt, now.isoformat(), result["status"], json.dumps(result)),
            )

    def inputs(self, cutoff):
        cutoff = utc(cutoff)
        checks, calendar, news = {}, [], []
        for source, started, available, state, outcome in self.conn.execute(
            "SELECT a.source, a.started, o.available, o.status, o.payload FROM attempts a "
            "LEFT JOIN outcomes o ON a.id=o.attempt ORDER BY a.rowid DESC"
        ):
            started = datetime.fromisoformat(started)
            available = datetime.fromisoformat(available) if available else started
            if started > cutoff or source in checks:
                continue
            if available > cutoff:
                available, state = started, None
            checked_at = started
            coverage_from, coverage_until = started - timedelta(days=1), started + timedelta(days=1)
            if source == "mt5_calendar" and state == "OK":
                snapshot = json.loads(outcome)["payload"]
                checked_at = datetime.fromisoformat(snapshot["exported_at"])
                coverage_from = datetime.fromisoformat(snapshot["coverage_from"])
                coverage_until = datetime.fromisoformat(snapshot["coverage_until"])
                if not 0 <= (cutoff - checked_at).total_seconds() <= 120 or cutoff > coverage_until:
                    state = "FAILED"
            currencies = (
                ("USD", "EUR", "JPY")
                if source == "mt5_calendar"
                else ("USD" if source == "fred" else SOURCES[source][1],)
            )
            checks[source] = FeedCheck(
                source=source,
                checked_at=checked_at,
                available_at=available,
                connection="OK"
                if state == "OK"
                else "THROTTLED"
                if state == "THROTTLED"
                else "FAILED",
                complete=False,
                coverage_from=coverage_from,
                coverage_until=coverage_until,
                currencies=currencies,
                verification="Transport only; inventory and delivery coverage unqualified",
            )
        for source, identity, revision, available, payload in self.conn.execute(
            "SELECT source, identity, revision, available, payload FROM revisions ORDER BY rowid"
        ):
            available = datetime.fromisoformat(available)
            if available > cutoff:
                continue
            payload = json.loads(payload)
            value = payload["value"]
            if source in {"bls", "mt5_calendar"}:
                calendar.append(
                    CalendarRevision(
                        source=source,
                        event_id=identity,
                        revision=revision,
                        currency=value["currency"] if source == "mt5_calendar" else "USD",
                        impact=value["impact"],
                        scheduled_at=value["scheduled_at"],
                        available_at=available,
                        status=value["status"],
                    )
                )
            else:
                news.append(
                    NewsEvidence(
                        item=NewsRevision(
                            source=source,
                            item_id=identity,
                            revision=revision,
                            url=value["url"],
                            headline="Official source update (metadata only)",
                            content_excerpt="Content not retained",
                            content_hash=value["content_hash"],
                            story_cluster=identity,
                            currencies=(SOURCES[source][1],),
                            published_at=value["published_at"],
                            first_observed_at=payload["first_observed_at"],
                            ingested_at=available,
                            available_at=available,
                            retention="HASH_ONLY",
                        )
                    )
                )
        return FilterInputs(
            provenance="PROVIDER_SHADOW",
            checks=tuple(checks.values()),
            calendar=tuple(calendar),
            news=tuple(news),
        )

    def evaluate(self, symbol, cutoff):
        result = assess(policy(), self.inputs(cutoff), symbol, cutoff)
        with self.conn:
            self.conn.execute(
                "INSERT INTO assessments VALUES (?, ?)", (str(uuid4()), result.model_dump_json())
            )
        return result


class JournalGate:
    def __init__(self, path):
        self.path = Path(path).resolve()
        journal = Journal(self.path)
        try:
            self.journal_identity = journal.identity
            self.identity = digest(
                {"journal": journal.identity, "policy": policy().model_dump(mode="json")}
            )
        finally:
            journal.close()

    def restrict(self, market, symbol, cutoff):
        journal = Journal(self.path)
        try:
            if journal.identity != self.journal_identity:
                raise ValueError("journal identity changed")
            result = journal.evaluate(symbol, cutoff)
        finally:
            journal.close()
        return market.model_copy(
            update={
                "calendar_ok": market.calendar_ok and result.calendar_ok,
                "news_ok": market.news_ok and result.news_ok,
                "event_blackout": market.event_blackout or result.event_blackout,
            }
        )


def collect_once(
    journal, sources, *, tls="default", fred_key="", start=None, end=None, fetcher=fetch
):
    summary = {}
    for source in sources:
        attempt = journal.begin(source, datetime.now(UTC))
        try:
            result = fetcher(source, tls=tls, fred_key=fred_key, start=start, end=end)
            journal.finish(attempt, result, datetime.now(UTC))
        except Exception:
            result = {"status": "FAILED", "error": "COLLECTION_OR_REVISION_FAILURE"}
            journal.finish(attempt, result, datetime.now(UTC))
        summary[source] = result["status"]
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--sources", nargs="+", choices=(*SOURCES, "fred"), default=list(SOURCES))
    parser.add_argument("--tls", choices=("default", "native"), default="default")
    parser.add_argument("--fred-env", type=Path)
    parser.add_argument(
        "--bls-file", type=Path, help="import a manual calendar; never claims verified refresh"
    )
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--symbol", choices=("EURUSD", "USDJPY"), default="EURUSD")
    parser.add_argument("--cutoff", type=datetime.fromisoformat)
    args = parser.parse_args(argv)
    try:
        if (
            args.collect
            and "fred" in args.sources
            and not (args.fred_env and args.start and args.end)
        ):
            raise ValueError("FRED requires key file and bounded date window")
        with status_lock(args.journal.with_suffix(".collector")):
            journal = Journal(args.journal, create=args.collect or bool(args.bls_file))
            try:
                if args.bls_file:
                    attempt = journal.begin("bls", datetime.now(UTC))
                    try:
                        with args.bls_file.open("rb") as stream:
                            snapshot = bls.import_calendar(stream.read(LIMIT + 1))
                        journal.finish(
                            attempt,
                            {
                                "status": "OK",
                                "payload": snapshot.model_dump(mode="json"),
                                "provenance": "MANUAL_FILE",
                            },
                            datetime.now(UTC),
                        )
                    except Exception:
                        journal.finish(
                            attempt,
                            {"status": "FAILED", "error": "MANUAL_IMPORT_FAILED"},
                            datetime.now(UTC),
                        )
                if args.collect:
                    key = (
                        dotenv_values(args.fred_env).get("FRED_API_KEY", "")
                        if args.fred_env
                        else ""
                    )
                    print(
                        json.dumps(
                            {
                                "collection": collect_once(
                                    journal,
                                    list(dict.fromkeys(args.sources)),
                                    tls=args.tls,
                                    fred_key=key,
                                    start=args.start,
                                    end=args.end,
                                )
                            }
                        )
                    )
                result = journal.evaluate(args.symbol, args.cutoff or datetime.now(UTC))
                print(result.model_dump_json(indent=2))
            finally:
                journal.close()
        return 0
    except Exception:
        print(
            "Provider pipeline unavailable; entries remain blocked. No private diagnostics printed."
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
