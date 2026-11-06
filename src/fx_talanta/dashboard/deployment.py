"""Pinned, inspection-only deployment preflight and explicit foreground launch."""

import argparse
import hashlib
import json
import sqlite3
import ssl
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from fx_talanta.dashboard.models import Snapshot
from fx_talanta.dashboard.server import serve, validate_access
from fx_talanta.dashboard.sessions import Owner
from fx_talanta.domain.models import FrozenModel
from fx_talanta.provider_pipeline import status_lock

Role = Literal["snapshot", "owner", "server_cert", "server_key", "server_ca", "client_ca"]
REQUIRED = {"snapshot", "owner", "server_cert", "server_key", "server_ca"}


class Spec(FrozenModel):
    version: Literal["dashboard-deployment/1"] = "dashboard-deployment/1"
    execution_enabled: Literal[False] = False
    bind: str = "127.0.0.1"
    port: Annotated[int, Field(ge=1, le=65535)]
    public_origin: str
    state: Path
    mode: Literal["NEW", "RESUME"]
    minimum_certificate_hours: Annotated[int, Field(ge=1, le=8760)] = 72
    files: dict[Role, Path]

    @model_validator(mode="after")
    def paths(self):
        if not REQUIRED <= self.files.keys():
            raise ValueError("required deployment artifacts missing")
        if not self.state.is_absolute() or any(not p.is_absolute() for p in self.files.values()):
            raise ValueError("absolute paths required")
        for path in [self.state, *self.files.values()]:
            if any(
                p.is_symlink() or getattr(p, "is_junction", lambda: False)()
                for p in [path, *path.parents]
            ):
                raise ValueError("linked paths prohibited")
        state = self.state.resolve()
        if any(p.resolve() == state or state in p.resolve().parents for p in self.files.values()):
            raise ValueError("deployment artifacts must be outside inspection state")
        validate_access(
            self.bind,
            self.public_origin,
            self.files["server_cert"],
            self.files["server_key"],
            self.files.get("client_ca"),
        )
        origin = urlsplit(self.public_origin)
        if origin.scheme != "https" or (origin.port or 443) != self.port:
            raise ValueError("HTTPS origin must match listener port")
        return self


class Profile(Spec):
    hashes: dict[Role, Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]]
    package_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def package_digest():
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(
        p for p in root.rglob("*") if p.suffix in {".py", ".sql", ".js", ".css", ".html"}
    ):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def read(path, limit=65536):
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("artifact exceeds size limit")
    return raw


def artifacts(spec):
    return {
        role: read(path, 8 * 1024 * 1024 if role == "snapshot" else 65536)
        for role, path in spec.files.items()
    }


def tls_check(spec):
    """Verify key, chain, hostname and lifetime using memory BIOs, without sockets."""
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.minimum_version = ssl.TLSVersion.TLSv1_2
    server.load_cert_chain(spec.files["server_cert"], spec.files["server_key"])
    if "client_ca" in spec.files:
        server.load_verify_locations(cafile=spec.files["client_ca"])
        if not server.cert_store_stats()["x509_ca"]:
            raise ValueError("client trust bundle has no CA")
    # Client identity is intentionally not fabricated. Actual remote mTLS needs a separate test.
    client = ssl.create_default_context(cafile=spec.files["server_ca"])
    client.minimum_version = ssl.TLSVersion.TLSv1_2
    si, so, ci, co = (ssl.MemoryBIO() for _ in range(4))
    endpoints = [
        server.wrap_bio(si, so, server_side=True),
        client.wrap_bio(ci, co, server_hostname=urlsplit(spec.public_origin).hostname),
    ]
    done = [False, False]
    for _ in range(32):
        for i, endpoint in enumerate(endpoints):
            if not done[i]:
                try:
                    endpoint.do_handshake()
                    done[i] = True
                except ssl.SSLWantReadError:
                    pass
        for outgoing, incoming in [(so, ci), (co, si)]:
            if outgoing.pending:
                incoming.write(outgoing.read())
        if all(done):
            cert = endpoints[1].getpeercert()
            remaining = ssl.cert_time_to_seconds(cert["notAfter"]) - datetime.now(UTC).timestamp()
            if remaining < spec.minimum_certificate_hours * 3600:
                raise ValueError("certificate renewal required before launch")
            return
    raise ValueError("offline TLS handshake did not complete")


