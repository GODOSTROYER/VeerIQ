#!/usr/bin/env python3
"""Create private, disposable local OIDC realm material and TLS certificate."""

from __future__ import annotations

import json
import secrets
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / ".local-oidc"
REALM_DIR = PRIVATE / "realm"
TLS_DIR = PRIVATE / "tls"
REALM = "veeriq-local"
CLIENT_SECRET = secrets.token_urlsafe(36)
SUBJECTS = {
    "10000000-0000-4000-8000-000000000001": {
        "identity_id": "local-operator-a", "name": "Local Operator", "email": "operator-a@local.invalid",
        "role": "operator", "tenant_id": "atlas", "title": "Recovery operator", "initials": "LO", "color": "#2563EB",
    },
    "10000000-0000-4000-8000-000000000002": {
        "identity_id": "local-reviewer-a", "name": "Local Reviewer", "email": "reviewer-a@local.invalid",
        "role": "reviewer", "tenant_id": "atlas", "title": "Independent reviewer", "initials": "LR", "color": "#7C3AED",
    },
    "20000000-0000-4000-8000-000000000001": {
        "identity_id": "local-operator-b", "name": "Second Tenant Operator", "email": "operator-b@local.invalid",
        "role": "operator", "tenant_id": "beacon", "title": "Recovery operator", "initials": "TB", "color": "#059669",
    },
}


def main() -> None:
    if shutil.which("openssl") is None:
        raise SystemExit("openssl is required to create the private localhost TLS certificate")
    REALM_DIR.mkdir(parents=True, exist_ok=True)
    TLS_DIR.mkdir(parents=True, exist_ok=True)
    for path in (PRIVATE / ".env", REALM_DIR / f"{REALM}-realm.json"):
        if path.exists():
            raise SystemExit(f"{path.relative_to(ROOT)} already exists; remove the disposable .local-oidc directory to regenerate")
    users = []
    password_rows = []
    for subject, identity in SUBJECTS.items():
        password = secrets.token_urlsafe(18)
        users.append({
            "id": subject,
            "username": identity["email"],
            "email": identity["email"],
            "firstName": identity["name"].split()[0],
            "lastName": identity["name"].split()[-1],
            "enabled": True,
            "emailVerified": True,
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        })
        password_rows.append((identity["role"], identity["tenant_id"], identity["email"], password))
    realm = {
        "realm": REALM,
        "enabled": True,
        "sslRequired": "none",
        "clients": [{
            "clientId": "veeriq-local",
            "name": "VeerIQ local OIDC rehearsal",
            "enabled": True,
            "protocol": "openid-connect",
            "publicClient": False,
            "clientAuthenticatorType": "client-secret",
            "secret": CLIENT_SECRET,
            "standardFlowEnabled": True,
            "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": False,
            "redirectUris": ["https://localhost:8443/api/auth/callback"],
            "webOrigins": ["https://localhost:8443"],
            "attributes": {"pkce.code.challenge.method": "S256"},
        }],
        "users": users,
    }
    realm_path = REALM_DIR / f"{REALM}-realm.json"
    realm_path.write_text(json.dumps(realm, indent=2) + "\n", encoding="utf-8")
    realm_path.chmod(0o600)

    app_secret = secrets.token_urlsafe(48)
    env = {
        "POSTGRES_PASSWORD": secrets.token_urlsafe(30),
        "KEYCLOAK_ADMIN_USERNAME": "local-admin",
        "KEYCLOAK_ADMIN_PASSWORD": secrets.token_urlsafe(30),
        "REWINDSAFE_SESSION_SECRET": app_secret,
        "REWINDSAFE_OIDC_ISSUER": f"https://localhost:8444/realms/{REALM}",
        "REWINDSAFE_OIDC_CLIENT_ID": "veeriq-local",
        "REWINDSAFE_OIDC_CLIENT_SECRET": CLIENT_SECRET,
        "REWINDSAFE_OIDC_REDIRECT_URI": "https://localhost:8443/api/auth/callback",
        "REWINDSAFE_APP_ORIGIN": "https://localhost:8443",
        "REWINDSAFE_OIDC_SUBJECTS_JSON": json.dumps(SUBJECTS, separators=(",", ":")),
    }
    env_path = PRIVATE / ".env"
    env_path.write_text("".join(f"{key}={value}\n" for key, value in env.items()), encoding="utf-8")
    env_path.chmod(0o600)
    credentials_path = PRIVATE / "credentials.txt"
    credentials_path.write_text(
        "Local Keycloak realm credentials (private; use only on this machine)\n"
        f"Admin: {env['KEYCLOAK_ADMIN_USERNAME']} / {env['KEYCLOAK_ADMIN_PASSWORD']}\n"
        + "\n".join(f"{tenant} {role}: {email} / {password}" for role, tenant, email, password in password_rows)
        + "\n",
        encoding="utf-8",
    )
    credentials_path.chmod(0o600)

    key = TLS_DIR / "localhost.key"
    cert = TLS_DIR / "localhost.crt"
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-nodes", "-days", "7",
        "-keyout", str(key), "-out", str(cert), "-subj", "/CN=localhost",
        "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
        "-addext", "extendedKeyUsage=serverAuth",
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    key.chmod(0o600)
    cert.chmod(0o600)
    print("Created private local OIDC fixture and seven-day localhost certificate.")
    print("Three users cover operator, reviewer, and a second tenant; generated credentials are stored only in .local-oidc/.")
    print("Private login details are in .local-oidc/credentials.txt.")


if __name__ == "__main__":
    main()
