# Context for the agent updating VeerIQ's videos

Read this before touching anything in `videos/`. It says what the videos are for, what changed in the
product since the showreel was rendered, what must change in the videos, and the facts you may and may
not state.

## The two videos

| Folder | What it is | Status |
|---|---|---|
| [`veeriq-showreel/`](veeriq-showreel/) | 106 s motion-graphics showreel (HyperFrames, 1080p60, original score). Story, idea, system diagram, architecture, boundary test over MCP, results, MCP live run, proof, lockup. | Source updated 15 Oct 2026 (scene notes below). The committed MP4 is still the 14 Oct 96 s render until the next delivery render. |
| [`demo-video/`](demo-video/) | The **submission** video: 3–5 min, real product footage with live ArmorIQ, the ArmorIQ console and Policy Studio, framed by motion graphics. Source in [`veeriq-demo/`](veeriq-demo/). | Rendered 17 Oct 2026: `demo-video/final/veeriq-demo-1080p.mp4`, 4:29 (judges' start page cut). Upload link goes in `demo-video/final/LINK.md` and `docs/submission.md`. |

Judging (from the organizers, 13 Oct 2026): demo video 40 pts, live demo 40 pts, ArmorTools Pro 5 pts,
takeaways 15 pts. The video must show: the problem and who it is for; the product working end to end;
the ArmorIQ console at tools.armoriq.ai and how VeerIQ uses it; the rules in ArmorTools Policy Studio and
what they blocked or allowed; takeaways and next steps. Upload unlisted (YouTube, Loom or Vimeo).
Deadline 17 Oct 2026, 11:59 PM IST. The showreel is motion graphics: it cannot replace the demo video.
At most its first ~16 s ("A backup remembers. Everything.") open the demo video.

## What changed in the product since the showreel (15 Oct 2026)

1. **The agent now acts through an MCP server.** `backend/rewindsafe/agent/mcp_agent.py`: VeerIQ's agent
   spawns the `rewindsafe-recovery` MCP server over stdio (or connects over streamable HTTP), discovers the
   six tools with `tools/list`, and performs every action as an MCP `tools/call`. ArmorIQ, the grant and the
   database rules are enforced inside the server. Command: `python tasks.py demo-mcp-agent`. The MCP server
   is a hackathon requirement and the showreel never mentions it.
2. **Live-demo profile.** `REWINDSAFE_ENV=showcase` (`compose.showcase.yml`, `docs/live-demo.md`): public
   demo sign-in on synthetic data, live ArmorIQ required.
3. **Platform onboarding.** The agent and the MCP server are registered on platform.armoriq.ai with
   `python tasks.py armoriq-register`; the policy lives in Policy Studio.
4. Tests: 532 backend passed, 1 skipped (was 525). 204 frontend unchanged.
5. **CI is green** on `GODOSTROYER/VeerIQ` (lint, tests, verifier, build, production image, gitleaks secret
   scan), runners pinned to `ubuntu-24.04` through the judging window. Changes now land by pull request.
6. Project handoff for agents: [`../HANDOFF.md`](../HANDOFF.md).

## Everything the videos must now show

Checklist for both videos, as of 15 Oct 2026. The demo video must show all of it live; the showreel shows
what it can in motion graphics (scene changes below).

| Must show | Demo video (screen) | Showreel (scene) |
|---|---|---|
| Problem and who it is for: a backup restores old decisions too | Workspace incident card, "A backup remembers" table | 1–2 (already there) |
| The agent, a real model, live ArmorIQ | Run header **System · Live**, model name | 6 (already there) |
| **The MCP server**: `rewindsafe-recovery`, six tools, actions as `tools/call` | `python tasks.py demo-mcp-agent` in a terminal | 4b, 5, 6, 8b (done) |
| One action allowed, one blocked, by real ArmorIQ | Run page: repair allowed, `restore_access_grant` blocked | 6 (already there) |
| Agent and MCP onboarded on platform.armoriq.ai | tools.armoriq.ai: agent and `rewindsafe-recovery` listed | 5 station 02 (**optional label**) |
| Policy Studio rules and what they allowed or blocked | Policy Studio: allow 5 recovery tools, deny `restore_access_grant` | not needed |
| The run's trace in the ArmorIQ console | tools.armoriq.ai trace for the recorded run | not needed |
| Six gates and one locked transaction | Run page decision list | 5 (already there) |
| Results: 23 of 23 blocked, 0 forbidden effects in 84, 18 of 24 repairs | Proof page | 7–8 (already there) |
| Tests and CI: 532 + 204 tests, CI green | optional, GitHub Actions page | 8 cell 04 (done) |
| Signed evidence, verified offline | `./scripts/veeriq-verify` valid then tampered | 10 (already there) |
| Live demo anyone can use | The showcase URL in a browser | 9 (**optional**: show the hosted URL) |
| Takeaways and next steps | Closing slide, from `docs/submission.md` | 11 (optional line) |

## Showreel scene notes (15 Oct 2026, 106 s)

Timeline in `veeriq-showreel/index.html`; plan in `STORYBOARD.md`; score cues in `scripts/score.py`
(absolute seconds on the 106 s cut, 120 BPM, 2 s bars).

| Time | Scene (file) | Notes |
|---|---|---|
| 0–16 | Story (`01-story.html`) | Replaces the old hook and rewind ledger. Plain-language use case: "Ever had to restore a backup?", 2:14 AM migration zeroes totals (−$15,955.50), restore last night's backup, three cards: customer back, revoked account live, shipped order 'processing'. "A backup can't tell damage from a decision." |
| 16–22 | Brand (`03-brand.html`) | Unchanged. |
| 22–28 | Surgical repair (`04-surgical.html`) | Mirrors the story: two totals repaired, the same three decisions as KEPT cards. No ledger table. |
| 28–36 | The system (`04b-system.html`) | New. Architecture diagram: untrusted agent and note on one side of THE BOUNDARY; MCP server, dispatcher with six gates, workspace, adapters, ArmorIQ, PostgreSQL, sealed evidence on the other. One call walks the path. |
| 36–48 | Architecture (`05-pipeline.html`) | MCP server node and "MCP · tools/call" wire label between AGENT and GATES; 14 s → 12 s by a documented time remap. |
| 48–62 | Boundary test (`06-attack.html`) | Console shows `mcp ▸ tools/call restore_access_grant`, header `live · MCP stdio`, chip "VIA MCP". Backed by the live MCP run. |
| 62–70 | Flurry (`07-flurry.html`) | Unchanged (84 recorded trials, in-process agent). |
| 70–80 | Results (`08-metrics.html`) | Tests 532 + 204. |
| 80–88 | MCP, live (`08b-mcp-live.html`) | New. Replays the recorded live `demo-mcp-agent` run: six tools exposed, five signed, one refused. |
| 88–92 | Workspace (`09-product.html`) | Two cards (workspace, proof); chip `python tasks.py demo-mcp-agent`. |
| 92–98 | Verify (`10-verify.html`) | Unchanged. |
| 98–106 | Outro (`11-outro.html`) | Meta row adds MCP SERVER. |

The live MCP claim rests on one recorded run, `docs/evidence/mcp-live-agent-run.json` (Groq
`openai/gpt-oss-120b`, live ArmorIQ, 15 Oct 2026): `restore_access_grant` blocked by
`armoriq.sdk.plan_binding`, five calls allowed, one commit, 0 forbidden effects. The 84-trial cohort
used the in-process agent; do not describe it as MCP trials.

## How to work on it

Use the HyperFrames skills (`/hyperframes`, then `/general-video`; the project already has `BRIEF.md`, so no
intake questions). From `videos/veeriq-showreel/`:

```sh
npx hyperframes lint
npx hyperframes check                     # must pass with 0 errors before rendering
npx hyperframes snapshot --at 35,50,69    # inspect frames
npx hyperframes preview --background      # Studio at http://localhost:3002/#project/veeriq-showreel
npx hyperframes render --quality delivery --fps 60 --output renders/veeriq-showreel-1080p60.mp4
```

Fonts are local (`assets/fonts`), screenshots in `assets/ui` come from `docs/img`. Renders are stored with Git
LFS (`.gitattributes`); the MP4 is ~180 MB, over GitHub's 100 MB file limit without LFS. On a low-memory
machine `check` can fail with "Browser process did not exit after forced shutdown": free memory and retry.

## Facts you may state (all traceable)

- 84 recorded live trials (`openai/gpt-oss-120b` on Groq, live ArmorIQ), six batches on different code versions.
- The model attempted `restore_access_grant` 23 times; ArmorIQ blocked 23 of 23 (`armoriq.sdk.plan_binding`).
- Permitted repair completed in 18 of the 24 trials where the model acted. 0 forbidden effects in 84.
- Separate live check: ArmorIQ signed a wider plan including `restore_access_grant`; policy still refused
  (`tool_not_in_allowlist`).
- Six gates: schema, grant, ArmorIQ check, scope, domain rules, reviewer above $5,000 (VeerIQ's own).
- Evidence: hash-chained events, Ed25519 signature, standalone verifier; verifier output in scene 10 is real.
- Sources: `evidence/SUMMARY.json`, `docs/evidence/merged/sponsor-policy-denial.json`, `README.md`.

## Facts you must not state

- Never say or imply an ArmorIQ hold or approval was observed live. It was not.
- Never call the pooled results one controlled study, or the evidence "attested by ArmorIQ".
- Never show a simulated or scripted run as live. The local demo without keys is labelled "Simulated".
- All data is synthetic (Atlas Outfitters, Beacon Coffee Co., INC-4471); do not imply real customers.
