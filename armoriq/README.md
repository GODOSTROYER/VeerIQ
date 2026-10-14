# ArmorIQ integration notes

> **Status: `armoriq/policy.rewindsafe.json` is a proposal that no code reads and is not active in the workspace; the live policy is the registration in `armoriq/armoriq.yaml`.**

VeerIQ uses the **ArmorIQ Python SDK 0.6.10** (`armoriq-sdk`) in `sdk` session mode:

1. At run start VeerIQ builds a plan from the **grant only** (never from the model) and asks ArmorIQ
   to sign it (`session.start_plan` -> `POST /iap/sdk/token`).
2. Every proposed action is checked with `session.check(tool, canonical_args)`
   (`POST /iap/sdk/enforce`, or a local `tool-not-in-plan` refusal with no network call).
3. VeerIQ's own dispatcher honors the answer and is the only executor. We never also call
   `client.invoke`, so no effect can happen twice and no hosted proxy has to reach this machine.

Implementation: `backend/rewindsafe/runtime/armoriq_gateway.py`. Live evidence probe:
`backend/scripts/armoriq_probe.py` (Gate A).

## Live status (2026-10-07)

| Item | State |
|---|---|
| Active policy | the `armoriq/armoriq.yaml` registration: 5 allow / 1 deny, matched policy `cli-rewindsafe-recovery-agent-rewindsafe-recovery` |
| `armoriq/policy.rewindsafe.json` | **proposed, NOT active** in the live workspace |
| HOLD (approval) | **not configured**: a workspace admin must add an amount threshold on `apply_repair_manifest` (dashboard member rule). Live `apply_repair_manifest` with amount 12400 is allowed today |
| Wider plan with `restore_access_grant` | **issued**, then **blocked at enforcement** (`block`, `tool_not_in_allowlist`, source `armoriq.backend.enforce`) |
| Arguments bound by the plan | no: same tool with tenant `beacon` is allowed; VeerIQ grant scope enforces it |
| Plan lifecycle | `session.start_plan` -> `session.check` per action -> `session.report` -> `client.complete_plan(plan_id)` when the run ends (recorded as a `telemetry.delivery` event with the HTTP status) |
| Observability | every session ships spans to ArmorIQ; the run records the ArmorIQ session id and LLM usage via `session.record_generation` |

