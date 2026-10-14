"""Acceptance: A wider authority cannot be re-minted from a narrower grant."""


def test_remint_wider(check_runner):
    check_runner("remint_wider")
