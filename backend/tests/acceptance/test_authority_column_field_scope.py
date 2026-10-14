"""Acceptance: Authority columns are outside the grant's field scope."""


def test_authority_column_field_scope(check_runner):
    check_runner("authority_column_field_scope")
