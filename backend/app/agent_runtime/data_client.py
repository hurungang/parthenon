"""Agent Runtime — Control Center data client.

Fetches all agent configuration and manages session lifecycle via HTTP calls
to Control Center's internal data APIs, authenticated with the agent-instance
mTLS certificate.

Agent Runtime has ZERO direct database access.  All data flows through this client.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0  # seconds
_RETRY_BASE_DELAY = 1.0


def _allow_insecure_internal_fallback() -> bool:
    """Return True only for explicit development-mode insecure fallback opt-in."""
    environment = os.environ.get("ENVIRONMENT", "").strip().lower()
    opt_in = os.environ.get("ALLOW_INSECURE_INTERNAL_CALL_FALLBACK", "").strip().lower()
    return environment == "development" and opt_in in {"1", "true", "yes", "on"}


class ControlCenterDataError(Exception):
    """Raised when a Control Center data API call fails."""


class ControlCenterDataClient:
    """HTTP client for Control Center internal data APIs using mTLS.

    Usage::

        manager = CertificateManager()
        client = ControlCenterDataClient(cert_manager=manager)

        context = await client.get_agent_context(agent_type_id)
        plan = await client.get_agent_plan(agent_type_id)
        model = await client.get_model_config(model_config_id)

    The client reuses the mTLS-configured ``httpx.AsyncClient`` from the
    ``CertificateManager`` so certificate rotation is transparent.
    """

    def __init__(
        self,
        cert_manager: Any,  # app.agent_runtime.certificate_manager.CertificateManager
        control_center_url: str | None = None,
    ) -> None:
        self._cert_manager = cert_manager
        self._control_center_url = (
            control_center_url
            or os.environ.get("CONTROL_CENTER_URL", "http://localhost:8000")
        ).rstrip("/")

    # ── Private helpers ───────────────────────────────────────────────────────

    def _make_client(self) -> httpx.AsyncClient:
        """Return an mTLS-configured HTTP client using the current agent cert."""
        if self._cert_manager is None:
            if _allow_insecure_internal_fallback():
                logger.warning(
                    "Agent Runtime data client using insecure HTTP fallback because "
                    "ALLOW_INSECURE_INTERNAL_CALL_FALLBACK is enabled in development"
                )
                return httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
            raise RuntimeError(
                "Agent Runtime certificate manager is unavailable; "
                "internal Control Center calls fail closed"
            )
        try:
            return self._cert_manager.configure_mtls_client()
        except Exception as exc:
            if _allow_insecure_internal_fallback():
                logger.warning(
                    "Certificate not loaded; using insecure HTTP fallback in development: %s",
                    exc,
                    exc_info=True,
                )
                return httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
            raise RuntimeError(
                "Agent Runtime service certificate is required for internal calls"
            ) from exc

    def _url(self, path: str) -> str:
        return f"{self._control_center_url}/api/v1/internal/data{path}"

    async def _get(self, path: str) -> dict[str, Any]:
        """GET request with error propagation and auto-recovery from 401."""
        url = self._url(path)
        async with self._make_client() as client:
            try:
                resp = await client.get(url, timeout=_DEFAULT_TIMEOUT)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                # Auto-recover from 401 certificate errors
                if exc.response.status_code == 401 and "certificate" in exc.response.text.lower():
                    logger.warning(
                        "Certificate invalid (401) on GET %s — triggering re-bootstrap",
                        path
                    )
                    await self._auto_recover_certificate()
                    # Retry once after re-bootstrap
                    async with self._make_client() as retry_client:
                        retry_resp = await retry_client.get(url, timeout=_DEFAULT_TIMEOUT)
                        retry_resp.raise_for_status()
                        return retry_resp.json()
                
                raise ControlCenterDataError(
                    f"CC data API GET {url} returned {exc.response.status_code}: "
                    f"{exc.response.text[:200]}"
                ) from exc
            except Exception as exc:
                raise ControlCenterDataError(
                    f"CC data API GET {url} failed: {exc}"
                ) from exc

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST request with error propagation and auto-recovery from 401."""
        url = self._url(path)
        async with self._make_client() as client:
            try:
                resp = await client.post(url, json=body, timeout=_DEFAULT_TIMEOUT)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                # Auto-recover from 401 certificate errors
                if exc.response.status_code == 401 and "certificate" in exc.response.text.lower():
                    logger.warning(
                        "Certificate invalid (401) on POST %s — triggering re-bootstrap",
                        path
                    )
                    await self._auto_recover_certificate()
                    # Retry once after re-bootstrap
                    async with self._make_client() as retry_client:
                        retry_resp = await retry_client.post(url, json=body, timeout=_DEFAULT_TIMEOUT)
                        retry_resp.raise_for_status()
                        return retry_resp.json()
                
                raise ControlCenterDataError(
                    f"CC data API POST {url} returned {exc.response.status_code}: "
                    f"{exc.response.text[:200]}"
                ) from exc
            except Exception as exc:
                raise ControlCenterDataError(
                    f"CC data API POST {url} failed: {exc}"
                ) from exc

    async def _patch(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """PATCH request with error propagation and auto-recovery from 401."""
        url = self._url(path)
        async with self._make_client() as client:
            try:
                resp = await client.patch(url, json=body, timeout=_DEFAULT_TIMEOUT)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                # Auto-recover from 401 certificate errors
                if exc.response.status_code == 401 and "certificate" in exc.response.text.lower():
                    logger.warning(
                        "Certificate invalid (401) on PATCH %s — triggering re-bootstrap",
                        path
                    )
                    await self._auto_recover_certificate()
                    # Retry once after re-bootstrap
                    async with self._make_client() as retry_client:
                        retry_resp = await retry_client.patch(url, json=body, timeout=_DEFAULT_TIMEOUT)
                        retry_resp.raise_for_status()
                        return retry_resp.json()
                
                raise ControlCenterDataError(
                    f"CC data API PATCH {url} returned {exc.response.status_code}: "
                    f"{exc.response.text[:200]}"
                ) from exc
            except Exception as exc:
                raise ControlCenterDataError(
                    f"CC data API PATCH {url} failed: {exc}"
                ) from exc

    async def _auto_recover_certificate(self) -> None:
        """Auto-recover from certificate validation failure by re-bootstrapping.
        
        This is called when a 401 error with "certificate" in the message is encountered.
        It triggers the certificate manager to delete old certs and bootstrap new ones.
        """
        logger.info("Auto-recovery: requesting certificate manager to re-bootstrap")
        try:
            # Trigger re-bootstrap by calling load_certificate with force
            await self._cert_manager.load_certificate()
            logger.info("Auto-recovery: certificate re-bootstrapped successfully")
        except Exception as exc:
            logger.error("Auto-recovery failed: %s", exc)
            raise ControlCenterDataError(f"Certificate auto-recovery failed: {exc}") from exc

    # ── Agent configuration ───────────────────────────────────────────────────

    async def get_agent_plan(self, agent_type_id: uuid.UUID) -> dict[str, Any] | None:
        """Return the active plan for an agent type, or None if not found.

        Calls ``GET /internal/data/agent-types/{agent_type_id}/plan``.
        """
        try:
            return await self._get(f"/agent-types/{agent_type_id}/plan")
        except ControlCenterDataError as exc:
            if "404" in str(exc):
                return None
            logger.warning("Failed to fetch plan for agent_type=%s: %s", agent_type_id, exc)
            return None

    async def get_agent_context(self, agent_type_id: uuid.UUID) -> dict[str, Any]:
        """Return full execution context for an agent type.

        Calls ``GET /internal/data/agent-types/{agent_type_id}/context``.

        Returns a dict with keys: system_instruction, model_id, model_config_id,
        role_id, allowed_tools, sop_content, mcp_session_context,
        tool_definitions, tool_name_map, role_mcp_sessions, sops, skills,
        identity_name, role_name, identity_role_valid, input_type, output_type,
        output_schema, primary_sop_id, is_active.
        """
        return await self._get(f"/agent-types/{agent_type_id}/context")

    async def get_model_config(self, model_config_id: uuid.UUID) -> dict[str, Any]:
        """Return model configuration with decrypted API credentials.

        Calls ``GET /internal/data/model-configs/{model_config_id}``.
        Returns dict with keys: id, display_name, provider_type, api_base_url,
        api_key (decrypted), enabled_models.
        """
        return await self._get(f"/model-configs/{model_config_id}")

    # ── Availability preflight (Phase 3.10) ─────────────────────────────────

    async def preflight_availability(
        self,
        model_name: str,
        vendor_model_config_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Pre-execution availability check via Control Center.

        Called by Agent Runtime before dispatching any agent execution.
        On deny, the runtime records the reason in an execution log
        event and blocks dispatch with ``AgentJob.termination_category``
        of ``model_disabled`` or ``vendor_disabled``.

        Calls ``POST /internal/data/preflight/availability``.

        Returns dict with keys: allowed (bool), reason (str|None),
        disabled_reason (str|None), blocked_by (str|None).
        """
        body: dict[str, Any] = {"model_id": model_name}
        if vendor_model_config_id is not None:
            body["vendor_model_config_id"] = str(vendor_model_config_id)
        return await self._post("/preflight/availability", body)

        # ── Typed output methods ──────────────────────────────────────────────────

    def _internal_url(self, path: str) -> str:
        """Construct URL for internal endpoints (not under /data)."""
        return f"{self._control_center_url}/api/v1/internal{path}"

    async def _internal_post(
        self, path: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """POST to an internal (non-data) endpoint with error handling."""
        url = self._internal_url(path)
        async with self._make_client() as client:
            try:
                resp = await client.post(url, json=body, timeout=_DEFAULT_TIMEOUT)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                raise ControlCenterDataError(
                    f"CC internal POST {url} returned {exc.response.status_code}: "
                    f"{exc.response.text[:200]}"
                ) from exc
            except Exception as exc:
                raise ControlCenterDataError(
                    f"CC internal POST {url} failed: {exc}"
                ) from exc

    async def validate_typed_output(
        self, data_type_id: uuid.UUID, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate an agent output payload against a data type schema.

        Calls ``POST /api/v1/internal/validate-output``.
        Returns ``{"valid": bool, "errors": [...]}``.
        """
        return await self._internal_post(
            "/validate-output",
            {"data_type_id": str(data_type_id), "payload": payload},
        )

    async def persist_typed_output(
        self,
        data_type_id: uuid.UUID,
        agent_type_id: uuid.UUID,
        session_id: uuid.UUID,
        field_values: dict[str, Any] | None,
        validation_status: str,
        raw_output: str | None = None,
    ) -> dict[str, Any]:
        """Persist a typed agent output record to Control Center.

        Calls ``POST /api/v1/internal/agent-outputs``.
        Returns the created ``AgentOutput`` record as a dict.
        """
        body: dict[str, Any] = {
            "data_type_id": str(data_type_id),
            "agent_type_id": str(agent_type_id),
            "execution_session_id": str(session_id),
            "validation_status": validation_status,
        }
        if field_values is not None:
            body["field_values"] = field_values
        if raw_output is not None:
            body["raw_output"] = raw_output
        return await self._internal_post("/agent-outputs", body)

    # ── Session management ────────────────────────────────────────────────────

    async def get_session(self, session_id: uuid.UUID) -> dict[str, Any] | None:
        """Return session metadata, or None if not found.

        Calls ``GET /internal/data/sessions/{session_id}``.
        """
        try:
            return await self._get(f"/sessions/{session_id}")
        except ControlCenterDataError as exc:
            if "404" in str(exc):
                return None
            raise

    async def claim_queued_sessions(self, limit: int = 4) -> list[uuid.UUID]:
        """Atomically claim queued sessions from the Control Center queue.

        Calls ``POST /internal/data/sessions/claim-queued``.
        Returns a list of session UUIDs transitioned to 'running'.
        """
        data = await self._post("/sessions/claim-queued", {"limit": limit})
        return [uuid.UUID(sid) for sid in data.get("session_ids", [])]

    async def mark_session_running(self, session_id: uuid.UUID) -> None:
        """Transition a session to running status.

        Calls ``PATCH /internal/data/sessions/{session_id}/status``.
        """
        await self._patch(f"/sessions/{session_id}/status", {"status": "running"})

    async def mark_session_waiting_for_human(
        self, session_id: uuid.UUID, intervene_request_id: str | None,
        conversation_history: list | None = None,
    ) -> None:
        """Transition a session to waiting_for_human status.

        Calls ``PATCH /internal/data/sessions/{session_id}/status``.
        """
        body: dict = {"status": "waiting_for_human"}
        if intervene_request_id:
            body["intervene_request_id"] = intervene_request_id
        if conversation_history is not None:
            body["conversation_history"] = conversation_history
        await self._patch(f"/sessions/{session_id}/status", body)

    async def mark_session_completed(
        self, session_id: uuid.UUID, output_data: dict[str, Any]
    ) -> None:
        """Transition a session to completed and persist output data.

        Calls ``PATCH /internal/data/sessions/{session_id}/status``.
        """
        await self._patch(
            f"/sessions/{session_id}/status",
            {"status": "completed", "output_data": output_data},
        )

    async def mark_session_failed(
        self,
        session_id: uuid.UUID,
        error_message: str,
        stop_category: str | None = None,
        stop_reason: str | None = None,
        stop_details: dict[str, Any] | None = None,
    ) -> None:
        """Transition a session to failed and record the error.

        Calls ``PATCH /internal/data/sessions/{session_id}/status``.
        """
        payload: dict[str, Any] = {
            "status": "failed",
            "error_message": error_message,
        }
        if stop_category is not None:
            payload["stop_category"] = stop_category
        if stop_reason is not None:
            payload["stop_reason"] = stop_reason
        if stop_details is not None:
            payload["stop_details"] = stop_details
        await self._patch(f"/sessions/{session_id}/status", payload)

    async def save_output(
        self, session_id: uuid.UUID, output_data: dict[str, Any]
    ) -> None:
        """Submit execution result to Control Center.

        Calls ``POST /internal/data/sessions/{session_id}/result``.
        Transitions the session to completed and persists the output.
        """
        await self._post(
            f"/sessions/{session_id}/result",
            {"output_data": output_data},
        )

    # ── Execution logging ─────────────────────────────────────────────────────

    async def log_execution_event(
        self,
        session_id: uuid.UUID,
        event_type: str,
        message: str,
        data: dict[str, Any],
        log_level: str = "INFO",
        event_category: str = "functional",
        actor_type: str = "system",
    ) -> None:
        """Write a structured execution log entry to Control Center.

        Calls ``POST /internal/data/sessions/{session_id}/log``.
        Failures are swallowed — logging must never abort execution.
        """
        try:
            await self._post(
                f"/sessions/{session_id}/log",
                {
                    "event_type": event_type,
                    "log_level": log_level,
                    "message": message,
                    "data": data,
                    "event_category": event_category,
                    "actor_type": actor_type,
                },
            )
        except Exception as exc:
            logger.warning(
                "Failed to ship execution log entry for session %s: %s", session_id, exc
            )

    async def log_prompt(
        self,
        session_id: uuid.UUID,
        system_instruction: str | None,
        user_prompt: str | None,
    ) -> None:
        """Capture the full prompt (system + user) before the first LLM call.

        Writes a ``prompt_captured`` execution log entry.
        Failures are swallowed.
        """
        await self.log_execution_event(
            session_id=session_id,
            event_type="prompt_captured",
            message="Prompt captured before first LLM call",
            data={
                "system_instruction": system_instruction,
                "user_prompt": user_prompt,
                "system_instruction_length": len(system_instruction or ""),
                "user_prompt_length": len(user_prompt or ""),
            },
        )

    # ── Tool-call recording ──────────────────────────────────────────────────

    async def record_tool_call(
        self,
        *,
        session_id: uuid.UUID,
        session_kind: str,
        tool_name: str,
        route_type: str,
        status: str,
        duration_ms: int | None = None,
        mcp_slug: str | None = None,
        error: str | None = None,
    ) -> None:
        """Record a single tool execution to Control Center (fire-and-forget).

        Writes to ``POST /internal/data/tool-calls`` so the Agent Runtime
        Monitor can render per-node tool-call history for agent jobs AND
        conversation turns (``session_kind`` distinguishes the two).

        Best-effort by design: recording failures are logged and swallowed —
        they must never break the tool execution they describe.
        """
        body: dict[str, Any] = {
            "records": [
                {
                    "session_id": str(session_id),
                    "session_kind": session_kind,
                    "tool_name": tool_name,
                    "route_type": route_type,
                    "mcp_slug": mcp_slug,
                    "status": status,
                    "duration_ms": duration_ms,
                    "error": error,
                }
            ]
        }
        try:
            await self._post("/tool-calls", body)
        except Exception as exc:
            logger.warning(
                "Failed to record tool call %s for session %s: %s",
                tool_name,
                session_id,
                exc,
            )
