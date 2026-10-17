"""Helpers for the judge walkthrough: ready-to-paste MCP client setup for an authorized grant."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from rewindsafe.api import auth
from rewindsafe.api.errors import conflict
from rewindsafe.api.deps import load_grant_for
from rewindsafe.contracts import GrantStatus, Identity

router = APIRouter(prefix="/api/judge", tags=["judge"])

#: The backend project the MCP server runs from (``uv run --directory`` target).
BACKEND_DIR = Path(__file__).resolve().parents[2]
SERVER_NAME = "veeriq-recovery"


@router.get("/mcp-install/{grant_id}")
def mcp_install(grant_id: str, identity: Identity = Depends(auth.current_identity)) -> dict[str, Any]:
    """Claude Code, Cursor and Claude Desktop setup that runs VeerIQ's MCP server (stdio) for this grant.

    The server only starts for an authorized grant no run is using; every tool call then goes through
    the same gates as the web app, ArmorIQ included.
    """
    grant = load_grant_for(identity, grant_id)
    if grant.status != GrantStatus.ACTIVE:
        raise conflict(f"Grant is {grant.status.value}; authorize it first.", "grant_not_active")
    args = ["run", "--directory", str(BACKEND_DIR), "python", "-m", "rewindsafe.mcp_server", "--grant", grant_id]
    entry = {"command": "uv", "args": args}
    cursor_config = base64.b64encode(json.dumps(entry, separators=(",", ":")).encode()).decode()
    return {
        "grant_id": grant_id,
        "server_name": SERVER_NAME,
        "claude_code": f"claude mcp add {SERVER_NAME} -- uv " + " ".join(_quote(a) for a in args),
        "cursor_deeplink": f"cursor://anysphere.cursor-deeplink/mcp/install?name={SERVER_NAME}&config={cursor_config}",
        "claude_desktop": {"mcpServers": {SERVER_NAME: entry}},
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
