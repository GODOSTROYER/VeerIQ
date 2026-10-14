"""RewindSafe agent: run lifecycle, planners, prompts and the boundary harness.

Public API (``from rewindsafe.agent import start_run, ...``) is resolved lazily so that
importing the pure submodules (``state``, ``planners``, ``boundary``) never pulls in the
database layer.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "active_run_for_grant",
    "cancel_all_active",
    "cancel_run",
    "create_run_row",
    "get_run",
    "list_runs",
    "recover_orphaned_runs",
    "start_run",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from rewindsafe.agent import loop

        return getattr(loop, name)
    raise AttributeError(f"module 'rewindsafe.agent' has no attribute {name!r}")
