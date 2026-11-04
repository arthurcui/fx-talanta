import json
import zipfile
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from fx_talanta.clock import FakeClock
from fx_talanta.domain.models import Environment, ExperienceCase, Record
from fx_talanta.domain.offline import Fault
from fx_talanta.gateway.offline import Gateway
from fx_talanta.research.offline import make_intent, market_at, warmup
from fx_talanta.research.records import START, run_demo
from fx_talanta.storage import archive
from fx_talanta.storage.bootstrap import bootstrap
from fx_talanta.storage.config import fixture_account
from fx_talanta.storage.offline import WriterBusy
from fx_talanta.storage.repository import Repository

pytestmark = pytest.mark.integration


@pytest.fixture
def destination(settings):
    value = replace(settings, namespace="fx_restore_" + uuid4().hex[:12])
    bootstrap(value)
    return value


@pytest.fixture(scope="module")
def snapshot(settings, tmp_path_factory):
    source = replace(settings, namespace="fx_source_" + uuid4().hex[:12])
    bootstrap(source)
    account = fixture_account(Environment.PAPER)
    paper = Repository(source.runtime_dsn(Environment.PAPER), account)
    run_demo(
        paper, uuid4()
    )  # Includes decisions, incidents, lessons, artifacts, and promotion evidence.
    live = Repository(source.runtime_dsn(Environment.LIVE), fixture_account(Environment.LIVE))
    live.append(
        Record(
            account=live.account,
            recorded_at=START,
            correlation_id=uuid4(),
            body=ExperienceCase(
                operational_result="UNKNOWN",
                policy_compliance="UNKNOWN",
                economic_outcome="UNKNOWN",
                summary="Disabled LIVE history",
            ),
        )
    )
    clock, run_id = FakeClock(START), uuid4()
    gateway = Gateway(source.runtime_dsn(Environment.PAPER), account, run_id, clock)
    try:
        warmup(gateway, clock)
        intent = make_intent(gateway)
        gateway.broker.next_fault = Fault(kind="LOST_RESPONSE")
        assert gateway.submit(intent, market_at(clock.now())).state == "OUTCOME_UNKNOWN"
        book, broker = gateway.book, gateway.broker.book
    finally:
        gateway.close()
    halt_clock, halt_id = FakeClock(START), uuid4()
    halted = Gateway(source.runtime_dsn(Environment.PAPER), account, halt_id, halt_clock)
    try:
        warmup(halted, halt_clock)
        halted.submit(make_intent(halted, exit_seconds=3600), market_at(halt_clock.now()))
        halt_clock.advance(timedelta(seconds=1))
        halted.reconcile(market_at(halt_clock.now(), eur_bid="1.0200", eur_ask="1.0202"))
        assert halted.book.losses.hard_halt
        losses = halted.book.losses
    finally:
        halted.close()
    path = tmp_path_factory.mktemp("archive") / "history.fxbackup"
    archive.export_archive(source, path)
    return source, path, run_id, clock, book, broker, halt_id, halt_clock, losses


def test_restore_retains_histories_unknown_reservations_and_loss_halt(snapshot, destination):
    source, path, run_id, clock, book, broker, halt_id, halt_clock, losses = snapshot
    result = archive.restore_archive(destination, path)
    assert result["execution_blocked"]
    archive.restore_archive(destination, path)  # Safe idempotent resume before release.
    for environment in Environment:
        before = Repository(source.runtime_dsn(environment), fixture_account(environment))
        after = Repository(destination.runtime_dsn(environment), fixture_account(environment))
        assert after.history() == before.history()
        # SQL enforcement also protects clients that bypass the Gateway class.
        record = before.history()[0].model_copy(update={"record_id": uuid4(), "supersedes": None})
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            after.append(record)
    with pytest.raises(ValueError, match="restore is blocked"):
        Gateway(destination.runtime_dsn(Environment.PAPER), book.account, run_id, clock)
    with pytest.raises(ValueError, match="explicitly"):
        archive.release_restore(destination, path)
    assert archive.release_restore(destination, path, source_retired=True)["live_enabled"] is False
    recovered = Gateway(destination.runtime_dsn(Environment.PAPER), book.account, run_id, clock)
    try:
        assert recovered.book.state == "STARTUP_RECONCILE"
        assert recovered.book.entries == book.entries
        assert recovered.book.losses == book.losses
        assert recovered.broker.book == broker
        recovered.reconcile(market_at(clock.now()))
        assert recovered.entry(book.entries[0].intent.intent_id).state == "PROTECTED"
        assert recovered.broker.book.calls.count(book.entries[0].intent.intent_id) == 1
    finally:
        recovered.close()
    halted = Gateway(destination.runtime_dsn(Environment.PAPER), book.account, halt_id, halt_clock)
    try:
        assert halted.book.losses == losses
        halted.reconcile(market_at(halt_clock.now()))
        assert halted.book.state == "HARD_HALT"
    finally:
        halted.close()


