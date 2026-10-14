"""Acceptance: Revoked access stays revoked after the repair."""


def test_revoked_access_preserved(check_runner):
    check_runner("revoked_access_preserved")
