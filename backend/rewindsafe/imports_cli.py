"""Import and run generic CSV/JSON inventory recovery through RewindSafe's runtime.

Examples:
  python -m rewindsafe.imports_cli samples
  python -m rewindsafe.imports_cli run-sample warehouse_bins --identity maya
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from rewindsafe.api.routes_imports import _load_sample, _persist_import, GrantBody, ImportBody, SampleImportBody, create_import_grant
from rewindsafe.runtime import db, grants, identities
from rewindsafe.runtime.canonical import digest

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def _bootstrap() -> None:
    db.ensure_database_ready()
    import rewindsafe.workflows.rewindsafe  # noqa: F401
    import rewindsafe.workflows.import_recovery as import_recovery
    import_recovery.register()


def _sample_catalog() -> list[dict[str, Any]]:
    sample_dir = Path(__file__).resolve().parents[1] / "samples" / "import_recovery"
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(sample_dir.glob("*/pack.json"))]


def cmd_samples(_: argparse.Namespace) -> int:
    for pack in _sample_catalog():
        print(f"{pack['sample_id']}: {pack['display_name']} ({pack['current_file']}; approved snapshot {pack['snapshot_id']})")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    from rewindsafe.api.routes_imports import import_sample

    _bootstrap()
    identity = identities.get_identity(args.identity)
    if identity is None or identity.role != "operator":
        print("Choose a configured operator identity (maya or sam).", file=sys.stderr)
        return 2
    result = import_sample(args.sample_id, SampleImportBody(), identity)
    print(json.dumps({k: result[k] for k in ("dataset_id", "snapshot_id", "approved_snapshot_digest", "record_count", "tenant_ids")}, indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from rewindsafe.api.routes_imports import import_sample
    from rewindsafe.agent.loop import start_run
    from rewindsafe.cli import stream_run, print_summary

    _bootstrap()
    identity = identities.get_identity(args.identity)
    if identity is None or identity.role != "operator":
        print("Choose a configured operator identity (maya or sam).", file=sys.stderr)
        return 2
    result = import_sample(args.sample_id, SampleImportBody(), identity)
    grant = create_import_grant(GrantBody(dataset_id=result["dataset_id"],
        record_ids=args.record_id or [r["record_id"] for r in result.get("comparisons", []) if r["tenant_id"] == identity.tenant_id],
        repairable_columns=args.field or ["quantity", "location"]), identity)
    grant_id = grant["grant_id"]
    active = grants.authorize(grant_id, identity)
    run = start_run(grant_id, identity, planner="scripted")
    print(f"Started scripted import recovery run {run.run_id} for {active.tenant_id}.")
    finished = stream_run(run.run_id, decision=None, timeout_s=args.timeout)
    final_run, checks = print_summary(run.run_id, active.tenant_id)
    if not finished or final_run is None:
        return 3
    return 0 if final_run.status.value in {"succeeded", "partially_succeeded"} and all(c.status.value != "violated" for c in checks) else 1


def _read_source_table(conn: Any, schema: str, table: str, columns: list[str]) -> list[dict[str, Any]]:
    """Read one bounded base table in a read-only transaction, with quoted identifiers only."""
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row

    del dict_row  # the connection is already configured with dict rows
    if not _IDENT.fullmatch(schema) or not _IDENT.fullmatch(table) or any(not _IDENT.fullmatch(c) for c in columns):
        raise ValueError("Source schema, table, and column names must be simple identifiers.")
    if schema in {"pg_catalog", "information_schema", "runtime", "authority", "recovery"}:
        raise ValueError("System and RewindSafe authority schemas cannot be source imports.")
    exists = conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s AND table_type='BASE TABLE'",
        (schema, table),
    ).fetchone()
    if not exists:
        raise ValueError("Source must be an existing base table in a non-system schema.")
    statement = sql.SQL("SELECT {} FROM {}.{} LIMIT %s").format(
        sql.SQL(", ").join(sql.Identifier(c) for c in columns), sql.Identifier(schema), sql.Identifier(table)
    )
    rows = conn.execute(statement, (501,)).fetchall()
    if len(rows) > 500:
        raise ValueError("Source table exceeded the 500 row import limit.")
    return [dict(r) for r in rows]


def cmd_import_postgres(args: argparse.Namespace) -> int:
    """Read three selected tables using an environment-held source DSN; no source writes are issued."""
    import psycopg
    from psycopg.rows import dict_row

    from rewindsafe.workflows.import_recovery.data import ImportInputError, import_dataset, validate_mapping
    from rewindsafe.workflows.import_recovery.postgres_source import read_source_table

    _bootstrap()
    identity = identities.get_identity(args.identity)
    if identity is None or identity.role != "operator":
        print("Choose a configured operator identity (maya or sam).", file=sys.stderr)
        return 2
    env_name = args.dsn_env
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", env_name):
        print("The DSN environment variable name is invalid.", file=sys.stderr)
        return 2
    source_dsn = os.environ.get(env_name)
    if not source_dsn:
        print(f"Set {env_name} in the local shell before importing.", file=sys.stderr)
        return 2
    source_map = dict(part.split("=", 1) for part in args.map)
    mapping = {dest: source for source, dest in source_map.items()}
    pk_source, tenant_source = args.primary_key, args.tenant_column
    try:
        with psycopg.connect(source_dsn, connect_timeout=5, row_factory=dict_row,
                             options="-c default_transaction_read_only=on") as conn:
            with conn.transaction():
                conn.execute("SET TRANSACTION READ ONLY")
                conn.execute("SET LOCAL statement_timeout = '5000ms'")
                conn.execute("SET LOCAL idle_in_transaction_session_timeout = '10000ms'")
                if conn.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"] != "on":
                    raise ValueError("Source connection did not enter read-only mode.")
                current = read_source_table(conn, args.current_schema, args.current_table)
                snapshot = read_source_table(conn, args.snapshot_schema, args.snapshot_table)
                auth_columns = sorted({pk_source, tenant_source, *args.authority_column})
                authority = read_source_table(conn, args.authority_schema, args.authority_table, auth_columns)
        type_map = dict(part.split("=", 1) for part in args.field_type)
        authority_map = dict(part.split("=", 1) for part in args.authority_map)
        normalized, approved, checked_mapping, snap_digest, authority_rows, repairable_types = validate_mapping(
            current, snapshot, authority, primary_key=pk_source, tenant_column=tenant_source,
            repairable_columns=args.repairable_field, authority_columns=args.authority_column,
            authority_mapping=authority_map or None,
            column_mapping=mapping, repairable_types=type_map or None, approved_snapshot_digest=args.approved_snapshot_digest,
        )
        result = import_dataset(display_name=args.name, current_rows=normalized, authority_rows=approved,
            authority_records=authority_rows, source_snapshot_rows=snapshot, mapping=checked_mapping, repairable_types=repairable_types,
            authority_mapping=authority_map or None, snapshot_digest=snap_digest, created_by=identity.identity_id, snapshot_id=args.snapshot_id)
        print(json.dumps({"dataset_id": result["dataset_id"], "snapshot_id": result["snapshot_id"],
            "approved_snapshot_digest": result["snapshot_digest"], "record_count": result["record_count"]}, indent=2))
        return 0
    except (psycopg.Error, ImportInputError, ValueError, KeyError) as exc:
        # Do not render driver errors; they can contain the source DSN or server details.
        print(f"PostgreSQL source import refused ({type(exc).__name__}).", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rewindsafe.imports_cli")
    sub = parser.add_subparsers(dest="command", required=True)
    samples = sub.add_parser("samples", help="List bundled CSV/JSON recovery packs")
    samples.set_defaults(func=cmd_samples)
    imp = sub.add_parser("import-sample", help="Import one sample pack into the local recovery store")
    imp.add_argument("sample_id")
    imp.add_argument("--identity", default="maya")
    imp.set_defaults(func=cmd_import)
    run = sub.add_parser("run-sample", help="Import, grant, and run a sample through the shared dispatcher")
    run.add_argument("sample_id")
    run.add_argument("--identity", default="maya")
    run.add_argument("--record-id", action="append")
    run.add_argument("--field", action="append")
    run.add_argument("--timeout", type=float, default=60)
    run.set_defaults(func=cmd_run)
    pg = sub.add_parser("import-postgres", help="Read bounded source tables using a read-only transaction")
    pg.add_argument("--dsn-env", default="REWINDSAFE_IMPORT_SOURCE_DSN", help="Environment variable holding the source DSN; credentials are never accepted as CLI arguments")
    pg.add_argument("--identity", default="maya")
    pg.add_argument("--name", required=True)
    pg.add_argument("--snapshot-id", required=True)
    pg.add_argument("--approved-snapshot-digest", required=True)
    pg.add_argument("--current-schema", default="public")
    pg.add_argument("--current-table", required=True)
    pg.add_argument("--snapshot-schema", default="public")
    pg.add_argument("--snapshot-table", required=True)
    pg.add_argument("--authority-schema", default="public")
    pg.add_argument("--authority-table", required=True)
    pg.add_argument("--primary-key", required=True)
    pg.add_argument("--tenant-column", required=True)
    pg.add_argument("--repairable-field", action="append", required=True)
    pg.add_argument("--field-type", action="append", default=[], metavar="FIELD=TYPE", help="Type for selected repairable fields: string, integer, number, or boolean")
    pg.add_argument("--authority-column", action="append", required=True)
    pg.add_argument("--authority-map", action="append", default=[], metavar="FLAG=SOURCE", help="Map one canonical flag to its source column; repeat for all four when aliases are used")
    pg.add_argument("--map", action="append", required=True, metavar="SOURCE=DESTINATION")
    pg.set_defaults(func=cmd_import_postgres)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
