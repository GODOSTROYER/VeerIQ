"""Acceptance: A rejected approval changes nothing."""


def test_approval_reject(check_runner):
    check_runner("approval_reject")