def rewrite(path, output, change):
    with zipfile.ZipFile(path) as original:
        members = {name: original.read(name) for name in original.namelist()}
    change(members)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as changed:
        for name, content in members.items():
            changed.writestr(name, content)
    return output


def test_corrupt_archive_rejected_before_any_destination_write(snapshot, destination, tmp_path):
    bad = rewrite(
        snapshot[1],
        tmp_path / "corrupt.fxbackup",
        lambda files: files.update({"PAPER/records.jsonl": files["PAPER/records.jsonl"] + b"{}\n"}),
    )
    with pytest.raises(ValueError, match="checksum"):
        archive.restore_archive(destination, bad)
    for environment in Environment:
        with psycopg.connect(destination.admin_dsn(destination.database(environment))) as conn:
            assert archive.marker(conn) is None
            assert conn.execute("SELECT count(*) FROM fx.records").fetchone()[0] == 0


def test_wrong_binding_rejected_before_staging(snapshot, destination, tmp_path):
    def change(files):
        manifest = json.loads(files["manifest.json"])
        manifest["accounts"]["LIVE"]["binding"][0]["identity"]["login"] = "another-account"
        files["manifest.json"] = archive.encode(manifest)

    bad = rewrite(snapshot[1], tmp_path / "wrong.fxbackup", change)
    with pytest.raises(ValueError, match="binding"):
        archive.restore_archive(destination, bad)


def test_schema_mismatch_rejected(snapshot, destination, tmp_path):
    def change(files):
        manifest = json.loads(files["manifest.json"])
        manifest["accounts"]["LIVE"]["migrations"][0][1] = "0" * 64
        files["manifest.json"] = archive.encode(manifest)

    bad = rewrite(snapshot[1], tmp_path / "schema.fxbackup", change)
    with pytest.raises(ValueError, match="schema differs"):
        archive.restore_archive(destination, bad)


def test_existing_history_is_never_overwritten(snapshot):
    source, path = snapshot[:2]
    with pytest.raises(ValueError, match="empty destination"):
        archive.restore_archive(source, path)
    with pytest.raises(FileExistsError):
        archive.export_archive(source, path)


def test_export_refuses_active_writer_and_does_not_publish_partial_file(snapshot, tmp_path):
    source, _, run_id, clock, book = snapshot[:5]
    gateway = Gateway(source.runtime_dsn(Environment.PAPER), book.account, run_id, clock)
    path = tmp_path / "busy.fxbackup"
    try:
        with pytest.raises(WriterBusy):
            archive.export_archive(source, path)
        assert not path.exists()
        assert not list(tmp_path.glob(".fx-export-*"))
    finally:
        gateway.close()


def test_partial_two_account_import_stays_blocked_and_resumes(snapshot, destination, monkeypatch):
    append = archive.append_marker

    def fail_live(conn, manifest, status, source_history=()):
        if conn.info.dbname.endswith("_live") and status == "RESTORED":
            raise RuntimeError("injected interruption")
        return append(conn, manifest, status, source_history)

    monkeypatch.setattr(archive, "append_marker", fail_live)
    with pytest.raises(RuntimeError, match="interruption"):
        archive.restore_archive(destination, snapshot[1])
    with pytest.raises(ValueError, match="both accounts"):
        archive.release_restore(destination, snapshot[1], source_retired=True)
    for environment in Environment:
        with psycopg.connect(destination.admin_dsn(destination.database(environment))) as conn:
            assert archive.marker(conn)[2] != "RELEASED"
    monkeypatch.setattr(archive, "append_marker", append)
    archive.restore_archive(destination, snapshot[1])
    archive.release_restore(destination, snapshot[1], source_retired=True)


