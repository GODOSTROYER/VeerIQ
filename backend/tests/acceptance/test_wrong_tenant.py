"""Acceptance: Another tenant's order cannot be added to the batch."""


def test_wrong_tenant(check_runner):
    check_runner("wrong_tenant")
