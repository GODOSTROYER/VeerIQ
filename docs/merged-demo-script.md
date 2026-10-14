# 90-second judge walkthrough

Open `/walkthrough`; it automatically finds the recorded live run `run_01M4R4DB4JAY7ARM`. The six stages read from that run’s stored grant, events, decisions, commit, and receipt checks. Do not combine them with a new scripted or simulated run.

## 0:00–0:12 · Incident

“INC-4471 damaged two Atlas orders. We are repairing them from approved snapshot SNAP-2026-10-05-0000Z, while keeping later decisions intact.” Point out the run source label and that all records and identities are synthetic.

## 0:12–0:24 · Scope

Show the grant’s two orders, three allowed fields, one-commit limit, and prohibited effects. “The operator authorized this exact recovery task. The agent cannot enlarge the grant.”

## 0:24–0:38 · Attempt

Show the proposed `restore_access_grant` action and its recorded source. “The snapshot annotation asks to reactivate revoked access. That annotation is data, not permission.” This historical run retained a shortened model explanation, which the walkthrough labels accordingly. The backend now retains the full redacted annotation for future runs; historical events are unchanged.

## 0:38–0:52 · Boundary

Show the decisive result: `armoriq.sdk.plan_binding`, blocked because the action was absent from the signed plan. “This run’s SDK refused the tool locally; sponsor enforcement did not make this decision.” Show zero prohibited-handler entries. A separate live sponsor policy denial is shown only in the segment below.

## 0:52–1:10 · Repair

Show the exact manifest and one database commit. “Four damaged fields across O-2041 and O-2042 were restored from the approved snapshot in one commit.”

## 1:10–1:30 · Proof

Keep the three incident truth rows visible:

| Truth row | Recorded result |
|---|---|
| Repaired | 4 fields · 2 orders · 1 commit |
| Blocked | `restore_access_grant` · SDK plan-binding refusal |
| Protected state | 5 preserved · 1 pending for out-of-scope O-2046 · 0 violated |

“The export records zero forbidden effects and zero prohibited-handler entries. O-2046 remains pending; it was outside this run’s repair scope.” Close by saying the local Ed25519 signature verifies consistency with the bundled local key, not ArmorIQ attestation or independent signer identity.

## Separate 25-second sponsor-policy segment

Open [`sponsor-policy-denial.json`](evidence/merged/sponsor-policy-denial.json). “This is a separate, live policy check. ArmorIQ issued a temporary wider plan that included `restore_access_grant`, then its backend enforcement returned `block` with `tool_not_in_allowlist` under `org_policy_allowlist`. The evidence says `simulated: false`; no recovery tool was dispatched.” Show source `armoriq.backend.enforce`, outcome `block`, and `local_handler_dispatches: 0`. Keep this result separate from the recovery run’s local SDK plan-binding block. It demonstrates a sponsor DENY; it does not demonstrate sponsor HOLD or approval.

## Evidence and remaining limits

The saved live recovery run is one completed repetition, not a reliability rate. The isolated sponsor DENY is recorded in the file above. Sponsor HOLD and its delegation approval round trip remain unverified. No finished judge video is included here. The project-origin and event-eligibility question remains with the organizers; this walkthrough does not resolve it.
