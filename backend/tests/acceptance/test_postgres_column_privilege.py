"""Acceptance: PostgreSQL itself refuses authority-column writes."""


def test_postgres_column_privilege(check_runner):
    check_runner("postgres_column_privilege")
