"""Acceptance: Enforcement outage fails closed and is not a policy denial."""


def test_enforcement_unavailable(check_runner):
    check_runner("enforcement_unavailable")
