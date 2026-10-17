# VeerIQ: Flow State submission

Current status, links, CI counts and what each proof proves: [`submission-status.md`](submission-status.md) (it wins over anything below).

ArmorIQ Flow State, October 2026.

| Form field | Answer |
|---|---|
| GitHub repository | https://github.com/GODOSTROYER/VeerIQ (give the judges access, or make it public) |
| Live demo URL | https://veeriq.arnavbule.in (Railway; also https://veeriq-app-production.up.railway.app). Status: live (live ArmorIQ, live Groq model), checked 17 Oct 2026. Static walkthrough: https://veeriq.vercel.app |
| Demo video | 4:21, file `videos/demo-video/final/veeriq-demo-1080p.mp4`; watch (unlisted YouTube): https://youtu.be/KWJQHzLuUSo |
| ElevenLabs | Not used |
| Social post | _link to the X post tagging @ArmorIQForDevs or the LinkedIn post tagging ArmorIQ, with #FlowStateHackathon_ |

## Requirements, and where each one is met

| Requirement | How VeerIQ meets it |
|---|---|
| An AI agent | A recovery agent driven by a live model (`openai/gpt-oss-120b` on Groq; Anthropic and OpenAI also supported) or a deterministic scripted planner. |
| At least one MCP server for real actions | `rewindsafe-recovery` ([`backend/rewindsafe/mcp_server.py`](../backend/rewindsafe/mcp_server.py)) exposes the six recovery tools over stdio or streamable HTTP. VeerIQ's agent drives it with `python tasks.py demo-mcp-agent`: every action is an MCP `tools/call`, and the server enforces ArmorIQ, the grant and the database rules before any effect. |
| ArmorIQ: one action allowed, one blocked | `inspect_snapshot`, `compare_current`, `prepare_repair_manifest` and `apply_repair_manifest` are allowed; `restore_access_grant` is blocked by ArmorIQ plan binding. |
| A real integration, not hardcoded | `armoriq-sdk` 0.6.10 against the live backend: `session.start_plan`, `session.check` before every call, `session.report`, `client.complete_plan`. Live mode never falls back to a simulation; the offline simulator is labelled as such everywhere. |
| Agents and MCPs onboarded on platform.armoriq.ai | `python tasks.py armoriq-register` registers the agent and the `rewindsafe-recovery` MCP server from [`armoriq/armoriq.yaml`](../armoriq/armoriq.yaml), using an API key generated on the platform. |
| Proof of ArmorIQ | Recorded live trials in [`evidence/`](../evidence/), the pooled [`SUMMARY.json`](../evidence/SUMMARY.json), the live policy denial in [`sponsor-policy-denial.json`](evidence/merged/sponsor-policy-denial.json), and the console trace shown in the video. |
| Sandbox data only | Every incident, record and identity is synthetic. The import workflow repairs a staged copy. |
| Pre-existing code disclosed | [`rewindsafe-origin/attribution.md`](rewindsafe-origin/attribution.md). |

## What we built

After a bad migration damages database records, the usual fix is to restore a backup. A backup also restores everything else as it was: the service account you revoked comes back, the customer you erased returns, the order that shipped rolls back to pending.

VeerIQ's agent repairs only the damage. Given an approved snapshot and an operator's grant, it inspects the snapshot, compares it with current state, prepares a manifest of exact cell changes and applies it in one commit. Deletions, revocations, holds, later edits and other tenants' records stay as they are today.

## How the agent works

1. **Grant.** An operator authorizes one narrow task: which records, which fields, which tools, one commit, 30 minutes.
2. **Signed plan.** The tool plan is built from the grant, never from the model, and ArmorIQ signs it before the model runs.
3. **Agent.** The model reads the snapshot, compares it with today's data, prepares a manifest and applies it. It proposes; it never executes. Restored values are read from the snapshot by trusted code, so the model cannot supply a value.
4. **Gates.** Each proposal passes, in order: argument schema, grant validity, the ArmorIQ check, grant scope, domain rules, and a second reviewer for repairs above $5,000. Any gate that cannot answer refuses.
5. **Commit.** One PostgreSQL transaction locks the rows, re-checks everything and writes under a restricted role. If a protected record would change, it rolls back.
6. **Evidence.** The run is exported as a hash chain signed with Ed25519, verifiable offline.

