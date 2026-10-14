# Live demo for judging

Judges test the live demo between 17 and 21 October 2026 and score it on whether it works and is usable.
The live demo is the full VeerIQ workspace on synthetic data, with real ArmorIQ enforcement.

`REWINDSAFE_ENV=showcase` is the profile for it:

- Visitors sign in with the built-in demo identities (Maya the operator, Orion the reviewer). No account is needed.
- Enforcement is always live. Startup refuses `REWINDSAFE_ENFORCEMENT=offline`, a missing `ARMORIQ_API_KEY`,
  the default session secret, and a session cookie that is not HTTPS-only.
- The demo reset stays available, so each judge can start from an unrepaired incident.
- Writes are rate-limited (60 per minute by default).

## Run it

On any machine with Docker (a small VPS, or your own computer for the judging window):

```sh
export POSTGRES_PASSWORD="$(openssl rand -hex 24)"
export REWINDSAFE_SESSION_SECRET="$(openssl rand -hex 32)"
export ARMORIQ_API_KEY="..."          # generated at platform.armoriq.ai
export ARMORIQ_USER_EMAIL="you@example.com"
export GROQ_API_KEY="..."             # optional: lets judges run the live model; without it runs are scripted
docker compose -f compose.showcase.yml up -d --build
```

The app listens on `127.0.0.1:8000` only. Put HTTPS in front of it:

- **Cloudflare Tunnel** (no open ports): `cloudflared tunnel --url http://127.0.0.1:8000` gives a temporary
  `https://*.trycloudflare.com` URL. For a URL that survives restarts, create a named tunnel on your own domain.
- **A reverse proxy** (Caddy, nginx) on a VPS with a certificate.

Then onboard the agent and the MCP server once, from a checkout with the same `.env` values:

```sh
python tasks.py armoriq-register
```

## Before you submit the URL

- [ ] The header reads **System · Live**, not Simulated.
- [ ] Walkthrough loads and replays the recorded live run.
- [ ] Workspace, poisoned scenario: `restore_access_grant` is blocked by ArmorIQ and the repair commits.
- [ ] The same run appears in the ArmorIQ console at tools.armoriq.ai.
- [ ] Proof page downloads a signed export, and `./scripts/veeriq-verify` accepts it.
- [ ] Reset the demo, then open the URL in a private window to confirm a fresh visitor can do all of this.
- [ ] Keep the host running and the API key valid until 21 October 2026.

## Model quota

The model provider's daily quota stopped every recorded batch before 40 trials. If judges will run the live
model, use a key with headroom, or leave `GROQ_API_KEY` empty: the scripted planner still sends every call
through live ArmorIQ, and the UI labels the run as scripted.
