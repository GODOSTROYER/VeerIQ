"""Acceptance: A failed audit report is recorded but never undoes the receipt."""


def test_audit_delivery_failure(check_runner):
    check_runner("audit_delivery_failure")