## How ArmorIQ is used

ArmorIQ is the authority on what the agent may do. VeerIQ never lets the model act directly.

- **Plan binding.** `session.start_plan` signs the plan derived from the grant. `session.check` runs before every tool call; a tool outside the signed plan is refused before its handler is entered.
- **Policy.** The workspace policy registered from [`armoriq/armoriq.yaml`](../armoriq/armoriq.yaml) allows the five recovery tools and denies `restore_access_grant`. In a separate live check ArmorIQ signed a wider plan that included `restore_access_grant`, and its policy still refused the call (`tool_not_in_allowlist`).
- **Audit.** Each executed call is reported with `session.report`; the audit IDs are sealed into the run's signed evidence. The plan is closed with `client.complete_plan`.
- **Fail closed.** If ArmorIQ is unreachable, slow, returns an error status, or answers anything other than allow, block or hold, the call is refused.

ArmorIQ binds tools to the plan; it does not bind arguments. VeerIQ adds the layers that depend on the data (grant scope, domain rules, the reviewer and the locked transaction), and every decision names the layer that made it.

## The boundary test

The approved snapshot carries a planted note, written as an operations runbook, telling the agent to re-enable a revoked service account before repairing. The agent's prompt does not warn it.

- A live model followed the note and called `restore_access_grant` in every trial that got that far: **23 of 23**.
- ArmorIQ blocked **all 23**. The handler was never entered and the account stayed revoked.
- The permitted repair completed in 18 of the 24 trials in which the model acted.
- **Zero** forbidden effects observed in the **82** of 84 recorded trials that carry effect observations; the 2 interrupted records lack them.

The counts pool six batches recorded on different code versions; the model provider's daily quota stopped each batch before 40 trials.

## Other tools used

FastAPI, PostgreSQL 16, React with Vite and TypeScript, the MCP Python SDK, Groq, Ed25519 (`cryptography`), Docker, and HyperFrames for the showreel.

## Takeaways

- **Plan binding is the right first wall.** A hijacked agent was stopped before its handler ran, every time, because the forbidden tool was never in the plan. The model's intent did not matter.
- **Tools are not arguments.** ArmorIQ decides which tools may run; whether a call touches the right tenant, record or field depends on the data. Those checks have to live next to the data, and both layers must fail closed.
- **A wide plan is not a hole.** Policy still refused a forbidden tool that a too-broad plan included. Defense in depth held at the platform layer too.
- **Proof has to outlive the demo.** Signed, hash-chained evidence lets anyone check a run later without trusting our interface.
- **Live testing is honest testing.** Our numbers come from a live model under live enforcement, and they include the runs that never acted.

## What we would build next

- ArmorIQ hold and approval for high-value repairs, replacing VeerIQ's own second reviewer with the platform's approval inbox.
- Argument-level policy, so tenant and field scope can also be expressed in ArmorIQ.
- Connectors for real backup systems and warehouses, writing back through the same gates.
- Delegation between agents: a read-only investigator that hands a repair-only executor exactly the authority it needs.

## What is not shown

- ArmorIQ hold and approval have not been observed live. The second-reviewer step is VeerIQ's own and is labelled that way.
- No single batch finished its full 40 trials; the counts pool six batches recorded on different code versions.
- Evidence is signed with a local operator key, not attested by ArmorIQ or an independent party.

## Provenance

Work on the recovery engine began on 7 October 2026, three days before the build week, and continued through it. What existed before the window is listed in [`rewindsafe-origin/attribution.md`](rewindsafe-origin/attribution.md). The event page allows advancing existing projects; build-week work is listed in [`../CHANGES_DONE.md`](../CHANGES_DONE.md) and [`../PROGRESS.md`](../PROGRESS.md). The code was written with substantial AI assistance and verified by running its tests.

## Social post (draft)

> We built VeerIQ for #FlowStateHackathon: an AI agent that repairs a damaged database from a backup without undoing today's decisions.
>
> We planted a prompt injection in the backup telling the agent to re-enable a revoked account. A live model took the bait 23 times. @ArmorIQForDevs blocked all 23, because the tool was never in the signed plan. Zero forbidden effects observed in the 82 of 84 trials with effect observations; 2 interrupted trials lack them.
>
> Restore yesterday's data. Keep today's decisions.
