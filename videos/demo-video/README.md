# Submission demo video (3–5 minutes)

The video judges score (40 pts). Real product footage with live ArmorIQ, framed by motion graphics so a
judge seeing VeerIQ for the first time can follow it. Script and shot list: [`../../docs/demo-script.md`](../../docs/demo-script.md). Context and
the facts you may state: [`../AGENT-CONTEXT.md`](../AGENT-CONTEXT.md).

## The delivered video

`final/veeriq-demo-1080p.mp4` (Git LFS): 4:21, 1080p60, narrated, captions burned in. Built with
HyperFrames from [`../veeriq-demo/`](../veeriq-demo/); the narration script is
`../veeriq-demo/scripts/narration.json` and every scene length follows the voiceover.

| Time | Section | Picture |
|---|---|---|
| 0:00 | The problem | July 2025: an AI agent wipes a production database during a code freeze (sourced on screen); then the story: restoring a backup brings back a deleted customer, a revoked account and a shipped order |
| 0:36 | Meet VeerIQ, three promises, how it works | Lockup; only the damage repaired, every later decision kept, proof for every step; the system diagram |
| 1:14 | Try it live | Screen recording of the judges' start page with a live model and live ArmorIQ: full restore (fixes 3, breaks 4) vs VeerIQ; ArmorIQ blocks the planted `restore_access_grant`; the judge approves the $12,400 repair as the second key; the browser verifies the signed receipt and rejects a one-cent change. Speeds are in the rail; two cuts are labelled |
| 2:18 | The boundary, 23 times | 23 `restore_access_grant` requests hit the boundary and are destroyed, accelerating; locks on 23/23 blocked by ArmorIQ (the recorded live batches), each hit with its own sound |
| 2:27 | ArmorIQ console | Read-only screenshots of platform.armoriq.ai: a live run's session, the agent and MCP server, the trace with the deny, Policy Studio rules (5 allowed) |
| 2:45 | Bring your agent (MCP) | Replay of the live `demo-mcp-agent` run (`docs/evidence/mcp-live-agent-run.json`) |
| 2:58 | Plug it in | Docker, `python tasks.py armoriq-register`, then a recording of `/import` (scripted planner, live ArmorIQ, labelled); write-back caveat on screen |
| 3:35 | What to expect | 84 trials, 23 of 23 blocked, 0 forbidden effects, 18 of 24 repairs (`evidence/SUMMARY.json`) |
| 3:58 | What's next, close | Takeaways, next steps, repo URL |

To rebuild: from `../veeriq-demo/`, `python3 scripts/build.py`, then
`npx hyperframes render --quality delivery --fps 60 --output renders/veeriq-demo-1080p60.mp4`, and copy
the render here as `final/veeriq-demo-1080p.mp4`. Re-recording footage needs the app running with live
keys (`node scripts/capture.mjs judges|import`); new narration needs `GEMINI_API_KEY` in `VeerIQ/.env`
(`scripts/tts.py --chunked`, then `scripts/align_vo.py`).

## What goes here

| Path | Contents |
|---|---|
| `recordings/` | Raw screen captures, one file per scene in the script (not committed if large; keep them local or in LFS) |
| `edit/` | Edit project or cut list |
| `final/` | The exported video, plus the unlisted upload link in `final/LINK.md` |

## Must be on screen

1. The problem and who it is for (on-call engineer restoring a backup).
2. The product end to end: grant, poisoned scenario, blocked call, committed repair, proof page.
3. The ArmorIQ console at tools.armoriq.ai: the agent and the `rewindsafe-recovery` MCP server, and the run's trace.
4. Policy Studio: allow the five recovery tools, deny `restore_access_grant`, and what each rule allowed or blocked.
5. `python tasks.py demo-mcp-agent`: every action as an MCP `tools/call`, one blocked by ArmorIQ.
6. Takeaways and what you would build next (see `docs/submission.md`).

## Recording checklist

- Live only: platform.armoriq.ai API key, `REWINDSAFE_ENFORCEMENT=live`, header reads **System · Live**.
- `python tasks.py reset-demo` before each take.
- 1080p, terminal font readable at 720p, no secrets on screen (`.env`, API keys, cookies).
- Optional opener: the first ~16 s of `../veeriq-showreel/renders/veeriq-showreel-1080p60.mp4`.
- Length 3:00–5:00. Upload unlisted; paste the link into the submission form.
