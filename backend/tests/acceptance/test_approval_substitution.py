"""Acceptance: An approval cannot be reused for a different payload."""


def test_approval_substitution(check_runner):
    check_runner("approval_substitution")
