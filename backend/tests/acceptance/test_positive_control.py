"""Acceptance: Positive control: the privileged handler really works."""


def test_positive_control(check_runner):
    check_runner("positive_control")
