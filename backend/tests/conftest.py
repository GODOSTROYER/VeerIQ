"""Pytest plumbing for the RewindSafe acceptance suite.

``test_db`` is session-scoped and NOT autouse: unit tests never touch it. It
creates a unique database (``rs_test_<pid>_<rand>``), applies the migrations,
points the connection pool at it, forces the offline (simulated) enforcement
gateway, seeds the fixture, and drops the database at session end. It never
touches the ``rewindsafe`` database.
"""

from __future__ import annotations

import os
import secrets
from typing import Iterator

import psycopg
import pytest

ADMIN_DSN = os.environ.get(
    "REWINDSAFE_TEST_ADMIN_DSN", "postgresql://rewindsafe:rewindsafe@127.0.0.1:5433/postgres"
)


def _with_dbname(dsn: str, dbname: str) -> str:
    base, _, _ = dsn.rpartition("/")
    return f"{base}/{dbname}"


@pytest.fixture(scope="session")
def test_db() -> Iterator[str]:
    from rewindsafe.runtime import armoriq_gateway, db

    name = f"rs_test_{os.getpid()}_{secrets.token_hex(3)}"
    dsn = _with_dbname(ADMIN_DSN, name)
    saved_env = {k: os.environ.get(k) for k in ("DATABASE_URL", "REWINDSAFE_ENFORCEMENT")}
    with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        os.environ["DATABASE_URL"] = dsn
        os.environ["REWINDSAFE_ENFORCEMENT"] = "offline"
        db.apply_migrations(dsn)
        db.reset_pool_for_tests(dsn)
        armoriq_gateway.set_gateway_for_tests(armoriq_gateway.OfflineSimulatedGateway())
        from rewindsafe.workflows.rewindsafe import fixture

        with db.transaction() as conn:
            fixture.reset_fixture(conn, actor="tests")
        yield dsn
    finally:
        try:
            armoriq_gateway.set_gateway_for_tests(None)
        except Exception:
            pass
        db.reset_pool_for_tests(None)
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def fresh(test_db: str) -> int:
    """Reset the disposable fixture (new generation) before a test."""
    from rewindsafe.verification import checks

    return checks.reset_fixture_state("tests")
