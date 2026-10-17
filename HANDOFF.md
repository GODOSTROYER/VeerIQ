# Handoff for the next agent (15 October 2026)

VeerIQ is the team's entry for ArmorIQ Flow State: a recovery agent that repairs damaged database values
from an approved snapshot without undoing later decisions, with ArmorIQ deciding what the agent may do.
Submissions close **17 Oct 2026, 11:59 PM IST**; the live demo must work **17–21 Oct**; results 22 Oct.
Read [`README.md`](README.md), then [`docs/submission.md`](docs/submission.md) (form answers, takeaways),
then [`videos/AGENT-CONTEXT.md`](videos/AGENT-CONTEXT.md) if you touch the videos.

## Where things live

- **This repo, `GODOSTROYER/VeerIQ`** (private) is the submission repo. `main` started as one squashed commit;
  later changes arrive by pull request. The 180 MB showreel MP4 is in Git LFS (`.gitattributes`).
- The original team repo is `ayushcody/veeriq`. A local clone had this work on branch `hackathon-hardening`,
  uncommitted; treat this repo as the source of truth.

## What is done

- **Agent over MCP.** `backend/rewindsafe/agent/mcp_agent.py`: VeerIQ's planners drive the `rewindsafe-recovery`
  MCP server (stdio subprocess or streamable HTTP). Every action is an MCP `tools/call`; ArmorIQ, the grant and the
  database rules are enforced inside the server (`source="mcp"`). `python tasks.py demo-mcp-agent`. Verified on a
  real stdio subprocess with the offline simulation (no key on the dev machine).
- **Live-demo profile.** `REWINDSAFE_ENV=showcase` + `compose.showcase.yml` + `docs/live-demo.md`: demo sign-in,
  synthetic data, refuses to start without live ArmorIQ, a strong session secret and HTTPS-only cookies.
- **Hardening (14 Oct).** Schema limits in the dispatcher, ArmorIQ timeout and non-2xx fail-closed, append-only
  evidence and frozen grant scope (migration 006), production profile (OIDC + live required), MCP bearer token,
  admin routes hidden in production, import refusals, email masking, sealed-evidence trust basis.
- **Evidence.** 84 live trials pooled in `evidence/SUMMARY.json` (`python scripts/summarize_reliability.py`):
  23 of 23 injected `restore_access_grant` calls blocked by ArmorIQ plan binding, 0 forbidden effects observed in the 82 records with effect observations (2 interrupted records lack them).
- **Docs.** README requirement table and MCP section; `docs/submission.md`; 4-minute `docs/demo-script.md`;
  `docs/live-demo.md`; `PROGRESS.md` (dated log).
- **Videos.** 96 s HyperFrames showreel rendered 14 Oct (`videos/veeriq-showreel/`); needs updating, see
  `videos/AGENT-CONTEXT.md`. The 4:21 submission demo video is delivered at `videos/demo-video/final/veeriq-demo-1080p.mp4`; public upload link pending. Current status: `docs/submission-status.md`.
- **CI** passes on `main`: lint, 538 backend tests, verifier acceptance, reliability summary, 210 frontend tests,
  build, production image, gitleaks. Runners pinned to `ubuntu-24.04` through the judging window.

## What is not done

Only the team can do these:

1. ArmorTools Pro for every member at tools.armoriq.ai, code `FLOWSTATEPRO` (unjudged without it).
2. An API key generated at platform.armoriq.ai in `.env`, then `python tasks.py armoriq-register` (registers the
   agent and the MCP server). The ArmorClaude dev login on the dev machine is a staging plugin key, not this.
3. Policy Studio: confirm or create "allow the five recovery tools" and "deny `restore_access_grant`".
4. One live `python tasks.py demo-mcp-agent` run, to confirm the MCP path against live ArmorIQ.
5. The showcase is deployed on Railway (project `veeriq`, service `veeriq-app`) at https://veeriq.arnavbule.in. It starts only once `ARMORIQ_API_KEY` is set in the service variables and the DNS records are in place. Turn App Sleeping off for 17–21 Oct; the static walkthrough is at https://veeriq.vercel.app.
6. Record and upload the 3–5 min demo video (unlisted); post on X (@ArmorIQForDevs) or LinkedIn (ArmorIQ) with
   #FlowStateHackathon; submit https://forms.gle/fxkXnY8xgeyZ3QQX6.
7. Give judges access to this private repo, or make it public.

Not done and not claimed: ArmorIQ hold/approval has never been observed live; no fresh reliability cohort
on the current code; no load test or external security review.

## How to work here

```sh
npm run setup && npm run dev                # http://127.0.0.1:5173, offline simulation without keys
python tasks.py demo-agent-attack           # in-process agent
python tasks.py demo-mcp-agent              # agent over MCP
npm run test && npm run test:frontend       # backend needs Docker Postgres
```

On the dev machine the test Postgres is on port 5436: set
`REWINDSAFE_TEST_ADMIN_DSN=postgresql://rewindsafe:rewindsafe@127.0.0.1:5436/postgres`, and give pytest a writable
`--basetemp` on Windows. The machine also runs other heavy projects; low memory makes HyperFrames and Chrome
fail to shut down, so free memory before blaming the code.

Pushing here: open a PR, let CI pass, then merge. If someone asks for a single-commit history again, rebuild it
with a temporary `GIT_INDEX_FILE`, `git commit-tree`, restore the eight executable bits (`git update-index
--chmod=+x`), push LFS objects first, then force-push. `.gitleaksignore` uses `file:rule:line` fingerprints so
the secret scan survives a rewritten history.

## Rules for anything you write

- Every number must trace to `evidence/`, `docs/evidence/` or a command's output.
- Never state or imply an ArmorIQ hold or approval was seen live.
- Label simulated and scripted runs as such; the security demo must use real ArmorIQ enforcement.
- All data is synthetic. Significant pre-existing work is disclosed in `docs/rewindsafe-origin/attribution.md`.
