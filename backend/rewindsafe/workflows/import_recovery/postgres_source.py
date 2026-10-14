"""Bounded read-only access to an operator-selected PostgreSQL source."""
from __future__ import annotations

import ipaddress
import socket
import unicodedata
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from rewindsafe.runtime.canonical import canonical_json
from rewindsafe.workflows.import_recovery.data import ImportInputError, MAX_FILE_BYTES, MAX_METADATA_COLUMNS, MAX_ROWS

_ALLOWED_DSN_KEYS = {"host", "port", "dbname", "user", "password", "sslmode", "application_name"}
_DENIED_SCHEMAS = {"pg_catalog", "information_schema", "runtime", "authority", "recovery"}


def _allowlisted_host(dsn: str, allowed_hosts: str) -> tuple[dict[str, str], str]:
    allowed = {item.strip().lower().rstrip(".") for item in allowed_hosts.split(",") if item.strip()}
    if not allowed:
        raise ImportInputError("PostgreSQL import is disabled until allowed source hosts are configured.")
    try:
        params = conninfo_to_dict(dsn)
    except Exception as exc:
        raise ImportInputError("PostgreSQL connection settings are invalid.") from exc
    if set(params) - _ALLOWED_DSN_KEYS:
        raise ImportInputError("PostgreSQL connection settings contain unsupported options.")
    host = str(params.get("host", "")).strip().lower().rstrip(".")
    if not host or "," in host or host not in allowed:
        raise ImportInputError("PostgreSQL source host is not on the configured allowlist.")
    if params.get("sslmode", "verify-full") != "verify-full":
        raise ImportInputError("PostgreSQL source connections must use sslmode=verify-full.")
    if params.get("hostaddr"):
        raise ImportInputError("Do not set hostaddr; the service pins it after host validation.")
    port_text = str(params.get("port", "5432"))
    try:
        port = int(port_text)
    except ValueError as exc:
        raise ImportInputError("PostgreSQL source port is invalid.") from exc
    if not 1 <= port <= 65535:
        raise ImportInputError("PostgreSQL source port is invalid.")
    try:
        resolved = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ImportInputError("PostgreSQL source host could not be resolved.") from exc
    addresses = []
    for entry in resolved:
        address = entry[4][0]
        try:
            canonical = str(ipaddress.ip_address(address))
        except ValueError:
            continue
        if canonical not in addresses:
            addresses.append(canonical)
    if not addresses:
        raise ImportInputError("PostgreSQL source host has no usable address.")
    pinned = dict(params)
    pinned.pop("sslmode", None)
    pinned["host"] = host
    pinned["hostaddr"] = addresses[0]
    pinned["port"] = str(port)
    pinned["sslmode"] = "verify-full"
    pinned["connect_timeout"] = "5"
    pinned["application_name"] = "rewindsafe-import-readonly"
    pinned["options"] = "-c default_transaction_read_only=on -c statement_timeout=5000 -c idle_in_transaction_session_timeout=10000"
    return params, make_conninfo(**pinned)


@contextmanager
def readonly_connection(dsn: str, allowed_hosts: str) -> Iterator[Any]:
    """Open a TLS-verified connection pinned to a prevalidated allowlisted host IP."""
    _, pinned_dsn = _allowlisted_host(dsn, allowed_hosts)
    conn = psycopg.connect(pinned_dsn, connect_timeout=5, row_factory=dict_row)
    try:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute("SET LOCAL statement_timeout = '5000ms'")
            conn.execute("SET LOCAL idle_in_transaction_session_timeout = '10000ms'")
            yield conn
    finally:
        conn.close()


def _valid_identifier(name: Any) -> bool:
    return (
        isinstance(name, str) and bool(name) and len(name.encode("utf-8")) <= 63
        and not any(unicodedata.category(ch) == "Cc" or ch == "\x00" for ch in name)
    )


def read_source_table(conn: Any, schema: str, table: str, columns: list[str] | None = None) -> list[dict[str, Any]]:
    """Read one bounded base table, all columns by default, using quoted identifiers."""
    if not _valid_identifier(schema) or not _valid_identifier(table) or (columns is not None and (not columns or any(not _valid_identifier(c) for c in columns))):
        raise ImportInputError("Source schema, table, and column names must be valid PostgreSQL identifiers.")
    if schema in _DENIED_SCHEMAS:
        raise ImportInputError("System and RewindSafe authority schemas cannot be source imports.")
    exists = conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s AND table_type='BASE TABLE'",
        (schema, table),
    ).fetchone()
    if not exists:
        raise ImportInputError("Source must be an existing base table in an allowed schema.")
    if columns is None:
        columns = [row["column_name"] for row in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
            (schema, table),
        ).fetchall()]
        if not columns or len(columns) > MAX_METADATA_COLUMNS:
            raise ImportInputError(f"Source tables must have between one and {MAX_METADATA_COLUMNS} columns.")
    if len(columns) != len(set(columns)):
        raise ImportInputError("Source columns must be unique.")
    selected = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
    relation = sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(table))
    size_query = sql.SQL("SELECT coalesce(sum(pg_column_size(src)), 0) AS total_bytes FROM (SELECT {} FROM {} LIMIT %s) AS src").format(selected, relation)
    approximate_bytes = conn.execute(size_query, (MAX_ROWS + 1,)).fetchone()["total_bytes"]
    if approximate_bytes > MAX_FILE_BYTES:
        raise ImportInputError("Source table exceeds the 2 MB import limit.")
    statement = sql.SQL("SELECT {} FROM {} LIMIT %s").format(selected, relation)
    rows = conn.execute(statement, (MAX_ROWS + 1,)).fetchall()
    if len(rows) > MAX_ROWS:
        raise ImportInputError(f"Source table exceeded the {MAX_ROWS} row import limit.")
    values = [dict(row) for row in rows]
    if any(isinstance(value, str) and len(value) > 10_000 for row in values for value in row.values()):
        raise ImportInputError("Source table contains a text cell exceeding 10,000 characters.")
    if len(canonical_json(values).encode("utf-8")) > MAX_FILE_BYTES:
        raise ImportInputError("Source table exceeds the 2 MB import limit.")
    return values
