# Submission demo video (3–5 minutes)

The video judges score (40 pts). A screen recording of the real product with live ArmorIQ, not motion
graphics. Script and shot list: [`../../docs/demo-script.md`](../../docs/demo-script.md). Context and
the facts you may state: [`../AGENT-CONTEXT.md`](../AGENT-CONTEXT.md).

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
