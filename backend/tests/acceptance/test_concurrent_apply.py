"""Acceptance: Two simultaneous applies commit once and never overspend the budget."""


def test_concurrent_apply(check_runner):
    check_runner("concurrent_apply")
