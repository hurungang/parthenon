"""Tests for the Agent Runtime script-tool execution endpoint.

Covers the ``script____<name>`` virtual-tool execution surface that
Communication Hub forwards to ``POST /internal/script-tools/execute``:

- The script's ``python_source`` runs in the sandbox and its result is returned
  as ``{"result": ...}`` (the CH ``call_tool`` contract shape).
- Sandbox/execution failures surface as a structured tool error
  (``{"error": ...}``), never a 502.
- Identity parity (SEC1): the script executes with a session-bound tool client
  built from the session's cert/tenant context — the script's ``tools.call``
  carries the same ``session_id``/``agent_type_id`` as the agent's own calls.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.agent_runtime.api import script_tools


class _FakeCertManager:
    """AR agent-instance cert double (the session's identity material)."""

    is_loaded = True
    cert_path = "/tmp/agent-cert.pem"
    key_path = "/tmp/agent-key.pem"


def _request(cert_manager: Any = None) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(certificate_manager=cert_manager or _FakeCertManager())
        )
    )


class _FakeRegistry:
    """CC script registry double returning a canned invocable script."""

    def __init__(self, script: dict[str, Any] | None) -> None:
        self._script = script
        self.agent_type_id: str | None = None
        self.name: str | None = None

    async def get_script_tool(self, agent_type_id: str, name: str) -> dict[str, Any] | None:
        self.agent_type_id = agent_type_id
        self.name = name
        return self._script


class _RecordingToolClient:
    """Session-bound CommHubToolClient double (call recording)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        session_id: str,
        agent_type_id: str,
        provenance: str = "llm",
        script_version: str | None = None,
    ) -> Any:
        self.calls.append(
            {
                "tool_name": tool_name,
                "arguments": arguments,
                "session_id": session_id,
                "agent_type_id": agent_type_id,
                "provenance": provenance,
                "script_version": script_version,
            }
        )
        return {"name": "Ada"}


def _body(**overrides: Any) -> script_tools.ScriptToolExecuteRequest:
    payload: dict[str, Any] = {
        "tool_name": "script____report",
        "tool_args": {},
        "session_id": "sess-1",
        "agent_type_id": "at-1",
    }
    payload.update(overrides)
    return script_tools.ScriptToolExecuteRequest(**payload)


class TestScriptToolExecute:
    @pytest.mark.asyncio
    async def test_script_tool_returns_script_result(self, monkeypatch):
        """The script's ``python_source`` runs in the sandbox and its returned
        dict is surfaced as ``{"result": ...}`` (telemetry stripped)."""
        monkeypatch.setattr(
            script_tools,
            "ScriptRegistryClient",
            lambda cm: _FakeRegistry(
                {
                    "name": "report",
                    "script_version_label": "v1",
                    "python_source": (
                        "def run(context, tools):\n"
                        "    return {'name': 'Ada', 'tier': 'gold'}\n"
                    ),
                }
            ),
        )

        response = await script_tools.execute_script_tool(
            _body(tool_args={"id": "c-1"}), _request()
        )

        assert response.error is None
        assert response.result == {"name": "Ada", "tier": "gold"}
        assert "__execution_telemetry__" not in response.result

    @pytest.mark.asyncio
    async def test_script_tool_sandbox_error_returns_tool_error(self, monkeypatch):
        """A sandbox violation surfaces as a structured tool error — the CH
        contract converts it to a tool error rather than a 502."""
        monkeypatch.setattr(
            script_tools,
            "ScriptRegistryClient",
            lambda cm: _FakeRegistry(
                {
                    "name": "report",
                    "script_version_label": "v1",
                    "python_source": (
                        "def run(context, tools):\n"
                        "    import os\n"
                        "    return {}\n"
                    ),
                }
            ),
        )

        response = await script_tools.execute_script_tool(_body(), _request())

        assert response.error is not None
        assert "sandbox" in response.error.lower()
        assert response.result is None

    @pytest.mark.asyncio
    async def test_script_tool_binds_session_identity(self, monkeypatch):
        """Identity parity (SEC1): the tool client is built from the session's
        cert manager, and the script's ``tools.call`` carries the same
        ``session_id``/``agent_type_id`` as the agent's own tool calls."""
        cert_manager = _FakeCertManager()
        tool_client = _RecordingToolClient()
        seen: dict[str, Any] = {}

        def _fake_session_bound(cm: Any) -> _RecordingToolClient:
            seen["cert_manager"] = cm
            return tool_client

        monkeypatch.setattr(
            script_tools, "_session_bound_tool_client", _fake_session_bound
        )
        registry = _FakeRegistry(
            {
                "name": "report",
                "script_version_label": "v1",
                "python_source": (
                    "def run(context, tools):\n"
                    "    got = tools.call('crm____getContact', {'id': context['id']})\n"
                    "    return {'got': got['name']}\n"
                ),
            }
        )
        monkeypatch.setattr(script_tools, "ScriptRegistryClient", lambda cm: registry)

        response = await script_tools.execute_script_tool(
            _body(
                tool_args={"id": "abc-123"},
                session_id="sess-42",
                agent_type_id="at-9",
            ),
            _request(cert_manager),
        )

        # The tool client was built from the session's cert/tenant identity.
        assert seen["cert_manager"] is cert_manager
        # Script resolved within the session's agent type.
        assert registry.agent_type_id == "at-9"
        assert registry.name == "report"
        # The script's tool call carried the session identity (identity parity).
        assert response.result == {"got": "Ada"}
        assert len(tool_client.calls) == 1
        call = tool_client.calls[0]
        assert call["session_id"] == "sess-42"
        assert call["agent_type_id"] == "at-9"
        assert call["provenance"] == "script"
        assert call["script_version"] == "v1"

    @pytest.mark.asyncio
    async def test_script_tool_not_found_returns_tool_error(self, monkeypatch):
        """An unknown script name resolves to a structured tool error."""
        monkeypatch.setattr(
            script_tools, "ScriptRegistryClient", lambda cm: _FakeRegistry(None)
        )

        response = await script_tools.execute_script_tool(
            _body(tool_name="script____missing"), _request()
        )

        assert response.result is None
        assert "not found" in (response.error or "").lower()

    @pytest.mark.asyncio
    async def test_non_script_tool_name_rejected(self, monkeypatch):
        """A non-``script____`` tool name is rejected before any lookup."""
        response = await script_tools.execute_script_tool(
            _body(tool_name="crm____getContact"), _request()
        )

        assert response.result is None
        assert "not a script tool" in (response.error or "").lower()


