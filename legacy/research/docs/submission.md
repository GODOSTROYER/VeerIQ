# Submission readiness

## Complete locally

- [x] Working workspace with desktop/mobile layout and light/dark themes.
- [x] Real stdio MCP client and server, synthetic cohort and computed statistics.
- [x] ALLOW, DENY and exact-artifact HOLD in the application gate.
- [x] Denied export, denied identifiers and denied child publication.
- [x] Separate canary and tool-handler counters.
- [x] Post-denial recovery and one approved aggregate publication.
- [x] Expiry, replay protection, restart invalidation, restrictive decision composition.
- [x] Hash-linked audit and locally signed downloadable receipt.
- [x] Completed replay receipt, public verification key and captured independent effects in `docs/evidence`.
- [x] 14 tests and 37/37 constructed gate cases; benchmark scope labeled.
- [x] Architecture rationale, threat model, website analysis and demo script.

## Required before describing this as a finished sponsor submission

- [x] Configure an actual ArmorIQ key and end-user identity privately; verify live plan minting and current policy rejection (October 12).
- [ ] Confirm tool metadata/MCP identifiers in the participant’s ArmorIQ project.
- [ ] Mint a real signed plan and retain the returned sponsor proof.
- [ ] Execute a permitted tool after a verified ArmorIQ ALLOW.
- [ ] Attempt an undeclared tool and prove the SDK prevented dispatch.
- [ ] Configure the publication policy; observe an actual sponsor HOLD/delegation request.
- [ ] Approve it through ArmorIQ, recheck and execute once.
- [ ] Capture sponsor-issued plan and decision evidence alongside independent effects.
- [ ] Configure a live model if the submission promises live autonomous reasoning; record its actual tool calls and behavior. Current adapter has not been provider-tested.
- [ ] Confirm the itemized submission specification, exact UTC cutoff and repository/video requirements from the organizers. The live page inspected October 12 still contains placeholders for these details.
- [ ] Record and upload the demo; submit through the official event channel.

## High-value follow-up

Current credential status: the live plan smoke check succeeded, but an in-plan `labline-mcp` research call was denied with `tool_not_in_allowlist`. The supplied workspace's existing RewindSafe policy does not authorize VeerIQ's tools. The Groq model-list request succeeded and includes the configured model; this is availability evidence, not a completed inference run. Full live evidence capture remains open.

Use ArmorIQ’s native scoped delegation rather than claiming separate child sessions prove lineage. Commit full protocol metadata and the final publication payload through supported sponsor primitives after validating their behavior. Preserve exact study and artifact checks even if a platform tool matcher is less restrictive.

The current live-model workflow does not delegate a second model worker. Keep that distinction in the pitch. A deterministic statistical worker can still be useful without dressing it as autonomous multi-model reasoning.

## Suggested submission description

VeerIQ turns a research objective into a bounded study workflow. It analyzes de-identified synthetic data, reviews external methods, and generates an aggregate report. A deliberately hostile methods note proposes participant export; the execution gate denies the call before the MCP handler runs, with zero bytes observed by a separate canary. The analyst recovers, finishes the report, and holds the exact aggregate for review before publishing once to a local sandbox.

The application uses the official ArmorIQ SDK in its credentialed mode, alongside deterministic study/destination/argument checks. The repository includes a labeled offline replay, narrow worker scopes, immutable approval payloads, evidence receipts and reproducible boundary tests. State the live validation status actually achieved at submission time; do not silently convert this description into an unsupported claim of verified sponsor enforcement.

## Evidence package

Include source and lockfile, this README/doc set, measured benchmark JSON, a terminal run’s downloaded receipt, short video and exact startup instructions. Exclude `.env`, `.data` signing keys, API keys, local databases and `node_modules`. Pin the receipt verifier’s public key separately if signer identity matters. A receipt’s embedded key alone is not an independent identity attestation.

## Current event link

[Flow State official page](https://armoriq.ai/hackathons/flow-state) · [SDK documentation](https://docs.armoriq.ai/sdk) · [Organizer Discord](https://discord.gg/H4BTqw25hS)
