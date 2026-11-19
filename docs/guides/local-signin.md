# Local workspace access

The local Docker preview uses `--local-workspace`: open http://127.0.0.1:8766/ directly. No account, password or launch shortcut is required. Anyone with access to this computer can use the workspace. Trading remains disabled.

This mode rejects non-loopback binds, public origins and owner/client-certificate configuration. Host, Origin and cross-site request checks remain, with a process-local CSRF token for mutations. It must not be exposed through a public proxy or remote port forwarding.

Existing strategies and research remain in the same state volume. Old local authentication records are retained but unused. The explicit `--local-signin` and HTTPS owner modes remain available for existing deployments; the preview no longer uses them.
