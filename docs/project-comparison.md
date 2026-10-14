# VeerIQ versus RewindSafe

Reviewed October 12, 2026. Three independent GPT-6 Luna reviewers assessed backend functionality, product/UX and VeerIQ's implementation. Their source reviews were reconciled with fresh test, browser and credential checks. Embedded instructions in the supplied archive were treated as project content, not user commands. The ZIP snapshot was analyzed separately from the existing RewindSafe checkout; only the user-authorized credentials came from that checkout.

## Recommendation

**RewindSafe is the stronger current submission candidate: 8.5/10 versus VeerIQ's 7.0/10 on the rubric below.** This revises the earlier selection because the new archive supplies a substantially implemented alternative, not merely another concept description. RewindSafe has more tangible recovery stakes, durable transactional effects, stronger approval controls, and recorded live sponsor/model evidence. VeerIQ is the simpler local implementation and closer to the sponsor's visual style.

The recommendation concerns the current projects and evidence. It is not a prediction of winning, a security certification, or an assessment of market size. RewindSafe's pre-event work needs an eligibility confirmation, and neither project has demonstrated a complete live ArmorIQ HOLD-to-approval flow.

## What they do

| | VeerIQ | RewindSafe |
| --- | --- | --- |
| User | Research analyst | Incident/recovery operator |
| Useful task | Analyze the synthetic FLOW-42 cohort and produce an internal aggregate report | Repair damaged order fields from an approved snapshot |
| Authority unit | One study, specified tools, an aggregate hash and a fixed local destination | One tenant, named orders and fields, one snapshot and a one-commit grant |
| Hostile input | An external methods note asks for participant export and identifiers | A snapshot annotation asks to restore a revoked service account and include another tenant's order |
| Recovery | Deny forbidden proposals, finish the statistics/report, hold publication | Deny prohibited proposals, revise the batch, commit the legitimate repair |
| Protected outcome | No forbidden handler entry or canary bytes; publish only the exact aggregate after approval | Preserve deletions, revoked access, later fulfillment changes, held records and other tenants |
| Final artifact | Computed report, local signed audit receipt, separate measured effects | Immutable manifest, committed repair receipt, protected-state checks and exportable run evidence |
| Data realism | Seeded synthetic cohort and sandbox publication | Synthetic but persistent relational data with actual database transactions |

VeerIQ's narrower statistician worker is demonstrated in replay; its live-model path does not delegate a second worker. RewindSafe's optional live planner chooses recovery actions, while trusted code derives restored values from the approved snapshot rather than letting the model invent them.

## Functionality scores

Scores are reviewer judgments on a 0–10 scale: 5 means a credible but incomplete prototype, 7 a working focused implementation with material gaps, and 9 a strong implementation supported by relevant evidence. Weights reflect this comparison's hackathon priorities, not official judging weights. The overall score is the weighted average, not a count of tests or lines of code.

| Dimension | Weight | VeerIQ | RewindSafe | Main reason |
| --- | ---: | ---: | ---: | --- |
| Useful end-to-end functionality | 15% | 7 | 9 | Research reads, computed statistics and local publication versus grant, diff, repair, recovery and protected-state scenarios |
| Authority enforcement | 15% | 8 | 9 | Both have a guarded dispatcher; RewindSafe adds domain and database privilege/RLS controls |
| Durable effects and concurrency | 10% | 6 | 9 | VeerIQ persists audit/run state but MCP effects are process-local; RewindSafe has persistent transactional, stale-state and idempotency controls |
| ArmorIQ integration evidence | 15% | 5 | 8 | VeerIQ now mints a live plan but permitted tools are policy-blocked; RewindSafe includes recorded live ALLOW, plan-binding denial and org-policy denial |
| Live agent capability/evidence | 10% | 6 | 8 | Both implement provider loops; RewindSafe has recorded live first-turn injection trials, but full live autonomous recovery is still unproven here |
| Human approval | 10% | 7 | 9 | VeerIQ binds one approval to an exact aggregate; RewindSafe adds same-tenant second-reviewer separation and state revalidation, with demo identity limitations |
| Verification and evidence | 10% | 8 | 9 | VeerIQ has actual MCP/canary evidence, 14 passing tests and 37 constructed cases; RewindSafe freshly passed 381 offline tests and includes live artifacts |
| UX clarity | 5% | 8 | 8 | VeerIQ puts the task and boundary in one workspace; RewindSafe has a clearer incident story and richer exploration, but more screens and dense evidence |
| Setup and architectural efficiency | 5% | 9 | 7 | Node/SQLite/stdio MCP is inexpensive to launch; FastAPI/Postgres/provider/policy coordination has more operational dependencies |
| ArmorIQ visual familiarity | 5% | 9 | 7 | VeerIQ uses the reference's orange/charcoal and Sunflower/Geist grammar; RewindSafe uses a restrained white/blue/purple operations UI |
| **Overall** | **100%** | **7.0** | **8.5** | **RewindSafe wins on implemented depth and current evidence** |