def state_check(spec, snapshot):
    if spec.mode == "NEW":
        if spec.state.exists():
            raise ValueError("NEW requires absent state")
        return
    path = spec.state / "inspection.sqlite"
    marker = spec.state / "restored-inspection-only.json"
    if marker.exists() and json.loads(read(marker)).get("status") != "VERIFIED_INSPECTION_ONLY":
        raise ValueError("incomplete restore")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("state integrity failure")
        if conn.execute("SELECT snapshot FROM binding").fetchall() != [
            (snapshot.model_dump_json(),)
        ]:
            raise ValueError("snapshot binding mismatch")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("broker_view_binding", "workflow_view_binding"):
            if table in tables and conn.execute(f"SELECT payload FROM {table}").fetchall() != [
                ("DISABLED",)
            ]:
                raise ValueError("external view binding is incompatible with inspection profile")


def check(profile):
    # Revalidate model_copy/mutated paths too; callers cannot bypass path restrictions.
    profile = Profile.model_validate(profile.model_dump())
    raw = artifacts(profile)
    if {k: hashlib.sha256(v).hexdigest() for k, v in raw.items()} != profile.hashes:
        raise ValueError("artifact fingerprint mismatch")
    if package_digest() != profile.package_sha256:
        raise ValueError("package fingerprint mismatch")
    snapshot = Snapshot.model_validate_json(raw["snapshot"])
    if snapshot.captured_at > datetime.now(UTC):
        raise ValueError("future snapshot")
    Owner.model_validate_json(raw["owner"])
    tls_check(profile)
    state_check(profile, snapshot)
    # TLS loaders open paths themselves; detect changes across those reads.
    if artifacts(profile) != raw:
        raise ValueError("artifacts changed during preflight")
    return dict(
        version="dashboard-deployment-check/1",
        status="READY_FOR_EXPLICIT_LAUNCH",
        checked_at=datetime.now(UTC).isoformat(),
        mode=profile.mode,
        package_sha256=profile.package_sha256,
        artifacts=profile.hashes,
        execution_enabled=False,
        model_calls_enabled=False,
        alert_delivery_enabled=False,
        target_host_qualified=False,
        full_M5_complete=False,
    )


def seal(spec):
    raw = artifacts(spec)
    profile = Profile(
        **spec.model_dump(),
        hashes={k: hashlib.sha256(v).hexdigest() for k, v in raw.items()},
        package_sha256=package_digest(),
    )
    check(profile)
    return profile


def launch(profile):
    check(profile)
    disabled = dict.fromkeys(
        (
            "telemetry",
            "telemetry_run",
            "session_file",
            "study_journal_config",
            "alert_config",
            "model_key_file",
            "model_budget_file",
            "broker_config",
            "broker_env_file",
            "broker_receipt_config",
            "simulator_env",
            "simulator_run",
            "simulator_market",
            "operator_token_file",
        )
    )
    args = argparse.Namespace(
        **disabled,
        state=profile.state,
        port=profile.port,
        bind=profile.bind,
        public_origin=profile.public_origin,
        tls_cert=profile.files["server_cert"],
        tls_key=profile.files["server_key"],
        tls_client_ca=profile.files.get("client_ca"),
        owner_file=profile.files["owner"],
        enable_alert_delivery=False,
        monitor_interval=5,
    )
    if profile.mode == "NEW":
        profile.state.mkdir(parents=True, exist_ok=False)
    with status_lock(profile.state / "dashboard.lock"):
        raw = artifacts(profile)
        if {k: hashlib.sha256(v).hexdigest() for k, v in raw.items()} != profile.hashes:
            raise ValueError("artifacts changed before launch")
        if package_digest() != profile.package_sha256:
            raise ValueError("package changed before launch")
        snapshot = Snapshot.model_validate_json(raw["snapshot"])
        if profile.mode == "RESUME":
            state_check(profile, snapshot)
        serve(snapshot, args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("seal", "check", "run"))
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        raw = read(args.input)
        if args.operation == "run":
            if args.output:
                raise ValueError("run has no report output")
            launch(Profile.model_validate_json(raw))
            return
        if not args.output:
            raise ValueError("output required")
        result = (
            seal(Spec.model_validate_json(raw)).model_dump(mode="json")
            if args.operation == "seal"
            else check(Profile.model_validate_json(raw))
        )
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
    except (ValueError, OSError, sqlite3.Error):
        # Parsing errors may contain credential bytes or private paths. Never echo them.
        parser.exit(1, "Deployment preflight/launch failed; inspect private inputs locally.\n")


if __name__ == "__main__":
    main()