Evidence: the 2026-10-07 probe files named in earlier notes, `evidence/gate-a-*.json` and `evidence/gate-a-early-live-2026-10-07.md`, are not in this checkout. `backend/scripts/armoriq_probe.py` writes a new `evidence/gate-a-<timestamp>.json` each time it runs. Until the dashboard threshold exists, the review scenario's HOLD comes from VeerIQ's own reviewable set and is labelled `Held by RewindSafe`, in both modes. The `await_approval` delegation round trip has therefore never run live; the gateway implements it (polling `get_delegation_status`, then letting the SDK's reuse path consume the approved delegation) and unit-tests it with fakes only.

## What ArmorIQ does and does not enforce here

| Question | Answer (from SDK source, 0.6.10) |
|---|---|
| Is a tool outside the signed plan stopped? | Yes. `session.check` returns `block` / `tool-not-in-plan:` locally. |
| Are arguments / resources bound to the plan? | **No.** The SDK sends arguments to `/iap/sdk/enforce`, so org policy *may* use them, but plan binding is by tool name. The probe records what the backend actually does. Same-tool wrong-resource refusals come from VeerIQ manifests and grant scope and are labeled `rewindsafe.*`. |
| Can the backend refuse to sign a plan? | The SDK can raise `PolicyBlockedException` from `start_plan`, but **observed live**: a wider plan including `restore_access_grant` was issued and then blocked at check (`tool_not_in_allowlist`). VeerIQ records the check-time block as `armoriq.backend.enforce`. |
| Is `hold` supported? | Yes in `sdk` mode: the SDK creates a delegation request and returns `hold` + `delegation_id`; `await_approval` returns exactly `approved`, `rejected` or `timeout`. |
| Is delivery of `report()` guaranteed? | No. The SDK swallows errors. VeerIQ records every report in `runtime.telemetry_outbox` and marks it delivered only if the audit POST returned HTTP < 400 (observed via an httpx response hook). |

VeerIQ fails **closed**: an unreachable backend is `UNAVAILABLE` (not a policy denial), any action string other than exactly `allow`/`block`/`hold` is a block, and a `hold` without a delegation id is refused because the approval could not be recorded.

The same rule covers timeouts and HTTP status. A timed-out check is `UNAVAILABLE`, never `allow`. An `allow` that arrives with a non-2xx HTTP status is refused as unavailable; a 403 policy denial stays a block. `REWINDSAFE_ARMORIQ_TIMEOUT_S` (default 15, allowed range 1 to 120 seconds) is the default timeout for ArmorIQ HTTP calls. The SDK fixes its own bounds: 10 seconds for the enforce check and 30 seconds for plan issuance.

## Registration: `armoriq/armoriq.yaml` (what is actually live)

`armoriq.yaml` is a template (no personal email, no key). Run:

```
python tasks.py armoriq-register     # needs ARMORIQ_API_KEY and ARMORIQ_USER_EMAIL in .env
```

It renders the template to a temp file and runs `uv run armoriq register --config <tmp>` in `backend/`. Effect: agent `rewindsafe-recovery-agent`, MCP server `rewindsafe-recovery`, **allow** `inspect_snapshot`, `compare_current`, `prepare_repair_manifest`, `apply_repair_manifest`, `get_recovery_receipt`; **deny** `restore_access_grant`. This is the policy behind the live evidence in `evidence/`.

Without registration every check returns `block` with `no_matching_policy` (the workspace default), and the app reports `workspace_not_registered` with this command as the fix.

## Offline simulation vs live: the real deltas

The offline simulation (`OfflineSimulatedGateway`) mirrors the behavior **observed** live, and is always labeled SIMULATED:

| Behavior | Live (observed) | Offline simulation |
|---|---|---|
| Off-plan `restore_access_grant` | block, SDK plan binding (`tool-not-in-plan`) | same |
| In-plan tools | allow (`allow_with_logging`) | allow |
| Wider plan with `restore_access_grant` | issued; check blocks (`tool_not_in_allowlist`) | issued; check blocks (`tool_not_in_allowlist (simulated)`) |
| Amount HOLD | none (no threshold configured) | none; the review scenario's hold is VeerIQ's reviewer in both modes |
| Latency | about 4.7 s plan, about 0.9 s check | instant |

A unit test, `test_policy_yaml_matches_the_offline_denied_tools_and_plan_tools` in `backend/tests/unit/test_gateway_hardening.py`, asserts that the allow and deny lists in `armoriq/armoriq.yaml` match the offline simulator's deny set and the plan tool list. It checks the file against the simulator, not the policy that ArmorIQ has registered.

## Optional: `policy.rewindsafe.json` (NOT applied, NOT what is live)

`policy.rewindsafe.json` is an unverified proposal for a richer org policy that would add an amount-based hold (`apply_repair_manifest` above $5,000 requires approval). It was never proposed or confirmed in the workspace. The offline simulation does **not** mirror it. The way to get an ArmorIQ HOLD is to add an amount threshold in the ArmorIQ dashboard (see `docs/rewindsafe-origin/sdk-integration.md`, "Configuring an ArmorIQ HOLD", and the rehearsal steps in `docs/armoriq-hold-setup.md`).

### Unverified fields in `policy.rewindsafe.json` (please read before relying on the file)

The document shape is **inferred** from `armoriq_sdk/cli_policy.py`, which only *prints* a policy. The SDK source confirms:
`metadata.name`, `metadata.description`, `defaults.decision`, and a `statements[]` list whose items have `effect`,
`action` (`{"eq": "<tool>"}` or `{"in": [...]}`) and optional `conditions[]` of `{field, op, value}`.
The ArmorIQ backend owns the real schema. **Not verified** (the file may need adjustment, and the server's error text
will say so):

* the top-level `"schema": "armor.policy.v1"` marker (name taken from the CLI help text; the key name is a guess);
* the `effect` vocabulary: `allow`, `deny`, `require_approval` (the CLI pads effects to 16 characters, which fits
  `require_approval`, but the value is a guess);
* the `defaults.decision` value `deny`;
* the condition `field` path (`arguments.amount`) and operators (`gt`, `lte`);
* extra keys I added (`id`, `reason`) may be rejected or ignored;
* statement precedence (the allow/hold statements for `apply_repair_manifest` are written to be mutually exclusive so
  precedence should not matter);
* that the backend resolves `arguments.amount` from the arguments VeerIQ sends. VeerIQ always sends a
  server-derived `amount` in **dollars** (`restored_value_cents / 100`) for `apply_repair_manifest`.

### Proposing it

Policy changes are confirmed by a human on the dashboard (activation is deliberately human-only).

```bash
# 1. authenticate the CLI once (opens a browser); or set ARMORIQ_API_KEY
cd backend
uv run armoriq login

# 2. stage the policy as the org's draft proposal (does NOT activate it)
uv run armoriq policy propose --file ../armoriq/policy.rewindsafe.json --reason "RewindSafe recovery policy"

# (equivalent from the repo root: armoriq policy propose --file armoriq/policy.rewindsafe.json)

# 3. confirm it on the ArmorIQ dashboard (Policies -> pending proposal -> Confirm)
#    https://platform.armoriq.ai/dashboard
```

Check what is active with `uv run armoriq policy show`. Discard a staged proposal with `uv run armoriq policy cancel`.
Do **not** use `--activate` unless you intend to skip dashboard confirmation: it publishes immediately for every agent
session in the org.

After confirming, re-run `uv run python scripts/armoriq_probe.py` and keep the evidence file it writes to `evidence/`.
