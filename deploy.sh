#!/usr/bin/env bash
# Usage: ./deploy.sh [main|bounty]
set -euo pipefail
cd "$(dirname "$0")"
target="${1:-main}"

case "$target" in
  main)
    git fetch origin
    git checkout main
    git pull --ff-only origin main
    docker compose up -d --build caddy apc-main
    ;;
  bounty)
    # The bugbounty branch is frozen at 12:00 AM on 16 Oct. Build it once; never rebuild by accident.
    if docker compose --profile bounty ps -q apc-bounty | grep -q . && [ "${FORCE:-0}" != "1" ]; then
      echo "apc-bounty is already running. Refusing to rebuild (set FORCE=1 to override)." >&2
      exit 1
    fi
    rm -rf .bounty-src
    git clone --branch bugbounty --single-branch "$(git remote get-url origin)" .bounty-src
    docker compose --profile bounty up -d --build apc-bounty caddy
    ;;
  *)
    echo "Usage: $0 [main|bounty]" >&2
    exit 2
    ;;
esac
docker compose ps
