"""Acceptance: Reusing an idempotency key for a different payload is refused."""


def test_key_reuse_different_payload(check_runner):
    check_runner("key_reuse_different_payload")
