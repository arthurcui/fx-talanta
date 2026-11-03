# Calendar/news collection and entry integration

The integration now connects bounded public collection, durable metadata storage,
point-in-time normalization, blackout assessment and the offline gateway's entry
checks. It runs independently of MT5 and does not change broker runs or databases.
PR #10 is merged. This completes the implemented **shadow integration**;
required live-provider qualification remains incomplete and entries stay blocked.

The [current qualification campaign](provider-acceptance.md) tracks the exact
coverage gaps and prospective delivery evidence separately from this integration.

## Sources and actual verification

The [integration evidence](evidence/calendar-news-integration-20261102.json)
records a bounded collection on November 2, 2026 UTC:

| Input | Result | Use |
| --- | --- | --- |
| Fed monetary-policy RSS | Parsed successfully | Attributable news metadata |
| ECB announcements RSS | Parsed with verified native TLS | Attributable news metadata |
| BOJ updates RSS | Parsed successfully | Attributable news metadata |
| Saved BLS ICS | 92 normalized calendar events | Explicitly manual schedule evidence |
| Direct BLS refresh | HTTP 403, retained as a failed attempt | Does not replace saved events or certify refresh |
| FRED API | Successful bounded date collection | Date-level corroboration; never converted into invented midnight events |

The three news feeds produced 77 items. Only IDs, original/canonical URLs,
publication/observation/availability timestamps and content hashes are retained;
article text and headlines are not archived. BOJ publishes HTTP attribution links
inside its HTTPS feed: the adapter retains the original link and exposes the same
official-host path with HTTPS. It never fetches article links. The first attempt's
BOJ parsing failure remains in its original local journal; the successful second
attempt uses a distinct journal rather than replacing that evidence.

These official announcement feeds do not establish comprehensive breaking-news
coverage. The BLS/FRED scope does not establish a complete USD/EUR/JPY event
inventory. A good response, empty feed or repeated content cannot certify coverage.
Provider inputs are labeled `PROVIDER_SHADOW`; the filter cannot turn them into
fixture evidence or authorize entries. The five-second quote ceiling and stricter
two-second entry rule are unchanged.

## Manual development calendar

Use the [BLS upload tool](manual-bls-upload.md) to select a saved `.ics` file,
preserve its bytes and revisions, and see an on-demand reminder after seven days
or when the schedule runs out. No background reminder or MT5 dependency is added.
The tool writes the same provider journal format used by the entry filter.

## Durable collection and replay

Each attempt is committed before retrieval. A separate immutable outcome records
success, failure, throttling or timeout; an interrupted attempt stays incomplete.
Each source runs in a separate child with a 45-second wall-clock watchdog, a
15-second socket timeout and a 2 MiB response limit. There are no automatic retries
or redirect following. TLS certificate and hostname verification remain enabled.
An optional explicit native trust context handles the observed Windows ECB chain.
FRED uses its existing bounded pagination adapter inside the child deadline.

The isolated SQLite journal stores attempts, outcomes, revisions and assessments.
Updates and deletes are rejected by triggers. The collector has a local exclusive
file lock. This is a single-host shadow journal, not a replacement for account
PostgreSQL, a multi-host service or a tamper-proof storage system. Back it up while
the collector is stopped. No subscription or recurring task is created.

Unchanged news is deduplicated. Revisions retain their original publication and
first-observed times. Calendar regressions and conflicting sequences fail closed;
an omitted event is not treated as a cancellation. Historical assessments include
only evidence available by their cutoff; subsequent corrections cannot rewrite
them. All calendar expectations remain retained rather than being dropped from a
rolling window. Input collections retain the filter's 10,000-item bound; overflow
fails closed and requires an explicit retention/archival design before unattended
long-term deployment.

From this checkout, with a Python environment containing the pinned dependencies:

```powershell
python -m fx_talanta.provider_pipeline --journal .local/calendar-news.sqlite --collect --sources fed ecb boj bls fred --fred-env C:/SideProjects/fx-talanta/.local/fred.env --start 2026-11-02 --end 2026-12-02 --bls-file C:/SideProjects/fx-talanta/.local/bls.ics --symbol EURUSD
python -m fx_talanta.provider_pipeline --journal .local/calendar-news.sqlite --symbol USDJPY
```

The date window above reproduces this dated check; select a new explicit window
for later collection. Use `--tls native` only in an isolated environment with
`requirements-provider-probe.txt` installed. The key stays in the private env file.
Repeat collection explicitly to append a new attempt; do not repeat `--bls-file`
unless intentionally importing that file again. For replay, omit `--collect` and
provide `--cutoff` with a timezone-aware timestamp. Exit zero means an assessment
was produced, not successful coverage or permission to trade.

## Automatic offline entry checks

Construct a new offline `Gateway` with
`news_gate=JournalGate(private_journal_path)` from `fx_talanta.provider_pipeline`.
The gateway persists the journal/policy identity with its mandate. Restarting that
run without the gate, with a replacement journal, or with a different policy is
rejected. Existing fixture-only runs remain unchanged; adding the gate requires
a new run ID. This hook does not create a connected broker execution path.

For an entry, the gateway assesses only the intent's normalized pair, first before
risk sizing and again immediately before submission. Restrictions can only become
tighter. Missing/corrupt storage blocks entries. Every successful assessment saves
the policy/input hashes, cutoff, exact revision references and blocking reasons.
Protective management and exits do not require healthy news inputs. Tests cover
outages between sizing/submission, restart bypass attempts and closing an existing
fixture position during an outage.

## Broker-independent calendar collection

Calendar/news collection must run in the Python application using direct HTTP
providers, independently of broker terminals. MT5 is reserved for broker
connectivity. The terminal calendar experiment was retired on November 3, 2026
at the user's request because its service, terminal session, file exchange and
scheduled importer added deployment dependencies and recovery failure modes.

The FOREX calendar service is stopped and its scheduled importer is disabled.
The MQL5 exporter/service, build/install/scheduling helpers and automatic file
collector have been removed. See the [retirement record](automatic-calendar.md).
Historical captures and their offline validators remain available for evidence
replay; they are not an active calendar provider or a deployment prerequisite.

The retained BLS ICS, FRED and official RSS adapters, immutable journal, UTC and
revision validation, and per-pair entry restrictions do not require MT5. Direct
BLS refresh previously returned HTTP 403; a saved ICS remains manual evidence.
FRED dates and official RSS announcements do not establish complete USD/EUR/JPY
calendar or breaking-news coverage. No replacement provider is certified by this
change, and neither expired nor historical captures can satisfy current coverage.

Remaining release blockers are direct-provider coverage/latency qualification,
reliable automatic HTTP refresh and the eventual connected execution adapter.
Free access is the first choice; paid access is considered only if necessary.
Missing, stale or unqualified required coverage continues to block entries.
Trading stays disabled. No broker qualification run was started or altered.
