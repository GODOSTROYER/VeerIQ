---
workflow: general-video
flow: automation
storyboard: no
message: "An AI agent reached past its boundary 23 times. The boundary held every time."
destination: youtube
aspect: 1920x1080
language: en
audience: ArmorIQ Flow State judges and engineers who build with AI agents
length: 106s
angle: showreel
---

## Intent

A showcase film for VeerIQ, the hackathon entry for ArmorIQ Flow State. The user asked for
"a dynamic motion graphics video that shows what an incredible motion designer you are, like
it's your showreel for a résumé. Go all out. Use amazing typography." It must "absolutely boast
about the project and the problem, the solution, its architecture, metrics etc."

Tone: confident, cinematic, precise. A typographic showreel, not a slide deck. No voiceover:
the type and the motion carry the story, with an authored score and sound design.

## Customizations

- Authored, deterministic score (synthesized locally, 120 BPM, cuts on the bar grid) plus the
  bundled HyperFrames sound-effect library for hits, whooshes and UI ticks.
- Real product screenshots from `docs/img/` in one camera-flight beat.
- Real verifier output (`scripts/veeriq_verify.py`) in the proof beat.
- 15 Oct revision: the opening is a relatable story in plain language (no record IDs or ledger
  table), VeerIQ is introduced as the answer, the architecture is shown as a full system diagram,
  and MCP is shown working: the agent acts through the `rewindsafe-recovery` MCP server, and a
  dedicated beat replays the recorded live `demo-mcp-agent` run
  (`docs/evidence/mcp-live-agent-run.json`).

## Notes

- Every number and claim must trace to the repository: `evidence/SUMMARY.json`, `README.md`,
  `docs/evidence/merged/sponsor-policy-denial.json`, the verifier output.
- Never state or imply that an ArmorIQ hold or approval was observed live. The second reviewer
  above $5,000 is VeerIQ's own gate.
- Pooled results come from six recorded batches on different code versions; say "recorded live
  trials", not "a controlled study".
- All incident data is synthetic (Atlas Outfitters, Beacon Coffee Co., INC-4471).