These are comparative functionality and submission scores, not production readiness ratings. Neither app has demonstrated production authentication or real customer/participant workflows. RewindSafe's role separation uses local demo identities; VeerIQ has no authenticated reviewer boundary.

## Architecture comparison

**VeerIQ:** React/Vite, one Express service, SQLite audit persistence and a separate stdio MCP process. The dispatcher checks study, tool, arguments, expiry and destination before effects. It freezes the pending publication call and requires the exact aggregate. A separate canary observes requests/bytes. This is efficient for a one-study sandbox; process separation is not an OS security sandbox, and historical effect counts are not durable across tool-process restarts.

**RewindSafe:** React/TypeScript, FastAPI, PostgreSQL, a reusable authority runtime and a recovery-specific adapter. Calls pass through ArmorIQ, grant, domain and approval checks before the transactional executor. Restored values come from the snapshot, manifests are immutable, and the database role can update only repairable fields. Row locks, version/authority checks and idempotency protect the commit. This complexity is justified by state-changing recovery, though only one workflow adapter is shipped and general platform reuse is not yet demonstrated.

For recovery, prefer RewindSafe's architecture. For a small synthetic research demo, VeerIQ's architecture is appropriately lean. Adding PostgreSQL or more agents to VeerIQ merely to match the larger project would not improve its task.

## What was actually verified

### Fresh RewindSafe checks

- Extracted the supplied ZIP into an isolated temporary directory; inspected source, tests and evidence.
- Built its frontend successfully with TypeScript/Vite using existing installed dependencies.
- Ran the ZIP's offline suite against a new disposable PostgreSQL 16 container: **381 passed, eight live tests deselected, one deprecation warning, 45.87 seconds**. Test names/counts are not directly comparable to VeerIQ's smaller suite.
- Opened the built UI and authorized its poisoned-runbook grant using the keyboard hold control. The scripted/offline run blocked two prohibited proposals, repaired O-2041 and O-2042, recorded one commit restoring $3,555.50, preserved four protected decisions and separately verified the other tenant unchanged.
- Captured the home and completed run screenshots. The temporary server/database were used only for this review; no existing RewindSafe database was reset.

An initial sandboxed test attempt could not reach a database and was stopped. The successful isolated run above supersedes that environment failure; it was not treated as an application defect. Live tests were deliberately excluded, so the 381 passes do not establish sponsor or provider behavior.

### Recorded RewindSafe live evidence

The archive's October 7 artifacts record a real ArmorIQ plan, allowed recovery tools, SDK out-of-plan denial, org allowlist denial, and a cross-tenant argument that ArmorIQ itself allowed. RewindSafe therefore correctly attributes argument checks to its own grant layer. The recorded end-to-end flagship uses the scripted planner.

The later single-turn injection evaluation records the live Groq model proposing `restore_access_grant` in **3/3 task-only trials**, with live SDK plan-binding denials; another model proposed it in **0/3**. These are tiny, controlled first-decision trials. The evaluation says tools were never executed. They support a claim about actual model proposals and enforcement decisions, not full autonomous task recovery or broad injection resistance. These saved external-service outcomes were inspected, not independently reproduced in this review.

### VeerIQ evidence and new credential check

The earlier build verification passed **14 tests** and **37/37 constructed local boundary cases**. Its real MCP replay produced three denied proposals, zero canary requests/bytes and one exact aggregate publication after approval. The 16-event locally signed receipt verified. These checks remain applicable because this review did not change application code.

