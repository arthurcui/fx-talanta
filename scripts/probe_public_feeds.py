"""One-shot, bounded metadata probe; never connects to broker or decision inputs."""

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

URLS = {
    "fed": "https://www.federalreserve.gov/feeds/press_monetary.xml",
    "ecb": "https://www.ecb.europa.eu/rss/press.html",
    "boj": "https://www.boj.or.jp/en/rss/whatsnew.xml",
    "bls": "https://www.bls.gov/schedule/news_release/bls.ics",
}
LIMIT = 2 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def summarize_xml(body):
    text = body.decode("utf-8-sig")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("DTD/entity declaration rejected")
    root = ET.fromstring(text)
    if root.tag.split("}")[-1] not in {"rss", "RDF", "feed"}:
        raise ValueError("not a supported feed")
    items = [e for e in root.iter() if e.tag.split("}")[-1] in {"item", "entry"}]
    timestamps, ids, missing = [], [], 0
    for item in items:
        fields = {e.tag.split("}")[-1]: e.text for e in item}
        stamp = fields.get("pubDate") or fields.get("date") or fields.get("published")
        identity = fields.get("guid") or fields.get("id") or fields.get("link")
        if identity:
            ids.append(identity)
        if not stamp:
            missing += 1
            continue
        try:
            parsed = (
                parsedate_to_datetime(stamp)
                if fields.get("pubDate")
                else datetime.fromisoformat(stamp)
            )
            if parsed.tzinfo is None:
                raise ValueError("timezone missing")
            timestamps.append(parsed.astimezone(UTC))
        except (ValueError, TypeError):
            missing += 1
    return {
        "format": root.tag.split("}")[-1],
        "items": len(items),
        "items_with_ids": len(ids),
        "duplicate_ids": len(ids) - len(set(ids)),
        "timestamp_missing_or_invalid": missing,
        "earliest_publication": min(timestamps).isoformat() if timestamps else None,
        "latest_publication": max(timestamps).isoformat() if timestamps else None,
        "future_timestamp_count": sum(t > datetime.now(UTC) for t in timestamps),
    }


def probe(name, last_modified=None):
    url = URLS[name]
    start = time.monotonic()
    result = {
        "source": name,
        "url": url,
        "observed_at": datetime.now(UTC).isoformat(),
        "qualified_for_trading": False,
    }
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "FX-Talanta-Qualification/0.1",
            "Accept": "application/rss+xml, application/xml, text/calendar",
        },
    )
    if last_modified:
        request.add_header("If-Modified-Since", last_modified)
        result["conditional_request"] = True
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=15) as response:
            body = response.read(LIMIT + 1)
            if len(body) > LIMIT:
                raise ValueError("response exceeds bound")
            result.update(
                status=response.status,
                bytes=len(body),
                content_type=response.headers.get("Content-Type"),
                etag_present=bool(response.headers.get("ETag")),
                last_modified=response.headers.get("Last-Modified"),
                body_sha256=hashlib.sha256(body).hexdigest(),
            )
            if name == "bls":
                text = body.decode("utf-8-sig")
                if not text.startswith("BEGIN:VCALENDAR"):
                    raise ValueError("not an iCalendar response")
                result.update(
                    format="ical",
                    events=text.count("BEGIN:VEVENT"),
                    timezone_lines=sorted(
                        {line for line in text.splitlines() if line.startswith("TZID:")}
                    ),
                    start_field_types=sorted(
                        {
                            line.split(":", 1)[0]
                            for line in text.splitlines()
                            if line.startswith("DTSTART")
                        }
                    ),
                )
            else:
                result.update(summarize_xml(body))
            result["probe_state"] = "PARSED"
    except urllib.error.HTTPError as exc:
        result.update(
            status=exc.code, probe_state="NOT_MODIFIED" if exc.code == 304 else "HTTP_ERROR"
        )
    except urllib.error.URLError as exc:
        result.update(probe_state="TRANSPORT_ERROR", error_type=type(exc.reason).__name__)
    except (OSError, ValueError, ET.ParseError):
        result["probe_state"] = "TRANSPORT_OR_FORMAT_ERROR"
    result["request_seconds"] = round(time.monotonic() - start, 3)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sources", nargs="+", choices=tuple(URLS), default=list(URLS))
    parser.add_argument("--prior", type=Path, help="previous metadata for conditional requests")
    args = parser.parse_args()
    previous = {}
    if args.prior:
        previous = {
            r["source"]: r
            for r in (json.loads(line) for line in args.prior.read_text().splitlines())
        }
    # Exclusive creation prevents overwriting an earlier qualification attempt.
    with args.output.open("x", encoding="utf-8") as stream:
        for name in dict.fromkeys(args.sources):
            result = probe(name, previous.get(name, {}).get("last_modified"))
            stream.write(json.dumps(result) + "\n")
            stream.flush()
            print(json.dumps(result))


if __name__ == "__main__":
    main()
