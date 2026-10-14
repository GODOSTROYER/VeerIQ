# VeerIQ readiness progress

## Acceptance policy
Scores describe observed evidence, not a promised 10/10. Live means a real service response captured during this work. Offline/scripted modes retain labels. No retry or adapter may widen an authorized grant. Private keys and credentials remain excluded from Git and packages.

## Initial inspection
- Read README, current architecture, dispatcher, adapter contract, auth, planner retry loop, and origin limitations.
- PROGRESS.md and active docs/limitations.md were missing; docs/architecture.md still described the archived research app. Active architecture is FastAPI/React/PostgreSQL.
- Baseline: 385 passing tests, 8 deselected; latest suite took 39.72 seconds, not 35 minutes.
- Guarded effects: registry/schema and lifecycle, ArmorIQ, grant, domain, review, revalidation, adapter executor and restricted database role. Operator-only synthetic reset/positive-control routes are separate privileged administrative paths; they are not agent repair bypasses.
- Restored values are derived from the approved snapshot in trusted code.
- Five prepared order scenarios and signed local Ed25519 evidence are present.
- Live credentials remain private; configured ArmorIQ SDK mode and Groq default model will be checked without printing secrets.
- Local Git initialized from the previously verified source bundle, baseline commit 946d6a6. New commits follow acceptance checks. This is new local history, not proof of original project dates.

## Work items
| Item | State | Verification / evidence |
|---|---|---|
| Reliability eval and bounded retries | In progress | 40-trial cohort finished: 40 provider-rate-limit failures, 0 repairs, 0 poisoned proposals; zero effects does not establish adversarial robustness. evidence/reliability-20261012T160152Z.json; higher daily quota required |
| Own-data import and second adapter | Verified sample runtime | 63 focused import/API tests passed; live scripted import run_01M4RCWFEGB344NY repaired SKU-402 and preserved later edit SKU-512; signed export docs/evidence/merged/import-live-sealed.json verified offline |
| Live ArmorIQ HOLD / approve / reject / timeout | Blocked by dashboard capability | User confirmed amount condition unsupported; isolated $12,400 call returned live ArmorIQ ALLOW (docs/evidence/merged/hold-rule-first-check.json) |
| Standalone offline verifier | Passed standalone acceptance | 6 verifier acceptance tests passed; verification/samples/ valid and tampered exports, pinned public key; UI download links added |
| Accessible judge flow / screenshots / video | Accessibility/screenshots/video recorded | docs/evidence/ui-audit.json; 24 real captures in docs/img; independent manual reader-flow review passed |
| Auth, deployment, CI, observability | Implemented; external login pending | 9 auth tests passed; production image built; isolated Compose Postgres healthy, API correctly rejected unreachable synthetic issuer; real issuer and hosted CI pending |
| Why this matters | Quantified read-only fixture comparison | Four synthetic harms derived from actual fixture snapshot/current values; docs/evidence/blunt-restore-counterfactual.json; GDPR Article 17 and NIST least privilege links |

## External acceptance limits
- Real first-time human usability test requires a participant; an independent agent review is not a substitute.
- Hosted CI cannot be called green without a real run. Local checks alone are labelled local.
- Sponsor approval requires your dashboard action after a real delegation appears.
- Existing-project eligibility remains an organizer question.

## Latest checks
- Dispatcher SHA-256 remains 3394bc0cda48cc14b879705bae2086e33ad0fabf2d21c6bf4f71ddbf918cb2a2, equal to the baseline.
- User requested manual pacing on /how. Replaced the automatic gate timeline with Start request, Next check, Previous step and restart controls; keyboard, desktop/mobile, reduced-motion and pause persistence checks passed. Audit: docs/evidence/ui-audit.json; six pages have zero serious/critical axe findings and no overflow at 1280/1440/1920/390 px.

- Verifier discovered and corrected global PostgreSQL event allocation: a run can begin above 1 or have gaps from concurrent runs. It requires strictly increasing IDs, matching chain nodes, signed count/head and linked digests; it does not assume per-run allocation. New live-import export passes.
- Offline verification commit 821dd85 and global event verification correction bb33ad4 passed 6 checks; manual pacing commit 017be44 passed keyboard and responsive review.

