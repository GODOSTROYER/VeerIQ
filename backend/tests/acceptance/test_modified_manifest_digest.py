"""Acceptance: A tampered manifest digest is refused."""


def test_modified_manifest_digest(check_runner):
    check_runner("modified_manifest_digest")
