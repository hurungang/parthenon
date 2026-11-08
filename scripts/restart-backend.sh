#!/usr/bin/env bash
# Restart Parthenon services (CC, CH, AR, Frontend) on macOS using the project venv.
# Usage: scripts/restart-backend.sh
# Do NOT use the system/Cellar Python — it lacks the project dependencies
# (opentelemetry exporters etc.) and workers die silently at startup.
#
# Startup order matters: Communication Hub and Agent Runtime validate Control
# Center reachability at startup and FAIL FAST (sys.exit) when CC is not up.
# Each service is therefore launched only after the previous one answers on
# its port (port-ready polling — never fixed sleeps; CC startup includes
# seeders/adoption and can take well over 10s).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend" || exit 1
PY="$ROOT/.venv/bin/python"
LOG="$ROOT/backend/logs"

# Per-service bootstrap keys from .env: each service presents its own
# key as SERVICE_BOOTSTRAP_KEY (AR ↔ AGENT_RUNTIME_BOOTSTRAP_KEY,
# CH ↔ COMM_HUB_BOOTSTRAP_KEY). CC is the CA and needs none.
AGENT_KEY="$(grep '^AGENT_RUNTIME_BOOTSTRAP_KEY=' .env | cut -d= -f2)"
CH_KEY="$(grep '^COMM_HUB_BOOTSTRAP_KEY=' .env | cut -d= -f2)"

pkill -9 -f "uvicorn app.main" 2>/dev/null
pkill -9 -f "uvicorn app.communication_hub" 2>/dev/null
pkill -9 -f "uvicorn app.agent_runtime" 2>/dev/null
# Orphaned multiprocessing workers (--reload spawn children) survive their
# parents and keep the ports bound — kill any listener on the service ports.
for port in 8000 8001 8002; do
  lsof -tiTCP:$port -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null
done
# Frontend: kill stale Vite dev (5173) and preview (4173) servers
lsof -tiTCP:5173 -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null
lsof -tiTCP:4173 -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null
sleep 2

start() { # $1=module $2=port $3=logfile $4=extra env (KEY=value, optional)
  if [ -n "${4:-}" ]; then
    nohup env "$4" "$PY" -m uvicorn "$1" --host 0.0.0.0 --port "$2" --no-access-log >> "$LOG/$3" 2>&1 < /dev/null &
  else
    nohup "$PY" -m uvicorn "$1" --host 0.0.0.0 --port "$2" --no-access-log >> "$LOG/$3" 2>&1 < /dev/null &
  fi
  disown
}

# wait_ready port name [timeout_seconds]
# Poll until the port answers with ANY HTTP status. Any non-000 response means
# the server is up — 401/403/404 are fine (fail-closed endpoints stay
# fail-closed; docs may be disabled). Only connection failure (000) means
# "not ready yet".
wait_ready() {
  local port="$1" name="$2" timeout="${3:-60}"
  local waited=0 code
  while true; do
    code=$(curl -s -m 3 -o /dev/null -w "%{http_code}" "http://localhost:$port/docs" 2>/dev/null)
    if [ "$code" != "000" ]; then
      echo "✅ $name (port $port) ready after ${waited}s (HTTP $code)"
      return 0
    fi
    if [ "$waited" -ge "$timeout" ]; then
      echo "❌ $name (port $port) did not become ready within ${timeout}s"
      return 1
    fi
    sleep 2
    waited=$((waited + 2))
  done
}

# ── 1. Control Center first (CH/AR validate CC reachability at startup) ────
cc_ok=0
start app.main:app 8000 control-center.log
if wait_ready 8000 "Control Center" 90; then cc_ok=1; fi

# ── 2. Communication Hub (needs CC up) ──────────────────────────────────────
ch_ok=0
if [ "$cc_ok" = "1" ]; then
  start app.communication_hub.main:app 8002 communication-hub.log "SERVICE_BOOTSTRAP_KEY=$CH_KEY"
  if wait_ready 8002 "Communication Hub" 60; then ch_ok=1; fi
else
  echo "⏭️  Skipping Communication Hub — Control Center never became ready"
fi

# ── 3. Agent Runtime (needs CC up) ──────────────────────────────────────────
ar_ok=0
if [ "$cc_ok" = "1" ]; then
  start app.agent_runtime.main:app 8001 agent-runtime.log "SERVICE_BOOTSTRAP_KEY=$AGENT_KEY"
  if wait_ready 8001 "Agent Runtime" 60; then ar_ok=1; fi
else
  echo "⏭️  Skipping Agent Runtime — Control Center never became ready"
fi

# ── 4. Frontend — Vite dev server (5173; never treat 4173 preview as ready) ─
cd "$ROOT/frontend" || exit 1
nohup npm run dev >> "$LOG/frontend.log" 2>&1 < /dev/null &
disown
cd "$ROOT/backend"
fe_ok=0
if wait_ready 5173 "Frontend" 60; then fe_ok=1; fi

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "=== Final status ==="
ok=1
[ "$cc_ok" = "1" ] || { echo "❌ Control Center (port 8000)"; ok=0; }
[ "$ch_ok" = "1" ] || { echo "❌ Communication Hub (port 8002)"; ok=0; }
[ "$ar_ok" = "1" ] || { echo "❌ Agent Runtime (port 8001)"; ok=0; }
[ "$fe_ok" = "1" ] || { echo "❌ Frontend (port 5173)"; ok=0; }
if [ "$ok" = "1" ]; then
  echo "All services healthy."
else
  echo "One or more services failed — check $LOG/ and $ROOT/frontend.log"
fi
exit $((1 - ok))
