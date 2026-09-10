"""Per-connection MCP protocol session state and lifecycle management.

Tracks protocol state (initialized flag, negotiated capabilities) and the
authenticated identity context (identity token, agent identity/role, permission
set, skills) for each connected external MCP client.

The identity token and permission context are held **server-side only** — they
are never serialized into a client-visible response or session object.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

#: MCP protocol version negotiated with clients.
MCP_PROTOCOL_VERSION = "2024-11-05"

#: Default idle timeout (seconds) after which an MCP session is garbage-collected.
DEFAULT_SESSION_TTL_SECONDS = 3600

#: Interval (seconds) between opportunistic cleanups of expired sessions.
CLEANUP_INTERVAL_SECONDS = 300


@dataclass
class McpSession:
    """State for a single external MCP client connection."""

    session_id: str
    initialized: bool = False
    protocol_version: str = MCP_PROTOCOL_VERSION
    client_info: dict[str, Any] | None = None
    client_capabilities: dict[str, Any] | None = None

    # ── Authenticated context (server-side only) ──────────────────────────
    identity_token: str | None = None
    agent_identity_id: str | None = None
    agent_role_id: str | None = None
    permissions: list[str] = field(default_factory=list)
    skills: list[dict[str, Any]] = field(default_factory=list)
    api_key_name: str | None = None

    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)

    def touch(self) -> None:
        """Record activity on this session, deferring idle expiry."""
        self.last_activity = time.time()

    def is_expired(self, ttl_seconds: int) -> bool:
        """Return ``True`` if the session has exceeded its idle timeout."""
        return (time.time() - self.last_activity) > ttl_seconds

    def to_public_context(self) -> dict[str, Any]:
        """Return a safe, client-facing subset of session context.

        Deliberately excludes the identity token and any credential material.
        """
        return {
            "session_id": self.session_id,
            "initialized": self.initialized,
            "protocol_version": self.protocol_version,
            "agent_role_id": self.agent_role_id,
            "api_key_name": self.api_key_name,
        }


class McpSessionManager:
    """In-memory session registry with TTL-based idle cleanup.

    Sessions are keyed by a server-generated UUID. This manager is
    process-local (no shared store) — consistent with the Communication Hub's
    stateless, no-DB design. For a multi-replica CH deployment a Redis-backed
    session store would be required, but that is out of scope for this change.
    """

    def __init__(self, ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[str, McpSession] = {}
        self._last_cleanup: float = time.time()

    def create_session(self, **auth_context: Any) -> McpSession:
        """Create a new session seeded with the resolved auth context."""
        session = McpSession(session_id=uuid.uuid4().hex, **auth_context)
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> McpSession | None:
        """Look up a session by ID, returning ``None`` if unknown or expired."""
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.is_expired(self.ttl_seconds):
            self._sessions.pop(session_id, None)
            return None
        session.touch()
        return session

    def delete_session(self, session_id: str) -> None:
        """Drop a session, e.g. after an explicit client disconnect."""
        self._sessions.pop(session_id, None)

    def cleanup_expired(self) -> int:
        """Remove all expired sessions; return the number removed."""
        self._last_cleanup = time.time()
        expired = [
            sid for sid, s in self._sessions.items() if s.is_expired(self.ttl_seconds)
        ]
        for sid in expired:
            self._sessions.pop(sid, None)
        return len(expired)

    def maybe_cleanup(self) -> int:
        """Run cleanup at most once per :data:`CLEANUP_INTERVAL_SECONDS`."""
        if (time.time() - self._last_cleanup) >= CLEANUP_INTERVAL_SECONDS:
            return self.cleanup_expired()
        return 0
