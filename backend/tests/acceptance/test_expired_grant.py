"""Acceptance: An expired grant cannot act."""


def test_expired_grant(check_runner):
    check_runner("expired_grant")