## 2026-10-12 continued acceptance work
- Full local backend suite: 418 passed, 1 optional TLS integration skip, 8 live tests deselected, 42.88 seconds. A separate verified-TLS read-only PostgreSQL source acceptance run passed; docs/evidence/merged/import-postgres-tls.json documents its simulated ArmorIQ/scripted source.
- Recorded 44-second import/verifier demo: docs/video/veerIQ-demo.webm. Sponsor HOLD is explicitly unverified in the video.
- Import UI now maps each of four authority flags to source headers and invalidates a previous preview when the PostgreSQL source changes. Frontend type check/build passed. Backend source metadata and custom-header acceptance work remains underway; final integrated revalidation is still required.
- Updated architecture and limitations to distinguish JSON-key enforcement in trusted code from physical database privileges, and to disclose quota, sponsor, provider, hosted CI, and human-test gaps.

- Refreshed six-page accessibility audit after authority mapping UI: zero serious/critical issues, no overflow at 1280/1440/1920/390 px; manual progression/reduced-motion checks passed. Fresh captures saved.
- Re-ran six standalone verifier acceptance checks successfully; dispatcher hash matches baseline and Git diff is empty. Recorded verifier UI evidence committed as 5da47e4.
- Added README judge path, explicit Not claimed section, evidence-backed scorecard/submission claim and requirement-by-requirement acceptance audit. Scores remain provisional until final integrated acceptance finishes.

- Final integrated local suite after metadata/authority alias changes: 419 passed, 1 optional external TLS skip, 8 live tests deselected in 45.83 seconds. Correctness lint passed. Artifact: docs/evidence/integrated-checks.json.

- Import focused acceptance: 63 passed with positive verified-TLS source configured; human-readable headers/custom authority aliases/source metadata protection verified. Separate commits: reliability 82bf1ae, imports 17be62e, auth/deploy/CI/observability da6d181. External live acceptance gaps remain explicit.

- Refreshed final demo: 41.76 seconds, actual run run_01M4RFW72HSC79XG succeeded with scripted planner/live ArmorIQ, two repaired fields, one commit, all 16 protected-state checks held. Evidence docs/evidence/video-recording.json.

- Real rendered grant modal keyboard acceptance passed: early release cancels, long Enter hold triggers exactly one intercepted request, no repair started, reduced motion enabled, zero serious/critical modal axe issues. Artifact docs/evidence/hold-keyboard-audit.json; reproducible frontend/scripts/hold-audit.mjs.

- Source packaging is reproducible via scripts/package_submission.py, excludes private PEM blocks/local credentials, and includes unpack/start instructions. Working tree was clean after verified commits.
- User requested that we conduct the first-view check ourselves; dispatched a fresh GPT 6 Luna reviewer with no conversation history or code access, tasked with browser-only comprehension/timing. This remains an agent review, not a human acceptance claim.

- Fresh browser-only Luna review completed; approximate 90-second comprehension, no fresh run because incident was repaired. Report docs/evidence/agent-first-view-review.json explicitly labels agent rather than human observation.
- Fixed landing discoverability: incident cause visible by default; prepared/repaired state, role guidance, poisoned-note detail control and walkthrough link are explicit. Build passed.
- Review exposed missing per-check historical import detail: existing receipts store changes with checks=[], and finish events previously stored only summary/counts. Added immutable recorded run-end check details for future events; old runs must remain marked detailed checks unavailable. Eighteen lifecycle checks passed, including persistence when current adapter state changes. Integrated regression underway.

- Continuation: reviewer agent hit its usage limit mid-fix; root is finishing the run display. Integrated regression now 420 passed, 1 optional TLS skip, 8 live tests deselected in 44.19 seconds. New checks are labelled end-of-run observations; older import runs remain explicit about missing detailed historical verification.

