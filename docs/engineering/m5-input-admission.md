# Typed simulation input admission

The adapter in `fx_talanta.evaluation.inputs` connects normalized local source envelopes
to the [durable input queue](m5-runner-operations.md), the existing simulator and the
read-only dashboard. It replaces hand-built safety flags at this integration boundary
with a typed, retained source record. It does not fetch market/news/calendar data, call
a model, connect to a terminal, start a campaign or qualify a provider.

## Contract and authority

`Envelope` requires a source UUID, stable event UUID and sequence, SYNTHETIC or
RECORDED_OFFLINE provenance, a channel label, claimed source receipt time, original
market snapshot and incremental completed bars. It may include calendar/news safety
evidence. Each safety record carries a CLEAR/BLOCKED/UNAVAILABLE state, covered currency
legs, availability/expiry timestamps and a reference hash. News content is a bounded
NEUTRAL/ADVERSE/UNAVAILABLE classification, not arbitrary provider prose or instructions.

Source receipt time, coverage and reference hashes are **caller assertions**. A source
UUID or EA/PYTHON/MCP label is not authenticated provenance, an attached collector or
independent clock qualification. Synthetic evidence can exercise the contract but cannot
close M1 gaps. Production source adapters and qualified references remain separate work.

Normalization records its own local time and retains the original market, safety
evidence, identities and a hash of the exact bar delta. Quote/conversion timestamps are
never replaced with receipt time. Timestamp contracts require timezone information and
normalize representation to UTC; they do not infer a broker-server timezone offset.
Future market, bar or safety availability relative to the claimed receipt is rejected.
The runner revalidates the normalized fields and bar hash against this source record.

The adapter can only **narrow** the original market safety:

- Missing, expired, unavailable or incomplete currency coverage disables the relevant
  safety flag. Both EUR and USD are required for EURUSD; USD and JPY for USDJPY.
- A blocked calendar marks blackout. Existing blackout, closed session and disabled
  calendar/news flags cannot be cleared by normalization.
- Missing news content disables common news availability. Shared calendar/news safety
  applies to all arms; only the AI_NEWS selector receives news interpretation content.
- Calendar/news expiry is rechecked at actual runner admission. Waiting in the queue
  cannot retain an earlier safety clearance, even with a quote younger than two seconds.
- Quote freshness remains enforced independently by the unchanged two-second governor.

The runner preserves the entire source record in the committed Tick and reconstructs
the same transition on restart. Original source flags and the narrower normalization
are both inspectable. A reference hash is not verified against an external provider by
this component. The existing 64 KiB Tick limit includes the retained source record;
split bar history into bounded deltas rather than expanding the limit.

## Queue integration and retry

```powershell
python -m fx_talanta.evaluation.operations enqueue-envelope --queue .local/source.sqlite --binding-hash $bindingHash --input envelope.json
python -m fx_talanta.evaluation.operations drain-one --queue .local/source.sqlite --binding-hash $bindingHash
```

The envelope source UUID must match the pinned queue binding. The first input fixes
manual-versus-normalized mode and its declared channel/provenance; subsequent inputs
cannot mix modes or silently change the source label. Runner provenance must also match
the registered simulation provenance. Invalid admission leaves pending evidence intact.

Same-ID identical input retry reuses the **first** normalization time and queued receipt,
including after process restart or safety expiry. Changed content under that ID fails;
retry cannot refresh timestamps or safety windows. The existing commit/acknowledgement
recovery applies without another simulated transition. This adapter adds no automatic
retry loop, source failover, deadline extension, budget reset or execution authority.

Legacy manually built Tick fixtures remain supported for existing tests. They are not
silently upgraded to normalized evidence. The dashboard separately counts normalized
inputs and displays asserted channel labels with an explicit qualification warning;
these labels are not the live EA/Python/MCP connection status cards.

## Acceptance and remaining work

```powershell
$env:PYTHONPATH = "src;."
python -m tools.qualification.runner_operations_acceptance --normalized-inputs --output .local/input-admission-new
python -m tools.qualification.m5_acceptance --output .local/input-admission-checks-new.json
```

The bounded exercise admits six synthetic envelopes, reopens the queue consumer,
checks duplicate delivery, settles one simulated position per comparison arm and stops.
Fault tests cover incomplete/expired coverage, queued expiry with fresh quotes, missing
news content, JPY coverage, source identity/mode/provenance changes, future input,
normalization tampering and unchanged retry timestamps. Headless browser acceptance
reads the actual fixture runner and verifies the source labels. No external calls occur.

Remaining integration/qualification includes actual source collectors and independently
verified evidence, real model selection integration, connected fault/reconciliation and
broker administration, eligible candidate/cost qualification and deployment/receiver
acceptance. The required eight weeks **AND** 100 closed PAPER trades are not supplied by
this exercise. B01 stays `REJECT_FOR_PROMOTION`, prior failures remain preserved, trading
is disabled, and full M5 remains open.

The [source-hashed acceptance report](../evidence/m5-input-admission-checks-20261106.json)
records 221 backend checks and 11 headless browser scenarios passed, with zero skips
or flaky results. The [normalized-input exercise](../evidence/m5-input-admission-synthetic-20261106.json)
records six acknowledged normalized inputs and one simulated close per arm. Both
reports match the tested source bytes; these are not prospective trading results.
