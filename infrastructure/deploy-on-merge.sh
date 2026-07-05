#!/bin/bash
# deploy-on-merge.sh — rebuild telos/web and restart telos-web.service.
# Invoked via SSM from telos / telos-ops deploy workflows.
set -uo pipefail

REPO=/home/ec2-user/telos
echo "=== telos deploy $(date -u +%FT%TZ) — telos@$(git -C "$REPO" rev-parse --short HEAD) telos-ops@$(git -C "$REPO/../telos-ops" rev-parse --short HEAD) ==="

cd "$REPO/web"
npm install --no-audit --no-fund --silent || { echo "npm install FAILED"; exit 1; }
NODE_OPTIONS=--max-old-space-size=700 npm run build || { echo "web build FAILED"; exit 1; }

# Hydrate dashboard env from telos-ops/.env (operator-maintained; not committed).
ENVF="$REPO/../telos-ops/.env"
if [[ -f "$ENVF" ]]; then
  grep -E '^(TAX_PROJECTION_PATH|METRON_API_URL|METRON_TENANT_ID|METRON_PORTFOLIO_ID)=' "$ENVF" \
    > "$REPO/web/.env.production.local" || true
fi

sudo systemctl restart telos-web
sleep 4

code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3001/dash)
case "$code" in
  200) echo "deploy OK — telos-web HTTP $code" ;;
  *) echo "telos-web check FAILED (HTTP $code)"; exit 1 ;;
esac
