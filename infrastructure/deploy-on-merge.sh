#!/bin/bash
# deploy-on-merge.sh — rebuild telos/web and restart telos-web.service.
# Invoked via SSM from telos / telos-ops deploy workflows.
#
# The post-restart health probe polls with a bounded deadline instead of a fixed
# `sleep 4` and one curl: `npm run start` cold-starts Next.js on a shared, loaded box
# and is sometimes not listening 4s after the restart, so the single probe read
# HTTP 000 (no connection) on a healthy deploy (telos runs 40582494053, 41174930868)
# while the next deploy of the same SHAs, a minute later, answered 200.
# The deadline stays well under the 100s `aws ssm wait command-executed` budget in
# .github/workflows/deploy.yml so a genuinely dead service still reports its output.
#
# Paths and probe settings are overridable by environment so tests/test_deploy_on_merge.py
# can run this script against a fake box; production uses the defaults.
set -uo pipefail

REPO="${TELOS_REPO:-/home/ec2-user/telos}"
HEALTH_URL="${TELOS_HEALTH_URL:-http://127.0.0.1:3001/dash}"
HEALTH_TIMEOUT="${TELOS_HEALTH_TIMEOUT:-30}"
HEALTH_INTERVAL="${TELOS_HEALTH_INTERVAL:-2}"
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

sudo systemctl restart telos-web || { echo "systemctl restart telos-web FAILED"; exit 1; }

start=$SECONDS
deadline=$((SECONDS + HEALTH_TIMEOUT))
attempts=0
while :; do
  attempts=$((attempts + 1))
  code=$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$HEALTH_URL")
  [[ "$code" == "200" ]] && break
  (( SECONDS >= deadline )) && break
  sleep "$HEALTH_INTERVAL"
done

if [[ "$code" == "200" ]]; then
  echo "deploy OK — telos-web HTTP $code after $((SECONDS - start))s ($attempts probes)"
else
  echo "telos-web check FAILED (HTTP $code after ${HEALTH_TIMEOUT}s, $attempts probes)"
  # Unit state only, never journal lines: this output lands in a PUBLIC Actions log,
  # and the dashboard's log could carry projection values.
  echo "telos-web unit: $(systemctl is-active telos-web 2>/dev/null || true)"
  exit 1
fi
