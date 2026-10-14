"""Acceptance: State that changes after preview blocks the commit."""


def test_stale_after_preview(check_runner):
    check_runner("stale_after_preview")
