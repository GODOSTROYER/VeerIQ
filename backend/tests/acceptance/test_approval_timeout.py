"""Acceptance: An unanswered approval times out and changes nothing."""


def test_approval_timeout(check_runner):
    check_runner("approval_timeout")
