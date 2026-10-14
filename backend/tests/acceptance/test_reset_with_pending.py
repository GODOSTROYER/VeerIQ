"""Acceptance: A fixture reset invalidates pending manifests and approvals."""


def test_reset_with_pending(check_runner):
    check_runner("reset_with_pending")
