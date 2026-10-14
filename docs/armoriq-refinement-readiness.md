# ArmorIQ refinement readiness

Audit date: 2026-10-12. The initial section records a read-only review of the checked-in gateway, probe, registration files, and evidence available at that time. A verification appendix below updates the initial pending DENY assessment using the subsequently saved live probe evidence. No policy change is recorded.

## Current state

The root `.env` contains an ArmorIQ API key and user identity (presence only was checked; values were not printed). `docs/credential-status.json` records a successful plan mint at 2026-10-12 12:17:38Z, then an ArmorIQ `tool_not_in_allowlist` denial for an in-plan `labline-mcp` research tool. That is evidence of a live sponsor decision for that tool, not for VeerIQ’s recovery tools. The undeclared identifiers tool in the same smoke check was separately refused by plan binding.

The recovery integration docs record a real workspace registration from `armoriq/armoriq.yaml` on October 7: five recovery tools allowed and `restore_access_grant` denied. The checked-in YAML remains a template, and `armoriq/policy.rewindsafe.json` is labeled proposed, unverified, and never applied. An October 12 saved live probe now supplies direct evidence for the wider-plan denial described below. This captured decision establishes the result for that check; the template still does not query current dashboard assignment.

The saved October 12 recovery run (`run_01M4R4DB4JAY7ARM`) is live ArmorIQ evidence for plan issuance and allowed in-plan tools. Its `restore_access_grant` proposal was blocked by `armoriq.sdk.plan_binding` because it was absent from the signed plan; that decision took about 0.14 ms and did not call sponsor enforcement. The separate application-review run (`run_01M4R4X1K61W70GE`) shows RewindSafe’s own approval HOLD, HTTP 403 for self-approval, a second reviewer, and an allowed sponsor recheck. It does not show an ArmorIQ HOLD or delegation.

## Recorded sponsor DENY

[`evidence/merged/sponsor-policy-denial.json`](evidence/merged/sponsor-policy-denial.json) records the isolated wider-plan check. ArmorIQ issued a temporary plan containing `restore_access_grant`, then returned a raw `block` with reason `tool_not_in_allowlist` at `armoriq.backend.enforce`; the normalized invariant is `org_policy_allowlist`. The decision is live (`mode=live`, `simulated=false`), and the evidence records `local_handler_dispatches=0`. This is a genuine sponsor policy DENY for the captured check. No recovery tool was dispatched and no local handler was entered.

The saved check establishes that the sponsor policy denied this wider-plan enforcement request. It does not certify the current dashboard state for future runs or demonstrate a sponsor HOLD.

The broader `python tasks.py live-evidence` command runs more than this isolated check. It also makes a $12,400 `apply_repair_manifest` enforcement check at step 5 and can create a pending ArmorIQ delegation if a threshold has since been added. It never approves that delegation or executes a repair. Any live check creates plan/enforcement activity in the sponsor service audit trail, even though it does not alter policy or application data. The recorded DENY probe is complete; there is no need to repeat it to support the current evidence claim.

The saved recovery run is not sufficient for this claim. In an honest timeline, distinguish these sources explicitly:

| Observed result | Correct attribution |
|---|---|
| Tool absent from the signed plan; local refusal with no enforcement request | `armoriq.sdk.plan_binding` |
| Tool included in a temporary wider plan; saved probe returned `block` / `tool_not_in_allowlist` | `armoriq.backend.enforce`, sponsor org policy; see `sponsor-policy-denial.json` |
| Enforcement endpoint unreachable or SDK call fails | `UNAVAILABLE`, fail-closed behavior; not a policy denial |
| Domain or app reviewer requires approval, without sponsor delegation | RewindSafe application HOLD |
| ArmorIQ returns `hold` with a delegation ID | Sponsor HOLD; show the matched policy and delegation separately from RewindSafe approval |

The saved sponsor DENY has been checked for `mode=live`, `simulated=false`, `outcome=block`, source `armoriq.backend.enforce`, invariant `org_policy_allowlist`, raw action `block`, and reason `tool_not_in_allowlist`. A local refusal, default-deny for no matching registration, or `UNAVAILABLE` must not be presented as this result.

## What is missing for a genuine sponsor HOLD

No environment variable or local file can enable this with the current setup. The active recovery registration contains an allowlist and a tool deny but no amount condition. The recorded October 7 probe allowed `apply_repair_manifest` with amount 12,400, and the current repo docs say no threshold is configured. The offline simulation’s configurable HOLD threshold and the proposed `policy.rewindsafe.json` are not sponsor evidence.

The missing sponsor-side configuration is an active ArmorIQ dashboard rule for the existing `rewindsafe-recovery.apply_repair_manifest` tool: require approval when its server-derived `arguments.amount` is greater than 5,000 USD, while keeping the existing allowlist and `restore_access_grant` deny. The proposal’s JSON schema and condition syntax are explicitly unverified; do not register or upload that file as though its format were supported. This audit did not inspect the sponsor dashboard, so current activation cannot be independently ruled out. A workspace admin must check the rule assignment and threshold there.

