# ArmorIQ SDK integration

Tested against `armoriq-sdk==0.6.10`. The facts below were read from the installed package source (`armoriq_sdk/client.py`, `session.py`), as recorded in `docs/architecture.md` section 1. Re-read the source if the SDK version changes.

**Status:** the facts below were confirmed live on 2026-10-07 (`evidence/gate-a-early-live-2026-10-07.md`), except HOLD / `await_approval`, which has not been observed because no amount threshold is configured in the workspace. See "Live-verified behavior" for the observed table.

## Chosen route

Session SDK mode, with RewindSafe's dispatcher as the single executor:

```
grant -> session.start_plan(tool_calls) -> signed intent token (plan)
per proposal: session.check(tool, canonical_args) -> allow | block | hold
   allow -> our sole executor runs the effect
   hold  -> delegation request; await_approval; plus RewindSafe approval
   block -> stop; no handler entered
afterwards: session.report(...) (best effort audit, tracked in an outbox)
```

We never also call `client.invoke` for the same effect, so there is no double execution, and no hosted ArmorIQ proxy has to reach localhost.

## Facts that shape the design

- `ArmorIQClient(api_key=..., use_production=True)`. Keys start with `ak_live_`, `ak_test_` or `ak_claw_`. The constructor validates the key against the proxy `/health` endpoint (a network call). Endpoints default to production and can be overridden by `ARMORIQ_ENV`, `BACKEND_ENDPOINT` and related variables.
- `client.for_user(email).start_session(SessionOptions(mode="sdk", default_mcp_name=..., validity_seconds=..., llm=...))` returns a session.
- `session.start_plan(tool_calls, goal=...)` builds the plan, captures it, and requests an intent token (token id, plan hash, plan id, expiry, policy validation, policy snapshot, step proofs). Issuance can raise `PolicyBlockedException` when organization policy denies a tool in the plan, or `InvalidTokenException`.
- `session.check(tool, args)` returns an `EnforceResult` (`allowed`, `action` in allow/block/hold, `reason`, `delegation_id`, `matched_policy`, `obligations`). It **returns** denials rather than raising, so the caller must honor the result. In sdk mode:
  1. A tool not in the signed plan is blocked locally with reason `tool-not-in-plan:...`, with no network call. RewindSafe labels this source `armoriq.sdk.plan_binding`.
  2. Otherwise the arguments, token and policy snapshot are POSTed to `/iap/sdk/enforce`. Source `armoriq.backend.enforce`.
  3. Any exception becomes a block with reason `enforce-unavailable:...` (fail closed). RewindSafe classifies this as **unavailable**, never as a policy denial.
  4. A hold creates a delegation request and returns immediately with a `delegation_id`.
- `await_approval(delegation_id, timeout, interval)` returns exactly `"approved"`, `"rejected"` or `"timeout"`.
- `session.report(...)` posts to `/iap/audit` and **swallows errors**. A normal return does not prove delivery, so RewindSafe records each report in `runtime.telemetry_outbox` and says "returned without raising" rather than "delivered" where it matters.
- HOLD in `local` mode is converted to BLOCK by the SDK, which is why sdk mode is used.

### Argument binding is RewindSafe's job, not the SDK path's

On the path we use, `client.invoke` only checks that the action **name** is in the plan, and its Merkle proof covers the step's action leaf, not its parameters. So "same tool, wrong resource" rejections (wrong tenant, an order outside the grant, a field outside scope, a tampered manifest digest) come from RewindSafe's immutable manifest and grant scope, and the UI and evidence label them that way. The backend `/iap/sdk/enforce` receives the arguments and may apply argument-aware policy; RewindSafe records exactly what it returns and does not assume.

## Live-verified behavior (2026-10-07)

Observed against the real service (SDK 0.6.10, sdk mode, workspace registered from `armoriq/armoriq.yaml`).

| Probe | Observed |
|---|---|
| `start_plan` for the 5 recovery tools | Token minted in about 4.7 s (once per run); plan hash, 5 step proofs; matched policy `cli-rewindsafe-recovery-agent-rewindsafe-recovery` |
| In-plan `inspect_snapshot` | allow, `allow_with_logging`, about 0.88 s |
| Off-plan `restore_access_grant` | block, `tool-not-in-plan`, source `armoriq.sdk.plan_binding`, 0 ms, no network |
| `apply_repair_manifest` with `tenant=beacon` | **allow**: ArmorIQ does not bind arguments; RewindSafe's grant scope blocks it |
| `apply_repair_manifest` amount 12400 | allow: **no HOLD threshold** configured |
| Wider plan including `restore_access_grant` | Token **issued** (`denied_tools=[]`); the check then returns block `tool_not_in_allowlist` (org policy), source `armoriq.backend.enforce` |
| Before registration | every check blocked with `no_matching_policy` (workspace default is block) |
| `local` session mode | fails closed (`token-signature-invalid`, public key disabled); use `sdk` |
| End of run | call `client.complete_plan(plan_id)`; the session does not do it |

