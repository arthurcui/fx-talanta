# Manual BLS Windows acceptance

Verified on 2026-11-03 UTC using the user's actual saved BLS calendar, a separate
development journal, and the native Windows file chooser. The code is based on
main `1c12f5b1211f48a1b8fefdb81f939614ce544e72` (merged PR #10), with the visible
chooser owner added in this change. [Sanitized results](evidence/manual-bls-windows-20261103.json)
include the earlier real-file CLI and offline gateway verification separately.

## Desktop interactions and persisted results

The original withdrawn Tk owner did not expose a targetable application window
during this test. A visible, titled owner and explicit dialog parent made the
chooser discoverable and operable. This records the observed desktop behavior;
it does not claim that the original picker failed on every Windows installation.

| Actual interaction | Observed result |
| --- | --- |
| Select the saved `bls.ics`, click Open | Exit 0, `IMPORTED`, 92 recognized events, 8 upcoming at capture time |
| Reopen and click Cancel | Exit 0, cancellation message; journal attempts remain 1 |
| Select a local HTML file named `invalid.ics`, click Open | Exit 2, reminder/error output; successful calendar retains 92 events and original hash |
| Run `status` after rejection | `LAST_UPLOAD_FAILED_OR_INTERRUPTED`; reminder instructs a fresh download/upload |
| Launch `upload --choose` directly from the CLI, select original file | Exit 0, `UNCHANGED`; warning cleared, original review deadline retained |

After these interactions the journal has three attempts/outcomes (`OK`, `FAILED`,
`OK`) and exactly 92 revisions. The archive matches the original 80,672-byte file:
SHA-256 `92a350111ace106deaab5584e4084366bd367b594a0d0bad116008d82d63e501`.
The review deadline remains 2026-11-10T03:43:20.405821Z after duplicate recovery.

The first three dialogs used a temporary interactive test launcher to capture
stdout; the final recovery used the documented CLI directly. The temporary task
was removed. No scheduler or service is required by the product. Results and
reminders are terminal output; only file selection uses a graphical dialog.

## Clock and filtering checks

With the real imported journal and a **simulated** clock at its seven-day review
deadline, `status` reports `REVIEW_OVERDUE`; the journal bytes remain unchanged.
This does not represent seven elapsed days of operation.

Earlier real-file verification converted the JOLTS source time
`DTSTART;TZID=US-Eastern:20261103T100000` to `2026-11-03T15:00:00Z`.
For EURUSD and USDJPY, simulated assessments at -31, -15, 0 and +31 minutes from
that event returned target-event blackout values false, true, true and false.
Entries remained blocked throughout because provider qualification is incomplete.
Offline gateway simulations at 14:45 UTC rejected both entries and opened zero
positions, using only the isolated `fx_calendar_test` database namespace.

## Acceptance scope

Local validation: all 338 native tests passed, including isolated PostgreSQL
integration tests; Ruff lint and formatting passed across source, tests and
scripts. Two added tests cover a missing desktop and a dialog-opening error,
including CLI fallback and window cleanup. These mocked error tests supplement
the actual interactions above. Both protected broker checkouts remained clean;
the temporary UI task and its test processes were absent after verification.

The manual development workflow has actual desktop evidence, not only mocked
chooser tests. The saved file is manually sourced, covers only the recognized
BLS USD releases, and does not qualify a complete calendar or general forex news
feed. Trading remains disabled. Neither broker checkout, terminal, binding,
observation database nor evidence was changed by this verification.

Future changes must distinguish automated fixture tests, real-file checks,
native UI interactions and simulated times in their acceptance reports. A passing
fixture suite alone is insufficient to declare an affected desktop workflow ready.
