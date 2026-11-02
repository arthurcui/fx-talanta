"""Cross-profile acceptance fixture; never connects to an external broker."""

import argparse
import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fx_talanta.clock import FakeClock
from fx_talanta.domain.models import Environment, ExperienceCase, Record
from fx_talanta.domain.offline import BrokerBook, Fault, GatewayBook
from fx_talanta.fixtures import START, run_demo
from fx_talanta.gateway.offline import Gateway
from fx_talanta.offline_fixtures import make_intent, market_at, warmup
from fx_talanta.storage.archive import export_archive, release_restore, restore_archive
from fx_talanta.storage.bootstrap import bootstrap
from fx_talanta.storage.config import Settings, fixture_account
from fx_talanta.storage.repository import Repository


def checkpoint(gateway, clock):
    return {
        "run_id": str(gateway.run_id),
        "at": clock.now().isoformat(),
        "gateway": gateway.book.model_dump(mode="json"),
        "broker": gateway.broker.book.model_dump(mode="json"),
    }


def save_bundle(settings, directory, checkpoints):
    directory.mkdir(parents=True, exist_ok=True)
    export_archive(settings, directory / "history.fxbackup")
    with (directory / "checkpoints.json").open("x", encoding="utf-8") as stream:
        json.dump(checkpoints, stream, indent=2)


def prepare(settings, directory):
    paper = Repository(settings.runtime_dsn(Environment.PAPER), fixture_account(Environment.PAPER))
    run_demo(paper, uuid4())
    live = Repository(settings.runtime_dsn(Environment.LIVE), fixture_account(Environment.LIVE))
    live.append(
        Record(
            account=live.account,
            recorded_at=START,
            correlation_id=uuid4(),
            body=ExperienceCase(
                operational_result="UNKNOWN",
                policy_compliance="UNKNOWN",
                economic_outcome="UNKNOWN",
                summary="LIVE remains disabled",
            ),
        )
    )
    checkpoints = []
    for scenario in ("unknown", "halt"):
        clock = FakeClock(START)
        gateway = Gateway(settings.runtime_dsn(Environment.PAPER), paper.account, uuid4(), clock)
        try:
            warmup(gateway, clock)
            intent = make_intent(gateway, exit_seconds=3600)
            if scenario == "unknown":
                gateway.broker.next_fault = Fault(kind="LOST_RESPONSE")
            entry = gateway.submit(intent, market_at(clock.now()))
            if scenario == "unknown":
                assert entry.state == "OUTCOME_UNKNOWN" and entry.reservation.volume > 0
            else:
                clock.advance(timedelta(seconds=1))
                gateway.reconcile(market_at(clock.now(), eur_bid="1.0200", eur_ask="1.0202"))
                assert gateway.book.losses.hard_halt
            checkpoints.append(checkpoint(gateway, clock))
        finally:
            gateway.close()
    save_bundle(settings, directory, checkpoints)
    print(json.dumps({"prepared": ["OUTCOME_UNKNOWN", "HARD_HALT"], "accounts": ["PAPER", "LIVE"]}))


def restore(settings, source, output=None):
    archive = source / "history.fxbackup"
    checkpoints = json.loads((source / "checkpoints.json").read_text())
    restore_archive(settings, archive)
    first = checkpoints[0]
    try:
        blocked = Gateway(
            settings.runtime_dsn(Environment.PAPER),
            fixture_account(Environment.PAPER),
            UUID(first["run_id"]),
            FakeClock(datetime.fromisoformat(first["at"])),
        )
    except ValueError as error:
        assert "restore is blocked" in str(error)
    else:
        blocked.close()
        raise AssertionError("restored account was not blocked")
    # prepare() closed every source writer. This isolated acceptance harness can
    # therefore make the explicit handoff attestation without user intervention.
    release_restore(settings, archive, source_retired=True)
    updated = []
    for expected in checkpoints:
        clock = FakeClock(datetime.fromisoformat(expected["at"]))
        book = GatewayBook.model_validate(expected["gateway"])
        gateway = Gateway(
            settings.runtime_dsn(Environment.PAPER), book.account, UUID(expected["run_id"]), clock
        )
        try:
            assert gateway.book == book.model_copy(update={"state": "STARTUP_RECONCILE"})
            assert gateway.broker.book == BrokerBook.model_validate(expected["broker"])
            gateway.reconcile(market_at(clock.now()))
            if book.losses.hard_halt:
                assert gateway.book.state == "HARD_HALT"
            else:
                entry = gateway.entry(book.entries[0].intent.intent_id)
                assert entry.state == "PROTECTED"
                assert gateway.broker.book.calls.count(entry.intent.intent_id) == 1
            updated.append(checkpoint(gateway, clock))
        finally:
            gateway.close()
    if output:
        save_bundle(settings, output, updated)
    print(
        json.dumps(
            {
                "restore_verified": True,
                "unknown_recovered_without_resubmit": True,
                "loss_halt_preserved": True,
                "live_enabled": False,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--namespace", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("directory", type=Path)
    restore_parser = sub.add_parser("restore")
    restore_parser.add_argument("directory", type=Path)
    restore_parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    settings = replace(Settings.load(args.env_file), namespace=args.namespace)
    bootstrap(settings)
    if args.command == "prepare":
        prepare(settings, args.directory)
    else:
        restore(settings, args.directory, args.output)


if __name__ == "__main__":
    main()
