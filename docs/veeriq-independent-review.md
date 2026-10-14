# VeerIQ independent review

## Verdict

VeerIQ is a coherent, inspectable local prototype with a useful research workflow and a carefully bounded execution path. Its local replay is supported by concrete MCP and canary evidence. RewindSafe is currently the stronger hackathon demonstration on the evidence described in its README: it reports actual ArmorIQ service decisions and live LLM runs, while VeerIQ's live ArmorIQ integration and provider workflow remain unvalidated. This comparison uses VeerIQ source and checked-in evidence, but RewindSafe's README claims have not been independently source-audited here.

| Category | VeerIQ | RewindSafe | Basis |
|---|---:|---:|---|
| Useful end-to-end workflow | 7/10 | 9/10 | VeerIQ computes a synthetic study aggregate, creates a report, and publishes after review. RewindSafe describes a more consequential recovery workflow with a repair manifest, protected-state checks, and a database commit. |
| Authority boundary | 8/10 | 9/10 | VeerIQ checks study, tool, arguments, destination, expiry, and artifact hash in one dispatcher, then calls isolated MCP handlers. RewindSafe reports layered ArmorIQ, grant, domain, and PostgreSQL column-privilege checks. |
| Approval and effect handling | 8/10 | 8/10 | VeerIQ binds a one-use approval to the exact publication call and rechecks both gates before dispatch. RewindSafe describes an exact repair manifest, second-reviewer approval, and transactional stale-state checks. |
| Live model and sponsor evidence | 4/10 | 9/10 | VeerIQ has a bounded live-model loop and official SDK adapter, but its own docs say credentials and live provider behavior have not been validated. RewindSafe's README reports a live signed plan, allow and deny decisions, and live Groq runs. |
| Architecture and evidence readiness | 7/10 | 8/10 | VeerIQ's modular monolith, SQLite event chain, signed receipt, and independent canary are simple to inspect. RewindSafe reports database-backed effects and multiple live evidence artifacts, with greater setup complexity. Its README also flags pre-event project work that may need organizer confirmation. |

Scores are comparative judgments about the artifacts available for this review, not security certifications or measured product quality. RewindSafe's scores rely on its README's summary of evidence; its implementation and referenced evidence files were outside this review's requested scope.

## What VeerIQ demonstrates

The local replay is more than a mocked UI. `server/transport.mjs` starts a stdio MCP server in a separate process and a loopback canary. `server/dispatcher.mjs` deep-copies and hashes each proposed call, applies the protocol decision, checks the configured ArmorIQ adapter, and invokes MCP only after an ALLOW. `server/scope.mjs` fixes the study to FLOW-42 and denies identifiers, raw export, scope escape, unapproved arguments, wrong destinations, and mismatched aggregate hashes. The replay worker receives a narrower tool set.

The approval flow is unusually concrete for a demo. `server/engine.mjs` records the pending call and its hash, sets a short expiry, prevents concurrent approval, rechecks the call after a user decision, and refuses to turn a sponsor HOLD into an application approval. The MCP publication handler independently fetches its own report and rejects a different hash or a duplicate publication.

The checked-in run evidence reports one execution of each permitted research handler, one approved sandbox publication, and zero canary requests or bytes. The receipt contains 16 hash-linked events and verifies with the supplied public key. The benchmark artifact reports 37/37 constructed boundary cases passing. These are local, constructed checks: the benchmark does not measure general prompt-injection resistance, and a public key shipped beside a receipt proves consistency rather than signer identity. The effects snapshot is also separate from the signed receipt.

## Important limitations

- **Sponsor enforcement is not demonstrated.** The local ArmorIQ adapter is a permissive stub; the protocol gate supplies the local boundary. The official SDK path is present, but the docs say real token minting, registered policy behavior, sponsor HOLD, and live approval have not been validated. VeerIQ should not be presented as having verified live ArmorIQ enforcement yet.
- **Live model behavior is not evidenced.** A Chat Completions tool loop exists, capped at 12 turns, but there is no recorded provider run. It does not delegate the statistician worker, so the replay's narrower child workflow should not be described as live multi-agent delegation.
- **The security boundary is local and narrow.** Data and effects are synthetic and loopback-only. The API has no user authentication or multi-tenant identity. The MCP process is separated from the API but is not an OS sandbox. The local signing key and operator are trusted; the operator can rewrite and re-sign local history.
- **Research validity is illustrative.** The cohort is seeded synthetic data, and the statistics are a demonstration rather than clinical evidence. The available case suite exercises fixed boundary shapes; it does not establish broad resistance to semantic or covert-channel attacks.
- **Submission evidence is incomplete.** VeerIQ has a reproducible local receipt and clear disclosures, but the required live sponsor ALLOW, out-of-plan DENY, sponsor HOLD and approval sequence, live-model record, and final event requirements remain open in `docs/submission.md`.

## Comparison notes

RewindSafe's README reports one especially useful distinction: ArmorIQ's live plan binding and org allowlist blocked a forbidden tool, while the same live service allowed a different tenant argument. That supports its decision to implement tenant, resource, and field scope in its own grant layer. It also reports that its amount HOLD is not configured, so its review scenario uses RewindSafe's own approval layer. Those disclosures make the reported live evidence more credible, while leaving a real policy acceptance step open.

RewindSafe also reports a live LLM option and a deterministic scripted reenactment when no model key is present, with the modes labeled separately. Its README flags that work began before the event's build window and says the team must confirm eligibility with organizers. That is a material submission risk even though its implementation evidence appears ahead of VeerIQ's.

VeerIQ's strongest differentiator in this comparison is the quality of its local execution evidence and its tight scope: the forbidden handler and independent sink are observable, the exact aggregate approval is testable, and limitations are stated plainly. If judged on the source and evidence available today, choose RewindSafe for stronger demonstrated live integration and end-to-end realism, subject to eligibility confirmation. Choose VeerIQ if the judging emphasis favors a small, reproducible boundary demonstration and the team can complete and capture live sponsor validation before submission.