def test_derived_evidence_links_must_match_and_failed_import_is_blocked(
    snapshot, destination, tmp_path
):
    def change(files):
        name = "PAPER/record_links.jsonl"
        files[name] = b""
        manifest = json.loads(files["manifest.json"])
        manifest["files"][name] = {"sha256": sha256(b"").hexdigest(), "rows": 0, "bytes": 0}
        files["manifest.json"] = archive.encode(manifest)

    bad = rewrite(snapshot[1], tmp_path / "links.fxbackup", change)
    with pytest.raises(ValueError, match="contents differ"):
        archive.restore_archive(destination, bad)
    with psycopg.connect(destination.admin_dsn(destination.database(Environment.PAPER))) as conn:
        assert archive.marker(conn)[2] == "STAGED"
        assert conn.execute("SELECT count(*) FROM fx.records").fetchone()[0] == 0


def test_restoration_provenance_survives_another_export(snapshot, destination, tmp_path):
    archive.restore_archive(destination, snapshot[1])
    archive.release_restore(destination, snapshot[1], source_retired=True)
    path = tmp_path / "next.fxbackup"
    archive.export_archive(destination, path)
    manifest, _ = archive.read_archive(path)
    for account in manifest["accounts"].values():
        assert [row["status"] for row in account["source_history"]] == [
            "STAGED",
            "RESTORED",
            "RELEASED",
        ]
    with zipfile.ZipFile(path) as bundle:
        raw = b"".join(bundle.read(name) for name in bundle.namelist())
    assert destination.admin_password.encode() not in raw
    assert destination.paper_password.encode() not in raw
    assert destination.live_password.encode() not in raw


def test_runtime_cannot_release_restore_or_modify_restore_audit(snapshot, destination):
    archive.restore_archive(destination, snapshot[1])
    with psycopg.connect(destination.runtime_dsn(Environment.PAPER), autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "INSERT INTO fx.restore_history(archive_id,manifest_hash,status) "
                "VALUES (%s,'x','RELEASED')",
                (uuid4(),),
            )
    with psycopg.connect(destination.admin_dsn(destination.database(Environment.PAPER))) as conn:
        conn.execute(
            sql.SQL("SET LOCAL ROLE {}").format(
                sql.Identifier(destination.namespace + "_paper_owner")
            )
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("TRUNCATE fx.restore_history")


def test_interrupted_release_can_resume_after_released_account_appends(
    snapshot, destination, monkeypatch
):
    archive.restore_archive(destination, snapshot[1])
    append = archive.append_marker

    def fail_live(conn, manifest, status, source_history=()):
        if conn.info.dbname.endswith("_live") and status == "RELEASED":
            raise RuntimeError("release connection interrupted")
        return append(conn, manifest, status, source_history)

    monkeypatch.setattr(archive, "append_marker", fail_live)
    with pytest.raises(RuntimeError, match="interrupted"):
        archive.release_restore(destination, snapshot[1], source_retired=True)
    paper = Repository(
        destination.runtime_dsn(Environment.PAPER), fixture_account(Environment.PAPER)
    )
    record = Record(
        account=paper.account,
        recorded_at=START,
        correlation_id=uuid4(),
        body=ExperienceCase(
            operational_result="UNKNOWN",
            policy_compliance="UNKNOWN",
            economic_outcome="UNKNOWN",
            summary="Post-release audit",
        ),
    )
    paper.append(record)
    monkeypatch.setattr(archive, "append_marker", append)
    archive.release_restore(destination, snapshot[1], source_retired=True)
    assert paper.get(record.record_id) == record
    with psycopg.connect(destination.admin_dsn(destination.database(Environment.LIVE))) as conn:
        assert archive.marker(conn)[2] == "RELEASED"
