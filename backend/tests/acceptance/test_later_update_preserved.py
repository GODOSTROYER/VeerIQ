"""Acceptance: A legitimate later update survives the repair."""


def test_later_update_preserved(check_runner):
    check_runner("later_update_preserved")
