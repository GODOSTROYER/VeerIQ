# Merged project readiness

## Current project

The active demo is VeerIQ’s recovery workspace backed by RewindSafe’s PostgreSQL engine. Its showcased run is `run_01M4R4DB4JAY7ARM`: Groq `openai/gpt-oss-120b` ran with live ArmorIQ; four fields across two orders were repaired in one commit; the attempted revoked-access restoration was blocked by `armoriq.sdk.plan_binding`; the run recorded zero forbidden effects and zero prohibited-handler entries.

All incident data and identities are synthetic demo fixtures. The Ed25519 evidence signature is made with the local RewindSafe key. It establishes integrity relative to that key, not ArmorIQ sponsorship, independent witness, or real-world signer identity.

## Evidence status

| Area | Status | What the evidence supports |
|---|---|---|
| Durable recovery | Demonstrated | PostgreSQL-backed order repair, revalidation, and a single successful transactional commit in the recorded run. |
| Live planner | Demonstrated in one run | Groq `openai/gpt-oss-120b` completed the recorded synthetic recovery and proposed the revoked-access action. This is one recorded workflow, not a general model-behavior rate. |
| ArmorIQ plan binding | Demonstrated in the recorded run | The SDK’s local check refused the action because the tool was outside the signed plan. Attribute this to `armoriq.sdk.plan_binding`; it does not show that sponsor policy denied the call. |
| Sponsor policy DENY | Demonstrated in a separate live check | [`sponsor-policy-denial.json`](evidence/merged/sponsor-policy-denial.json) records a wider plan issued with `restore_access_grant`, followed by ArmorIQ `block` / `tool_not_in_allowlist` at `armoriq.backend.enforce` under `org_policy_allowlist`. `simulated` is false and `local_handler_dispatches` is zero. |
| Forbidden effects | None recorded | The run reports zero forbidden effects and zero entries into prohibited handlers. |
| Separate reviewer approval | Demonstrated in a second run | `run_01M4R4X1K61W70GE` used the scripted planner and live ArmorIQ. The operator’s approval request returned HTTP 403; a separate demo reviewer approved the exact manifest; two fields on O-2046 committed once, with all eight protected-state checks held. This was an application-level hold, not sponsor HOLD. |
| Sponsor HOLD and approval | Open | No live sponsor HOLD with a delegation ID or sponsor approval round trip has been verified. The UI’s local second-reviewer flow is separate. |
| Local automated suite | Recorded | Latest run: 385 passed, 8 deselected; the earlier 384-pass result predates the annotation regression case. The runner uses scripted planning and offline ArmorIQ simulation; it does not re-run or validate the live run. |
| Evidence signature | Locally verifiable | The payload, ordered event chain, and embedded-key signature can be checked. Independent signer identity requires a separately trusted public key. |

The merged exports are [`live-recovery.json`](evidence/merged/live-recovery.json), [`approval-recovery.json`](evidence/merged/approval-recovery.json), and [`sponsor-policy-denial.json`](evidence/merged/sponsor-policy-denial.json). `operator-public-key.pem` is bundled to pin the recorded local signer for verification. It does not make the signer independent or certify the evidence. The live recovery receipt reports 2 repaired checks, 5 preserved checks, 1 pending check for out-of-scope O-2046, and 0 violated checks; do not describe all eight checks as preserved.

## Run locally

Requirements: Node.js, Python 3.12, `uv`, and Docker Compose. The setup command installs dependencies and starts the local PostgreSQL database. Default settings are for a scripted, offline demo.

```sh
npm run setup
npm run dev
```

Open http://127.0.0.1:5173. For completion checks, the project scripts are:

```sh
npm run build
npm run test
npm run verify-receipt -- /absolute/path/to/sealed-evidence.json
```

`npm run verify-receipt` checks the exported evidence envelope. To also verify the signer against a key obtained independently:

```sh
npm run verify-receipt -- /absolute/path/to/sealed-evidence.json --public-key /absolute/path/to/trusted-public-key.pem
```

The API exports sealed run evidence from `GET /api/runs/{run_id}/sealed-evidence` after normal session authentication and tenant ownership checks. The export reads persisted evidence; it does not run tools. Keep private keys and credentials outside committed artifacts.

For a live repetition, set `REWINDSAFE_ENFORCEMENT=live`, supply an ArmorIQ API key and authorized identity, and configure a live planner/provider in `.env`. The ArmorIQ workspace must register the RewindSafe MCP/tool metadata. The app fails closed when live ArmorIQ is unavailable. A live-model response that declines an attack is not evidence that enforcement blocked an attempted action; show both the model proposal and the attributed runtime decision when available.

## Open before submission

- Configure the intended ArmorIQ sponsor HOLD policy and capture the complete HOLD, delegation approval, fresh recheck, and one-time commit path.
- Repeat live workflow runs to establish reliability beyond the one saved recovery run, and produce the judge video; the 90-second script is in [merged-demo-script.md](merged-demo-script.md).
- Retain a sealed export for the showcased run and its effects evidence. Share a trusted public key separately if signer identity is part of the claim.
- Resolve the pre-existing RewindSafe project-origin and event-eligibility question with event organizers. The attribution notes record that development began before the stated Flow State build window and that organizer confirmation remains unrecorded. Do not imply the new VeerIQ UI or live run answers that question.
- Present the feature as a synthetic prototype. Local demo identities, one workflow, fixture-reset behavior, and the privileged local operator boundary are not production deployment controls.

See [architecture](merged-architecture.md), [demo script](merged-demo-script.md), and the [sealed evidence notes](../backend/docs/merged-evidence.md) for the detailed walkthrough and verification limits.
