# Attribution and provenance

## Eligibility disclosure (pre-event work)

- **The earliest commit in this repository is dated 2026-10-12.** The history starts with one baseline commit of the existing project, `946d6a6` ("Record verified VeerIQ recovery prototype baseline"), which adds 342 files and 55,565 lines. That commit is dated inside the build window, so the split between pre-event and event-week work inside the baseline cannot be read from this repository's commits.
- **The two pre-event commits are not in this repository.** The earlier local history recorded `125bfc8` (2026-10-07 18:09 IST, baseline: contracts, schema, architecture contract) and `247feb5` (2026-10-07 19:09 IST, integrated build: runtime, domain, agent, API, frontend, tests, docs). `git cat-file -t` finds no object for either hash in this repository.
- **Pre-event work began 2026-10-07**, according to that earlier local history. The ArmorIQ Flow State build period is October 10-17 ([event-requirements.md](event-requirements.md)). The event page (Luma) allows teams to "build something new or push an existing side project further during the week", but neither source states a rule about work done before the window.
- **The team must confirm with the organizers** that advancing this existing project is permitted, and record their answer in [event-requirements.md](event-requirements.md). No answer is recorded there yet. Until confirmed, treat eligibility as unconfirmed.

### What existed before Oct 10 (pre-event)

According to the earlier local history, which is not in this repository: the shared contracts and database schema; the authority runtime and offline simulated gateway; the order-repair workflow (fixture, adapter, invariants); the scripted planner and agent loop; the HTTP API and MCP server; the React frontend; the offline acceptance and verification suites; the first live ArmorIQ probe and registration (`evidence/gate-a-early-live-2026-10-07.md`, which is not present in this repository). The early live ArmorIQ evidence is also dated 2026-10-07.

### Built during the event window

27 commits follow the baseline: 13 on 12 October and 14 on 13 October. Grouped by subject (hashes in brackets):

- **Offline verification.** Pinned-key verifier and tamper samples; event sequences checked against signed chain links; recorded valid and tampered exports; authenticated public-key download; a hosted walkthrough whose downloaded evidence was checked offline. (`821dd85`, `bb33ad4`, `5da47e4`, `8496c6d`, `f0231e0`)
- **Live reliability.** Bounded retries and cohort evidence; cohorts resumable across quota windows; incomplete model manifests rejected before dispatch; reliability wording marked provisional. (`82bf1ae`, `7a6f803`, `2b7a37f`, `91cfd5f`)
- **Imports.** Declarative snapshot imports with immutable authority and source metadata; Unicode headers read over a verified TLS PostgreSQL connection; protected checks and import receipts stored at run completion. (`17be62e`, `4cd7202`, `d4249cd`)
- **Identity, deployment and CI.** Fail-closed OIDC sessions, deployment CI and scoped observability; a local OIDC full-stack check with a persistent workspace signing key; hosted CI record and full-history secret scan; reproducible, credential-excluded submission packaging; PEM scanner fix; test cleanup waits for the readiness probe. (`da6d181`, `8496c6d`, `b02387b`, `c00b428`, `8d34b63`, `f31d1d3`, `ec5afd2`, `063263a`)
- **ArmorIQ evidence.** Explicit server-returned audit IDs kept in signed recovery evidence. (`01eafcf`)
- **Judge flow and claims.** Explanation advances through explicit reader actions; accessible judge flow and recorded demo; demo refreshed with a live ArmorIQ scripted import; keyboard hold cancellation; GitLab's 2017 postmortem added alongside four fixture-derived reversed decisions; readiness audit lists its gaps. (`017be44`, `40929f9`, `758c5c6`, `890373c`, `3fe3df9`, `170ebfa`, `523d46c`)
- **14 October hardening pass.** Not yet committed at the time of writing (working tree on `hackathon-hardening`): production profile; MCP token check for non-loopback hosts; append-only evidence migration `006`; dispatcher checks schema limits; ArmorIQ refuses allows with non-2xx status; pinned-key mismatch reported as invalid; import hardening; masked customer emails in the agent view. Details in `PROGRESS.md`.

## AI-assisted build

This project was built with substantial AI assistance (Claude Code orchestrating parallel build agents against a written [architecture contract](architecture.md)). Humans set the product direction, the contract and the acceptance bar and are responsible for the submission. The code, tests and docs were largely machine-written and then verified by running the test suite and the verification suite. The synthetic data (tenants, customers, orders, the poisoned annotation) is invented for the demo and describes no real company or person.

The runtime LLM planner is optional. With a key it uses Anthropic, Groq (OpenAI-compatible, default `openai/gpt-oss-120b`) or OpenAI, in that auto order; otherwise the deterministic scripted planner runs, which is a re-enactment and not a model. Every run labels which planner was used.

## Dependencies

Declared in `backend/pyproject.toml` (locked in `backend/uv.lock`) and `frontend/package.json` (locked in `frontend/package-lock.json`). Principal ones:

| Component | Used for |
|---|---|
| `armoriq-sdk` 0.6.10 | ArmorIQ signed plans, enforcement checks, approvals, audit reports |
| PostgreSQL 16 (`postgres:16-alpine` in `compose.production.yml`) | Application data, authority tables, runtime state, role privileges |
| psycopg 3 + psycopg_pool | Synchronous database access |
| FastAPI / uvicorn | HTTP API and SSE |
| pydantic / pydantic-settings | Contracts and configuration |
| cryptography (Ed25519), PyJWT | Evidence signing (`runtime/sealed_evidence.py`); OIDC token validation (`api/oidc.py`) |
| anthropic, openai SDKs | LLM planners. Declared as ordinary dependencies; used only when a provider key is set (Groq and OpenAI through the OpenAI-compatible client) |
| MCP Python SDK (FastMCP) | MCP server over the same dispatcher |
| pytest (dev group) | Backend test suite |
| React 18, react-router-dom 7, Vite 6, TypeScript 5.6, Tailwind CSS v4, motion 11, lucide-react | Frontend |
| Vitest, Playwright, @axe-core/playwright (dev) | Frontend test script (`npm test`) and browser accessibility checks |
| Geist, Geist Mono, Sunflower (`@fontsource` packages, self-hosted, imported in `frontend/src/main.tsx`) | Typography |

Check the manifests for exact versions and licenses; this table is a summary, not a lockfile.

## Prior art acknowledged

`pg_restore --no-acl` and similar tools restore data and can drop or reinstate privileges from a backup. RewindSafe does not claim to invent snapshot restore; the contribution is restoring selected values from a snapshot under a current-authority layer. See [limitations.md](limitations.md).
