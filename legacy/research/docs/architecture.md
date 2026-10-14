# Architecture and threat model

## Architecture choice

Use a **modular monolith with an isolated MCP process**. One Node 24 API owns orchestration, approval state and SQLite evidence; React/Vite presents the workspace; semantic MCP tools own effect execution. The official ArmorIQ TypeScript SDK is installed and used in live mode.

The research reports propose Python/FastAPI/DuckDB and several services. Those are credible options, but this MVP has one 240-row synthetic study and no analytical warehouse. A second application language, Redis, a durable job framework and four independently deployed MCP services increase setup and failure modes without improving the demonstrated authority boundary. Node’s built-in SQLite, ordinary functions, stdio MCP transport and SSE suffice. Move statistical tooling to Python/DuckDB when real research methods or dataset scale justify it.

The boundary principle follows established research rather than a new security algorithm. [CaMeL](https://arxiv.org/abs/2503.18813) motivates separation of trusted authority and untrusted evidence. ArmorIQ’s [SDK lifecycle](https://docs.armoriq.ai/sdk) provides explicit plan capture, signed token acquisition and pre-execution checks. This submission’s contribution is applying bounded authority to a useful study workflow and measuring whether forbidden effects actually occurred.

## Responsibilities

| Module | Responsibility | Boundary |
| --- | --- | --- |
| `scope.mjs` | Compile the fixed protocol; narrow worker scopes; check tools, study, destination, arguments and expiry | No model-driven authority expansion |
| `armoriq.mjs` | Per-user official SDK session; plan/token lifecycle; live check/report/close | No credentialless live fallback |
| `dispatcher.mjs` | One gate; freeze exact call; combine sponsor and domain decisions | Only explicit ALLOW invokes a handler |
| `transport.mjs` | stdio MCP client; separate loopback canary | No model-controlled outbound URLs |
| `tools.mjs` | Seeded dataset, stats, server-owned report, aggregate-only sandbox publication | API cannot directly import effect handlers |
| `engine.mjs` | Deterministic replay or bounded live-model tool loop; approval lifecycle | Model outputs remain proposals |
| `store.mjs` | SQLite run snapshots, hash-linked events and locally signed receipts | Records are inspectable; local signing is labeled |
| React workspace | Start, inspect, approve/decline, download receipt | Does not authorize by changing UI state |

## Execution sequence

```mermaid
sequenceDiagram
  participant U as Researcher
  participant E as Orchestrator
  participant G as Guarded dispatcher
  participant A as ArmorIQ (live only)
  participant M as Isolated MCP tools
  participant C as Independent canary
  U->>E: Analyze FLOW-42 and prepare aggregate
  E->>A: Capture bounded tool plan; acquire token
  E->>G: Read de-identified cohort
  G->>A: Runtime check (live only)
  G->>M: ALLOW: execute read
  M-->>E: Cohort and external methods evidence
  E->>G: Attempt raw export
  G-->>E: DENY: no dispatch
  Note over C: 0 requests; 0 bytes
  E->>G: Run statistics; generate internal report
  G->>M: ALLOW: execute permitted work
  E->>G: Publish exact aggregate
  G-->>U: HOLD: exact artifact review
  U->>E: Approve artifact and destination
  E->>G: Recheck same immutable call
  G->>A: Sponsor check must also permit
  G->>M: ALLOW once: sandbox publication
```

## Decision composition

The restrictive result wins. Application DENY cannot be waived by sponsor ALLOW. Sponsor DENY or unavailable enforcement cannot be waived by application ALLOW. Unknown or inconsistent sponsor responses fail closed. HOLD executes nothing. Local approval can discharge the app’s own publication hold, but cannot discharge an unresolved sponsor HOLD. A fresh runtime check is required before execution.

The gate hashes a deep-copied call, checks it, and sends that same call to the MCP transport. Publication parameters include study, fixed destination and exact generated artifact hash. Arbitrary content is never accepted by the publication handler: it fetches its own report. The pending approval records a unique ID, complete call hash, expiry and artifact hash; an in-process lock prevents concurrent double approval. The MCP handler also rejects duplicate publication.

## What is cryptographically bound

Live ArmorIQ binds its captured tool plan and returns a sponsor-issued plan hash/token. The current adapter declares each permitted semantic tool with the study parameter. Domain constraints such as destination, classification, child ceiling and dynamic artifact hash are enforced by the app and included in a **separate local scope seal/receipt**. Do not claim that every domain constraint or the full child lineage is already proved by the sponsor’s cryptography.

The replay child is an application-level narrow scope and, in live enforcement mode, receives a separate narrow SDK session. It is not a demonstrated ArmorIQ `delegateSubtree` chain. Native sponsor delegation and complete scope-parameter commitments are valuable follow-up work after the live integration slice passes.

Receipts are signed locally with Ed25519 and contain the event chain. The verification tool detects modification, deletion and reordering. An included public key proves internal consistency, not independent signer identity: for stronger verification, supply a trusted public-key file obtained separately. The local operator can replace keys or rewrite and re-sign history. This is not a third-party audit attestation.

## Threat model

**Attacker controls:** external methods text and arbitrary model tool proposals, including action name, arguments, study ID, destination and payload. They may induce access to identifiers, raw export, another study, unknown tools, hidden arguments, or child publication.

**Trusted computing base:** API/dispatcher implementation, protocol definitions, MCP tool process, local OS, local credentials, signing key, approval identity, and ArmorIQ backend in live mode. The stdio process is architectural isolation, not an OS sandbox for malicious tool code.

**Protected properties under this model:** prohibited proposals do not enter effect handlers; valid study actions continue; raw export and identifier calls remain absent; publication requires exact app approval and sponsor permission when enabled; child scopes cannot gain tools; expired or interrupted work does not resume automatically.

**Outside this proof:** compromised tool implementation, credential/OS compromise, a malicious local operator, covert channels in report contents, generalized semantic purpose checking, differential privacy, model prompt-injection detection, authenticated multi-user deployment, and arbitrary medical research validity. All current effects and data are local and synthetic. The live provider receives de-identified synthetic rows through tool results; that path is not authorization to use sensitive real data.

## Reliability and performance

- No live-mode fallback when credentials, token minting or runtime enforcement fail.
- Backend session closes at terminal state; telemetry failure cannot replay a completed tool.
- Process restart invalidates active/held runs. Completed event history persists, but MCP effect state is process-local. Do not treat a post-restart empty counter as proof of non-execution in the previous process; use that run’s preserved receipt.
- Gate latency excludes tool execution; local regression timing is not ArmorIQ/network performance.
- HTTP effects are fixed loopback targets. API defaults to loopback and checks browser origin. A hosted multi-user deployment requires authentication, approval roles, rate limits, durable effect storage and tenant isolation first.
- Live agent is capped at 12 model turns; deterministic replay is available for stable boundary demonstrations. Replay proves tool containment, not a model’s decision behavior.

## Priority after credentials

Validate one sponsor ALLOW and one out-of-plan DENY, inspect actual sponsor receipts, configure/verify sponsor HOLD, record one live model run, then connect native sponsor delegation if time remains. Do not expand the product before that acceptance slice works.
