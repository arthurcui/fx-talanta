"""Bounded official-calendar/feed probe; metadata only, never certifies coverage."""

import argparse
import json
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from fx_talanta.fred_calendar import NoRedirect

URLS = {
    "bea": "https://apps.bea.gov/API/signup/release_dates.json",
    "boj_calendar": "https://www.boj.or.jp/en/about/calendar/index.htm",
    "ecb_calendar": "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html",
    "eurostat_calendar": (
        "https://ec.europa.eu/eurostat/news/euro-indicators/release-calendar?type=listMonth"
    ),
    "japan_cpi": "https://www.stat.go.jp/english/data/cpi/1582.html",
    "japan_gdp": "https://www.esri.cao.go.jp/en/sna/kouhyou/kouhyou_top.html",
    "japan_labour": "https://www.stat.go.jp/english/data/roudou/1543.htm",
    "bls_releases": "https://www.bls.gov/feed/bls_latest.rss",
    "eurostat_releases": (
        "https://ec.europa.eu/eurostat/en/search?"
        "_estatsearchportlet_WAR_estatsearchportlet_collection=CAT_PREREL&"
        "p_p_id=estatsearchportlet_WAR_estatsearchportlet&p_p_lifecycle=2&"
        "p_p_mode=view&p_p_resource_id=atom&p_p_state=maximized"
    ),
}
LIMIT = 2 * 1024 * 1024


def bea_summary(raw, now):
    data = json.loads(raw)
    if not isinstance(data, dict) or not 1 <= len(data) <= 100:
        raise ValueError("BEA schema")
    result, total, duplicates = [], 0, 0
    for family, values in data.items():
        if family == "file_last_updated":
            if not isinstance(values, str):
                raise ValueError("BEA update metadata")
            continue
        dates = values["release_dates"]
        if not isinstance(dates, list) or len(dates) > 500:
            raise ValueError("BEA dates")
        parsed = []
        for value in dates:
            at = datetime.fromisoformat(value)
            if at.tzinfo is None or at.utcoffset() is None:
                raise ValueError("unqualified date-only or floating BEA time")
            parsed.append(at.astimezone(UTC))
        total += len(parsed)
        duplicates += len(parsed) - len(set(parsed))
        if family in {"GDP", "Gross Domestic Product", "Personal Income and Outlays"}:
            result.extend(
                {"family": family, "scheduled_utc": at.isoformat()}
                for at in sorted(set(parsed))
                if now <= at < now + timedelta(days=35)
            )
    return {
        "families": len(data) - int("file_last_updated" in data),
        "timestamp_rows": total,
        "duplicate_dates": duplicates,
        "upcoming_gdp_pce": result,
        "limitation": "Timestamp parsing only; independent reconciliation and revisions pending",
    }


def probe(source):
    import truststore

    row = {
        "source": source,
        "url": URLS[source],
        "started_at": datetime.now(UTC).isoformat(),
        "qualified_for_trading": False,
    }
    try:
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        request = urllib.request.Request(
            URLS[source],
            headers={
                "User-Agent": "FX-Talanta-Qualification/1",
                "Accept": "application/json, application/atom+xml, application/rss+xml, text/html",
            },
        )
        with urllib.request.build_opener(
            NoRedirect(), urllib.request.HTTPSHandler(context=context)
        ).open(request, timeout=15) as response:
            raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise ValueError("body bound")
            row.update(
                http_status=response.status,
                bytes=len(raw),
                body_sha256=sha256(raw).hexdigest(),
                content_type=response.headers.get("Content-Type"),
            )
        now = datetime.now(UTC)
        if source == "bea":
            row["parsed"] = bea_summary(raw, now)
        elif source.endswith("releases"):
            text = raw.decode("utf-8-sig")
            if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
                raise ValueError("entity declaration")
            root = ET.fromstring(raw)
            if root.tag.split("}")[-1] not in {"rss", "RDF", "feed"}:
                raise ValueError("feed root")
            items = [e for e in root.iter() if e.tag.split("}")[-1] in {"item", "entry"}]
            row["parsed"] = {
                "format": root.tag.split("}")[-1],
                "items": len(items),
                "item_field_names": sorted({e.tag.split("}")[-1] for i in items for e in i}),
            }
        else:
            row["parsed"] = {"event_normalization": "NOT_IMPLEMENTED", "coverage_verified": False}
        row.update(status="OK", received_at=now.isoformat())
    except urllib.error.HTTPError as exc:
        row.update(status="FAILED", http_status=exc.code, error="HTTP_ERROR")
    except Exception as exc:
        row.update(status="FAILED", error=type(exc).__name__)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", choices=URLS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.child:
        print(json.dumps(probe(args.child)))
        return
    if not args.output:
        parser.error("--output required")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve before fetching; interrupted attempts remain separate evidence.
    with args.output.open("x") as stream:
        stream.write(json.dumps({"status": "STARTED", "at": datetime.now(UTC).isoformat()}))
    results = []
    for source in URLS:
        try:
            process = subprocess.run(
                [sys.executable, __file__, "--child", source],
                capture_output=True,
                text=True,
                timeout=25,
            )
            row = (
                json.loads(process.stdout)
                if process.returncode == 0
                else {"source": source, "status": "FAILED", "error": "WORKER_FAILED"}
            )
        except Exception:
            row = {"source": source, "status": "FAILED", "error": "DEADLINE_OR_WORKER_FAILURE"}
        results.append(row)
        args.output.write_text(
            json.dumps(
                {
                    "checked_at": datetime.now(UTC).isoformat(),
                    "sources": results,
                    "qualified_for_trading": False,
                },
                indent=2,
            )
        )
        print(
            json.dumps(
                {k: row[k] for k in ("source", "status", "http_status", "parsed") if k in row}
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
