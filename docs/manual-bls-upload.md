# Manual BLS upload and review reminder

This is a free development workflow. Download the official
[BLS calendar](https://www.bls.gov/schedule/news_release/bls.ics) in your browser,
then select the saved `.ics` file. It requires no MT5 terminal, API key, FRED call,
web server, subscription or background task.

## Upload

From an installed project checkout, open the desktop file chooser:

```powershell
python -m fx_talanta.manual_bls upload --choose
```

The chooser opens an **FX-Talanta Calendar** owner window and a native **Upload
BLS calendar** dialog. Select a file and click **Open**; the result and review
reminder appear in the terminal that launched the command. Both windows close
after Open or Cancel. This is a file picker, not a full desktop dashboard.

The chooser requires Python's optional Tk desktop support. Alternatively, supply
an explicit file path (also suitable for Linux/Docker with a mounted file):

```powershell
python -m fx_talanta.manual_bls upload --file C:/SideProjects/fx-talanta/.local/bls.ics
python -m fx_talanta.manual_bls status
```

Successful uploads and status checks show the review reminder when needed;
Cancel only confirms that no changes were made. The default store is
`.local/manual-bls` under the current directory. Use the same explicit `--store`
on each invocation when launching from different directories:

```powershell
python -m fx_talanta.manual_bls --store C:/SideProjects/fx-talanta/.local/manual-bls status
```

Selecting Cancel makes no changes. Invalid/truncated/oversized files, unsupported
timezones and conflicting revisions are rejected. A rejected upload leaves the
previous successful calendar intact and records a failed attempt. The original
bytes are archived by SHA-256; existing archives are never replaced. An interrupted
attempt remains visible, and a corrupt/missing current archive produces an error
and reminder. Temporary archive files are not accepted calendar snapshots.

## Reminder behavior

Reminders appear **only when running this calendar tool**, as requested. No chat
reminder, OS notification, Windows task or recurring automation is enabled.

The result includes the last review time, next review date, upcoming event count,
last scheduled event and a readable message. A reminder appears when:

- no calendar has been uploaded;
- seven days have elapsed since the last accepted upload/manual confirmation;
- no non-cancelled events remain beyond the next seven days;
- the latest upload failed or was interrupted; or the local clock moved backwards.

Uploading identical bytes does not postpone the review date. If you downloaded
and checked the latest official file and BLS has not changed it, explicitly confirm:

```powershell
python -m fx_talanta.manual_bls upload --file C:/SideProjects/fx-talanta/.local/bls.ics --reviewed-latest
```

This resets only the manual review reminder. It does not assert a verified HTTP
fetch, create duplicate event revisions, backdate availability or certify source
freshness. The seven-day interval is a development housekeeping policy, not a
release-update latency guarantee. BLS can change its calendar between reviews.

## Journal and scope

`journal.sqlite` in the selected store uses the existing provider journal format.
It can be passed to `JournalGate` or the provider-pipeline assessment command;
blackout assessment retains the same point-in-time history and entry restrictions.
No broker database or binding is accessed. Raw archives, journal and lock file
remain private under `.local`; keep them together when backing up.

The existing importer recognizes Employment Situation, CPI, PPI and Job Openings
and Labor Turnover Survey (JOLTS), not every BLS event. This USD-only subset is
sufficient for development fixtures, not complete USD/EUR/JPY coverage or general
forex news. Provenance stays
`MANUAL_FILE` / `PROVIDER_SHADOW`, qualification remains false, and trading stays
disabled. A successful upload or a reminder that is not yet due does not authorize
entries. The file chooser is a local desktop dialog, not a browser upload server.

## Acceptance evidence

The [Windows acceptance report](manual-bls-windows-verification.md) records the
actual saved-file import, native picker interactions, persisted journal checks,
and reminder/gateway simulations. Before declaring this workflow ready after a
change, verify the real saved-file path and each affected user interaction;
fixture-only tests do not establish desktop acceptance. Report automated tests,
actual interactions, simulated clocks, and remaining limitations separately.
