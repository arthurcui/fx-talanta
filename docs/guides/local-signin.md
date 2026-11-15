# Local workspace sign-in

For a private development workspace on your own computer, launch the dashboard with
`--local-signin`. Open its ordinary URL, for example `http://127.0.0.1:8766/`.
There is no launch token to copy or bookmark.

On first visit, choose a username and a passphrase of 16–256 characters and repeat
the passphrase. Enter it in the page, never in chat or a repository file. Subsequent
visits use the normal username/passphrase form. The first owner cannot be replaced
through the setup endpoint after creation.

Sessions survive browser and service/container restarts. They expire after 30 days
or seven days without use, whichever comes first. **Sign out** revokes the current
session; **Sign out all sessions** invalidates every browser session immediately.
Neither action removes strategies or research evidence.

The separate `local-auth.sqlite` in the private workspace state stores a salted
scrypt password verifier, hashed session tokens, CSRF secrets, expiration times
and failed-login timestamps. Plaintext passphrases and bearer tokens are not stored.
Five failed attempts within a minute temporarily block sign-in, including across
restarts. Cookies are HttpOnly and SameSite=Strict. Origin/Host/CSRF checks remain.
Authentication refreshes only internal inspection/research access, never trading
authority. Session and credential state is excluded from the portable inspection
backup/restore workflow; a restored workspace requires its own sign-in setup.

This mode permits HTTP **only on 127.0.0.1**, for a trusted single-owner local machine.
It rejects public origins, remote binds and mixing with the remote-owner mode.
It is not an internet deployment option. Existing HTTPS/mTLS remote access and
HTTPS-only `--owner-file` behavior are unchanged. Docker must publish the preview
port on host 127.0.0.1 only; preserve its named state volume across upgrades.

The November 15 PR #65 preview update reused the existing named volume after a
verified private SQLite backup. Two strategy revisions and one freeze retained
identical fingerprints. AI strategy generation uses the existing ignored API-key
file mounted read-only, not a credential embedded in the image or browser. Trading
remains disabled; no broker or terminal is attached.
