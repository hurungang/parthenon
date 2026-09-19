"""Tool registry bridge — the single source of truth for MCP tool catalog + dispatch.

Builds the permission-filtered tool catalog returned by ``tools/list`` and
authorizes + dispatches ``tools/call``:

- System tools (``system____*``) → Control Center system-tool endpoints.
- Proxied MCP tools (``server_slug____tool``) → Control Center MCP proxy.
- ``load_skills`` → Control Center skill-resolution endpoint.

Reuses the existing permission resolution result (the role's allowed-tool set
attached to the session by ``ApiKeyAuthMiddleware``) and the existing
``SystemToolRegistry`` / ``McpProxyEngine`` paths unchanged. The identity token
is held server-side and never returned to the client.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.communication_hub.mcp.cc_client import build_cc_client, get_control_center_url
from app.services.agents.system_tool_registry import SystemToolRegistry
from app.services.agents.tool_naming import build_tool_name, get_bare_tool_name, is_system_tool, parse_tool_name

logger = logging.getLogger(__name__)

#: CH-level meta tool exposed to all authenticated MCP clients for skill discovery.
LOAD_SKILLS_TOOL_NAME = "load_skills"

_LOAD_SKILLS_DESCRIPTION = (
    "Discover all skills and SOPs the authenticated agent is permitted to access. "
    "Returns full skill definitions including tool schemas and updated_at timestamps. "
    "Pass an ISO 8601 'since' timestamp to retrieve only skills updated after it "
    "(incremental sync)."
)

_LOAD_SKILLS_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "since": {
            "type": "string",
            "description": "ISO 8601 timestamp; only skills updated after this are returned.",
        },
    },
}


def _canonicalize(name: str) -> str:
    """Normalize a tool name to canonical ``server____tool`` form."""
    try:
        server, tool = parse_tool_name(name)
        return build_tool_name(server, tool)
    except ValueError:
        if "/" in name:
            server, tool = name.split("/", 1)
            return build_tool_name(server, tool)
        return name


class ToolRegistryBridge:
    """Builds the permitted tool catalog and routes tool calls for MCP clients."""

    # ── Catalog ────────────────────────────────────────────────────────────

    def build_catalog(self, session: Any) -> list[dict[str, Any]]:
        """Build the permission-filtered ``tools/list`` payload for a session.

        Returns a list of ``{name, description, inputSchema}`` dicts covering:
        the ``load_skills`` meta tool, permitted system tools, and permitted
        proxied MCP tools (descriptions/schemas sourced from the role's skills
        where available, otherwise name-only stubs).
        """
        permitted: set[str] = set(session.permissions or [])

        # Map canonical tool name → (description, input_schema) from resolved skills.
        skill_tool_defs: dict[str, tuple[str | None, dict[str, Any] | None]] = {}
        for skill in session.skills or []:
            for tool in skill.get("tools", []) or []:
                name = tool.get("name")
                if not name:
                    continue
                skill_tool_defs[_canonicalize(name)] = (
                    tool.get("description"),
                    tool.get("input_schema"),
                )

        tools: list[dict[str, Any]] = []

        # 1. load_skills meta tool (always available to authenticated clients).
        tools.append(
            {
                "name": LOAD_SKILLS_TOOL_NAME,
                "description": _LOAD_SKILLS_DESCRIPTION,
                "inputSchema": _LOAD_SKILLS_INPUT_SCHEMA,
            }
        )

        # 2. System tools the role is permitted to use.
        for canonical in sorted(permitted):
            if not is_system_tool(canonical):
                continue
            bare = get_bare_tool_name(canonical)
            registered = SystemToolRegistry.get(bare)
            if registered is None:
                continue
            tools.append(
                {
                    "name": canonical,
                    "description": registered.description,
                    "inputSchema": registered.parameters,
                }
            )

        # 3. Proxied MCP tools the role is permitted to use.
        for canonical in sorted(permitted):
            if is_system_tool(canonical):
                continue
            description, input_schema = skill_tool_defs.get(canonical, (None, None))
            tools.append(
                {
                    "name": canonical,
                    "description": description or "",
                    "inputSchema": input_schema or {"type": "object", "properties": {}},
                }
            )

        return tools

    # ── Dispatch ───────────────────────────────────────────────────────────

    async def dispatch(
        self,
        request: Any,
        session: Any,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Authorize and dispatch a ``tools/call``.

        Returns the MCP result payload (``{"content": [...]}``). Raises
        :class:`PermissionError` for unauthorized tools and :class:`RuntimeError`
        for downstream failures (mapped to JSON-RPC errors by the protocol server).
        """
        if tool_name in (LOAD_SKILLS_TOOL_NAME, f"system____{LOAD_SKILLS_TOOL_NAME}"):
            return await self._call_load_skills(request, session, arguments)

        canonical = _canonicalize(tool_name)
        permitted: set[str] = set(session.permissions or [])
        if canonical not in permitted:
            raise PermissionError(f"Tool '{tool_name}' is not permitted for this API key")

        if is_system_tool(canonical):
            return await self._call_system_tool(request, session, canonical, arguments)
        return await self._call_mcp_tool(request, session, canonical, arguments)

    # ── CC calls ───────────────────────────────────────────────────────────

    async def _call_load_skills(
        self, request: Any, session: Any, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Resolve the role's accessible skills via Control Center."""
        cc_base = get_control_center_url()
        if not cc_base:
            raise RuntimeError("Control Center URL not configured")

        payload: dict[str, Any] = {"agent_role_id": session.agent_role_id}
        since = arguments.get("since")
        if since:
            payload["since"] = since

        result = await self._post_cc(
            request, cc_base, "/api/v1/internal/system-tools/skills/resolve", payload
        )
        return _text_result(json.dumps(result.get("skills", []), default=str))

    async def _call_system_tool(
        self, request: Any, session: Any, canonical: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Route a system tool to its Control Center endpoint."""
        cc_base = get_control_center_url()
        if not cc_base:
            raise RuntimeError("Control Center URL not configured")

        bare = get_bare_tool_name(canonical)
        endpoint_map = SystemToolRegistry.get_cc_endpoint_map(cc_base)
        endpoint = endpoint_map.get(bare)
        if not endpoint:
            raise RuntimeError(f"Unknown system tool: {bare}")

        payload = {
            "session_id": session.session_id,
            "tool_args": arguments,
        }
        result = await self._post_cc(request, cc_base, endpoint, payload)
        return _text_result(json.dumps(result.get("result", {}), default=str))

    async def _call_mcp_tool(
        self, request: Any, session: Any, canonical: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Route a proxied MCP tool to the Control Center MCP proxy."""
        cc_base = get_control_center_url()
        if not cc_base:
            raise RuntimeError("Control Center URL not configured")

        payload = {
            "tool_name": canonical,
            "tool_args": arguments,
            "agent_role_id": session.agent_role_id,
            "agent_identity_id": session.agent_identity_id,
            "agent_session_id": session.session_id,
        }
        result = await self._post_cc(
            request, cc_base, "/api/v1/internal/mcp/proxy-tool", payload
        )
        return _text_result(json.dumps(result.get("result", {}), default=str))

    async def _post_cc(
        self,
        request: Any,
        cc_base: str,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """POST JSON to Control Center over mTLS, returning the decoded body."""
        client_kwargs, headers = build_cc_client(request, cc_base)
        url = f"{cc_base}{path}"
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            detail = _extract_detail(exc)
            raise RuntimeError(detail) from exc
        except Exception as exc:  # noqa: BLE001 — surface clean errors to clients
            logger.exception("CH → CC call failed: %s", path)
            raise RuntimeError(f"Control Center call failed: {exc}") from exc


def _text_result(text: str) -> dict[str, Any]:
    """Wrap a text payload in the MCP tool-result content structure."""
    return {"content": [{"type": "text", "text": text}]}


def _extract_detail(exc: httpx.HTTPStatusError) -> str:
    try:
        return exc.response.json().get("detail", exc.response.text[:200])
    except Exception:  # noqa: BLE001
        return exc.response.text[:200] or f"HTTP {exc.response.status_code}"
