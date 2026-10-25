"""Per-session in-memory tool-call capture (post-run auto-compilation input).

Records the ordered MCP tool-call sequence of LLM-executed sessions in Agent
Runtime process memory so the auto-compiler can turn a successful LLM run into
a candidate step graph afterwards (Software 3.0 self-improvement, C1).

Security constraints (SEC3):
- The capture lives **only** in Agent Runtime process memory, bounded per
  session (last ~50 calls), for the session's lifetime.
- It is never persisted raw — the compiled step graph goes through the
  compiler's secret-shaped-field guard (``_assert_no_secrets``) before
  leaving the process.
- Capture is strictly best-effort: any failure here must never affect tool
  execution (every caller wraps recording in a swallow-all try/except).

Script-path executions are not captured (they are tagged with a
``script_version``/``provenance`` by the runner), so capture only ever
reflects genuine LLM-path tool calls.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

# Bounded memory: keep only the last N calls per session.
MAX_CALLS_PER_SESSION = 50

_captures: dict[str, deque[dict[str, Any]]] = {}
_lock = threading.Lock()


def record_tool_call(
    session_id: str,
    tool_name: str,
    tool_input: dict[str, Any],
    tool_output: Any,
) -> None:
    """Record one successful tool call for a session (best-effort caller).

    Never raises; a capture failure must not affect execution.
    """
    try:
        if not session_id:
            return
        record = {
            "tool_name": str(tool_name),
            "tool_input": dict(tool_input or {}),
            "tool_output": tool_output,
        }
        with _lock:
            buffer = _captures.get(session_id)
            if buffer is None:
                buffer = deque(maxlen=MAX_CALLS_PER_SESSION)
                _captures[session_id] = buffer
            buffer.append(record)
    except Exception as exc:  # pragma: no cover — defensive, never raise
        logger.debug("Tool-call capture failed (ignored): %s", exc)


def pop_tool_sequence(session_id: str) -> list[dict[str, Any]]:
    """Return and clear the captured sequence for a session (bounded, ordered).

    Returns calls as ``{"tool_name", "tool_input", "tool_output"}`` — the
    shape ``ScriptCompiler.compile_from_tool_sequence`` expects. Popping
    releases the memory promptly after the run; stale captures for sessions
    that never reach auto-compilation are dropped when a new run for the same
    session id starts or by process restart (memory is bounded regardless).
    """
    with _lock:
        buffer = _captures.pop(session_id, None)
    if not buffer:
        return []
    return list(buffer)


def clear(session_id: str) -> None:
    """Drop any captured sequence for a session (e.g. run start reset)."""
    with _lock:
        _captures.pop(session_id, None)
