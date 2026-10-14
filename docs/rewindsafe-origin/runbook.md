# Runbook

## Ports

| Port | Service |
|---|---|
| 5433 | PostgreSQL 16 (Docker, bound to 127.0.0.1) |
| 8020 | FastAPI backend (moved off 8000, which other local tools often use) |
| 5173 | Vite dev UI (proxies `/api` to 8020) |

## Prerequisites

Python 3.12, `uv`, Node 24, Docker Desktop running. Windows 11 is the primary dev platform; `make` is not available there, so use `python tasks.py`.

## Setup

```
python tasks.py setup
```

Copies `.env.example` to `.env` if missing, installs backend (uv) and frontend (npm) dependencies, starts Postgres from `docker-compose.yml`, applies `backend/migrations/*.sql`, and prints which modes the current `.env` produces. With no keys, the app runs in SIMULATED enforcement with the scripted re-enactment planner.

Optional configuration in `.env`: `ARMORIQ_API_KEY`, `ARMORIQ_USER_EMAIL`, `GROQ_API_KEY` (live LLM; planner auto order is Anthropic, Groq, OpenAI, scripted), `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`. See `docs/sdk-integration.md`.

## Going live

1. **Live ArmorIQ.** Put `ARMORIQ_API_KEY` and `ARMORIQ_USER_EMAIL` (the account that owns the key) in `.env`, then run `python tasks.py armoriq-register` once. It renders `armoriq/armoriq.yaml` with your email and registers the agent plus the allowlist (5 recovery tools allowed, `restore_access_grant` denied). Without it every check fails closed with `no_matching_policy`.
2. **Check it.** `python tasks.py live-evidence` writes `evidence/gate-a-<UTC>.json`; `/api/system/status` shows `enforcement.readiness` (`verified`, `unverified`, `failed` or `simulated`).
3. **Live LLM.** Put `GROQ_API_KEY` in `.env` (model defaults to `openai/gpt-oss-120b`, override with `REWINDSAFE_GROQ_MODEL`). `python tasks.py eval-injection` records how each available Groq model reacts to the poisoned snapshot (writes `evidence/injection-eval-<UTC>.json`; add `--with-enforcement` to pass proposed `restore_access_grant` calls through the live ArmorIQ check).
4. **Optional ArmorIQ HOLD (dashboard only, not done).** Add an amount threshold on `apply_repair_manifest` (approval required above $5,000) in the ArmorIQ dashboard. Re-run `live-evidence` and keep the file. Until then no ArmorIQ HOLD exists and the review scenario holds via RewindSafe's reviewer.

## Start

```
python tasks.py up
```

Open http://localhost:5173. Check `http://127.0.0.1:8020/api/health` (expects `{"ok":true}`) and `/api/system/status` for mode, planner and warnings. The header badge shows Live or Simulated.

On first start the database is migrated and the fixture seeded if empty.

## Reset the demo

Operator only (Nova): header "Reset demo", or

```
python tasks.py reset-demo
```

Reset restores the disposable fixture, bumps the fixture generation, cancels pending approvals and older non-terminal runs, and marks old manifests superseded. Run history remains. Reset before every demo take.

## Running the tests

```
python tasks.py test        # offline acceptance suite; creates and drops its own database
python tasks.py test-live   # Gate A; needs ARMORIQ_API_KEY and network
python tasks.py verify      # verification suite, results appear on the Proof Board
```

Tests use a throwaway database `rs_test_<pid>_<rand>` and never touch the `rewindsafe` database.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `connection refused` on 5433 | Docker not running or container stopped. Start Docker Desktop, then `docker compose up -d` |
| Port 5433 already in use | Another Postgres is bound. Stop it or change the mapping in `docker-compose.yml` and `DATABASE_URL` |
| Port 8020 or 5173 busy | Find the owner with `netstat -ano` (filter for the port), then `taskkill /PID <pid> /F` |
| App refuses to start with "live" message | `REWINDSAFE_ENFORCEMENT=live` without `ARMORIQ_API_KEY`. Set the key or use `auto`/`offline`. This is intentional: no silent fallback |
| Banner says SIMULATED | No ArmorIQ key configured. Expected offline. Not an ArmorIQ result |
| `test-live` exits 2 "BLOCKED" | Missing `ARMORIQ_API_KEY`. By design it is never a pass |
| Live run: "ArmorIQ blocked inspect_snapshot" / reason `no_matching_policy` or `workspace_not_registered` | Your workspace has no policy for this agent. Run `python tasks.py armoriq-register` (needs `ARMORIQ_USER_EMAIL` in `.env`) |
| `armoriq-register` says to set a variable | `ARMORIQ_API_KEY` and `ARMORIQ_USER_EMAIL` must both be in `.env` |
| Groq returns 429 / agent never finishes | Rate limit or bad key. Retry, or set `REWINDSAFE_PLANNER=scripted` for the labeled re-enactment |
| Draft says the fixture is dirty | A previous run already repaired orders. Use "Reset & run" or `python tasks.py reset-demo` |
| ArmorIQ decisions show `unavailable` | The SDK could not reach ArmorIQ (network, key, proxy). The system fails closed; check connectivity and the key prefix (`ak_live_`, `ak_test_`, `ak_claw_`) |
| Agent never finishes in LLM mode | Missing or invalid provider key (`GROQ_API_KEY`, `ANTHROPIC_API_KEY`); the app will not read ambient `ANTHROPIC_BASE_URL`. Use `REWINDSAFE_PLANNER=scripted` |
| UI shows stale data after reset | Hard refresh; the UI refetches on `state.changed` events |
| Approval never arrives | Switch identity to Orion (reviewer) and open Approvals; the requester cannot approve their own request |
| SSE stream drops | The UI falls back to polling `/events/list` |

### Windows notes

- Use PowerShell or Git Bash; `python tasks.py ...` works in both.
- Use forward slashes in paths passed to scripts.
- The backend uses synchronous psycopg because async psycopg is unreliable on Windows' Proactor event loop. Do not change it.
- If PowerShell blocks script activation, run commands through `uv run` rather than activating a venv.
- Docker Desktop must use the WSL2 or Hyper-V backend and be running before `setup`.
- Antivirus or file-lock errors during `npm install`: close editors holding `node_modules`, retry.

## Before recording the demo

1. `python tasks.py reset-demo`
2. Confirm header badge, planner label (live Groq or scripted re-enactment) and generation match what you will say.
3. Do one live Groq rehearsal and keep it as the labeled fallback; reset again. Follow `docs/demo-script.md`.
4. Close other tabs; set the browser to 1920x1080 at 100% zoom.
