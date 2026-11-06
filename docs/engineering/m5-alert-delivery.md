# Bounded alert delivery

## What is implemented

The dashboard's local notification spool can now feed an **explicitly configured
HTTPS receiver**. The optional delivery worker reserves a send durably before I/O,
retains delivery history and reconciles uncertain results through receipt lookups.
It never sends orders or enables trading. It is disabled by default and has not
been configured against a real destination as part of this engineering change.

Local-file delivery, receiver acceptance, and a person acknowledging an incident
are three distinct states. A successful HTTP response alone is insufficient: the
receiver must acknowledge the exact alert ID and payload digest. This implementation
is an engineering capability, not proof of operational delivery or human response.

## Explicit activation

Use an operator-controlled receiver that implements the contract below. There is
no built-in Slack, email, SMS or generic-webhook compatibility claim. Provision the
receiver and its credentials separately; do not put secrets into URLs, chat, Git or
dashboard inspection backups.

A private JSON configuration contains:

| Field | Meaning |
| --- | --- |
| `endpoint` | Exact HTTPS POST URL, no credentials/query/fragment/trailing slash |
| `token_file` | Private file containing a printable ASCII bearer token, 32..4096 characters |
| `ca_file` | Optional explicitly trusted CA PEM; otherwise normal system certificate validation |
| `expires_at` | Fixed timezone-aware delivery deadline |
| `max_messages` | Cumulative message slots, 1..1000, default 100; no reset on restart |

```powershell
python -m fx_talanta.dashboard.server --state .local/inspection-new --alert-config .local/alert-receiver.json --enable-alert-delivery
```

Both the configuration and `--enable-alert-delivery` are required. The CLI does not
discover destinations or credentials. Configuring only one option fails. This is
separate from owner login and never grants broker or simulator authority.

The receiver/policy fingerprint is bound to the inspection journal, including the
CA file's contents. Destination, token-file path, CA, deadline and message limit
cannot silently change on resume. Token content may be rotated at the same private
path with a controlled restart; it is never stored in the inspection database.
A restored inspection-only backup refuses outbound configuration. The token and CA
files are not included in the dashboard backup; no outbound authority is restored.

At first enablement the worker records the current incident high-water mark. It
will not send the retained historical backlog. New local incidents are eligible
only after their immutable local-file receipt was verified. Disabling delivery by
omitting both flags makes no external requests; later resuming the same policy
preserves its original watermark, consumed slots and uncertain sends.

## Wire contract

POST the following canonical UTF-8 JSON to `endpoint`:

```json
{
  "version": "fx-alert/1",
  "id": "a-stable-generated-UUID",
  "incident_id": 42,
  "observed_at": "2026-11-06T18:00:00+00:00",
  "message": "Inspection state changed; review your dashboard.",
  "source_sha256": "SHA-256-of-the-local-incident-payload",
  "execution_enabled": false
}
```

The fixed text intentionally omits raw incident evidence, free-form labels,
account identifiers, prices, broker positions, credentials and local paths.
`observed_at` is the local inspection timestamp, not the underlying market event's
publication time. `source_sha256` binds the original retained local payload.

Headers include `Authorization: Bearer ...`, `Idempotency-Key: <id>` and
`X-FX-Content-SHA256: <digest>`. The digest covers `json.dumps(payload,
sort_keys=True, separators=(",", ":"))` encoded as UTF-8. A receiver should deduplicate
by ID, reject changed content under the same ID, and durably retain receipts.

Only HTTP 200 with exactly the following JSON keys confirms an outcome:

```json
{"id":"the-same-UUID","digest":"the-exact-wire-digest","status":"ACCEPTED"}
```

`REJECTED` is also a terminal confirmed response. Other statuses, mismatched IDs or
digests, missing/extra keys, oversized replies, malformed JSON and transport errors
remain uncertain. `ACCEPTED` means the receiver reports durable acceptance; it does
not prove a downstream email/SMS was sent, that a person read it, or that the receiver
implements durable storage correctly. That requires separate deployment acceptance.

