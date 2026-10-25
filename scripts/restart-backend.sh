#!/usr/bin/env bash
# Restart Parthenon services (CC, CH, AR, Frontend) on macOS using the project venv.
# Usage: scripts/restart-backend.sh
# Do NOT use the system/Cellar Python — it lacks the project dependencies
# (opentelemetry exporters etc.) and workers die silently at startup.
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
start app.main:app 8000 control-center.log
sleep 10
start app.communication_hub.main:app 8002 communication-hub.log "SERVICE_BOOTSTRAP_KEY=$CH_KEY"
sleep 8
start app.agent_runtime.main:app 8001 agent-runtime.log "SERVICE_BOOTSTRAP_KEY=$AGENT_KEY"

# Frontend — Vite dev server (5173; never treat 4173 preview as ready)
cd "$ROOT/frontend" || exit 1
nohup npm run dev >> "$LOG/frontend.log" 2>&1 < /dev/null &
disown
cd "$ROOT/backend"
sleep 12

ok=1
probe() { # $1=port $2=path $3=name $4=method
  code=$(curl -s -m 8 -o /dev/null -w "%{http_code}" -X "$4" "http://localhost:$1$2" -H 'Content-Type: application/json' -d '{}' 2>/dev/null)
  if [ "$code" = "000" ]; then echo "❌ $3 (port $1) NOT responding"; ok=0; else echo "✅ $3 (port $1) → $code"; fi
}
probe 8000 /api/v1/scripts "Control Center" POST
probe 8001 /execute "Agent Runtime" POST
probe 8002 /internal/tools/call "Communication Hub" POST
code=$(curl -s -m 8 -o /dev/null -w "%{http_code}" http://localhost:5173/ 2>/dev/null)
if [ "$code" = "000" ]; then echo "❌ Frontend (port 5173) NOT responding"; ok=0; else echo "✅ Frontend (port 5173) → $code"; fi

[ "$ok" = "1" ] && echo "All services healthy." || echo "One or more services failed — check $LOG/ and $ROOT/frontend.log"
