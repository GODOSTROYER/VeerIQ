"""PostgreSQL access: sync psycopg 3 + ``psycopg_pool`` (architecture.md 4.1).

Async psycopg is intentionally not used (it breaks on Windows' Proactor loop).
All rows come back as dicts. JSONB columns are returned as Python objects.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from rewindsafe.config import BACKEND_DIR, get_settings

log = logging.getLogger(__name__)

MIGRATIONS_DIR = BACKEND_DIR / "migrations"
_MIGRATION_LOCK_KEY = 7_262_025_001  # pg_advisory_lock key serializing migration runs

# Objects 001_schema.sql creates that later migrations and runtime code depend on. A database with
# no migration record is adopted as 001 only when every one of them is present.
_V1_SCHEMAS = ("app", "authority", "recovery", "runtime")
_V1_ROLES = ("rs_executor", "rs_authority_admin")
_V1_TABLES = (
    "app.tenants", "app.customers", "app.orders", "app.incidents",
    "authority.tenant_epochs", "authority.tombstones", "authority.access_grants", "authority.record_holds",
    "recovery.snapshots", "recovery.annotations",
    "runtime.fixture_state", "runtime.task_grants", "runtime.runs", "runtime.proposals", "runtime.decisions",
    "runtime.manifests", "runtime.approvals", "runtime.receipts", "runtime.events", "runtime.mutator_entries",
    "runtime.telemetry_outbox", "runtime.verification_runs",
)
_V1_TRIGGERS = ("recovery.snapshots.snapshots_immutable", "runtime.manifests.manifests_immutable")

_lock = threading.Lock()
_pool: ConnectionPool | None = None
_dsn_override: str | None = None


def current_dsn() -> str:
    """The DSN the pool is (or would be) connected to."""
    return _dsn_override or get_settings().database_url


def dsn_override() -> str | None:
    """The test DSN override currently in force (``None`` when using DATABASE_URL)."""
    return _dsn_override


def get_pool() -> ConnectionPool:
    """Lazy process-wide pool built from settings (or the test override)."""
    global _pool
    with _lock:
        if _pool is None:
            pool = ConnectionPool(
                current_dsn(),
                min_size=1,
                max_size=12,
                kwargs={"row_factory": dict_row},
                open=False,
                name="rewindsafe",
            )
            pool.open(wait=True, timeout=15)
            _pool = pool
        return _pool


def reset_pool_for_tests(dsn: str | None) -> None:
    """Close the current pool and point the next ``get_pool()`` at ``dsn``.

    ``None`` clears the override (back to the configured DATABASE_URL).
    """
    global _pool, _dsn_override
    with _lock:
        if _pool is not None:
            try:
                _pool.close()
            except Exception:  # pragma: no cover - best effort
                log.exception("closing pool failed")
            _pool = None
        _dsn_override = dsn


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    """Pooled connection (dict rows). Commits on clean exit, rolls back on error."""
    with get_pool().connection() as conn:
        yield conn


@contextmanager
def transaction() -> Iterator[psycopg.Connection]:
    """Pooled connection wrapped in an explicit transaction block."""
    with get_pool().connection() as conn, conn.transaction():
        yield conn


@contextmanager
def autocommit_connection() -> Iterator[psycopg.Connection]:
    """Separate short-lived autocommit connection (not from the pool).

    Used for events, mutator entries and outbox rows so they are durable and
    visible immediately and survive a rolled-back business transaction.
    """
    conn = psycopg.connect(current_dsn(), autocommit=True, row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


def _v1_inventory(conn: psycopg.Connection) -> tuple[bool, list[str]]:
    """``(present, missing)``: whether any table 001_schema.sql creates exists, and which v1 objects are absent.

    Roles are cluster-wide, so they count toward ``missing`` but never toward ``present``: a fresh
    database in a cluster that already has the roles is still a fresh database.
    """
    in_schemas = list(_V1_SCHEMAS)
    schemas = {r["nspname"] for r in conn.execute(
        "SELECT nspname FROM pg_namespace WHERE nspname = ANY(%s)", (in_schemas,)).fetchall()}
    tables = {r["name"] for r in conn.execute(
        "SELECT n.nspname || '.' || c.relname AS name FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relkind IN ('r', 'p') AND n.nspname = ANY(%s)", (in_schemas,)).fetchall()}
    roles = {r["rolname"] for r in conn.execute(
        "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", (list(_V1_ROLES),)).fetchall()}
    triggers = {r["name"] for r in conn.execute(
        "SELECT n.nspname || '.' || c.relname || '.' || t.tgname AS name FROM pg_trigger t "
        "JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE NOT t.tgisinternal").fetchall()}
    missing = (
        [f"schema {s}" for s in _V1_SCHEMAS if s not in schemas]
        + [f"role {r}" for r in _V1_ROLES if r not in roles]
        + [f"table {t}" for t in _V1_TABLES if t not in tables]
        + [f"trigger {t}" for t in _V1_TRIGGERS if t not in triggers]
    )
    return any(t in tables for t in _V1_TABLES), missing


def apply_migrations(dsn: str | None = None) -> list[str]:
    """Apply ``backend/migrations/*.sql`` once each; returns the newly applied filenames.

    Applied files are tracked in ``runtime.schema_migrations``. A database that already
    contains the complete v1 schema but has no tracking rows (created by hand) adopts
    ``001_schema.sql`` as applied. A partial v1 schema is refused with an error naming the
    missing objects. A database with no v1 tables is migrated from scratch.
    """
    target = dsn or current_dsn()
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    applied_now: list[str] = []
    with psycopg.connect(target, autocommit=True, row_factory=dict_row) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (_MIGRATION_LOCK_KEY,))
        try:
            conn.execute("CREATE SCHEMA IF NOT EXISTS runtime")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS runtime.schema_migrations ("
                " filename text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now(),"
                " adopted boolean NOT NULL DEFAULT false)"
            )
            done = {r["filename"] for r in conn.execute("SELECT filename FROM runtime.schema_migrations")}
            for path in files:
                if path.name in done:
                    continue
                if path.name == "001_schema.sql" and not done:
                    present, missing = _v1_inventory(conn)
                    if present and missing:
                        raise RuntimeError(
                            "refusing to adopt a partial v1 schema as 001_schema.sql; missing: " + ", ".join(missing)
                        )
                    if present:
                        conn.execute(
                            "INSERT INTO runtime.schema_migrations (filename, adopted) VALUES (%s, true)",
                            (path.name,),
                        )
                        log.warning("adopted pre-existing schema as %s", path.name)
                        continue
                sql = path.read_text(encoding="utf-8")
                with conn.transaction():
                    conn.execute(sql)  # no params: multi-statement script, '%' is literal
                    conn.execute("INSERT INTO runtime.schema_migrations (filename) VALUES (%s)", (path.name,))
                applied_now.append(path.name)
                log.info("applied migration %s", path.name)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_LOCK_KEY,))
    return applied_now


def ensure_database_ready() -> None:
    """Migrate, then seed the synthetic fixture if ``runtime.fixture_state`` is empty."""
    apply_migrations()
    with connection() as conn:
        seeded = conn.execute("SELECT 1 FROM runtime.fixture_state WHERE id = 1").fetchone()
    if seeded:
        return
    # Imported lazily: the workflow package depends on the runtime package, not vice versa.
    from rewindsafe.workflows.rewindsafe.fixture import reset_fixture

    with transaction() as conn:
        reset_fixture(conn, actor="system")


def migrations_present() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))
