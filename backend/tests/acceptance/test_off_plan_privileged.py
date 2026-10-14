"""Acceptance: Off-plan privileged action never reaches its handler."""


def test_off_plan_privileged(check_runner):
    check_runner("off_plan_privileged")
