# Local OIDC rehearsal

This optional rehearsal uses a disposable Keycloak realm to exercise VeerIQ's actual authorization-code login, PKCE, token signature/issuer/audience/nonce checks, opaque server session, tenant mapping, and role checks. It does not contact a public identity provider or change production authentication rules.

Requirements: Docker Compose, Python 3, and OpenSSL. Ports `8443` and `8444` must be available. VeerIQ, Keycloak, and PostgreSQL run in a dedicated Compose project with separate volumes; only the two localhost HTTPS ports are exposed. The certificate and generated passwords are stored with mode `0600` under the ignored `.local-oidc/` directory.

Start the rehearsal:

```sh
./scripts/local-oidc/up.sh
```

Open `https://localhost:8443` in a browser and proceed through **Sign in**. The certificate is a short-lived self-signed localhost certificate. For a browser test, explicitly allow the certificate warning for this local session; do not add it to system trust. Generated account details are in `.local-oidc/credentials.txt`. The fixture has an operator and reviewer in the seeded `atlas` tenant plus an operator in the seeded `beacon` tenant. The account roles and tenant identities come from the server-side subject mapping; Keycloak profile claims do not grant VeerIQ authority.

To check the provider metadata and anonymous API boundary without printing credentials:

```sh
curl --cacert .local-oidc/tls/localhost.crt https://localhost:8444/realms/veeriq-local/.well-known/openid-configuration
curl --cacert .local-oidc/tls/localhost.crt https://localhost:8443/api/auth/config
```

To repeat full sign-in and authorization checks against the live local Keycloak and VeerIQ containers:

```sh
python3 scripts/local-oidc/check-login.py
```

This follows the real Keycloak login form over HTTPS, submits each generated account, then verifies the OIDC callback, server-side token validation, opaque secure cookie, mapped tenant and role, tenant-scoped identities and application data, cross-tenant grant isolation, role denials, and disabled demo impersonation. It reads credentials locally and prints only pass/fail outcomes.

With the repository's Playwright browser installed, run the isolated headless browser sign-in too:

```sh
node frontend/scripts/local-oidc-browser-check.mjs
```

The browser check ignores the self-signed certificate only in its own temporary local test contexts. VeerIQ's server still verifies that certificate through its mounted CA file.

Stop the app and remove only the dedicated rehearsal containers and database volume:

```sh
./scripts/local-oidc/down.sh
```

Remove `.local-oidc/` to erase the generated realm, login details, and keys. Do not reuse these local-only accounts or secrets in another environment. This rehearsal proves local protocol integration only; its self-signed certificate, synthetic identities, scripted planner, and offline ArmorIQ mode do not establish public production readiness or external identity-provider deployment.

The effect-producing login check assumes a fresh dedicated rehearsal database. For a repeat from scratch, use the documented `down.sh` and `up.sh` for this dedicated stack only; the main preview database is separate and must not be reset.
