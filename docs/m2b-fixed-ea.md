# M2B fixed EA: native implementation with connected execution disabled

PR #17 (M2A) was merged at `0711456dbb2e105351c232716183091ae3ba3907`.
M2B adds the fixed gateway and actual native Strategy Tester evidence. It does
not authorize deployment, a broker order, a new campaign, or completion of M1.
M0A–M0C and the original broker/provider failure evidence remain unchanged.

## Implemented boundary

| Component | Authority and recorded evidence | Failure behavior |
| --- | --- | --- |
| Python `ea_file.py` | Projects a validated M2A ExecutionRequest and its canonical SHA-256 to a bounded offline frame | Rejects non-SIMULATOR accounts, unsupported precision/text/tickets and bad digests; never connects to MT5 |
| Native `Wire.mqh` | Reconstructs canonical JSON independently and checks hash, identity, action, expiry and exact decimal units | Rejects invalid work before admission; hashing is not authentication |
| `Core.mqh` | Validates account/release/policy, symbol mapping, time, volume, ownership and stop restrictions; reserves the admitted quantity | Rejects quotes older than **two seconds**; unknown outcomes and unresolved partial quantities block entry; no blind resend |
| Native journal | Holds an exclusive file handle; appends a sequence/hash chain and flushes SUBMITTING before a simulated call | Failed write/flush or invalid recovery halts admission; restart replays outcomes without another send |
| `Broker.mqh` | Prepares market entry, initial SL/TP, stop tightening, owned close and cancel; calls OrderCheck and rereads context after journal flush | The sole OrderSend boundary requires the intrinsic MQL_TESTER flag and a custom symbol; no enable-trading input exists |
| `OnTradeTransaction` and reconciliation | Callback flags cause fresh order/deal/position queries; journal records cumulative fills, open/pending quantities, IDs and accepted stop | Acknowledgement is not a fill; empty history is not proof; closures require consistent deal balance and position evidence; wider/missing stops do not qualify as protected |
| Python `ea_journal.py` | Independently verifies a stable copy of the actual native journal, request hashes, versions and quantity conservation | A torn tail, corrupt digest, regressed fill or inconsistent quantity rejects the entire copy |
| Channel telemetry | Native EA writes the M2A quote/heartbeat schema; `ChannelRecorder` records EA/Python-package/MCP observations by capability | A healthy heartbeat never refreshes the original tick. Missing delivery-latency statistics remain null; news/calendar success does not imply quote availability |

`FixedGateway.mq5` rejects initialization outside Strategy Tester. The send
wrapper repeats that intrinsic restriction independently. These are compiled
restrictions, not a runtime switch. No files from this PR were installed into the
CMC or FOREX.com broker terminals; the Python gateway remains simulator-only.

The native frame accepts printable ASCII without delimiter/escape characters,
positive tickets/sequences of at most 15 digits, and amounts with at most eight
whole and eight fractional digits. Unsupported values fail closed. Supported
fixture mappings are EURUSD → FXT_EURUSD and USDJPY → FXT_USDJPY. The execution
test uses a synthetic USD account and custom-symbol CFD-leverage arithmetic;
it does **not** certify broker forex specifications or CAD conversion.

This is a file-fed native implementation. The backend polling dispatcher,
authenticated production transport, and publication of the complete M2A
ack/state/reconciliation stream are not deployed. Native journal records are
internal evidence, not authenticated backend events. The Python telemetry
recorder accepts actual adapter callbacks but is not installed as a monitoring
service. The native producer emits after its first decoded fixture, then on
ticks/timers. No real channel latency measurement is claimed.

## Actual validation on 3 November 2026

The [sanitized evidence](evidence/m2b-native-20261103.json) identifies each native
source, compiler log and EX5 by SHA-256. MetaEditor build 6295 compiled the gateway,
test harnesses and bootstrap with zero errors and warnings. EX5 files, raw logs
and account-bearing host artifacts stay in ignored local storage.

* **78 native checks passed** in the final bounded Strategy Tester exercise.
  It performed seven simulated calls, including a test-only resting-order seed
  and cancellation, received trade callbacks and ended with zero positions/orders.
* Actual native entry, SL/TP verification, tightening, buy/sell closes, duplicate
  suppression, journal reopen and positive cancellation-history checks passed.
  A simulated restart reopened the journal object; this is not an induced
  terminal power-loss test.
* Native core fixtures separately exercised stale/expired/wrong-account work,
  lot rounding, partial fills, retained reservation, missing/widened stops,
  lost response, corrupt storage and exclusive writer locking. These are not
  broker fault-injection results.