- Fresh run run_01M4RV8W669EWXB0 succeeded with live ArmorIQ/scripted planning and persisted all 18 preserved end-of-run checks. Signed export docs/evidence/merged/import-recorded-checks-sealed.json verifies offline (36 linked events, 2 receipt digests).
- Browser acceptance confirms new historical checks and repaired SKU values; legacy run stays Not recorded. Artifact docs/evidence/run-ui-verification.json. Extended axe/responsive audit to eight views (32 captures); corrected faded gate-text contrast, now zero serious/critical issues or overflow. Refreshed video is 43.12 seconds.

## Fresh live diagnostic — 2026-10-13

Default Groq model, task_only, one isolated trial completed without fallback. It attempted restore_access_grant once, blocked by live ArmorIQ plan binding, and completed the permitted repair with zero forbidden effects. Seven model calls used 19,998 input and 628 output tokens in 103.82 seconds. Evidence: evidence/reliability-20261012T201737Z.json. The 1/1 Wilson 95% interval (20.7%–100%) does not satisfy the multi-trial reliability acceptance criterion. No quota/account settings changed.

## Judge-facing refinements and downloaded sample acceptance

The landing incident now appears without expansion, scenario details name the poisoned note clearly, and imported grants and runs use record units. The independent GPT 6 Luna review is labelled an agent review, not a human study. Historical checks are captured at run completion; legacy runs without detail do not inherit current-state proof. Eight-view accessibility audit has zero serious/critical findings and 32 responsive captures. Frontend build passed.

The actual downloaded warehouse ZIP was uploaded as three files through the browser, mapped with bundled sample metadata, authorized and repaired in 15.7 seconds. One live-ArmorIQ/scripted commit, zero forbidden effects; docs/evidence/sample-upload-flow.json. This is automated timing, not first-time human timing. Full backend suite: 420 passed, one skipped, eight live checks deselected; dispatcher unchanged.

## Hosted CI first-push correction

GitHub run 38310643603 passed test-build (PostgreSQL tests, frontend build and production image). Secret scan failed because the action used the root commit's nonexistent parent. Replaced it with pinned Gitleaks 8.24.3 full-history scanning. Corrected the version-compatible allowlist syntax and retained default detection rules. Reviewed 147 historical findings: 138 public token IDs, three public-key digest outputs, one idempotency hash, four synthetic fixture findings and the scanner's regex. Exact fingerprints recorded in .gitleaksignore; no new arbitrary findings ignored. Local full-history scan of 17 commits passed with redacted output. Hosted rerun pending.

## Hosted CI acceptance observed

GitHub run 38434801253 at commit b02387b succeeded: correctness lint, PostgreSQL backend tests, frontend type/build, production image build and full-history secret scan. Live-service checks explicitly skipped, not claimed. Evidence saved in docs/evidence/hosted-ci.json with job/step timing. Earlier backend test step took 65 seconds on hosted Ubuntu. Real OIDC login, healthy authenticated production stack, sponsor HOLD, statistically meaningful live reliability and independent human usability remain outstanding. Public here.now static demo and repository links documented separately; no claim token committed.

## Public-download verification and hosted claim refresh

The here.now walkthrough now links the observed green CI and source repository. Same site updated incrementally; no duplicate or expiration extension. Actual public downloads of standalone verifier, key and both exports were tested offline: authentic export passed signature/hash/35-event chain/two receipt digests; tampered copy failed with payload digest mismatch. docs/evidence/hosted-publication.json records this evidence. Anonymous claim token remains private, expiry unchanged.

## Resumed toward remaining acceptance — 2026-10-13

Added GitLab’s primary-source 2017 postmortem to the landing incident and README, distinct from the four synthetic blunt-restore harms. The precedent describes older-snapshot recovery and unrecoverable later database changes, not revoked-access resurrection or a claim VeerIQ could recover absent data. Evidence: docs/evidence/problem-precedent.json. Frontend build passed; eight-view audit zero serious/critical and no overflow, captures refreshed. Problem/usefulness original acceptance now met; score10, average8.4.

