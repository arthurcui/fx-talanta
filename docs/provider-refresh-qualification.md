# Bounded provider refresh qualification

Historical short probes. See [current qualification](provider-acceptance.md) for
the expanded release feeds, frozen coverage inventory and prospective campaign.

On November 2, 2026, three Windows collection passes separated by at least one
minute each retrieved fresh FRED API dates and public-calendar times. All three
matched five events in the manual BLS reference across the four supported release
types. The immutable attempt chain verified correctly. This is a short transport
and reconciliation exercise, **not sustained availability, release-delivery
latency, complete currency coverage, or permission to trade**.

The [sanitized evidence](evidence/provider-refresh-20261102.json) retains actual
collection timestamps, hashes, normalized events, feed metadata and failures.
No API key, account identity or article text is included. Every attempt remains
execution-disabled and blocks entries regardless of comparison success.

## Repeatable collection and recovery

`python -m fx_talanta.calendar_qualification` performs one bounded attempt. Supply
`--env-file` pointing to the private FRED key file, `--bls-reference` pointing to
the manually downloaded ICS, `--start 2026-11-02 --end 2026-12-02`, and a fresh
`--output` JSON path. Subsequent calls take `--previous` with the previous output.
The output is created exclusively before network activity. Exit zero means the
FRED/BLS static comparison passed; inspect `bls_refresh.error` independently.

Each attempt contains the current FRED snapshot, current HTML comparison, direct
BLS refresh outcome, previous-attempt hash and last successful comparison baseline.
The baseline is retained solely to detect schedule changes after an outage; it is
never reused as current data. A failed attempt remains failed and visible in the
chain. Recovery against the same schedule can pass the narrow comparison; a
changed schedule requires review even if an intervening fetch failed. The manual
reference never acquires automatic-refresh provenance from being re-imported.

Synthetic tests exercise success → outage → recovery, rescheduling after an outage,
stale API replay, immutable history, and prevention of requests when output already
exists. These are failure simulations, not observed provider outages. The full
native regression/integration suite passed **297 tests** against the separate
fixture database. No broker source, process, terminal, environment or database was
modified. PRs #10 and #11 remain unmerged.

## Actual transport findings

| Source / path | Observed result | What remains unqualified |
| --- | --- | --- |
| FRED dates plus HTML times, Windows | Three passes; five matching events each | Actual revisions, sustained refresh, release latency, complete inventory |
| BLS current refresh function, Windows | HTTP 403 in every pass | Unattended direct refresh |
| BLS current refresh function, disposable Linux container | HTTP 403 | The existing adapter still cannot be promoted |
| BLS metadata probe, disposable Linux container | HTTP 200 twice; same 80,672-byte reference hash | Request/environment dependence and sustained cache freshness |
| BLS exact successful probe headers plus strict ICS parsing, Linux | HTTP 200; 92 supported events, verified timezone format | A single strict parse does not establish reliable refresh |
| Same BLS metadata probe, Windows | HTTP 403 | Cross-platform behavior |
| Fed monetary-policy RSS, Windows | One 200 followed by two conditional 304 responses | Completeness and actual release delivery |
| ECB RSS, Windows explicit native trust | Three valid 200 responses | Sustained delivery |
| Fed, ECB and BOJ RSS, Linux default verified TLS | Valid 200 responses; counts 15, 15 and 47 | Sustained delivery and broader news coverage |
| BOJ RSS, Windows | Three valid 200 responses | Intended retention/use scope and wider coverage |

The successful BLS probe uses the same honest User-Agent as the current adapter,
but additionally sends `Accept: application/rss+xml, application/xml, text/calendar`.
The Linux strict-parse check reproduced those exact headers. This is evidence of
request/environment-dependent behavior, not proof of which server, cache or edge
rule caused it. Windows still failed with that header. No cookies were exported,
browser identity imitated, TLS verification disabled, or global configuration
changed. The production refresh function remains unchanged; do not report its
403 as fixed merely because a different probe succeeded.

The successful strict response had a current HTTP Date, no Age or Cache-Control
header, and Last-Modified June 10, 2026. Its body matched the manual reference.
Those facts do not prove a stale file, but neither a current Date nor an unchanged
body establishes that the publisher's future schedule is complete and current.
The earlier browser repeat successes also remain a separate, profile-dependent
observation; browser restart and scheduled unattended operation were not tested.

## Next qualification gates

Keep the sources optional. Before adopting a required calendar feed, establish a
supported reproducible refresh path, cache/revalidation semantics, actual revision
handling and coverage against releases as they occur. Before adopting a required
news feed, finish the event/source inventory and retention scope, then measure
publication-to-receipt latency across relevant releases. Central-bank RSS and four
US statistical release types do not cover USD/EUR/JPY calendars and general forex
news. No trading filter or broker run was connected to these probes.
