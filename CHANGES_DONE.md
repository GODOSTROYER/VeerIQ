# Changes done for the Flow State submission (17 Oct 2026)

VeerIQ is now pitched as **Ctrl+Z for AI agents**: when an agent or a bad change wrecks your database, VeerIQ undoes only the damage and keeps everything decided since, and ArmorIQ makes sure the fixer can't go rogue too. The changes below turn that into something a judge can understand in ten seconds and try in three minutes.

Two branches carry the work:

| Branch | Contents |
|---|---|
| `ctrl-z-judges` | The product: the judges' start page, two backend endpoints, tests, docs (this file) |
| `submission-video` | The 4:29 submission video and its HyperFrames project (also carries the showreel update from PR #2) |

## 1. The judges' start page (`/`)

The home page is now a guided demo with one button per step, all on live data. Run the app (`python tasks.py up`) and open http://localhost:5173.

| Step | What the judge does | What they see |
|---|---|---|
| 1. The damage | Start the demo (resets the demo data) | Three orders zeroed by a bad change, and three decisions made after the backup that must stay: an erased customer, a revoked leaked credential, a shipped order |
| 2. Undo it two ways | Run the AI repair | **Left:** what restoring the whole backup does to today's data: fixes 3, **breaks 4** (erased records come back, the leaked credential is re-enabled, the shipped order goes back to processing). **Right:** VeerIQ's agent on a live model (gpt-oss-120b on Groq). It takes the bait of a planted note; **ArmorIQ blocks `restore_access_grant`** with its reason on screen; only the damage is repaired and every later decision stays |
| 3. You are the second key | Become the approver, approve | A $12,400 repair waits for a second person; the requester can't approve it. The judge approves the exact change and it commits in one locked transaction |
| 4. Check our work | Verify in my browser, then change one number | The run's signed receipt is verified by the browser's own crypto (SHA-256 hash chain + Ed25519); changing one cent makes it fail. Plus the 84-run scoreboard and one-click MCP setup for Claude Code, Cursor and Claude Desktop |

Details:
- Progress survives a refresh or a detour into the full run view.
- The previous home page (Mission Control) moved to `/workspace`; the nav has "Start here" and "Workspace".
- After the judge decides, the page says the approval is being re-checked (not "preparing").

Files: `frontend/src/pages/Judges/index.tsx`, `frontend/src/lib/verifyEvidence.ts`, `frontend/src/App.tsx`, `frontend/src/components/shell/AppShell.tsx` and small link updates.

## 2. Backend

| Endpoint | What it does |
|---|---|
| `GET /api/app/full-rollback-preview` | Read-only: compares the approved snapshot with live data for the signed-in tenant and lists what a whole-backup restore would repair and what it would break. Writes nothing |
| `GET /api/judge/mcp-install/{grant_id}` | For an authorized grant: the `claude mcp add` command, a Cursor install deeplink and the Claude Desktop config that run VeerIQ's MCP server over stdio |

Files: `backend/rewindsafe/workflows/rewindsafe/queries.py`, `backend/rewindsafe/api/routes_app.py`, `backend/rewindsafe/api/routes_judge.py`, `backend/rewindsafe/api/app.py`.

## 3. Tests

- `backend/tests/unit/test_judge.py` (6 tests): the rollback preview finds the 3 repairs and 4 harms, writes nothing, and keeps tenants apart; the MCP install endpoint returns working commands, refuses a draft grant and needs a session.
- `frontend/src/lib/verifyEvidence.test.ts` (6 tests): the in-browser verifier accepts the signed exports, rejects the shipped tampered copy and a one-cent change, keeps number tokens verbatim (1.0 stays 1.0) and reports malformed input as invalid.
- Frontend: 210 tests pass; production build passes.
- Backend unit suite: all pass except `test_poisoned_run_blocks_replans_and_still_repairs`, which fails only when the local `.env` sets live enforcement (its expected text says "simulated offline policy"); it fails the same way without these changes.

## 4. Docs

- `README.md`: opens with the pitch, the July 2025 incident (sourced), and a "For judges: try it in 3 minutes" table with a screenshot (`docs/img/judges-1440.png`).
- `docs/armoriq-findings.md`: what we learned building on ArmorIQ (plan binding 23/23; tools are checked, arguments are not; the amount-based hold could not be applied in our workspace; enforcement latency p50 828 ms / p95 1.56 s; what we would ask for).

## 5. The submission video (branch `submission-video`)

`videos/demo-video/final/veeriq-demo-1080p.mp4` (Git LFS): 4:29, 1080p60, narrated, captions burned in. Replaced on 17 Oct by the final 4:21 cut (same path); the section timings below describe the earlier 4:29 cut.

| Time | Section |
|---|---|
| 0:00 | The July 2025 incident (sourced on screen), then the story: a backup brings back what you decided since |
| 0:36 | Meet VeerIQ, three promises, the system diagram |
| 1:14 | Live screen recording of the judges' start page: full restore vs VeerIQ, ArmorIQ blocking the trap, the judge as second key, browser verification. Speeds shown in the rail; two cuts labelled |
| 2:18 | The boundary: 23 `restore_access_grant` requests destroyed at the wall, 23/23, with a hit for each |
| 2:27 | ArmorIQ console and Policy Studio (read-only screenshots of a live run) |
| 2:45 | MCP, plugging it in (Docker, `armoriq-register`, `/import`), what to expect, takeaways, repo URL |

Audio fixes since the first cut: narration lines are cut in the real pauses with the click and full-scale noise burst Gemini TTS leaves at each end removed; the music dips smoothly under each line instead of pumping between words; the digital glitch effects are gone.

Rebuild: `videos/demo-video/README.md`.

## Not done

- **Hosted demo.** _Historical note, superseded (17 Oct 2026):_ at the time of writing it was skipped and `veeriq.arnavbule.in` had no DNS record. Current deployment status: [`docs/submission-status.md`](docs/submission-status.md).
- **A real ArmorIQ hold.** The $12,400 approval is VeerIQ's own second-reviewer step and is labelled that way; the amount-based hold could not be applied in our ArmorIQ workspace (`docs/armoriq-hold-setup.md`).
- **Write-back to the source system.** Repairs land in VeerIQ's recovery workspace (said and shown in the video).

## Numbers used anywhere

Only from `evidence/SUMMARY.json`: 84 live trials, the model tried to re-enable the revoked account 23 times, ArmorIQ blocked 23 of 23, 0 forbidden effects observed in 82 records with effect observations (2 interrupted records lack them), 18 of 24 repairs. All data is synthetic.
