"""VeerIQ's agent, driving the rewindsafe-recovery MCP server.

The planner (scripted re-enactment or a live LLM) runs in this process. Every action it takes is a
JSON-RPC ``tools/call`` to the MCP server, which runs in its own process (stdio) or behind a URL
(streamable HTTP). The server owns the run: it binds the signed ArmorIQ plan from the grant, and each
call goes through ``dispatch(..., source="mcp")`` — schema, grant lifecycle, the ArmorIQ check, grant
scope, domain rules, approvals and the restricted PostgreSQL role. This agent never touches the
database, the dispatcher or ArmorIQ directly; it only sees what the MCP server answers.

    python -m rewindsafe.cli mcp-agent poisoned            # spawn the server over stdio
    python -m rewindsafe.cli mcp-agent poisoned --url http://127.0.0.1:8765/mcp

The server is asked for the full dispatcher outcome (``REWINDSAFE_MCP_RETURN_OUTCOME=1``) so the
same planners that drive in-process runs can read the deciding layer and the manifest digest.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio

from rewindsafe.agent.planners import select_planner
from rewindsafe.agent.state import (
    FAILURE_STATUSES,
    Action,
    AgentState,
    Finish,
    Note,
    ToolCall,
    decisive_decision,
    layer_label,
)
from rewindsafe.contracts import DispatchOutcome, DispatchStatus, ScenarioSpec, TaskGrant

BACKEND_DIR = Path(__file__).resolve().parents[2]
FAILURES = set(FAILURE_STATUSES) | {DispatchStatus.UNAVAILABLE, DispatchStatus.FAILED}


@dataclass
class McpStep:
    tool: str
    args: dict[str, Any]
    status: str
    layer: str
    reason: str
    source: str


@dataclass
class McpAgentResult:
    run_id: str
    tools: list[str]
    steps: list[McpStep] = field(default_factory=list)
    summary: str = ""
    planner: str = ""


def stdio_server(grant_id: str) -> Any:
    """Launch ``python -m rewindsafe.mcp_server --grant <id>`` as a subprocess speaking MCP over stdio."""
    from mcp.client.stdio import StdioServerParameters

    env = dict(os.environ)
    env["REWINDSAFE_MCP_RETURN_OUTCOME"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "rewindsafe.mcp_server", "--grant", grant_id],
        env=env,
        cwd=str(BACKEND_DIR),
    )


def _payload(result: Any) -> dict[str, Any]:
    """The bridge's dict, from structured content or the JSON text block."""
    data = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if isinstance(data, dict) and "outcome" not in data and isinstance(data.get("result"), dict):
        data = data["result"]
    if isinstance(data, dict) and "outcome" in data:
        return data
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except ValueError:
            raise RuntimeError(f"MCP server refused the call: {text[:300]}") from None
        if isinstance(parsed, dict) and "outcome" in parsed:
            return parsed
    raise RuntimeError("The MCP server returned no dispatcher outcome (is REWINDSAFE_MCP_RETURN_OUTCOME set?)")


def describe(outcome: DispatchOutcome) -> tuple[str, str, str]:
    """(layer, reason, decision source) for one outcome, labelled honestly."""
    d = decisive_decision(outcome)
    if outcome.status in FAILURES:
        reason = d.reason if d else str(outcome.observation.get("reason", outcome.status.value))
        return layer_label(d), reason, (d.source.value if d else "")
    allow = next((x for x in outcome.decisions if x.layer.value == "armoriq" and not x.shadow), None)
    return "allowed", "", (allow.source.value if allow else "")


async def run_mcp_agent(
    server: Any,
    grant: TaskGrant,
    scenario: ScenarioSpec,
    adapter: Any,
    *,
    planner: str = "auto",
    echo: Callable[[str], None] = print,
) -> McpAgentResult:
    """Run one planner against an MCP server until it finishes, the grant is spent, or a limit is hit."""
    from mcp import Client

    async with Client(server) as client:
        listed = await client.list_tools()
        names = [t.name for t in listed.tools]
        echo(f"MCP server '{getattr(client.server_info, 'name', 'rewindsafe-recovery')}' exposes: {', '.join(names)}")
        specs = [s for s in adapter.tool_specs() if s.name in names]
        chosen = select_planner(planner, scenario, specs)
        if chosen.kind == "harness":
            raise ValueError("The boundary harness runs in-process; use the clean, poisoned or review scenario.")
        state = AgentState(
            run_id="",
            grant=grant,
            scenario=scenario,
            tool_specs=specs,
            max_steps=grant.limits.max_steps,
            max_replans=grant.limits.max_replans,
        )
        out = McpAgentResult(run_id="", tools=names, planner=getattr(chosen, "label", chosen.name))
        echo(f"Planner: {out.planner}")
        idle = 0
        while state.steps_used < state.max_steps:
            step = await anyio.to_thread.run_sync(chosen.next, state)
            if isinstance(step, Note):
                idle += 1
                echo(f"  · {step.text}")
                if idle > 12:
                    out.summary = "The planner produced no actions."
                    break
                continue
            if isinstance(step, Finish):
                out.summary = step.summary
                echo(f"  ✓ {step.summary}")
                break
            if isinstance(step, Action):
                raise TypeError(f"Planner action {step.name!r} cannot run over MCP.")
            assert isinstance(step, ToolCall)
            idle = 0
            if state.last_outcome is not None and state.last_outcome.status in FAILURES:
                state.replans_used += 1
                if state.replans_used > state.max_replans:
                    out.summary = f"Stopped after {state.max_replans} replans without a way forward inside the grant."
                    break
            result = await client.call_tool(step.tool, step.args)
            data = _payload(result)
            out.run_id = str(data.get("run_id") or out.run_id)
            state.run_id = out.run_id
            outcome = DispatchOutcome.model_validate(data["outcome"])
            state.steps_used += 1
            state.record(step, outcome)
            layer, reason, source = describe(outcome)
            out.steps.append(McpStep(step.tool, dict(step.args), outcome.status.value, layer, reason, source))
            mark = "ALLOWED" if outcome.status not in FAILURES else outcome.status.value.upper()
            line = f"  → tools/call {step.tool}: {mark}"
            if reason:
                line += f" by {layer} [{source}] — {reason}"
            elif source:
                line += f" [{source}]"
            echo(line)
        else:
            out.summary = out.summary or f"Stopped at the step limit ({state.max_steps} tool calls)."
    return out
