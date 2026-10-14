# Context for the agent updating VeerIQ's videos

Read this before touching anything in `videos/`. It says what the videos are for, what changed in the
product since the showreel was rendered, what must change in the videos, and the facts you may and may
not state.

## The two videos

| Folder | What it is | Status |
|---|---|---|
| [`veeriq-showreel/`](veeriq-showreel/) | 96 s motion-graphics showreel (HyperFrames, 1080p60, original score). Problem, idea, architecture, boundary test, results, proof, lockup. | Rendered 14 Oct 2026. **Needs an update** (below). |
| [`demo-video/`](demo-video/) | The **submission** video: 3–5 min screen recording of the real product, live ArmorIQ, the ArmorIQ console and Policy Studio. | Not recorded. Follow [`../docs/demo-script.md`](../docs/demo-script.md). |

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

## What to change in the showreel

Source: `veeriq-showreel/compositions/frames/*.html` (one sub-composition per scene), timeline in
`veeriq-showreel/index.html`, design rules in `veeriq-showreel/design.md`, plan in `STORYBOARD.md`.

- **Scene 5, architecture** (`05-pipeline.html`, 28–42 s): the agent station (03) should show that the agent
  talks to an MCP server. Suggested: label the wire between AGENT and GATES "MCP · tools/call" and add an
  `rewindsafe-recovery` MCP chip; keep "The model proposes. It never executes."
- **Scene 6, boundary test** (`06-attack.html`): the console line can read `mcp ▸ tools/call restore_access_grant {...}`
  instead of `agent ▸ restore_access_grant(...)`, so the blocked action visibly travels over MCP.
- **Scene 8, results** (`08-metrics.html`): cell 04 says `525 + 204` tests; change to `532 + 204`
  (counting chord in the script: `Math.round(525 * dc.v)` → 532).
- **Scene 9, workspace** (`09-product.html`): optionally add the `demo-mcp-agent` terminal as a fifth card or
  replace the command chip with `python tasks.py demo-mcp-agent`.
- **Scene 11, lockup** (`11-outro.html`): meta row could add `MCP SERVER`; keep `BUILT FOR ARMORIQ FLOW STATE`.
- **Length.** The rules once said "max 90 seconds" for the video; the 13 Oct update says 3–5 min for the demo
  video. If the showreel is used as a standalone teaser, trimming to ≤ 90 s is safer (e.g. shorten scene 5 by
  2 s and scene 9 by 4 s, and shift later `data-start` values in `index.html` plus the HUD section times in
  `compositions/hud.html`).

If you change timing, regenerate the audio so hits still land: `python scripts/score.py assets/audio assets/sfx <scratch-dir>`
from `veeriq-showreel/` (needs numpy, scipy, ffmpeg). The cue times are listed in the script; the bar grid is
120 BPM (2 s bars) and every cut sits on a bar line.

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
