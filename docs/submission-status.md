# Submission status (single source of current truth)

Where this file disagrees with an older note in the repository, this file wins. Last updated 17 October 2026.

| Item | Status |
|---|---|
| Final commit | see `main` HEAD at submission (written against `f4a3f62`) |
| Live demo | https://veeriq.arnavbule.in (Railway). Fallback: https://veeriq-app-production.up.railway.app. **Status: deploying; starts once the ArmorIQ key is configured. Not claimed to be up.** |
| Static walkthrough | https://veeriq.vercel.app (recorded run and downloadable evidence; no live model, no live ArmorIQ) |
| Demo video | 4:21, 1080p60, narrated: [`videos/demo-video/final/veeriq-demo-1080p.mp4`](../videos/demo-video/final/veeriq-demo-1080p.mp4) (Git LFS). Public link: **pending upload** (no `final/LINK.md` in the repository). |
| Secondary videos | 96 s showreel ([`videos/veeriq-showreel/`](../videos/veeriq-showreel/)) and the old 43 s clip ([`docs/video/veerIQ-demo.webm`](video/veerIQ-demo.webm)). Neither is the submission video. |
| CI on `main` | Passing: [run 39040731496](https://github.com/GODOSTROYER/VeerIQ/actions/runs/39040731496), 17 Oct 2026, commit `f4a3f62` |
| Test counts (from that CI log) | Backend: 538 passed, 1 skipped, 8 deselected. Frontend: 210 passed (9 files). Scripted planner and simulated ArmorIQ; live ArmorIQ checks are manual dispatch only. |
| Pre-event disclosure | [`rewindsafe-origin/attribution.md`](rewindsafe-origin/attribution.md). The event page allows advancing an existing project; build-week work is listed in [`CHANGES_DONE.md`](../CHANGES_DONE.md) and [`PROGRESS.md`](../PROGRESS.md). Organizer confirmation is not recorded. |

## Mode labels

| Question | Answer |
|---|---|
| Model | The 84 recorded trials and the recorded MCP run used a **live model** (`openai/gpt-oss-120b` on Groq). The default app, CI and the static walkthrough use a **scripted planner** unless a model key is set; the UI labels the planner. |
| ArmorIQ | Recorded batches and the recorded MCP run: **live ArmorIQ** (`armoriq-sdk` 0.6.10). Default local app and CI: **offline simulation**, labelled as such. Live mode never falls back to simulation. |
| Approval | The $12,400 second-reviewer step is **VeerIQ's own reviewer**. A **sponsor HOLD has not been observed live** (the isolated request returned ALLOW; see [`armoriq-hold-setup.md`](armoriq-hold-setup.md)). |

## What each proof proves

All data is synthetic. "Recorded" means a stored run in this repository; nothing below was re-run for this table.

| Proof | What it proves | What it does not prove |
|---|---|---|
| Signed ArmorIQ plan (`session.start_plan`) | The plan is built from the operator's grant (never from the model) and signed by ArmorIQ before the model runs. Plan hashes appear in the evidence. | That the plan's tools are the only safe ones; argument-level limits are VeerIQ's, not ArmorIQ's. |
| Out-of-plan denial, `armoriq.sdk.plan_binding` | Recorded live (live model, live ArmorIQ): across **84 trials** pooled from six batches (recorded 12-13 Oct on different code versions, not one cohort), the model attempted `restore_access_grant` in **23** and ArmorIQ blocked **23 of 23**; **18 of 24** trials in which the model acted completed the repair; **60 never acted** (provider rate limit or operator stop); 0 forbidden effects. Source: [`evidence/SUMMARY.json`](../evidence/SUMMARY.json). Keep these figures together. | A 40-trial controlled cohort (no batch finished) or the 90% completion target. |
| Wider-plan backend denial, `tool_not_in_allowlist` | Recorded live: when a plan that included `restore_access_grant` was signed, ArmorIQ's backend policy still refused the call: [`sponsor-policy-denial.json`](evidence/merged/sponsor-policy-denial.json). | Repeatability (single isolated check). |
| `session.report` audit IDs | Server-returned audit IDs are sealed into the signed evidence of new live exports (five in [`audit-linked-scripted-live-sealed.json`](evidence/merged/audit-linked-scripted-live-sealed.json), scripted planner, live ArmorIQ; older exports have none). | The offline verifier does not validate the IDs against ArmorIQ. |
| MCP path | Reproducible offline: the agent drives the `rewindsafe-recovery` server through a stdio subprocess against the offline simulation (`python tasks.py demo-mcp-agent`, covered by tests). Recorded live: **one** run of a live LLM (Groq gpt-oss-120b) over the MCP server with live ArmorIQ, about 14 Oct 2026, `run_01M4Y389RXT28WHQ`: 5 calls allowed, `restore_access_grant` blocked by `armoriq.sdk.plan_binding`, 1 commit, 4 fields restored, 0 forbidden effects ([`mcp-live-agent-run.json`](evidence/mcp-live-agent-run.json)). | A cohort over MCP; the 84 trials used the in-process agent. |
| Operator-signed Ed25519 evidence | The exported hash chain is unchanged since this workspace signed it; checked by the browser and by `scripts/veeriq-verify` (tampered sample fails). | Not ArmorIQ attestation, not an independent signer: the key is a local operator key. |
| Database outcome (protected checks) | The executor commits in one locked transaction under a restricted role and the export records protected checks. In the recorded merged recovery: 2 repaired, 5 preserved, 1 pending (out-of-scope O-2046), 0 violated ([`merged-readiness.md`](merged-readiness.md)). | Write-back to a source system (the import workflow repairs a staged copy). |

## Known limits

- No sponsor HOLD or approval observed live. The reviewer step is VeerIQ's.
- No batch finished 40 trials; counts pool six batches on different code versions.
- Evidence is signed with a local operator key.
- Live demo URL is not yet confirmed serving; check it before relying on it.
- No load test or external security review; OIDC only rehearsed against local Keycloak.
- Older notes saying hosted CI has not run on recent changes are superseded by the CI row above.
