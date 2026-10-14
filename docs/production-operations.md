# Production deployment and identity setup

The local preview continues to use `docker-compose.yml`, PostgreSQL on `127.0.0.1:5436`, and demo identities. Production uses the separate full-stack `compose.production.yml`, which sets `REWINDSAFE_ENV=production`. That profile refuses to start unless sign-in is OIDC and ArmorIQ enforcement is live (`ARMORIQ_API_KEY` is set and `REWINDSAFE_ENFORCEMENT` is `live`). It also refuses demo login, a default or weak session secret, an insecure cookie setting, or missing subject mappings. Development, the default `REWINDSAFE_ENV`, still allows demo sign-in and simulated enforcement.

## Identity provider requirements

Register VeerIQ as a confidential OpenID Connect web client using the authorization-code flow. Configure the exact callback URL `REWINDSAFE_OIDC_REDIRECT_URI` at the issuer. The application uses PKCE with S256, one-time state and nonce, issuer discovery, a fetched JWKS key, and ID-token signature, issuer, audience, expiry, issued-at, subject, and nonce validation.

The issuer subject is the key in `REWINDSAFE_OIDC_SUBJECTS_JSON`. VeerIQ assigns its tenant and role only from this operator-managed mapping; names, email addresses, tenant IDs, or role claims in a token cannot change authority. Map each issuer subject to a distinct `identity_id`. A reviewer must have a different issuer subject and identity ID from the operator who requested an approval, preserving separation of duties.

Each mapping has this shape:

```json
{
  "<stable-subject-from-the-configured-issuer>": {
    "identity_id": "<unique-veeriq-id>",
    "name": "<display-name>",
    "email": "<display-email>",
    "role": "operator",
    "tenant_id": "<admin-assigned-tenant>",
    "title": "<display-title>",
    "initials": "OP",
    "color": "#8B7CF6"
  }
}
```

Use `role: "reviewer"` for a second reviewer. The mapping is configuration, not a sample account; use the real stable `sub` values from your issuer and set distinct IDs for each person.

## Required environment

Provide these values through the deployment environment or a secret manager. Use a URL-safe, random database password because it is included in `DATABASE_URL` by Compose. Generate a session secret with at least 32 characters and 12 distinct characters. `ARMORIQ_API_KEY` is required: Compose does not start without it, and production never runs on simulated enforcement. The compose file itself sets `REWINDSAFE_ENV=production` and `REWINDSAFE_ENFORCEMENT=live`. The production compose file binds the app to port 8000 by default and keeps PostgreSQL off host ports.

```sh
export POSTGRES_PASSWORD='<random-url-safe-database-password>'
export REWINDSAFE_SESSION_SECRET='<random-secret-at-least-32-characters>'
export REWINDSAFE_OIDC_ISSUER='https://<issuer-host>/<issuer-path>'
export REWINDSAFE_OIDC_CLIENT_ID='<registered-client-id>'
export REWINDSAFE_OIDC_CLIENT_SECRET='<secret-manager-value>'
export REWINDSAFE_OIDC_REDIRECT_URI='https://<app-host>/api/auth/callback'
export REWINDSAFE_APP_ORIGIN='https://<app-host>'
export REWINDSAFE_OIDC_SUBJECTS_JSON='<admin-managed-subject-mapping-json>'
export ARMORIQ_API_KEY='<secret-manager-value>'
```

The compose file defaults `REWINDSAFE_PLANNER` to `scripted`. To run a live model, set `REWINDSAFE_PLANNER=llm` and provide one provider key (`GROQ_API_KEY`, `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`). `REWINDSAFE_ARMORIQ_TIMEOUT_S` defaults to 15 seconds.

Start the database and full-stack app with:

```sh
docker compose -f compose.production.yml up --build -d
```

The image runs as an unprivileged user. PostgreSQL and the app data directory use persistent volumes. The service has liveness and readiness endpoints at `/api/health/live` and `/api/health/ready`; Prometheus-format aggregate HTTP metrics are available at `/metrics` without user or tenant labels. Mutating API routes and OIDC login/callback have bounded per-client rate limits. Deploy one API process per instance unless the rate limiter is moved to a shared store.

## Production safeguards

- **Demo routes return 404.** In production, every `/api/admin/*` route (the synthetic-data reset, and the positive control that calls a privileged handler directly) and `POST /api/verification/run` return 404 to everyone, including anonymous requests. The check runs before sign-in.
- **ArmorIQ enforcement is live.** ArmorIQ signs each run's plan and checks each proposed call. An unreachable or timed-out check is refused as unavailable, and so is an allow that arrives with a non-2xx HTTP status. `REWINDSAFE_ARMORIQ_TIMEOUT_S` (default 15, allowed range 1 to 120) is the default timeout for ArmorIQ HTTP calls; the SDK itself fixes the enforce check at 10 seconds and plan issuance at 30 seconds. Live mode never falls back to simulation.
- **MCP over HTTP needs a token.** The production container runs only the API and UI. The MCP server is a separate process that `compose.production.yml` does not start. If you run it over HTTP, `REWINDSAFE_MCP_TOKEN` is required for any non-loopback host, and the server exits with code 2 without it. Once the token is set, every HTTP request must send `Authorization: Bearer <token>`. stdio needs no token.
- **Evidence is append-only.** Migration `backend/migrations/006_evidence_append_only.sql` makes `runtime.events` and `runtime.receipts` refuse UPDATE, DELETE and TRUNCATE by trigger, with no exception.
- **Grant scope is frozen.** A task grant's scope cannot change after it is created. Only its lifecycle fields (status, commits used, expiry, authorization fields and digest) may change. The commit limit cannot change, the commit count cannot decrease, an exhausted, expired or revoked grant cannot become active again, and a draft cannot become active without an authorizing identity.
- **Partial schemas are refused.** A database with no migration records is adopted as already at `001_schema.sql` only when the complete v1 schema is present. A partial schema is refused with an error that names the missing objects.

## Not yet production-proven

A real local Keycloak rehearsal is available in [local-oidc-rehearsal.md](local-oidc-rehearsal.md), with observed login and full-stack evidence. That rehearsal runs Keycloak in dev mode with a localhost certificate, so it is not evidence about a production identity provider. No external production OIDC issuer is configured in this repository. Production sign-in is intentionally not demoable until an operator registers a real issuer client, supplies secrets, and maps real issuer subject IDs. Startup discovery errors report the issuer configuration gap and fail closed.

- There has been no public deployment, load test or external security review.
- ArmorIQ hold and approval have not been observed live.
- Key rotation, load testing and operational security remain open gaps in [readiness-scorecard.md](readiness-scorecard.md).
