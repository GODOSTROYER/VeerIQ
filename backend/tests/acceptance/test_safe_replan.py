"""Acceptance: After blocked actions the agent replans and still completes the repair."""


def test_safe_replan(check_runner):
    check_runner("safe_replan")
