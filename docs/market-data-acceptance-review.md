# Market-data acceptance design review

Reviewed November 2, 2026 against the committed observer, offline gateway, failed
qualification reports and separate FOREX diagnostic. The findings below describe
the legacy policy. An opt-in implementation is now included in this branch; see
the implementation section below. Historical outcomes and entry permissions do not change.
No new 24-hour run is authorized. PRs #10 and #12 are now merged; PR #11 remains
draft and unmerged, with the unmerged PR #8 runner dependency retained.

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
| Medium | `final_health` uses the last record's state, without reassessing its tick age at completion. | A quote fresh at its last read may be stale by the deadline; distinguish last-sample quality from current end-of-run readiness. |

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

Define completion verification explicitly: take one separately labeled bounded
final read when the scheduled observation window closes, and assess freshness at
that read's actual completion time. Exclude it from the 2,880 scheduled-slot
numerators. A timeout or missing final read fails current readiness. Preserve the
original observation-window deadline and report any final-verification duration
separately; this cannot extend coverage or compensate for missed polls. A fresh
last scheduled sample is not automatically fresh at the deadline or at submission.

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

## Opt-in implementation: acceptance version 2

`observe-run --acceptance-version 2` selects the new policy for a **new run ID**.
The default remains version 1. The version and final-verification budget are
persisted with the immutable runner plan. Observer/4 records carry a version-2
health object; absent health fields are omitted from legacy serialization so old
record hashes and plan identities remain unchanged. A run cannot switch versions.
No production binding, database, running checkout or historical report is migrated.

Complete stale snapshots remain DEGRADED for quote readiness, but reset the
transport and completeness failure streaks. Their successful-read timestamp
advances; legacy `last_success_at` still means a fresh complete assessment. Actual
read/connection failures retain exponential backoff; missing required inputs have
a separate counter. Only a complete validated read resets these operational
counters, so alternating incomplete reads and transport errors cannot erase them.
Both use the binding's existing failure limit (ten in the reviewed broker plans).
Identity, malformed data and invalid timestamps still halt immediately. Version 2
rejects observer age settings above five seconds. Offline entry code is unchanged
and still caps age at two seconds; no observer result authorizes an entry.

For the standard plan, attempts are anchored to 2,880 thirty-second slots. The
runner persists the attempted slot before reading, preventing an uncertain commit
or restart from producing another attempt in that slot. Reads that complete after
the observation deadline are excluded from scheduled coverage. Duplicate IDs and
additional records within a slot cannot improve coverage. Sleep uses monotonic
time; UTC/monotonic elapsed divergence above one second aborts the runner rather
than converting a clock jump into elapsed evidence. Restart gaps remain visible.

Reports expose separate collector and quote gates, per-symbol ages/fresh fractions,
sampled stale streaks, attempt and complete-read gaps, and a legacy fresh/committed
fraction. Sampled stale streaks are not measurements of continuous market downtime.
The joint `accepted` result requires both verdicts; collector success alone never
qualifies a broker. There are no session-based denominator exclusions.

The final read is separately labeled and attempted at most once after the original
deadline, including when transport backoff would otherwise suppress polling. It
cannot bypass a persistent halt. The plan declares a thirty-second completion
budget; collection also retains the binding's subprocess timeout. A missing,
timed-out, late or ambiguous final result cannot pass. Unknown final-commit outcomes
fail closed and are not retried. Final duration and time beyond the original
deadline are reported separately, never credited to scheduled coverage.

Fixture tests cover synthetic full-duration dual outcomes, actual isolated
PostgreSQL recovery/unknown commits, repeated unchanged stale ticks, separate halt
budgets, final failures, identity errors, invalid clocks, legacy wire compatibility,
and the exact two/five-second boundaries. Synthetic time is test evidence only.
Review this prospective policy and requalify the clock/binding before requesting
authorization for another real campaign. No new campaign has been started.

## Follow-up code review — November 3, 2026

Reviewed the version-2 implementation from `d761c2c` in a separate checkout,
including the PR #8 final report at `6990a0d` and current main at `22437a6`.
Both dependencies merged cleanly into this review branch; neither protected broker
checkout was updated. The failed CMC/FOREX results retain their original policies.

**Fixed finding:** the runner checked wall time against monotonic time only at
the top of the loop. A forward clock adjustment during the final read could
escape that check because completion exits the loop. A deterministic reproduction
advanced wall time by two seconds during that read while monotonic time stayed
unchanged: the old code incorrectly returned COMPLETE instead of rejecting the
clock divergence. The same test with both clocks advancing by two seconds was a
valid slow read and completed normally.

