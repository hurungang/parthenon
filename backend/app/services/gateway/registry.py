"""Gateway Endpoint Registry — in-memory route registry for agent type gateways.

Routes are deterministic: ``/gateway/{agent_type_id}``.  No database persistence
is needed — routes are re-registered from the agent catalogue on startup.
"""
from __future__ import annotations

import uuid
import logging

logger = logging.getLogger(__name__)


class GatewayEndpointRegistry:
    """In-memory registry mapping agent_type_id → http_base_path.

    Routes are deterministic and can be rebuilt from the agent catalogue without
    persistent storage.  Thread-safe for asyncio single-threaded environments.

    Usage::

        registry = GatewayEndpointRegistry()
        route = registry.register(agent_type_id)
        path = registry.resolve(agent_type_id)   # returns "/gateway/{agent_type_id}"
        all_routes = registry.list_all()
    """

    def __init__(self) -> None:
        self._routes: dict[str, str] = {}  # agent_type_id (str) → http_base_path

    def register(self, agent_type_id: uuid.UUID | str) -> str:
        """Register a gateway route and return its http_base_path."""
        key = str(agent_type_id)
        path = f"/gateway/{key}"
        if key not in self._routes:
            self._routes[key] = path
            logger.debug("Registered gateway route: %s → %s", key, path)
        return path

    def resolve(self, agent_type_id: uuid.UUID | str) -> str | None:
        """Return the http_base_path for an agent type, or None if not registered."""
        return self._routes.get(str(agent_type_id))

    def list_all(self) -> list[dict[str, str]]:
        """Return all registered routes as a list of dicts."""
        return [
            {"agent_type_id": k, "http_base_path": v}
            for k, v in sorted(self._routes.items())
        ]

    def clear(self) -> None:
        """Remove all registered routes (used in tests)."""
        self._routes.clear()
