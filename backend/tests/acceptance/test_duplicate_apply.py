"""Acceptance: A retried apply returns the original receipt without a second write."""


def test_duplicate_apply(check_runner):
    check_runner("duplicate_apply")
