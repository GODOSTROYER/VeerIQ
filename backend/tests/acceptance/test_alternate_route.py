"""Acceptance: No second route to the data: MCP and HTTP both go through the dispatcher."""


def test_alternate_route(check_runner):
    check_runner("alternate_route")
