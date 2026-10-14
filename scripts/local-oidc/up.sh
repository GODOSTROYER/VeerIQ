#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PRIVATE="$ROOT/.local-oidc"
ENV_FILE="$PRIVATE/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  python3 scripts/local-oidc/generate.py
fi

docker compose --env-file "$ENV_FILE" -f deploy/local-oidc/compose.yml up -d --build --wait
echo "VeerIQ OIDC rehearsal is ready at https://localhost:8443"
echo "Keycloak OIDC is at https://localhost:8444; credentials are in .local-oidc/credentials.txt"
