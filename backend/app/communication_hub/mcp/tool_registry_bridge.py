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
from app.core.internal_http import internal_httpx_client
from app.services.agents.system_tool_registry import SystemToolRegistry
from app.services.agents.tool_naming import (
    TOOL_SEPARATOR,
    build_tool_name,
    get_bare_tool_name,
    is_system_tool,
    parse_tool_name,
)

logger = logging.getLogger(__name__)

#: CH-level meta tool exposed to all authenticated MCP clients for skill discovery.
LOAD_SKILLS_TOOL_NAME = "load_skills"

#: Server slug decision tools are exposed under. Names are built with the
#: canonical ``decision____<name>`` four-underscore convention (shared
#: tool-naming helpers); stored names are plain.
DECISION_SERVER_SLUG = "decision"
DECISION_TOOL_PREFIX = f"{DECISION_SERVER_SLUG}{TOOL_SEPARATOR}"

_DECISION_LIST_PATH = "/api/v1/internal/system-tools/decision/list"
_DECISION_EXECUTE_PATH = "/api/v1/internal/system-tools/decision/execute"

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

    async def build_catalog(self, session: Any, request: Any = None) -> list[dict[str, Any]]:
        """Build the permission-filtered ``tools/list`` payload for a session.

        Returns a list of ``{name, description, inputSchema}`` dicts covering:
        the ``load_skills`` meta tool, the caller's tenant decision tools
        (``decision:``-prefixed, auto-generated descriptions), permitted
        system tools, and permitted proxied MCP tools.
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

        # 1b. Decision tools of the caller's tenant (forwarded to Control
        # Center). Canonical ``decision____<name>`` naming via the shared
        # tool-naming helpers. Tenant-contained: names resolve within the
        # session's tenant, so identical names in different tenants never
        # collide. CH holds no credentials — descriptions/schemas come from CC.
        for tool in await self._list_decision_tools(session, request):
            tools.append(
                {
                    "name": build_tool_name(DECISION_SERVER_SLUG, tool.get("name")),
                    "description": tool.get("description") or "",
                    "inputSchema": tool.get("input_schema")
                    or {
                        "type": "object",
                        "properties": {
                            "state": {
                                "type": "object",
                                "description": "Input state for the decision.",
                                "additionalProperties": True,
                            }
                        },
                    },
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

        # Decision tools: ``decision____<name>`` at the MCP surface. Tenant
        # containment is enforced by resolving the catalog within the
        # session's tenant; invocation is forwarded to Control Center's
        # decision execution path — CH holds no credentials and makes no
        # external calls.
        if tool_name.startswith(DECISION_TOOL_PREFIX):
            return await self._call_decision_tool(
                request, session, tool_name, arguments
            )

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

    async def _list_decision_tools(
        self, session: Any, request: Any = None
    ) -> list[dict[str, Any]]:
        """Fetch the caller's tenant decision-tool catalog from Control Center."""
        cc_base = get_control_center_url()
        if not cc_base:
            return []
        try:
            result = await self._post_cc(
                request,
                cc_base,
                _DECISION_LIST_PATH,
                {"tenant_id": getattr(session, "tenant_id", None)},
            )
            return list(result.get("tools", []))
        except Exception:  # noqa: BLE001 — catalog degrades without decision tools
            logger.exception("Failed to list decision tools from Control Center")
            return []

    async def _call_decision_tool(
        self,
        request: Any,
        session: Any,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Forward a ``decision____<name>`` invocation to Control Center (no credentials)."""
        cc_base = get_control_center_url()
        if not cc_base:
            raise RuntimeError("Control Center URL not configured")

        bare_name = tool_name[len(DECISION_TOOL_PREFIX):]
        tenant_id = getattr(session, "tenant_id", None)

        # Tenant containment: the tool must exist in the caller's tenant.
        known = {
            tool.get("name")
            for tool in await self._list_decision_tools(session, request)
        }
        if bare_name not in known:
            raise PermissionError(
                f"Decision tool '{tool_name}' is not available for this tenant"
            )

        # Accept either a bare tool name or "state"-wrapped arguments.
        input_state = arguments.get("state") if isinstance(arguments, dict) else None
        if not isinstance(input_state, dict):
            input_state = dict(arguments or {})

        payload = {
            "session_id": session.session_id,
            "tenant_id": tenant_id,
            "tool_name": bare_name,
            "input_state": input_state,
            "conversation_session_id": getattr(session, "session_id", None),
        }
        result = await self._post_cc(
            request,
            cc_base,
            _DECISION_EXECUTE_PATH,
            payload,
        )
        return _text_result(json.dumps(result.get("result", {}), default=str))

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
        # get_cc_endpoint_map returns FULL URLs — strip the base back off,
        # _post_cc re-attaches it.
        result = await self._post_cc(
            request, cc_base, endpoint[len(cc_base.rstrip("/")):], payload
        )
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
        # Tenant headers are attached by the internal_httpx_client egress
        # hook (forwards the session's CC-signed set verbatim; single-tenant
        # → headerless, unchanged).
        url = f"{cc_base}{path}"
        try:
            async with internal_httpx_client(**client_kwargs) as client:
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
