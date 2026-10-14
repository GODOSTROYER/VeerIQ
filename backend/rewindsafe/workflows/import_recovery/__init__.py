"""Import recovery workflow; registered with the existing shared dispatcher."""
from rewindsafe.workflows.import_recovery.adapter import ADAPTER, ImportRecoveryAdapter


def register() -> None:
    """Register on explicit application/CLI startup, not merely when routes import the module."""
    from rewindsafe.runtime.adapter import register_adapter

    register_adapter(ADAPTER)

__all__ = ["ADAPTER", "ImportRecoveryAdapter", "register"]