class TestInlineSourceExecution:
    """Inline ``python_source`` execution (CC optimize-and-verify path).

    Control Center forwards verification runs here with the FULL source and
    NO registry entry: AR must execute THAT source directly with the
    session-bound tool client — the ``tools`` facade is non-None, so
    ``tools.call(...)`` inside the script works (live-defect regression:
    the facade was None and every tool-backed script failed verification).
    """

    _SOURCE_WITH_TOOL_CALL = (
        "def run(context, tools):\n"
        "    project = tools.call('supabase____get_project', {'id': context['project_id']})\n"
        "    return {'project': project['name']}\n"
    )

    @pytest.mark.asyncio
    async def test_inline_source_executes_without_registry_lookup(self, monkeypatch):
        """``python_source`` in the payload executes directly — the CC script
        registry is NEVER consulted (there is no saved version yet)."""

        def _fail_registry(cm: Any) -> Any:
            raise AssertionError("registry lookup must be skipped for inline source")

        monkeypatch.setattr(script_tools, "ScriptRegistryClient", _fail_registry)

        response = await script_tools.execute_script_tool(
            _body(
                tool_name="script____inline",
                python_source=(
                    "def run(context, tools):\n"
                    "    return {'value': context.get('x', 0)}\n"
                ),
            ),
            _request(),
        )

        assert response.error is None
        assert response.result == {"value": 0}

    @pytest.mark.asyncio
    async def test_inline_source_tools_facade_is_not_none(self, monkeypatch):
        """The session-bound tool client is injected: ``tools`` is non-None and
        the script's ``tools.call(...)`` actually executes."""
        tool_client = _RecordingToolClient()
        monkeypatch.setattr(
            script_tools, "_session_bound_tool_client", lambda cm: tool_client
        )

        response = await script_tools.execute_script_tool(
            _body(
                tool_name="script____inline",
                tool_args={"input": {"project_id": "p-1"}},
                session_id="sess-7",
                agent_type_id="at-7",
                python_source=self._SOURCE_WITH_TOOL_CALL,
            ),
            _request(),
        )

        assert response.error is None
        assert response.result == {"project": "Ada"}
        assert len(tool_client.calls) == 1
        call = tool_client.calls[0]
        assert call["tool_name"] == "supabase____get_project"
        assert call["session_id"] == "sess-7"
        assert call["agent_type_id"] == "at-7"
        assert call["provenance"] == "script"

    @pytest.mark.asyncio
    async def test_inline_source_uses_input_context(self, monkeypatch):
        """The ``input`` context dict is the script's ``context``."""
        monkeypatch.setattr(
            script_tools,
            "ScriptRegistryClient",
            lambda cm: (_ for _ in ()).throw(AssertionError("no lookup")),
        )

        response = await script_tools.execute_script_tool(
            _body(
                tool_name="script____inline",
                tool_args={"input": {"x": 41}},
                python_source=(
                    "def run(context, tools):\n"
                    "    return {'value': context.get('x', 0)}\n"
                ),
            ),
            _request(),
        )

        assert response.error is None
        assert response.result == {"value": 41}

    @pytest.mark.asyncio
    async def test_inline_source_sandbox_error_surfaced(self, monkeypatch):
        """A sandbox compile/violation failure surfaces as a structured tool
        error — never a 500."""
        monkeypatch.setattr(
            script_tools,
            "ScriptRegistryClient",
            lambda cm: (_ for _ in ()).throw(AssertionError("no lookup")),
        )

        response = await script_tools.execute_script_tool(
            _body(
                tool_name="script____inline",
                python_source="def run(context, tools):\n    import os\n    return {}\n",
            ),
            _request(),
        )

        assert response.result is None
        assert response.error is not None
        assert "sandbox" in response.error.lower()
