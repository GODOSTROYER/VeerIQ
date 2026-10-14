"""Acceptance fixtures: a runner that executes one verification check against the test DB."""

from __future__ import annotations

import json
from typing import Callable

import pytest


@pytest.fixture
def check_runner(test_db: str) -> Callable[[str], dict]:
    from rewindsafe.verification import checks

    def run(check_id: str) -> dict:
        result = checks.run_check(check_id)
        if not result["passed"]:
            print(json.dumps(result, indent=2, default=str))
        assert result.get("error") is None, f"{check_id} crashed: {result.get('error')}"
        assert result["passed"], f"{check_id} failed; evidence above"
        return result

    return run