RewindSafe's response: block decisions from ArmorIQ are recorded with their source; the `remint_wider` probe records the ArmorIQ block as well as RewindSafe's `assert_within_grant`; the offline simulation mirrors this table (labeled simulated).

## Configuration

Set in `.env` at the repo root (see `.env.example`). Never commit keys.

| Variable | Purpose |
|---|---|
| `ARMORIQ_API_KEY` | Enables live mode when present (`REWINDSAFE_ENFORCEMENT=auto`) |
| `ARMORIQ_USER_EMAIL` | The ArmorIQ account that owns the key; used for the session and by `python tasks.py armoriq-register` |
| `ARMORIQ_AGENT_ID` | Optional, defaults to `rewindsafe-recovery-agent` (used by `armoriq-register`) |
| `GROQ_API_KEY`, `REWINDSAFE_GROQ_MODEL` | Live LLM planner (Groq, OpenAI-compatible); default model `openai/gpt-oss-120b` |
| `ARMORIQ_ENV` | Defaults to `production` |
| `ARMORIQ_SESSION_MODE` | Defaults to `sdk` |
| `ARMORIQ_MCP_NAME` | Defaults to `rewindsafe-recovery` |
| `REWINDSAFE_ENFORCEMENT` | `auto`, `live` or `offline`. `live` without a key fails at startup; there is no silent fallback |

`GET /api/system/status` reports mode, simulated flag, SDK version, and whether a key and user email are set. It never returns the key.

## Registering your workspace

Your own ArmorIQ workspace needs the agent and allowlist registered once, otherwise every check fails closed with `no_matching_policy`:

```
# .env: ARMORIQ_API_KEY=ak_..., ARMORIQ_USER_EMAIL=<account that owns the key>
python tasks.py armoriq-register
```

This renders `armoriq/armoriq.yaml` (a template with no personal email) with your values to a temp file and runs the SDK's `armoriq register` through `uv`. It applies: agent `rewindsafe-recovery-agent`, MCP server `rewindsafe-recovery`, allow the 5 recovery tools, deny `restore_access_grant`. This is the policy that was verified live. `armoriq/policy.rewindsafe.json` is an optional extra proposal (see `armoriq/README.md`) and was never applied; it is not what the live results came from.

## Configuring an ArmorIQ HOLD (not done yet)

A HOLD on large amounts needs an amount threshold on `apply_repair_manifest`, added by a human in the ArmorIQ dashboard (member rule, amount over $5,000, approve). Until then the live service allows amount 12400 and the review scenario's hold is RewindSafe's own reviewer. After adding the threshold, run `python tasks.py live-evidence` and keep the new `evidence/gate-a-*.json`; do not claim a HOLD before then.

## HOLD and approval flow

1. ArmorIQ returns `hold` (only once a threshold is configured; not observed yet) or the domain layer requires review (high-value manifest, or amount over the grant's review threshold).
2. RewindSafe creates an approval bound to the exact payload digest and the state constraints (authority epoch, row versions, fixture generation).
3. A second identity (reviewer, same tenant, not the requester) approves or rejects in the Approvals page.
4. In live mode with a delegation id, `await_approval` must also return `"approved"`. Both must approve.
5. After approval, grant, domain and state checks run again against current state. Approval never immunizes a payload against later change, and a changed digest does not match.
6. Reject, timeout and expiry end in a blocked proposal with no effect.

## Gate A probes (`python tasks.py test-live`)

Live probes exit BLOCKED (never pass, never skip silently) when `ARMORIQ_API_KEY` is missing. Observed results for the first five are in the table above; "Policy hold" and "Approval round trip" are still pending a configured threshold. What each is meant to prove:

| Probe | Proves |
|---|---|
| Key and session | The key validates and a session starts for the configured user |
| Plan issuance | `start_plan` returns a token with a plan hash for the five recovery tools |
| Plan binding block | `check("restore_access_grant", ...)` returns block with `tool-not-in-plan` and no handler entry |
| Allow control | A planned tool (for example `inspect_snapshot`) returns allow |
| Wider plan | Observed: ArmorIQ issues the token, then blocks `restore_access_grant` at check (`tool_not_in_allowlist`); recorded either way, since it depends on org policy |
| Policy hold | After a threshold is configured, a large `apply_repair_manifest` returns hold with a delegation id (pending) |
| Approval round trip | `await_approval` returns the exact string for approve and reject |
| Report delivery | `report` returns without raising; the outbox records the attempt |
| Unavailable | A forced outage is classified unavailable, not block |

The probe list is the intended design; the authoritative list is whatever `backend/tests/live/` contains. Probes record what ArmorIQ returned, and a probe whose outcome depends on organization policy documents its precondition rather than assuming it.
