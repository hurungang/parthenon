#!/usr/bin/env bash
# Stop the Agent Client demo app (macOS / Linux).
set -euo pipefail
PORT="${PORT:-7002}"

PID="$(lsof -ti :"$PORT" || true)"
if [ -n "$PID" ]; then
  kill -9 $PID
  echo "🛑 Stopped Agent Client Demo (port $PORT)"
else
  echo "✅ Agent Client Demo is not running on port $PORT"
fi
