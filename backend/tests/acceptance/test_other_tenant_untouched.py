"""Acceptance: The other tenant is untouched."""


def test_other_tenant_untouched(check_runner):
    check_runner("other_tenant_untouched")