After the rule is active, verify a harmless synthetic check and preserve the raw, sanitized result. A genuine HOLD must have live mode, source `armoriq.backend.enforce`, outcome `hold`, raw action `hold`, the matched policy, and a nonempty `delegation_id`. A HOLD with no delegation ID is classified `UNAVAILABLE` by this gateway because it cannot complete an approval round trip. The existing probe’s amount check records a HOLD but intentionally does not approve it. The complete round trip still requires the sponsor delegation to be approved, `await_sponsor_approval()` to observe that approval, the app reviewer to approve the exact RewindSafe payload, and the gateway to recheck before the one-time effect. Capture each result separately. Do not label the separate application-review run as sponsor approval evidence.

## Configuration and verification sequence

1. Keep the existing private `ARMORIQ_API_KEY` and `ARMORIQ_USER_EMAIL`; the key value must stay out of logs and evidence exports. Confirm locally that the integration still uses its previously verified SDK session, registered MCP name, and intended environment without printing their values. Do not run `armoriq-register` for this audit: registration changes sponsor workspace state.
2. In the ArmorIQ dashboard, inspect the active agent/policy assignment read-only. Confirm the five recovery tools, the `restore_access_grant` deny, and whether an amount rule is already active. The registration YAML in the repo is a template, not a live-state query.
3. The isolated wider-plan denial is already captured in `docs/evidence/merged/sponsor-policy-denial.json`; preserve this sanitized evidence and verify its attribution fields before presenting it. The probe requested a temporary broader signed plan and wrote sponsor audit activity, with no local handler dispatch.
4. Only after confirming or adding the dashboard threshold, run the $12,400 probe check against synthetic arguments. Stop after recording a HOLD unless the sponsor and application reviewers are explicitly part of the planned approval rehearsal. Retain the delegation ID privately or redact it consistently in any public recording.
5. For an approval rehearsal, use the normal application flow and show the sponsor delegation status, separate app approval, fresh ArmorIQ recheck, and one commit. Record an effect counter or handler-entry count to establish that the hold itself caused no effect and the approved execution happened once.

The app’s `/api/system/status` can report mode and cached readiness without returning the secret, but it can start a background live readiness probe when stale. This review did not call it because the checked-in evidence and probe code already answer the readiness question.

## Recording strategy and observed timing

Use the already recorded live recovery run as the primary live workflow clip. It starts at 2026-10-12 13:21:40Z and finishes at 13:23:27Z (about 1 minute 47 seconds). Plan issuance took about 5.15 seconds; four ArmorIQ enforcement checks had p50 0.98 seconds and p95 1.88 seconds. The same run’s SDK plan-binding refusal was effectively immediate (about 0.14 ms). The approval run spans about 1 minute 8 seconds and had a 4.90-second plan mint; its app approval wait accounts for much of the elapsed time. These are two recorded runs, not a latency guarantee.

For a short recording, show the live plan/ALLOW evidence, the model’s proposed `restore_access_grant`, then name the local plan-binding source and show zero prohibited-handler entries. Keep the RewindSafe reviewer flow in a second segment and call it an application HOLD. The separate sponsor-denial segment is now captured in `docs/evidence/merged/sponsor-policy-denial.json`; keep its backend source explicit. Add a sponsor-HOLD segment only after the dashboard rule and delegation round trip are genuinely observed. Keep the existing live clip as a fallback and leave time for the roughly five-second plan-mint delay; avoid a fresh full live run as the recording’s critical path.

The existing project-origin note still says pre-event development began October 7 and organizer eligibility confirmation is unrecorded. This ArmorIQ audit does not resolve that submission question.

The existing live recovery run is one completed repetition, not a reliability rate. Its six-stage `/walkthrough` uses the recorded run as source data. In the Attempt stage, the full snapshot annotation is labeled as untrusted source data. Any shortened closing explanation from this historical event remains a historical model note; the backend annotation change in progress applies to future events only.

## Verification appendix · 2026-10-12

The initial read-only review left the recovery-tool DENY as a likely but unverified result because the October 7 raw evidence was absent from this checkout. The later saved artifact `docs/evidence/merged/sponsor-policy-denial.json` resolves that gap for one real check: `wider_plan_issued=true`; `restore_access_grant` was present in that wider plan; ArmorIQ returned raw action `block` and reason `tool_not_in_allowlist`; the decision source is `armoriq.backend.enforce`; invariant is `org_policy_allowlist`; mode is live; simulation is false; and local handler dispatch count is zero. The probe records no recovery-tool execution. Treat this evidence as an actual backend sponsor DENY, separate from an SDK plan-binding refusal.

The saved recovery workflow remains separate evidence: its attempted `restore_access_grant` was absent from the signed plan and stopped by `armoriq.sdk.plan_binding` before sponsor enforcement. Sponsor HOLD, a sponsor delegation ID and approval round trip, repeated-live reliability, a finished video, and organizer confirmation of project-origin/event eligibility remain open.