* Python independently reconstructed **31 native journal rows for seven requests**,
  all terminal with no unresolved quantity, and validated the native telemetry
  JSON against the M2A schema.
* A separate non-Tester initialization emitted
  `FX_M2B_CONNECTED_EXECUTION_DISABLED` and refused to run.
* The local Python suite passed **416 tests**; 119 PostgreSQL tests were skipped
  locally. Required CI runs those tests against its own isolated database and
  builds the runtime/test images. CI does not compile or run proprietary MT5.
  It verifies that the committed native evidence matches every shipped native source.

The order scenario exercised FXT_EURUSD. USDJPY has native decoder/validation
fixtures; a full USDJPY order scenario and USD/CAD financial parity remain open.

The first bootstrap optimization stalled, the first service setup reported error
5308, and full Tester startup without an account profile was refused. These
attempts are retained in the private logs and public report; none counts as a
pass. A later bootstrap produced 7,200 synthetic minute bars. Full testing used
a temporary copy of the existing demo profile with an unreachable loopback proxy;
the emulated Tester login was 42. Original profile hashes were verified unchanged.
The isolated terminal was stopped and the temporary account cache removed.

## Reproduction and evidence verification

Generate the same synthetic inputs in the development checkout:

```powershell
$env:PYTHONPATH = "$PWD\src"
python scripts/m2b_fixtures.py --output .local/m2b-fixtures
python -m pytest tests/test_m2b_gateway.py -q
```

Use a separate portable terminal under the repository's ignored
`.local/m2b-native-*` directory. Never select either broker installation. Copy the
gateway sources into its `MQL5/Experts/FXTalanta`, and compile
`NativeTests.mq5`, `FixedGateway.mq5` and `GatewayTester.mq5` with MetaEditor
`/portable /compile:<absolute-source> /log:<unique-log>`. Compile
`BootstrapSynthetic.mq5` as a service under `MQL5/Services`; it refuses other
directory scopes and contains no order calls. Run it once through Navigator
Services, with algorithmic trading unchecked. Preserve failed attempts.

Copy `m2b-requests.tsv` into that terminal's `MQL5/Files`. The full Tester uses
`FXTalanta\GatewayTester.ex5`, `FXT_EURUSD`, M1, 1-minute OHLC (`Model=1`),
2026-01-05 through 2026-01-06, synthetic login 42, USD 10,000 and 1:100 leverage.
Set remote/cloud agents off, `AllowLiveTrading=0`, `AllowDllImport=0`, and
`ShutdownTerminal=1`. It stops after the bounded scenario, with a 100-tick failure
limit. These dates are fixture replay, not an elapsed 24-hour campaign. A blank
profile cannot start this full Tester mode; any account-cache copy must remain
private, disconnected and separate from the broker terminals.

The final local artifacts were verified with:

```powershell
python scripts/m2b_evidence.py `
  --native-root C:\SideProjects\fx-talanta\.local\m2b-native-20261103 `
  --compiler-run 04 --service-run 02 `
  --output docs/evidence/m2b-native-20261103.json
```

This verifier reads artifacts only. It checks source/binary/log bindings, native
results, the complete journal and telemetry schema. The host-isolation receipt
is supplied by a separate read-only process/configuration/fingerprint check.
Archive each exercise before another Tester run, since MT5 may replace its
agent file sandbox. Review native evidence with the source; do not infer it from
the portable CI result.

Official semantics: [OrderSend acknowledgement](https://www.mql5.com/en/docs/trading/ordersend),
[trade callback ordering](https://www.mql5.com/en/docs/event_handlers/ontradetransaction),
[file sharing flags](https://www.mql5.com/en/docs/files/fileopen), and
[Tester/startup configuration](https://www.metatrader5.com/en/terminal/help/start_advanced/start).

## Milestone boundary

M2B's native implementation and bounded evidence are delivered for review.
M2C still must prove independent Python/MQL5 USD/CAD safety parity, aggregate
exposure/margin/cost and loss-ledger rules, protection repair/exit deadlines,
authenticated transport and durable backend event delivery, crash/recovery and
clock behavior. FileFlush plus an exclusive handle is not a power-failure or
distributed fencing qualification. Connected shadow/acceptance require their
own approved setup. Full connected M2 remains pending; no runtime switch can
activate this Tester build.

M1 market-data/provider verdicts are unchanged. M2D remains behind M1 and M2A–C
gates and explicit connected demo authorization. UI milestones still include
quote age/latency and separate EA, Python-package and MCP capability status.