GET `endpoint/receipts/<id>` returns the same receipt contract. A 404 is **not**
permission to retry POST; receiver processing may still be outstanding. No receiver
response supplies commands to the dashboard or changes broker behavior.

## Delivery lifecycle and recovery

| State | Meaning / behavior |
| --- | --- |
| QUEUED | Eligible incident retained in the outbox, within the fixed cumulative cap |
| SENDING | Reservation committed before one POST attempt |
| DELIVERED | Exact authenticated receiver acknowledgement accepted locally |
| REJECTED | Exact receiver rejection; never silently retried |
| UNKNOWN | Send may have succeeded; only bounded GET lookups are allowed |
| EXPIRED | Deadline prevented a queued send; uncertainty already recorded remains visible |
| LIMIT_REACHED | No delivery slot; local incident/file remains retained |

There is at most one network operation per inspection cycle and one POST attempt
per alert. UNKNOWN receipts get at most three GET checks across restart. A crash
with SENDING committed becomes UNKNOWN on resume, never a new POST. This prevents
blind resend but can leave an alert undelivered if failure happened before the
receiver accepted it. After bounded recovery is exhausted, inspect the receiver
and retained history; no automatic refund, new ID, authority reset or resend occurs.
The system does not claim exactly-once external delivery.

Network work runs outside the inspection journal lock. A nonblocking pump lock
prevents duplicate concurrent dispatch in the process; the existing dashboard
workspace lock prevents concurrent server launches for the same inspection state.
TLS verifies the receiver's certificate/hostname, requires TLS 1.2+, uses no system
proxy discovery and never follows redirects. Reply bodies are capped at 4 KiB.
Socket operations have a three-second timeout and an additional four-second wire
watchdog after TLS connection. DNS resolution remains an operating-system concern
and is not claimed to have a portable hard deadline; host supervision belongs in
actual deployment acceptance.

Each queued/reserved/reconciled outcome appends a local audit event with time,
state, method and safe reason code. Confirmed replies retain a canonical receipt
hash. Raw exceptions, URLs, secrets and reply bodies are not persisted. SQL triggers
prevent ordinary audit-event changes/deletion. These records are local evidence,
not signed external attestations. Clock rollback blocks new delivery; rollback
while awaiting a reply preserves UNKNOWN with `CLOCK_ROLLBACK` rather than claiming
an accepted, correctly timed receipt.

## Dashboard and operating boundary

Notifications show local spool counts and acknowledgement separately from receiver
status and queued/in-flight/accepted/uncertain counts. Recent per-incident delivery
states/reasons are shown. A viewer can acknowledge the local incident but cannot
configure a destination, reset delivery limits, resend an alert or claim remote
human acknowledgement. Missing API results clear previously displayed details.

The local inspection sampler's health does not qualify broker/feed availability,
alert timeliness or remote deployment. Backups retain the outbox/audit evidence in
`inspection.sqlite`, but restoration remains inspection-only. The real receiver,
credential lifecycle, DNS/network outage behavior and human escalation procedure
still require operational acceptance. M1-M3 gaps, B01's rejected promotion verdict,
the two-second entry ceiling and full M5's original prospective gates remain intact.

## Verification

Tests use injected transports and an ephemeral local TLS receiver, never a real
recipient. They cover minimal payloads, separate local/human acknowledgement,
exact acceptance, lost replies and restart, reserved-send recovery, bounded lookups,
malformed/rejected responses, cumulative limits, expiry, clock rollback, concurrent
pumps, no historical backlog, restore refusal, endpoint constraints, certificate
verification and redirect refusal. Headless tests cover accepted/uncertain states
and stale-detail clearing. No campaign, broker operation, real model call, visible
browser or user application interaction is used.

[Source-hashed local acceptance](../evidence/m5-alert-delivery-20261106.json)
records **151 backend checks and ten headless browser scenarios passed**, zero
skipped/flaky. Broker and external model calls remain zero; full M5 is explicitly
incomplete. Only synthetic transports and an ephemeral local TLS receiver were used.
