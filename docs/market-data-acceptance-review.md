# Market-data acceptance design review

Reviewed November 2, 2026 against the committed observer, offline gateway, failed
qualification reports and separate FOREX diagnostic. **Design proposal only:**
no runtime, thresholds, bindings, historical outcomes or entry permissions change.
No new 24-hour run is authorized. PRs #10 and #11 remain unmerged.

## Recommendation

Separate collector operation, quote quality and permission to enter a trade.
A successful read of a stale quote is useful observation evidence, but it is never
a fresh quote or permission to trade. Continue a bounded read-only campaign through
valid stale quotes; fail the quote-availability assessment honestly when its gate
is missed. Halt for identity/integrity failures and exhausted transport/storage
recovery. Do not use a single HEALTHY label for these different questions.

The **five-second ceiling remains intact**: age above five seconds, future or
missing timestamps, unknown clock mapping or unavailable required quotes block new
entries. An age exactly five seconds meets that ceiling only; other gates still
apply. The current offline risk policy is stricter: `quote_age_seconds` is capped
at **two seconds**, consistent with the architecture's submission-age rule.
Preserve that two-second gate too. Five seconds is currently an observer setting,
not an implemented connected-trading entitlement. This review does not authorize
loosening the offline gateway to five seconds or adding a connected order path.

## Findings in the current implementation

| Priority | Finding | Consequence |
| --- | --- | --- |
| High | `Observer._poll` increments `failures` for every non-CURRENT result, including valid STALE_TICKS, and halts at the binding limit. | Read-only collection stops during quote droughts; nine stale reads followed by one timeout can exhaust a supposedly operational failure budget. |
| High | `Evidence.healthy` counts only HEALTHY records; acceptance uses that fraction and HEALTHY final state. | The report combines successful collection with market freshness. A connected collector can be operating correctly while quote availability fails. |
| High | The observer uses five seconds; the offline gateway uses at most two seconds. | Calling five seconds the existing entry rule is inaccurate. A new design must preserve both limits and their different purposes. |
| Medium | The first failing assessment reason and one aggregate state cover multiple symbols, bars and history completeness. | A stale EURUSD quote, missing history and an actual disconnect need separate evidence; per-symbol metrics must not silently reduce existing global entry safeguards. |
| Medium | `last_success_at` updates only for CURRENT; heartbeat measures runner activity, not fresh committed observations. | Neither a recent heartbeat nor a terminal `connected` flag establishes data quality. Dedicated successful-read and successful-commit timestamps are needed. |
| Medium | Thirty-second observation sampling is much slower than a two/five-second quote gate. | A soak can measure sampled availability but cannot certify continuous freshness or authorize a later entry using its last snapshot. |

Code references: [supervisor](../src/fx_talanta/observer/supervisor.py),
[runner/evidence](../src/fx_talanta/observer/runner.py),
[observation schema](../src/fx_talanta/domain/models.py),
[risk policy](../src/fx_talanta/domain/offline.py),
[freshness checks](../src/fx_talanta/risk/governor.py),
[submission/recovery checks](../src/fx_talanta/gateway/offline.py).

The cadence fix already keeps DEGRADED reads eligible for the next poll. It does
not separate their failure streak from transport failures. The new FOREX run
therefore achieved 100% elapsed-poll coverage and a 30.08-second maximum gap, yet
halted after ten consecutive stale observations. All original acceptance failures
remain valid under their declared rules.

## Proposed independent state dimensions

| Dimension | Evidence | What it controls |
| --- | --- | --- |
| Runner liveness | Process heartbeat and monotonic progress | Detect a stuck/dead worker; never grants market health |
| Transport/read status | SDK completion, connection flag, call duration, explicit error, last successful read | Bounded retry/backoff and transport-failure streak |
| Identity/integrity | Account/venue/path/build/currency/mode/SDK pins, schema, clock-policy validity | Immediate persistent halt on violation |
| Storage continuity | Successful immutable commit, sequence/run identity, last committed observation | Coverage, durability and bounded database recovery |
| Per-symbol quote quality | Broker tick timestamp, UTC mapping, local receipt/assessment times, age, repeated-tick indicator | Fresh/stale/unknown classification and entry veto |
| Other required data | Bar/history completeness, conversion/account freshness, calendar/news/session evidence | Separate quality vetoes and acceptance findings |
| Entry eligibility | Deterministic conjunction of all applicable risk and freshness gates, rechecked at submission | Permission for new exposure only; observer status cannot grant it |

Persist both UTC timestamps and monotonic call/scheduling durations. Keep the raw
timestamp convention and policy version available for audit. Report age at actual
assessment/submission, not an earlier convenient read time; do not subtract call
duration or reset a repeated tick's timestamp to make it fresh. One-time NTP checks
are not continuous clock qualification. A maximum permitted clock uncertainty and
its verification method must be declared before relying on entry-age measurements;
unknown mapping or uncertainty blocks entries, without rewriting past evidence.

## Prospective collection behavior

