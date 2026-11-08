#!/usr/bin/env bash
# Start the Agent Client demo app (macOS / Linux).
#
# Requires Python 3.11+. Prefers the repo project venv (../.venv), then
# python3.11, then python3 (validated). Override with PYTHON=/path/to/python3.11.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-7002}"

# ── Pick a Python >= 3.11 ────────────────────────────────────────────────────
if [ -n "${PYTHON:-}" ]; then
  PY="$PYTHON"
elif [ -x ../.venv/bin/python ]; then
  PY="$(cd ../.venv/bin && pwd)/python"
elif command -v python3.11 >/dev/null 2>&1; then
  PY="$(command -v python3.11)"
else
  PY="$(command -v python3 || true)"
fi

if [ -z "$PY" ] || ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)' 2>/dev/null; then
  echo "❌ Python 3.11+ is required but not found."
  echo "   Tried: \$PYTHON, ../.venv/bin/python, python3.11, python3."
  echo "   Set PYTHON=/path/to/python3.11 and retry."
  exit 1
fi

# If the chosen interpreter lacks the demo dependencies, install into a local venv.
if ! "$PY" -c 'import fastapi, uvicorn, httpx' 2>/dev/null; then
  echo "📦 Installing demo dependencies into a local venv…"
  if [ ! -d .venv ]; then "$PY" -m venv .venv; fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -q --upgrade pip
  pip install -q -e .
  PY="python"
fi

echo "Using Python: $("$PY" --version 2>&1)"
echo "🚀 Starting Agent Client Demo on http://localhost:${PORT}"
echo "   Press Ctrl+C to stop."
exec "$PY" -m uvicorn demo_app.main:app --host 0.0.0.0 --port "$PORT" --reload
