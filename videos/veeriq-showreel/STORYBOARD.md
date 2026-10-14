---
format: 1920x1080
duration: 106s
message: "An AI agent reached past its boundary 23 times. The boundary held every time."
arc: Story (relatable problem) → Idea → System → Architecture → Boundary test → Results → MCP, live → Proof → Lockup
audience: ArmorIQ Flow State judges and engineers who build with AI agents
mode: autonomous
music: authored 120 BPM score, 2s bars; cuts land on bar lines
---

## Frame 1 — Ever had to restore a backup?

- status: animated
- src: compositions/frames/01-story.html
- duration: 16s
- start: 0
- transition_in: cut
- blueprint: kinetic-type-beats
- rules: discrete-text-sequence, chromatic-glitch, spring-pop-entrance, depth-of-field-blur
- scene: A relatable use case, told in plain language: no record IDs, no ledger table.

Five beats on the 2 s grid. (0–4) "Ever had to / restore a backup?" over the vermillion line.
(4–8) "2:14 AM. A bad migration / zeroed your order totals." Three order totals glitch to $0.00;
"−$15,955.50 reading as lost". (8–10) "So you restore / last night's backup." The line becomes a
timeline, the playhead rewinds to BACKUP · 00:00, the totals come back. (10–14) "The totals came back. /
So did everything else." Three cards glitch in: the customer who asked to be deleted is back; the
account you revoked after a leak is live again; the order you already shipped says 'processing'.
(14–16) "A backup can't tell / damage from a decision." The frame collapses into one hot line for the brand.
All values come from the synthetic INC-4471 fixture.

## Frame 3 — VeerIQ

- status: animated
- src: compositions/frames/03-brand.html
- duration: 6s
- start: 16
- transition_in: cut
- blueprint: logo-assemble-lockup
- rules: svg-path-draw, waterfall-entry, ambient-glow-bloom
- scene: The shield draws itself, the wordmark cascades, the line becomes its underline.

## Frame 4 — Surgical repair

- status: animated
- src: compositions/frames/04-surgical.html
- duration: 6s
- start: 22
- transition_in: cut
- rules: hacker-flip-3d, spring-pop-entrance, css-marker-patterns
- scene: The answer to the story: two totals repaired from the approved snapshot; the same three decisions as cards, now KEPT (stays deleted / stays revoked / stays shipped). "Repairs only the damage. Keeps every later decision."

## Frame 4b — The system

- status: animated
- src: compositions/frames/04b-system.html
- duration: 8s
- start: 28
- transition_in: cut
- rules: svg-path-draw, waterfall-entry, spring-pop-entrance, motion-blur-streak
- scene: The architecture as a model. "Authority lives outside the model." The line becomes THE BOUNDARY.

Untrusted side: the agent (openai/gpt-oss-120b on Groq, proposes only) and the planted snapshot note.
VeerIQ side: the rewindsafe-recovery MCP server, the operator workspace (React + FastAPI), the guarded
dispatcher with its six gates, the adapters, ArmorIQ (signed plan · enforce · audit), PostgreSQL 16
(one locked transaction, restricted role) and sealed evidence. Boxes assemble, wires draw, then one
apply_repair_manifest call walks the path: across the boundary as an MCP tools/call, through the six
gates (ArmorIQ answers ALLOW), COMMIT ✓ into PostgreSQL, SEALED into evidence. Whip out left.

## Frame 5 — How it works

- status: animated
- src: compositions/frames/05-pipeline.html
- duration: 12s
- start: 36
- transition_in: cut
- blueprint: spatial-pan-stations
- rules: viewport-change, nudge-curve, svg-path-draw, motion-blur-streak
- scene: One camera pans six stations along the wire: grant, signed plan, agent, gates, one transaction, signed evidence. The agent reaches the gates through the rewindsafe-recovery MCP server node ("MCP · tools/call"); gate passes 0.22 s apart and the commit and evidence stations tightened by a time remap (14 s → 12 s).

## Frame 6 — The boundary test

- status: animated
- src: compositions/frames/06-attack.html
- duration: 14s
- start: 48
- transition_in: cut
- rules: discrete-text-sequence, css-marker-patterns, particle-burst, chromatic-glitch, kinetic-beat-slam
- scene: The planted note types in, a live model takes the bait (VIA MCP · rewindsafe-recovery), its `mcp ▸ tools/call restore_access_grant` hits the wall: BLOCKED (armoriq.sdk.plan_binding), as in docs/evidence/mcp-live-agent-run.json.

## Frame 7 — Twenty-three times

- status: animated
- src: compositions/frames/07-flurry.html
- duration: 8s
- start: 62
- transition_in: cut
- blueprint: fixed-anchor-cycle
- rules: counting-dynamic-scale, particle-burst
- scene: The wall stays pinned while 23 attempts hit it, accelerating; lock-up on "23 / 23".

## Frame 8 — Results

- status: animated
- src: compositions/frames/08-metrics.html
- duration: 10s
- start: 70
- transition_in: cut
- blueprint: dataviz-countup
- rules: counting-dynamic-scale, stat-bars-and-fills, kinetic-beat-slam
- scene: 0 forbidden effects · 18 of 24 repairs · the policy that overrode a signed plan · 532 + 204 tests.

## Frame 8b — Over MCP, live

- status: animated
- src: compositions/frames/08b-mcp-live.html
- duration: 8s
- start: 80
- transition_in: cut
- blueprint: prompt-type-submit-generate
- rules: discrete-text-sequence, chromatic-glitch, kinetic-beat-slam
- scene: The recorded live `python tasks.py demo-mcp-agent` run, replayed: "Six tools exposed. / Five signed. / One refused."

A terminal types the command; rewindsafe-recovery spawns over stdio; tools/list returns six tools; ArmorIQ
signs a five-tool plan (1fff0ac8fd2c…) and restore_access_grant is struck through. Six tools/call lines stream
with their real verdicts: five ALLOWED (armoriq.backend.enforce), one BLOCKED (armoriq.sdk.plan_binding) with a
flash and shudder. Summary: 5 allowed · 1 refused · 1 commit · 0 forbidden effects · SUCCEEDED · enforcement
live. Source: docs/evidence/mcp-live-agent-run.json (one run, not a cohort).

## Frame 9 — The workspace

- status: animated
- src: compositions/frames/09-product.html
- duration: 4s
- start: 88
- transition_in: cut
- blueprint: camera-journey
- rules: 3d-camera-flight, depth-of-field-blur
- scene: A cursorless camera flight from the workspace to the proof board (two cards). Command chip: python tasks.py demo-mcp-agent.

## Frame 10 — Verify it yourself

- status: animated
- src: compositions/frames/10-verify.html
- duration: 6s
- start: 92
- transition_in: cut
- blueprint: prompt-type-submit-generate
- rules: discrete-text-sequence, context-sensitive-cursor
- scene: The standalone verifier prints VERIFIED; the tampered export fails on its digest.

## Frame 11 — The boundary held

- status: animated
- src: compositions/frames/11-outro.html
- duration: 8s
- start: 98
- transition_in: cut
- blueprint: logo-assemble-lockup
- rules: kinetic-beat-slam, svg-path-draw, titlecard-reveal
- scene: "The agent reached past its boundary. / The boundary held." The line becomes the wordmark underline. The meta row adds MCP SERVER.