| Observation | Collector action | Entry behavior |
| --- | --- | --- |
| Valid, complete read with fresh required quotes | Commit at scheduled cadence; reset transport streak | Eligible only if every stricter risk/input gate also passes |
| Valid, complete read with stale quote(s) | Commit at scheduled cadence; record stale episode; reset transport streak; do not end the campaign solely for staleness | Block affected dependencies; retain current conservative global blocking until dependency scoping is implemented and tested |
| Timeout, read failure or disconnect | Record failed attempt; bounded exponential transport recovery; halt after ten consecutive transport failures | Block immediately; a heartbeat cannot clear it |
| Missing required fields/bars/history with identity still verified | Record precise missing components; continue bounded polling; maintain a separate integrity/completeness streak and halt at its predeclared limit (proposed ten) | Block; never count as a complete read |
| Wrong identity/path/build/currency/mode/SDK, malformed evidence, invalid clock mapping or clock rollback | Persistent halt; manual investigation | Block; no automatic recovery or account adoption |
| Database unavailable | Keep the existing twelve-failure bounded recovery and original deadline; reconstruct only committed evidence | Block; no freshness claim from uncommitted data |

Do not spin or issue extra requests to wait for a fresh quote. A stale-episode
alert is separate from terminating the collector. Pure quote staleness can fail
data acceptance without stopping the observation clock. Missing data must not be
mistaken for ordinary stale-but-valid quotes. Transport recovery requires a new
successful identity-verified read; quality and entry recovery additionally require
fresh, complete evidence and the existing gateway recovery checks. Never reuse a
previous green status after an error, or let a recent heartbeat clear a veto.

Protective management and exits retain their existing dedicated safety rules;
blocking new entries must not automatically disable them, nor authorize an unsafe
close based on stale state. This proposal does not change those gateway rules.

## Proposed next campaign: separate verdicts, unchanged entry protection

Use a new schema/policy version and new run ID only after implementation, review
and explicit authorization. Preserve all previous run IDs, records, gates and
NOT ACCEPTED outcomes. Do not re-score them as passes under this proposal.

**Collector acceptance:** retain the 86,400-second duration, at least 86,340-second
sample span, 30-second cadence, at least 95% distinct scheduled-slot coverage and
180-second maximum initial/intermediate/trailing observation gap. Also require
at least 95% scheduled slots to contain complete, identity-valid successful reads,
no integrity halt, no exhausted recovery, and a complete successful final read
within the declared trailing-gap budget. Its quotes may still be stale: report
that independently. A successfully recorded transport error is attempt evidence,
not a successful read. Count at most one read per scheduled slot; duplicate or
burst writes cannot cover missed slots. Define exactly 2,880 slots anchored to
the original start for a full 24-hour/30-second plan, using monotonic scheduling.
Report committed-attempt continuity separately from complete-read continuity.

**Quote availability:** retain the existing at-least-95% jointly fresh requirement
at the five-second observation threshold and require a fresh final observation
for the existing data-readiness target. Report each symbol separately as well as
the joint dependency set; include stale-duration distributions, worst episodes,
future timestamps, unknown/missing data and recovery. Missing slots count as not
fresh in scheduled-slot availability. Also publish the legacy fresh/committed-read
fraction so denominator changes are explicit. A collector pass with a quote fail
must be displayed as **collector passed / quote readiness failed**, never simply
"broker qualified". This review does not lower 95% or redefine stale as healthy.

**Entry safety:** every new-entry evaluation must independently refresh/revalidate
the required quote, conversion and account state at submission, apply the stricter
configured gate (currently two seconds offline), and always reject data older than
five seconds. A 30-second observer snapshot cannot be reused as standing entry
authorization. The next campaign remains read-only; no trading path is enabled.

Keep wall-clock 24-hour denominators. Record official, versioned session/maintenance
labels and distinguish known closed from unknown, but do not remove bad intervals
after seeing results. An alternative session-scoped target would require its own
prospective policy and authorization, with both all-time and session metrics shown.
A quiet market may fail quote availability without implying a broken connection.

## Required implementation and review before another run

1. Version the observation schema and acceptance plan. Add separate transport,
   integrity and quote-quality fields/counters, successful-read/commit timestamps,
   per-symbol ages and explicit attempt versus data coverage. Preserve historical
   record readers and halt semantics for existing run IDs; no rewrite or resume.
2. Test long stale streaks without collector termination or entry permission;
   mixed stale/timeout sequences; ten true transport failures; missing-data limits;
   identity changes; clock rollback/future ticks; database recovery; unchanged tick
   timestamps; duplicate/off-schedule samples; and session labels that cannot alter
   denominators. Tests must prove the two-second entry policy and five-second
   outer veto are not relaxed, including exact-boundary and just-over-boundary ages.
3. Test deterministic dual reports: collector-pass/quote-fail, both fail, and both
   pass with full-duration synthetic evidence. A short synthetic or connected smoke
   test never provides 24 hours of real acceptance evidence. Preserve original
   failed reports as regression fixtures with their original versions/outcomes.
4. Review the plan, clock verification, source commit, request budget, binding,
   recovery rules and distinct storage/output paths. Then request authorization
   for one new read-only campaign. Neither this review nor a merged PR authorizes
   that campaign, promotion, changed risk limits or live trading.

Evidence: [CMC final report in existing PR #8](https://github.com/arthurcui/fx-talanta/pull/8),
[FOREX campaigns and persistent-connection diagnostic](forex-readonly.md).
The diagnostic showed stale quotes on a persistent attachment and matching latest
history/latest-tick timestamps in its separate check. It narrows the investigation;
it does not establish whether upstream quote production or delivery is responsible.