User confirmed no OIDC provider and no Groq quota change. Fresh short-request live probe passed with TPM8000 but no daily-cohort capacity evidence (`evidence/groq-capacity-recheck-20261013.json`). Token audit found safe formatting savings insufficient for roughly825k-token full40trialcohort under200kTPD. Preparing checkpointed batching without shrinking the cohort; scheduling awaits explicit user response. Preparing a real disposable Keycloak/TLS full-stack rehearsal without production auth exceptions or system trust changes.

## Checkpointed full-cohort reliability collection

Added bounded invocation and stop-on-rate-limit options while preserving 20 trials per briefing, the original full 40-trial target, full poisoned content and unchanged execution path. Resume requires the same configuration and evaluator checksum. Failed completed attempts are retained; interruptions remain in separate history and prevent a blanket zero-effects claim. Partial evidence reports pending coverage and receives no finished timestamp. Eleven focused tests passed. The initial batching version passed 424 integrated tests in 53.15 seconds; final checksum/history guard suite recorded separately. Instructions: docs/reliability-batching.md. No recurring job scheduled without user response.

## Real local OIDC deployment and per-workspace signing key

Dedicated Compose API/UI, PostgreSQL, Keycloak and TLS proxy healthy. Three actual browser logins plus HTTPS form/code/PKCE exchanges verified secure HttpOnly sessions, token/issuer/nonce/audience validation, server-mapped roles/tenants, cross-tenant 404, role denials and blocked demo impersonation. Separate fixture reviewer approved a payload-bound scripted/offline repair. Application UID10001; private signing key mode0600. Original preview DB and system trust store untouched. Evidence: docs/evidence/local-oidc-rehearsal.json.

Added authenticated public-key download for the current persistent signer, stable across calls and matching signed exports. A real OIDC-authenticated export and public key from the dedicated container passed standalone verification: 42 linked events, two receipt digest occurrences and valid signature. Key delivered by authenticated transport is not independent attestation. Six focused tests passed. Browser contexts alone ignored local self-signed certificate errors; backend verified the mounted certificate. Keycloak dev mode, local fixture identities and offline ArmorIQ are labelled; no public production claim. Production readiness8, current average8.5.

## 2026-10-13 final verification and manual evaluation preparation

Final backend suite: 433 passed, one skipped, eight live checks deselected in 45.64s. Dispatcher remains unchanged. Local real Keycloak login, separated reviewer approval, container sample downloads and public-key export verified; this is a local rehearsal, not public production auth. Complete axe ruleset passed eight views with zero serious/critical issues.

Pre-fix live diagnostic: 5/6 completed, zero forbidden effects (`evidence/reliability-20261013T172610Z.json`); partial-manifest failure preserved and diagnosed. Bounded planner completeness feedback added without authority expansion. Post-fix collection: 1/40 successful, zero forbidden effects, 39 pending (`evidence/reliability-20261013T175457Z.json`). Manual resume prepared; user explicitly declined scheduling. No further live LLM calls planned today.

Live ArmorIQ audit response now retains explicit canonical audit IDs. A scripted live repair produced five IDs and a signed export (`docs/evidence/merged/audit-linked-scripted-live-sealed.json`), verified with the published operator key. This is operator-signed integrity with server-returned IDs, not sponsor attestation or a live HOLD round trip.

## 2026-10-14 hardening and submission pass

Hardening, not yet committed at time of writing (working tree on `hackathon-hardening`). Production profile: `REWINDSAFE_ENV=production` refuses to start without OIDC sign-in and live ArmorIQ enforcement; demo-only routes return 404; `compose.production.yml` requires `ARMORIQ_API_KEY`. MCP HTTP requires `REWINDSAFE_MCP_TOKEN` on non-loopback hosts and checks the bearer token when set.

Migration `006_evidence_append_only.sql`: `runtime.events` and `runtime.receipts` append-only; task grant scope frozen after creation; commit count cannot decrease; closed grant cannot be reactivated; draft cannot become active without an authorizing identity. Migration adoption refuses a partial schema.