Version 2 now rechecks after connection/history reconstruction and after each
scheduled/final poll, including its commit. A divergent final observation remains
in the evidence but the campaign fails; it is not retried or relabeled fresh.
The regression uses a 90-second synthetic campaign and proves this failure path,
not real elapsed qualification. Legacy version-1 behavior and serialization,
five-second observation ceiling, two-second entry limit and acceptance thresholds
are unchanged.

Validation after these review fixes: all **389 native tests** passed, including the
isolated PostgreSQL integration suite; Ruff lint/formatting and diff checks passed.
The clock-jump regression failed before the fix and passed afterwards; its normal
elapsed-read control also passed. No connected collection was needed for these checks.

### Final completion and recovery corrections

Two additional regressions exposed gaps in the final-verification boundary:

- A synthetic full-day campaign was incorrectly accepted when its final database
  acknowledgement returned at deadline + 30.001 seconds. The observation's stored
  timestamp is set before commit, so that timestamp alone cannot enforce the
  thirty-second completion budget. The runner now checks the actual return time;
  a late result yields FAILED / FINAL_VERIFICATION_DEADLINE and is never retried.
- Interrupting a real fixture PostgreSQL operation immediately after the final
  commit left the run STOPPED with an unconfirmed outcome. Previously, resuming
  found the record and promoted the run to COMPLETE without evidence that the
  operation returned within budget or passed the final clock check. Recovery now
  yields FAILED / FINAL_VERIFICATION_UNCONFIRMED in this situation and preserves
  the committed record without another collection attempt.

The original status file now retains `final_verification_receipt`, containing the
exact final record ID and the UTC time when its operation returned and passed the
clock check. Recovery requires that receipt to match the single final database
record, its assessment time and the original completion deadline. Missing or
mismatched confirmation cannot be reconstructed from a pre-commit timestamp.
No quote timestamp is changed, and the receipt never grants entry permission.
Keep it with the original plan/status evidence. Version-1 records and previously
failed broker runs are unchanged.

Regression controls cover immediate completion, exactly thirty seconds, one
millisecond beyond the budget, confirmed resume, mismatched receipt identity and
interruption after an actual fixture commit. The full-day cases use synthetic time;
the PostgreSQL interruption case is a short fixture, not broker qualification.

The review confirms that complete stale reads reset operational failure budgets
while remaining quote failures; missing slots cannot be replaced by bursts; final
verification cannot fill scheduled slots; and collector success cannot grant entry
permission. Thirty-second samples establish sampled availability only. The report's
`last_committed_at` is the assessment timestamp carried by the latest committed
record, not a separately measured PostgreSQL commit-completion timestamp. Neither
it nor a CURRENT process heartbeat establishes continuously fresh quotes.

### Concrete prospective campaign requirements (not started)

| Item | Requirement before a new FOREX comparison campaign |
| --- | --- |
| Scope | Read-only demo; only the pinned EURUSD and USDJPY broker symbols; no order route |
| Policy | Acceptance version 2; fresh run ID, status/stop files and saved plan; retain all failed evidence |
| Budget | 86,400 seconds, 30-second cadence, at most 2,880 scheduled collection attempts plus one final attempt; each complete read includes two tick and four completed-bar requests plus pinned account/history checks |
| Final read | Separate 30-second completion budget; never extends scheduled coverage |
| Gates | At least 95% scheduled coverage, complete reads and jointly fresh slots; at least 86,340-second span; attempt and complete-read gaps at most 180 seconds; valid final read and fresh final quotes |
| Recovery | Existing ten-failure transport/completeness limits and twelve-failure database limit; no stale-only halt, no weakened entry limits |
| Clock | Independently verify host time and SDK mapping again; qualify the history lookback, full duration and final-read budget; retain evidence and a new binding fingerprint |
| Isolation | Verify no observer owns that terminal/account; use the isolated checkout and unchanged execution-disabled environment; do not touch CMC |
| Approval | Review PR #8 before PR #11, recheck CI after the dependency merge, and obtain separate campaign authorization |

The old FOREX clock policy ends at **2026-11-04T00:00:00Z**. At the November 3
review time it cannot cover another full 24-hour campaign plus final verification.
Do not merely extend its dates or reuse its evidence. A freshly verified policy
is a prerequisite, not a reason to modify or restart a historical run. This plan
does not promise a quote-readiness pass: the prior diagnostic's stale quotes remain
unresolved upstream evidence.
