"""VeerIQ's agent driving the rewindsafe-recovery MCP server: every action is an MCP tools/call.

The server runs in-process here (``mcp.Client(server)``) with the offline ArmorIQ simulation; the CLI
spawns the same server over stdio. Either way the agent never calls the dispatcher itself.
"""

from __future__ import annotations

import anyio

from rewindsafe import mcp_server


def _authorized(scenario_id: str):
    import rewindsafe.workflows.rewindsafe.adapter  # noqa: F401
    from rewindsafe.runtime import grants
    from rewindsafe.runtime.adapter import get_adapter
    from rewindsafe.runtime.identities import get_identity

    adapter = get_adapter("rewindsafe.order_repair")
    maya = get_identity("maya")
    scenario = next(s for s in adapter.scenarios() if s.scenario_id == scenario_id)
    grant = grants.authorize(grants.create_draft(adapter, scenario, maya).grant_id, maya)
    return adapter, scenario, grant


def _run(scenario_id: str):
    from rewindsafe.agent.mcp_agent import run_mcp_agent
    from rewindsafe.runtime.armoriq_gateway import OfflineSimulatedGateway

    adapter, scenario, grant = _authorized(scenario_id)
    server = mcp_server.build_server(grant.grant_id, gateway=OfflineSimulatedGateway(), return_outcome=True)
    lines: list[str] = []
    result = anyio.run(lambda: run_mcp_agent(server, grant, scenario, adapter, planner="scripted", echo=lines.append))
    server.rewindsafe_bridge.close()
    return grant, result, lines


def test_poisoned_agent_over_mcp_is_blocked_then_repairs(fresh):
    from rewindsafe.agent import get_run
    from rewindsafe.runtime import events, mutators

    _, result, lines = _run("poisoned")
    assert "restore_access_grant" in result.tools and len(result.tools) == 6
    by_tool = {s.tool: s for s in result.steps}
    blocked = by_tool["restore_access_grant"]
    assert blocked.status == "blocked" and blocked.layer.startswith("ArmorIQ")
    assert by_tool["apply_repair_manifest"].status == "executed"
    assert any("tools/call restore_access_grant: BLOCKED" in line for line in lines)

    run = get_run(result.run_id)
    assert run.planner == "mcp-client" and run.status.value in {"succeeded", "partially_succeeded"}
    proposals = [e for e in events.list_events(result.run_id, limit=500) if e.type == "agent.proposal"]
    assert len(proposals) == len(result.steps)
    assert {(e.data or {}).get("source") for e in proposals} == {"mcp"}  # every action arrived over MCP
    assert mutators.count_entries("restore_access_grant", run_id=result.run_id) == 0


def test_clean_agent_over_mcp_repairs_without_a_block(fresh):
    _, result, _ = _run("clean")
    assert result.steps and all(s.status in {"executed", "duplicate"} for s in result.steps)
    assert any(s.tool == "apply_repair_manifest" for s in result.steps)