Dispatcher enforces `maxItems`, `maxLength` and `maximum` from tool schemas. `dispatch-baseline.sha256` no longer matches `runtime/dispatch.py`; the "unchanged dispatcher" wording is corrected in the docs.

ArmorIQ gateway refuses an allow with a non-2xx status; a test keeps `armoriq/armoriq.yaml` and the offline simulator in step. Evidence verification reports `valid: false` when a pinned key does not match the signer, and reports `trust_basis`.

Import: refuses empty manifests before the single commit; re-derives restore values from digest-covered source records; locks authority rows during apply. Agent-facing snapshot view masks customer email addresses.

Tests: backend suite 525 passed, 1 skipped (needs external TLS PostgreSQL), 8 live tests excluded, run locally on PostgreSQL 16 (Windows 11). Hosted CI has not run on these changes.

Pooled reliability: `python scripts/summarize_reliability.py` writes `evidence/SUMMARY.json`. 84 trials across six batches: acted 24; poisoned action attempted 23, all 23 blocked by ArmorIQ plan binding; repairs completed 18; forbidden effects 0; never acted 60 (2 operator interruptions). Batches recorded on different code versions. No batch finished its 40 requested trials.

Post-fix cohort `reliability-20261013T175457Z.json` (1 of 40) cannot be resumed: the evaluator fingerprints the enforcement source files, which changed on 14 October. A new cohort must start on the current code.

Docs: attribution rewritten from this repository's history (earliest commit 12 October; `125bfc8` and `247feb5` absent here; origin paths fixed; dependency table checked against the manifests). Limitations, readiness scorecard and acceptance audit brought in line with the pooled counts, dispatcher wording and test counts. README, submission write-up and demo script rewritten to the same facts.

Outstanding: hosted CI on these changes; fresh live cohort on the new code; live-model demo video (the current demo uses the scripted planner); ArmorIQ hold/approval (not observed live); organizer confirmation of pre-event work (not recorded); making the repository visible to judges.

## 2026-10-15: aligned with the Flow State rules

Rules from the organizers' Discord: an AI agent, at least one MCP server for real actions, ArmorIQ allowing one action and blocking another for real, agents and MCPs onboarded on platform.armoriq.ai, a 3–5 minute video showing the ArmorIQ console and Policy Studio, a live demo working 17–21 October, and takeaways.

MCP: the built-in agent called the dispatcher in-process, so the MCP server was only a bring-your-own-agent path. New `rewindsafe/agent/mcp_agent.py` runs the same planners against the `rewindsafe-recovery` MCP server; every action is an MCP `tools/call`, and the server enforces ArmorIQ, the grant and the database rules (`source="mcp"`). `python tasks.py demo-mcp-agent` spawns the server over stdio; `--url` connects to a streamable-HTTP server. Verified locally with a real stdio subprocess (offline ArmorIQ simulation, no key on this machine): `restore_access_grant` blocked, B-3002 blocked by grant scope, repair committed, all protected checks hold. The MCP server now also lets a run read its own receipt after spending its one commit.

Live demo: `REWINDSAFE_ENV=showcase` allows demo sign-in on synthetic data but refuses to start without live ArmorIQ, a strong session secret and HTTPS-only cookies. `compose.showcase.yml` runs it; `docs/live-demo.md` covers HTTPS and the checklist.

Docs: README requirement table and MCP section; `docs/submission.md` rewritten to the form fields with takeaways, next steps and a social post draft; `docs/demo-script.md` rewritten as a 4-minute script covering the console and Policy Studio.

Tests: 532 passed, 1 skipped, 8 live deselected (PostgreSQL 16, Windows 11).

Outstanding for the team: ArmorTools Pro for every member (FLOWSTATEPRO); a platform.armoriq.ai API key in `.env` and `python tasks.py armoriq-register`; the Policy Studio rules; a live `demo-mcp-agent` run; hosting the showcase until 21 October; recording and uploading the video; the social post; the submission form by 17 October, 11:59 PM IST.
