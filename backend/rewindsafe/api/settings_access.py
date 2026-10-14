"""Single access point for application settings (tolerates ``get_settings()`` or a module singleton)."""

from __future__ import annotations

from typing import Any

from rewindsafe import config


def get_settings() -> Any:
    fn = getattr(config, "get_settings", None)
    if callable(fn):
        return fn()
    singleton = getattr(config, "settings", None)
    if singleton is not None:
        return singleton
    return config.Settings()
