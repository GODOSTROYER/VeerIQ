"""RewindSafe order-repair workflow. Importing this package registers the adapter with the runtime."""

from __future__ import annotations

import logging

from rewindsafe.workflows.rewindsafe.adapter import RewindSafeAdapter

log = logging.getLogger(__name__)

ADAPTER = RewindSafeAdapter()

try:
    from rewindsafe.runtime.adapter import register_adapter
except ModuleNotFoundError as exc:  # only the runtime adapter module being absent is tolerated
    if exc.name != "rewindsafe.runtime.adapter":
        raise
    log.warning("rewindsafe.runtime.adapter is not available; RewindSafe adapter was NOT registered")
else:
    register_adapter(ADAPTER)

__all__ = ["ADAPTER", "RewindSafeAdapter"]