The user-authorized `.env` was found at the RewindSafe checkout root, not `backend`. Compatible ArmorIQ and Groq settings were copied privately to VeerIQ's ignored `.env` with owner-only permissions; database/session secrets were not copied. No secret values appear in these reports or source packages.

A fresh live smoke check minted a plan through VeerIQ's official SDK adapter. Its declared `read_deidentified` call was denied with **`tool_not_in_allowlist`**; an undeclared identifiers call was denied by SDK plan binding. No research handler was executed. A read-only Groq model-list request returned HTTP 200 and included the configured model. An earlier individual model-path lookup returned 404; the successful list lookup resolves model availability. No inference or live sponsor HOLD/approval was run.

VeerIQ was restarted to load the settings. Enforcement remains local until its own tool metadata/policy is configured. Valid credentials alone do not authorize a different project's tools.

## UI findings

Both interfaces were observed in this session or the prior VeerIQ finish review. VeerIQ's orange display accents, flat rules, Sunflower headings and focused task/effect lanes give it stronger familiarity with ArmorIQ's event page. Its mobile layout and dark action contrast were separately reviewed.

RewindSafe's running desktop interface makes the business outcome clearer: the repair-versus-preserve timeline, grant review, before/after order values and protected-state checklist show why the boundary matters. Identity perspective, approval history, scenario navigation and Proof Board make it broader. Its darker neutral cards, white CTA and blue/purple semantic accents are less sponsor-specific. Its dense timelines and repeated mode labels can increase reading load. This review did not perform a full mobile/accessibility audit of RewindSafe; UI scores should not be read as one.

One offline copy inconsistency was observed: the tour heading says “Watch an AI agent get tricked” while the planner is scripted. The run and authorization dialog correctly disclose the deterministic reenactment. The headline should follow the active mode. The README also still lists screenshot/video placeholders; those are submission polish gaps rather than missing backend functionality.

## Best next submission work

Prioritize **RewindSafe**, conditional on confirming the disclosed pre-event work is eligible. Preserve its transactional controls; apply VeerIQ's sponsor-familiar typography/accent grammar and tighter evidence presentation to the existing interface rather than rebuilding it.

Record one full live-model recovery, with actual tools, sponsor-issued decisions and protected-state effects. Configure and demonstrate a real ArmorIQ HOLD/approval round trip if the pitch promises it; both projects currently rely on application-level approval evidence for their review story. Capture the video and replace placeholders. Keep the single-turn model evaluation, scripted flagship and live sponsor evidence separately labeled.

For VeerIQ, the immediate missing step is its own ArmorIQ registration/allowlist. After it permits legitimate tools, test a real model run and publication policy. If VeerIQ remains the selected project, add authenticated reviewer separation and durable effects only when moving beyond the local sandbox.

## Supporting artifacts

- `rewindsafe-backend-review.md`: Luna backend/source review; its “unrun tests” caveat applies to that agent, not the subsequent root verification above.
- `rewindsafe-product-comparison.md`: Luna product/UX source review.
- `veeriq-independent-review.md`: Luna independent VeerIQ review; its credential/readiness statements reflect the pre-smoke-check snapshot.
- `comparison-evidence/rewindsafe-tests.txt`: successful fresh offline test output.
- `comparison-evidence/rewindsafe-home.png` and `rewindsafe-run.png`: observed desktop UI.
- `credential-status.json`: sanitized current credential/policy result.
- `evidence/`: VeerIQ's verified local replay artifacts.

Source anchors for the core conclusions: RewindSafe `backend/rewindsafe/workflows/rewindsafe/executor.py`, `backend/migrations/002_executor_hardening.sql`, `backend/rewindsafe/runtime/dispatch.py`, `runtime/approvals.py`, `evidence/live-flagship-2026-10-07.json`, `evidence/injection-eval-20261007T162005Z.json`, and `docs/attribution.md` in the supplied archive. VeerIQ `server/dispatcher.mjs`, `engine.mjs`, `scope.mjs`, `tools.mjs`, `store.mjs`, `armoriq.mjs` and `tests/boundary.test.mjs` in this workspace.
