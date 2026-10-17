"""Helpers for the judge walkthrough: ready-to-paste MCP client setup for an authorized grant."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from rewindsafe.api import auth
from rewindsafe.api.errors import conflict
from rewindsafe.api.deps import load_grant_for
from rewindsafe.contracts import GrantStatus, Identity

router = APIRouter(prefix="/api/judge", tags=["judge"])

#: Stands in for the visitor's own checkout. The server's filesystem path is never returned.
CHECKOUT_PLACEHOLDER = "<path-to-your-VeerIQ-checkout>"
SERVER_NAME = "veeriq-recovery"


@router.get("/mcp-install/{grant_id}")
def mcp_install(grant_id: str, identity: Identity = Depends(auth.current_identity)) -> dict[str, Any]:
    """Setup for running VeerIQ's MCP server from the visitor's OWN checkout, for this grant.

    The stdio server needs the visitor's checkout, Python env and database, so the commands carry a
    placeholder path (never this server's path). Every tool call still goes through the same gates
    as the web app, ArmorIQ included.
    """
    grant = load_grant_for(identity, grant_id)
    if grant.status != GrantStatus.ACTIVE:
        raise conflict(f"Grant is {grant.status.value}; authorize it first.", "grant_not_active")
    backend = f"{CHECKOUT_PLACEHOLDER}/backend"
    args = ["run", "--directory", backend, "python", "-m", "rewindsafe.mcp_server", "--grant", grant_id]
    entry = {"command": "uv", "args": args}
    return {
        "mode": "local-checkout",
        "grant_id": grant_id,
        "server_name": SERVER_NAME,
        "placeholder": CHECKOUT_PLACEHOLDER,
        "setup_steps": [
            "Clone the VeerIQ repo and run `npm run setup` in it (installs the backend and starts its database).",
            f"Replace {CHECKOUT_PLACEHOLDER} below with the path to that checkout.",
            "Run the command in your MCP client. The grant must exist in that checkout's database, so authorize a task there.",
        ],
        "claude_code": f"claude mcp add {SERVER_NAME} -- uv " + " ".join(_quote(a) for a in args),
        "claude_desktop": {"mcpServers": {SERVER_NAME: entry}},
        "local_http": (
            f"cd {CHECKOUT_PLACEHOLDER}/backend && uv run python -m rewindsafe.mcp_server "
            f"--grant {grant_id} --http --port 8765"
        ),
        "tools": [
            "inspect_snapshot",
            "compare_current",
            "prepare_repair_manifest",
            "apply_repair_manifest",
            "get_recovery_receipt",
            "restore_access_grant",
        ],
    }


def _quote(arg: str) -> str:
    return f"'{arg}'" if any(c in arg for c in " '\"$") else arg
