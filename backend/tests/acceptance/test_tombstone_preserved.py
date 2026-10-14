"""Acceptance: Deleted records are never resurrected."""


def test_tombstone_preserved(check_runner):
    check_runner("tombstone_preserved")
