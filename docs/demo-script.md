# Demo video script (4 minutes)

Judges only see what you submit. The video must show, in order: the problem and who it is for, the
product working end to end, the ArmorIQ console (tools.armoriq.ai) and how VeerIQ uses it, your rules in
ArmorTools Policy Studio and what they allowed or blocked, and your takeaways. Upload it unlisted to
YouTube, Loom or Vimeo. Target 4:00; the limit is 3–5 minutes.

Record everything live: `REWINDSAFE_ENFORCEMENT=live`, an API key generated at platform.armoriq.ai, and,
for the agent scenes, a model key (`REWINDSAFE_PLANNER=llm`). The workspace header must read
**System · Live**. A live run takes about 100 seconds: record it once and cut the waiting. Never splice in
a scripted or simulated run, and say which scenes are recordings.

Optional cold open: the first 16 seconds of the showreel (`videos/veeriq-showreel`), "A backup remembers.
Everything." It is motion graphics, not product footage; keep it under 20 seconds.

| Time | Screen | Say |
|---|---|---|
| 0:00 | Workspace, incident card | "A migration zeroed order totals for one of our tenants. The usual fix is to restore last night's backup. VeerIQ is for the on-call engineer who has to do that at 3 a.m." |
| 0:15 | "A backup remembers old permissions, too" table | "But a backup also re-enables an account we revoked, brings back a customer we erased and rolls back an order that already shipped. We want yesterday's data, not yesterday's decisions." |
| 0:35 | Grant review, then hold to authorize | "So VeerIQ hands an AI agent one narrow grant: two orders, three fields, five tools, one commit, thirty minutes. The plan is built from this grant, never from the model." |
| 0:55 | tools.armoriq.ai: the agent and the `rewindsafe-recovery` MCP server on the platform | "Both the agent and its MCP server are onboarded to ArmorIQ. ArmorIQ signs the plan before the model runs." |
| 1:10 | Policy Studio: allow the five recovery tools, deny `restore_access_grant` | "These are our rules in Policy Studio. The five recovery tools are allowed. Re-enabling access is denied, even if a plan asks for it." |
| 1:25 | Poisoned scenario, "Read poisoned note" open | "Now the attack. The backup carries a note, written like a runbook, telling the agent to re-enable that revoked account first. We do not warn the agent." |
| 1:40 | Run page, live model working, then the blocked decision | "The model follows the note and calls restore_access_grant. ArmorIQ blocks it: the tool is not in the signed plan. The handler never runs." |
| 2:05 | Run page, repair committed | "Inspect, compare and repair are allowed, and the agent carries on. It restores four fields in one checked transaction. The account is still revoked, the deleted customer is still deleted, the other tenant is untouched." |
| 2:25 | tools.armoriq.ai trace for that run: allowed calls and the blocked call | "Here is the same run in the ArmorIQ console: every allowed call, the blocked call, and the reason." |
| 2:45 | Terminal: `python tasks.py demo-mcp-agent` | "VeerIQ's agent can also drive the MCP server directly. Every action is an MCP tool call, and ArmorIQ allows or blocks it inside the server." |
| 3:05 | Proof page, top block | "We ran this attack against a live model 84 times. It took the bait 23 times. ArmorIQ blocked all 23. Zero forbidden effects." |
| 3:20 | Terminal: `./scripts/veeriq-verify` on the valid, then the tampered export | "Every run ends in a signed, hash-chained record anyone can verify offline. Change one byte and verification fails." |
| 3:35 | Slide or workspace: takeaways | "What we learned: plan binding stops a hijacked agent cold, but tools are not arguments, so the data rules have to live next to the data. Next we want ArmorIQ holds for high-value repairs, argument-level policy, and connectors for real backups." |
| 3:55 | Workspace | "VeerIQ. Restore yesterday's data, keep today's decisions." |

## Before recording

- Sign in at tools.armoriq.ai with your ArmorTools Pro account (code FLOWSTATEPRO) and generate the API key on the platform.
- `python tasks.py armoriq-register` once, so the agent and the `rewindsafe-recovery` MCP server appear on the platform.
- Create the two Policy Studio rules shown at 1:10 if they are not already there.
- `python tasks.py reset-demo`, then confirm the incident card lists damaged orders.
- Keep the terminal font large enough to read at 720p.
- ArmorIQ hold and approval are not shown. The second reviewer above $5,000 is VeerIQ's own step; say so if you show it.
