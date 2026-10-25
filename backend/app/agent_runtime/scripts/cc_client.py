"""Control Center client for the Agent Runtime script framework.

All registry interactions (serving-version lookup, candidate submission,
evidence, fallback reporting, execution records, repair attempts) go through
CC internal APIs over mTLS using the AR service identity — never direct DB
access. There are no execution modes; the dispatcher fetches the current
serving script version directly (absent → LLM path).

The response-scrutiny helper ``verify_no_identity_tokens`` is reused from
``metadata_client`` so script payloads are held to the same no-token bar.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from app.agent_runtime.metadata_client import (
    CertificateLoadError,
    MetadataClientError,
    verify_no_identity_tokens,
)
from app.core.internal_http import internal_httpx_client

logger = logging.getLogger(__name__)


class ScriptRegistryClientError(MetadataClientError):
    """Raised when a script registry call to Control Center fails."""


class ScriptRegistryClient:
    """HTTP client for CC ``/api/v1/internal/scripts`` endpoints."""

    def __init__(self, cert_manager: Any) -> None:
        self._cert_manager = cert_manager
        self._control_center_url = os.environ.get("CONTROL_CENTER_URL", "")

    def _url(self, path: str) -> str:
        if not self._control_center_url:
            raise ScriptRegistryClientError("CONTROL_CENTER_URL not set")
        return f"{self._control_center_url.rstrip('/')}/api/v1/internal/scripts{path}"

    def _client_kwargs(self) -> dict[str, Any]:
        if not self._cert_manager.is_loaded:
            raise CertificateLoadError("Certificate not loaded; cannot call Control Center")
        return self._cert_manager.mtls_client_kwargs()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> Any:
        """Perform one mTLS request, verifying responses contain no tokens."""
        url = self._url(path)
        try:
            async with internal_httpx_client(
                timeout=timeout, **self._client_kwargs()
            ) as client:
                response = await client.request(
                    method, url, json=json_body, params=params
                )
        except httpx.HTTPError as exc:
            raise ScriptRegistryClientError(f"CC script registry call failed: {exc}") from exc

        if response.status_code >= 400:
            raise ScriptRegistryClientError(
                f"CC script registry call {method} {path} failed "
                f"(HTTP {response.status_code}): {response.text[:300]}"
            )
        if not response.content:
            return None
        data = response.json()
        verify_no_identity_tokens(data)
        return data

    # ── Serving-version lookup (script-first dispatch; no mode resolution) ─

    async def get_serving_version(
        self,
        agent_type_id: str,
        workflow_skill_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Fetch the current verified/compiled serving version for a workflow.

        Returns ``None`` when no serving version exists (→ LLM path).
        """
        params: dict[str, Any] = {"agent_type_id": agent_type_id}
        if workflow_skill_id:
            params["workflow_skill_id"] = workflow_skill_id
        payload = await self._request("GET", "/serving-version", params=params)
        if isinstance(payload, dict) and payload.get("script_version_id"):
            return payload
        return None

    # ── Optimized-plan lookup (execution preference) ───────────────────────

    async def get_optimized_plan(self, agent_type_id: str) -> dict[str, Any] | None:
        """Fetch the fresh ready OptimizedImplementationPlan, if any.

        Returns ``None`` when absent / stale / failed → the dispatcher falls
        back to the base implementation plan (LLM path). Only the freshness
        gate (ready AND newer than the base plan) is resolved server-side.
        """
        payload = await self._request(
            "GET", "/optimized-plan", params={"agent_type_id": agent_type_id}
        )
        if isinstance(payload, dict) and payload.get("optimized_plan_id"):
            return payload
        return None

    # ── Invocable script tools (script____<name> virtual-tool surface) ────

    async def list_invocable_scripts(self, agent_type_id: str) -> list[dict[str, Any]]:
        """List the agent type's compiled scripts as invocable virtual tools."""
        payload = await self._request(
            "GET", "/invocable", params={"agent_type_id": agent_type_id}
        )
        if isinstance(payload, dict):
            return list(payload.get("items") or [])
        return list(payload or [])

    async def get_script_tool(
        self, agent_type_id: str, name: str
    ) -> dict[str, Any] | None:
        """Resolve one invocable script tool by its bare name (``script____<name>``).

        ``name`` is the script definition name (the suffix after the
        ``script____`` virtual-tool prefix). Returns ``None`` when no compiled
        script with that name exists for the agent type.
        """
        items = await self.list_invocable_scripts(agent_type_id)
        for item in items:
            if item.get("name") == name:
                return item
        return None

    # ── Versions & candidates (C2) ────────────────────────────────────────

    async def get_version(self, version_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/versions/{version_id}")

    async def submit_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/candidates", json_body=payload)

    # ── Verification evidence (V2) ────────────────────────────────────────

    async def submit_verification(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/verifications", json_body=payload)

    async def get_llm_reference(self, session_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/llm-reference/{session_id}")

    # ── Fallbacks, executions & repairs (F2, G2, E9/E10) ──────────────────

    async def report_fallback(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/fallbacks", json_body=payload)

    async def report_execution(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/executions", json_body=payload)

    async def report_repair(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Report a repair attempt; CC persists RepairAttempt + repaired candidate."""
        return await self._request("POST", "/repairs", json_body=payload)

    async def promote_version(self, version_id: str) -> dict[str, Any]:
        """Promote a verified version to compiled (the serving version)."""
        return await self._request(
            "POST", "/promote", json_body={"script_version_id": version_id}
        )

    async def list_repairs(self, script_definition_id: str) -> list[dict[str, Any]]:
        """List repair attempts for a script (bounded-retry bookkeeping)."""
        payload = await self._request(
            "GET", "/repairs", params={"script_id": script_definition_id}
        )
        if isinstance(payload, dict):
            return list(payload.get("items") or [])
        return list(payload or [])

    # ── LLM mock recordings (Phase 4: record/replay via CC — never DB) ────

    def _mock_url(self, path: str) -> str:
        if not self._control_center_url:
            raise ScriptRegistryClientError("CONTROL_CENTER_URL not set")
        base = self._control_center_url.rstrip("/")
        return f"{base}/api/v1/internal/llm-mock{path}"

    async def submit_mock_recordings(
        self, recordings: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Batch upsert LLM mock recordings via CC (record mode, 4.2)."""
        url = self._mock_url("/recordings")
        if not self._cert_manager.is_loaded:
            raise CertificateLoadError("Certificate not loaded; cannot call Control Center")
        try:
            async with internal_httpx_client(
                timeout=30.0, **self._client_kwargs()
            ) as client:
                response = await client.post(
                    url, json={"recordings": recordings}
                )
        except httpx.HTTPError as exc:
            raise ScriptRegistryClientError(f"CC mock recording submit failed: {exc}") from exc
        if response.status_code >= 400:
            raise ScriptRegistryClientError(
                f"CC mock recording submit failed (HTTP {response.status_code}): "
                f"{response.text[:300]}"
            )
        return response.json() if response.content else {}

    async def get_mock_recording(
        self,
        recording_key: str,
        model_identifier: str | None = None,
    ) -> dict[str, Any] | None:
        """Look up one recording by key for deterministic replay (4.3)."""
        url = self._mock_url("/recordings")
        params: dict[str, Any] = {"recording_key": recording_key}
        if model_identifier:
            params["model_identifier"] = model_identifier
        if not self._cert_manager.is_loaded:
            raise CertificateLoadError("Certificate not loaded; cannot call Control Center")
        try:
            async with internal_httpx_client(
                timeout=30.0, **self._client_kwargs()
            ) as client:
                response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise ScriptRegistryClientError(f"CC mock recording lookup failed: {exc}") from exc
        if response.status_code >= 400:
            raise ScriptRegistryClientError(
                f"CC mock recording lookup failed (HTTP {response.status_code})"
            )
        if not response.content:
            return None
        return response.json()
