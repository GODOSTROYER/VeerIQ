#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PRIVATE="$ROOT/.local-oidc"
if [[ -f "$PRIVATE/.env" ]]; then
  docker compose --env-file "$PRIVATE/.env" -f deploy/local-oidc/compose.yml down --volumes --remove-orphans
fi
echo "Local OIDC containers stopped and their dedicated rehearsal database volume removed."
