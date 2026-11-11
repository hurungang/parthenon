"""Regression tests for cc-assistant-management-tool-coverage fix round.

A. ``execute_script`` system-tool description teaches the iteration-saving
   pattern (combine multiple associated tool calls + computation) while
   keeping the verification primitive as a secondary note.
B. Conversational sessions never ship execution-log entries:
   - executor logging wrapper suppression flag,
   - script-tool endpoint skips the log shipper for conversation turns,
   - CC ``/sessions/{id}/log`` endpoint acks FK violations for conversation
     sessions as a 200 no-op (defense in depth, never break the caller).
C. ``guardrail_update`` is emitted as soon as the LLM delegation returns —
   a hung/failing ``append_conversation_turn`` persistence tail can no
   longer swallow the websocket event.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

import app.api.ws.chat as chat_module
from app.api.ws.chat import _process_message
from app.agent_runtime.api import script_tools
from app.services.agents import system_tool_registry as registry_module
from app.services.agents.runtime_executor import AgentRuntimeExecutor


# ── A. execute_script description ────────────────────────────────────────────


class TestExecuteScriptDescription:
    def _tool(self) -> Any:
        return registry_module.SystemToolRegistry.get("execute_script")

    def test_describes_iteration_saving_purpose(self):
        description = self._tool().description.lower()
        assert "iteration" in description
        assert "multiple" in description

    def test_describes_tools_facade_and_contract(self):
        description = self._tool().description
        assert "tools" in description
        assert "run(context, tools)" in description
        assert "dict" in description

    def test_describes_when_not_to_use(self):
        description = self._tool().description.lower()
        assert "single tool call" in description

    def test_verification_primitive_kept_as_secondary(self):
        description = self._tool().description.lower()
        assert "verification primitive" in description
        assert "script_version_id" in description

    def test_python_source_param_updated(self):
        param_description = self._tool().parameters["properties"]["python_source"][
            "description"
        ].lower()
        assert "run(context, tools)" in param_description
        assert "tools." in param_description

    def test_schema_stays_bounded(self):
        """Schema size stays bounded (spec change guard)."""
        tool = self._tool()
        blob = repr(tool.description) + repr(tool.parameters)
        assert len(blob) < 2000


# ── B. conversational execution-log shipping skip ────────────────────────────


class _RecordingDataClient:
    def __init__(self) -> None:
        self.ships: list[dict[str, Any]] = []

    async def log_execution_event(self, **kwargs: Any) -> None:
        self.ships.append(kwargs)


def _bare_executor(data_client: Any) -> AgentRuntimeExecutor:
    executor = object.__new__(AgentRuntimeExecutor)
    executor._data_client = data_client
    return executor


class TestConversationLogShipSuppression:
    @pytest.mark.asyncio
    async def test_suppressed_wrapper_ships_nothing(self):
        data_client = _RecordingDataClient()
        executor = _bare_executor(data_client)
        executor._suppress_execution_log_shipping = True

        await executor._log_execution_event(
            session_id=uuid.uuid4(),
            event_type="tool_call",
            message="m",
            data={},
        )

        assert data_client.ships == []

    @pytest.mark.asyncio
    async def test_unsuppressed_wrapper_ships(self):
        data_client = _RecordingDataClient()
        executor = _bare_executor(data_client)

        await executor._log_execution_event(
            session_id=uuid.uuid4(),
            event_type="tool_call",
            message="m",
            data={},
        )

        assert len(data_client.ships) == 1

    @pytest.mark.asyncio
    async def test_conversation_turn_sets_and_restores_flag(self):
        """The public conversational entrypoint enables suppression for the
        turn and restores the previous value afterwards."""
        executor = _bare_executor(_RecordingDataClient())
        seen_flags: list[bool] = []

        async def _inner(**kwargs: Any) -> tuple[str, dict, list]:
            seen_flags.append(
                getattr(executor, "_suppress_execution_log_shipping", False)
            )
            return "ok", {}, []

        executor._execute_conversation_turn_from_context_inner = _inner  # type: ignore[method-assign]

        await executor.execute_conversation_turn_from_context(
            agent_type_id=uuid.uuid4(),
            agent_context={},
            model_config={"provider_type": "openai"},
            messages=[],
            conv_session_id=uuid.uuid4(),
        )

        assert seen_flags == [True]
        assert getattr(executor, "_suppress_execution_log_shipping", False) is False


class TestScriptToolConversationShipSkip:
    @pytest.mark.asyncio
    async def test_conversation_turn_gets_no_log_shipper(self, monkeypatch):
        """When the request is a conversation turn (``conv_session_id`` set),
        the script-tool endpoint builds NO execution-log shipper."""
        captured: dict[str, Any] = {}

        class _FakeRunner:
            def __init__(self, tool_client: Any, log_shipper: Any = None) -> None:
                captured["log_shipper"] = log_shipper

            async def execute_python_source(self, *args: Any, **kwargs: Any) -> dict:
                return {"ok": True}

        monkeypatch.setattr(script_tools, "ScriptRunner", _FakeRunner)
        monkeypatch.setattr(
            script_tools, "_session_bound_tool_client", lambda cm: object()
        )
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    certificate_manager=_FakeCertManager(),
                    data_client=object(),
                )
            )
        )

        response = await script_tools.execute_script_tool(
            script_tools.ScriptToolExecuteRequest(
                tool_name="script____x",
                tool_args={"input": {}},
                session_id=str(uuid.uuid4()),
                agent_type_id=str(uuid.uuid4()),
                python_source="def run(context, tools):\n    return {}\n",
                conv_session_id=str(uuid.uuid4()),
            ),
            request,
        )

        assert response.error is None
        assert captured["log_shipper"] is None

    @pytest.mark.asyncio
    async def test_agent_job_turn_keeps_log_shipper(self, monkeypatch):
        """Non-conversational (agent-job) turns keep the log shipper."""
        captured: dict[str, Any] = {}

        class _FakeRunner:
            def __init__(self, tool_client: Any, log_shipper: Any = None) -> None:
                captured["log_shipper"] = log_shipper

            async def execute_python_source(self, *args: Any, **kwargs: Any) -> dict:
                return {"ok": True}

        monkeypatch.setattr(script_tools, "ScriptRunner", _FakeRunner)
        monkeypatch.setattr(
            script_tools, "_session_bound_tool_client", lambda cm: object()
        )
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    certificate_manager=_FakeCertManager(),
                    data_client=object(),
                )
            )
        )

        await script_tools.execute_script_tool(
            script_tools.ScriptToolExecuteRequest(
                tool_name="script____x",
                tool_args={"input": {}},
                session_id=str(uuid.uuid4()),
                agent_type_id=str(uuid.uuid4()),
                python_source="def run(context, tools):\n    return {}\n",
            ),
            request,
        )

        assert captured["log_shipper"] is not None


class _FakeCertManager:
    is_loaded = True
    cert_path = "/tmp/agent-cert.pem"
    key_path = "/tmp/agent-key.pem"


class TestCcLogEndpointFkTolerance:
    def _endpoint(self):
        from app.api.v1.internal.session_data import log_execution_event

        return log_execution_event

    def _body(self) -> Any:
        from app.api.v1.internal.session_data import LogExecutionEventRequest

        return LogExecutionEventRequest(
            event_type="tool_call",
            log_level="INFO",
            message="m",
            data={},
            event_category="functional",
            actor_type="system",
        )

    def _failing_db(self, conv_session: Any) -> Any:
        class _DB:
            def add(self, entry: Any) -> None:
                pass

            async def flush(self) -> None:
                raise IntegrityError("stmt", {}, Exception("fk"))

            async def rollback(self) -> None:
                pass

            async def get(self, model: Any, key: Any) -> Any:
                return conv_session

        return _DB()

    @pytest.mark.asyncio
    async def test_fk_violation_for_conversation_session_returns_200(self):
        conv = SimpleNamespace(id=uuid.uuid4())
        response = await self._endpoint()(
            session_id=uuid.uuid4(),
            body=self._body(),
            db=self._failing_db(conv),
        )
        assert response.entry_id is not None

    @pytest.mark.asyncio
    async def test_fk_violation_for_unknown_session_still_500(self):
        with pytest.raises(HTTPException) as exc_info:
            await self._endpoint()(
                session_id=uuid.uuid4(),
                body=self._body(),
                db=self._failing_db(None),
            )
        assert exc_info.value.status_code == 500


# ── C. guardrail_update emitted before persistence ───────────────────────────


class TestGuardrailUpdateBeforePersistence:
    @pytest.mark.asyncio
    async def test_on_guardrail_usage_called_even_when_persistence_fails(self, monkeypatch):
        """The guardrail usage callback fires the moment delegation returns —
        before (and regardless of) append_conversation_turn."""
        conv_id = uuid.uuid4()
        usage_payload = {"max_iterations": 24, "cumulative_iterations": 3}
        calls: list[dict[str, Any]] = []

        async def _fake_delegate(**kwargs: Any) -> tuple[str, dict, list]:
            return "reply text", usage_payload, []

        async def _fake_prepare(self: Any, conv_session_id: Any, message: str) -> dict:
            return {"agent_type_id": str(uuid.uuid4()), "messages": []}

        async def _fake_append(self: Any, **kwargs: Any) -> dict:
            calls.append({"append": True})
            raise RuntimeError("append-turn persistence hang")

        class _DataClient:
            prepare_conversation_turn = _fake_prepare
            append_conversation_turn = _fake_append

        monkeypatch.setattr(
            chat_module, "_delegate_conversation_turn_to_agent_runtime", _fake_delegate
        )

        app = SimpleNamespace(state=SimpleNamespace(data_client=_DataClient()))

        async def _on_guardrail_usage(usage: dict[str, Any]) -> None:
            calls.append({"guardrail": usage})

        with pytest.raises(RuntimeError, match="append-turn"):
            await _process_message(
                conv_session_id=conv_id,
                user_message="hi",
                is_first_message=False,
                app=app,
                on_guardrail_usage=_on_guardrail_usage,
            )

        assert calls and "guardrail" in calls[0]
        assert calls[0]["guardrail"] == usage_payload
