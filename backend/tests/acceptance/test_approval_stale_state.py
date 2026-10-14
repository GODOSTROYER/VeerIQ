"""Acceptance: An approval does not immunize against later state changes."""


def test_approval_stale_state(check_runner):
    check_runner("approval_stale_state")
