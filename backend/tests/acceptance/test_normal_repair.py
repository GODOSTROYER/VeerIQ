"""Acceptance: Normal repair commits exactly the approved snapshot values."""


def test_normal_repair(check_runner):
    check_runner("normal_repair")
