---
format: 1920x1080
duration: 269.44s
message: "Ctrl+Z for AI agents: restore yesterday's data, keep today's decisions."
audience: ArmorIQ Flow State judges seeing VeerIQ for the first time
mode: autonomous
narration: Gemini TTS (Charon), scripts/narration.json; scene lengths follow the voiceover
---

Generated from `scripts/build.py` (scene lengths and voiceover offsets) and `scripts/narration.json`. Lines l05a-c, l05d and l09 belong to the previous cut and are no longer placed.

## 1. hook — 0:00.0, 15.6 s  (`compositions/frames/00-hook.html`)

July 2025: an AI coding agent wiped a production database during a code freeze and wrongly said it couldn't be undone; there was a backup. Sourced on screen (eWeek, heise, AIID #6120). New scene `00-hook.html`.

> July, twenty twenty-five. An AI coding agent wiped a company's production database, in the middle of a code freeze. Then it said the damage couldn't be undone. It could. There was a backup. But a backup has a catch.

## 2. story — 0:15.6, 20.4 s  (`compositions/frames/01-story.html`)

Restoring a backup brings back a deleted customer, a revoked account and a shipped order (reused from the showreel, retimed).

> Ever had to restore a backup? At two in the morning, a bad migration wipes your order totals. So you roll back to last night. The totals come back. But so does everything else: the customer who asked to be deleted, the account you revoked after a leak, the order you already shipped.

## 3. brand — 0:36.0, 7.0 s  (`compositions/frames/03-brand.html`)

Lockup.

> Meet VeerIQ. It repairs only the damage, and keeps every decision you made since.

## 4. promise — 0:43.0, 12.6 s  (`compositions/frames/02-promise.html`)

Three cards: only the damage repaired, every later decision kept, proof for every step.

> Here's what you get. Damaged values, restored from an approved snapshot. Deletions, revoked access and later edits, left exactly as they are. And a signed record of every step.

## 5. system — 0:55.6, 18.6 s  (`compositions/frames/04b-system.html`)

System diagram: the agent proposes, the MCP server, six gates with ArmorIQ, one locked transaction (reused, retimed).

> An AI agent does the repair, but it never holds the keys. It can only propose. Every action goes through VeerIQ's MCP server and six gates, including ArmorIQ, which signs the plan before the model runs. And every change lands in one locked database transaction.

## 6. judges — 1:14.2, 64.5 s  (footage + overlay)

Screen recording of the judges' start page (`assets/footage/judges.mp4`, `scripts/capture.mjs judges`), live model and live ArmorIQ: the damage; full restore (fixes 3, breaks 4) vs VeerIQ, where ArmorIQ blocks the planted restore_access_grant; the judge approves the $12,400 repair as second reviewer; the browser verifies the signed receipt and rejects a one-cent change. Speeds are shown in the rail; the model's remaining 53 s and a 5 s commit wait are cut and labelled.

> Here it is, live: control-Z for AI agents. Anyone can run this demo in about three minutes. Step one: three orders were damaged, and three decisions were made after the backup. Those must stay.
> Step two: two ways to undo it. Restoring the backup fixes three orders, but breaks four things that happened since. VeerIQ gives an AI agent one narrow job instead. And the backup hides a note, telling it to re-enable the revoked account.
> A live model takes the bait. ArmorIQ blocks the call, because it was never in the signed plan. The agent repairs only the damage, and every later decision stays.
> Step three: one repair is worth twelve thousand four hundred dollars. VeerIQ won't let anyone commit that alone: not the agent, and not the person who asked. So the judge becomes the second key, and approves the exact change.
> Step four: don't trust our screen. Your own browser checks the signed receipt. Change a single cent, and it fails.

## 7. flurry — 2:18.7, 8.4 s  (`compositions/frames/07-flurry.html`)

23 `restore_access_grant` requests hit the boundary and are destroyed, accelerating, then lock on 23/23 (reused from the showreel). No narration: each destruction has a synthesized hit and tick, 23/23 lands on a boom (`scripts/mix_bed.py`).

## 8. console — 2:27.1, 18.6 s  (`compositions/frames/05d-console.html`)

Read-only screenshots of platform.armoriq.ai: a live run's session, the agent and MCP server, the trace with the deny, Policy Studio's five allow rules.

> In the ArmorIQ console, our live runs show up: the agent and its MCP server, every allowed call, and the one that was blocked.
> And these are our rules in Policy Studio: the five recovery tools are allowed, and restoring access is denied.

## 9. mcp — 2:45.7, 12.6 s  (`compositions/frames/08b-mcp-live.html`)

Replay of the live `demo-mcp-agent` run (`docs/evidence/mcp-live-agent-run.json`, reused from the showreel).

> Bring your own agent. Any MCP client can drive VeerIQ's recovery server. Six tools are exposed, five are signed, and one is refused, all checked inside the server.

## 10. integrate — 2:58.3, 13.6 s  (`compositions/frames/07-integrate.html`)

Four steps; terminals for `docker compose ... up` and `python tasks.py armoriq-register` with its real output.

> So how do you plug VeerIQ into your system? Four steps. First, deploy it with Docker.
> Second, connect ArmorIQ with one command. It registers the agent, the MCP server, and the policy.

## 11. import — 3:11.9, 23.7 s  (footage + overlay)

Recording of `/import` (`assets/footage/import.mp4`): scripted planner, live ArmorIQ, labelled. Write-back caveat on screen.

> Third, bring your data: CSV, JSON, or a read-only Postgres, plus an approved snapshot. Then map your columns: what may be repaired, and what must never change.
> Finally, authorize one narrow repair and run it. You get a receipt and a signed evidence file. Today, repairs land in VeerIQ's recovery workspace. Writing back to your own systems is next.

## 12. expect — 3:35.6, 22.8 s  (`compositions/frames/08-expect.html`)

Outcomes and the numbers from `evidence/SUMMARY.json`: 84 trials, 23 of 23 blocked, 0 forbidden effects, 18 of 24 repairs.

> So what can you expect? Only damaged values restored. Every later decision kept. Forbidden actions stopped before they run, with the layer that stopped them named. In eighty-four live trials, the model tried to re-enable the revoked account twenty-three times. ArmorIQ blocked all twenty-three. Zero forbidden effects.

## 13. learned — 3:58.4, 19.0 s  (`compositions/frames/12-learned.html`)

Two takeaways, three next steps.

> What we learned: plan binding stops a hijacked agent cold. But tools aren't arguments, so data rules have to live next to the data. Next, we want ArmorIQ holds for high-value repairs, argument-level policy, and connectors that write back through the same gates.

## 14. outro — 4:17.4, 12.0 s  (`compositions/frames/11-outro.html`)

Lockup, tagline, repo URL.

> VeerIQ. Restore yesterday's data. Keep today's decisions.
