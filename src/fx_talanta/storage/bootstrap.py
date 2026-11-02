"""Administrative setup, deliberately separate from runtime repositories."""

from hashlib import sha256
from importlib.resources import files

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from fx_talanta.domain.models import Environment
from fx_talanta.storage.config import Settings, fixture_account


def bootstrap(settings: Settings) -> None:
    """Create only the named fixture databases/roles; preserve existing records."""
    allowed_hosts = {"localhost", "127.0.0.1", "::1"}
    if settings.profile == "docker":
        allowed_hosts.add("postgres")
    if settings.host not in allowed_hosts:
        raise ValueError("bootstrap requires a local or explicit Compose fixture database")
    migrations = sorted(
        (
            p
            for p in files("fx_talanta").joinpath("storage/migrations").iterdir()
            if p.name.endswith(".sql")
        ),
        key=lambda p: p.name,
    )
    for environment in Environment:
        database = settings.database(environment)
        owner, writer = f"{database}_owner", f"{database}_writer"
        password = (
            settings.paper_password if environment == Environment.PAPER else settings.live_password
        )
        with psycopg.connect(settings.admin_dsn(), autocommit=True) as admin:
            # Serialize competing setup invocations, including CREATE DATABASE.
            admin.execute("SELECT pg_advisory_lock(640031)")
            if not admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (owner,)).fetchone():
                admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(owner)))
            if not admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (writer,)).fetchone():
                admin.execute(
                    sql.SQL("CREATE ROLE {} LOGIN NOINHERIT PASSWORD {}").format(
                        sql.Identifier(writer), sql.Literal(password)
                    )
                )
            if not admin.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (database,)
            ).fetchone():
                admin.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        sql.Identifier(database), sql.Identifier(owner)
                    )
                )
            admin.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
            )
            admin.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(database), sql.Identifier(writer)
                )
            )
        with psycopg.connect(settings.admin_dsn(database)) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(640031)")
            conn.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
            conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(owner)))
            for path in migrations:
                version = int(path.name.split("_", 1)[0])
                migration = path.read_text("utf-8")
                checksum = sha256(migration.encode()).hexdigest()
                exists = conn.execute("SELECT to_regclass('fx.schema_migrations')").fetchone()[0]
                row = (
                    conn.execute(
                        "SELECT checksum FROM fx.schema_migrations WHERE version=%s", (version,)
                    ).fetchone()
                    if exists
                    else None
                )
                if row:
                    if row[0] != checksum:
                        raise ValueError("migration checksum mismatch; add a new migration")
                    continue
                conn.execute(migration)
                if version == 1:
                    conn.execute(
                        "INSERT INTO fx.account_binding(identity) VALUES (%s)",
                        (Jsonb(fixture_account(environment).model_dump(mode="json")),),
                    )
                conn.execute(
                    "INSERT INTO fx.schema_migrations(version, checksum) VALUES (%s, %s)",
                    (version, checksum),
                )
            binding = conn.execute("SELECT identity FROM fx.account_binding").fetchone()[0]
            if binding != fixture_account(environment).model_dump(mode="json"):
                raise ValueError("existing database has a different account binding")
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA fx TO {}").format(sql.Identifier(writer)))
            conn.execute(
                sql.SQL(
                    "GRANT SELECT ON fx.account_binding, fx.records, fx.record_links TO {}"
                ).format(sql.Identifier(writer))
            )
            conn.execute(
                sql.SQL(
                    "GRANT INSERT (record_id, kind, recorded_at, supersedes, payload) "
                    "ON fx.records TO {}"
                ).format(sql.Identifier(writer))
            )
            conn.execute(
                sql.SQL("GRANT USAGE ON SEQUENCE fx.records_sequence_seq TO {}").format(
                    sql.Identifier(writer)
                )
            )
            conn.execute(
                sql.SQL("GRANT SELECT, INSERT ON fx.offline_journal TO {}").format(
                    sql.Identifier(writer)
                )
            )
            conn.execute(
                sql.SQL("GRANT SELECT ON fx.restore_history TO {}").format(sql.Identifier(writer))
            )
