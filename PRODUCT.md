# VeerIQ · RewindSafe

<!-- impeccable:product-schema 1 -->

## Platform
Local web application: the VeerIQ recovery workspace, with a production profile. It repairs synthetic order incidents and user-supplied CSV, JSON or read-only PostgreSQL data. The local preview uses demo sign-in, a scripted planner and simulated ArmorIQ enforcement. The production profile requires OIDC sign-in and live ArmorIQ enforcement. It is not deployed publicly.

## Product purpose
Repair damaged values from an approved snapshot, while preserving legitimate current decisions such as later edits, deletions, holds, revoked access, and tenant boundaries.

## Users
Hackathon judges evaluating an acting agent and its authority boundary. The workspace models an incident operator and an independent reviewer through clearly labeled synthetic demo identities. Demo identities are for local use and are not production authentication. The production profile signs operators and reviewers in through OIDC; the operator maps each issuer subject to a VeerIQ identity, tenant and role.

## Product behavior
The agent inspects incident state, prepares an immutable repair manifest, and proposes only changes inside a task grant. In live mode, ArmorIQ signs a plan built from the grant and checks each proposed call against it. VeerIQ checks grant scope and current domain state, requires a second reviewer for repairs above $5,000, then revalidates and commits through a PostgreSQL transaction. Events and sealed run evidence make the decisions inspectable. The six-stage `/walkthrough` uses an actual recorded run as its source and presents incident, scope, attempt, boundary, repair, and proof in that order. Incident truth stays visible in three rows: what was repaired, what was blocked, and what was preserved or remains pending. Decision sources use plain labels, with detail available on demand. The import workflow applies the same checks to user-supplied data. It repairs a staged copy and does not write back to the source system.

## Architecture
One React/Vite frontend and FastAPI backend, PostgreSQL 16 for workflow state and transactional effects, and an optional isolated MCP server using the same dispatcher. Local setup selects scripted planning and offline ArmorIQ simulation. Live mode can use Groq, Anthropic, or OpenAI planners and the ArmorIQ SDK. The production compose file runs the app as a non-root, read-only container next to PostgreSQL, with OIDC and live enforcement required. Database migrations make run events and receipts append-only and freeze task-grant scope.

## Brand
VeerIQ is the product identity: charcoal surfaces, ArmorIQ orange accents, and Geist / Geist Mono / Sunflower typography. The interface makes proposed intent, enforcement decisions, approvals, and committed effects visible. Branding conveys familiarity with Flow State and does not imply sponsor endorsement.

## Evidence and limits
The recorded live run `run_01M4R4DB4JAY7ARM` used Groq `openai/gpt-oss-120b` and live ArmorIQ. It repaired four fields across two orders in one commit; the SDK's local plan binding stopped a revoked-access proposal because it was outside the signed plan. Its proof reports two repaired checks, five preserved checks, one pending check for O-2046, zero violated checks, zero forbidden effects, and zero prohibited-handler entries. A separate saved live probe received an actual ArmorIQ backend policy block for `restore_access_grant` after issuing a wider plan; it recorded no recovery-tool dispatch. The SDK refusal and backend denial are separate evidence.

Pooled across six recorded batches, the live reliability runs recorded 84 trials. The model acted in 24. It attempted the poisoned action (`restore_access_grant`) in 23, and ArmorIQ plan binding blocked all 23. The permitted repair completed in 18 of the 24 trials where the model acted. There were zero forbidden effects across all 84 trials. Sixty trials never acted, because of the model provider's rate limit or an operator stop. The batches were recorded on different code versions, so they are not one controlled cohort. Totals are in `evidence/SUMMARY.json`.

The ArmorIQ HOLD has not been observed live. The workspace dashboard could not apply an amount condition, so the second-reviewer step shown in the demo is VeerIQ's own control, not sponsor approval. The identities and records are synthetic. Evidence is signed with a local Ed25519 key and is not attested by ArmorIQ or an independent party. A 43-second recorded demo is in `docs/video/veerIQ-demo.webm`. The production profile has not been deployed publicly. OIDC was rehearsed against a local Keycloak; there has been no load test or external security review. Whether the pre-event work is eligible under the event rules is not resolved by this evidence; see `docs/rewindsafe-origin/attribution.md`.

This prototype is not a certified compliance system or general proof against prompt injection, and its production profile has not been deployed or independently reviewed.
