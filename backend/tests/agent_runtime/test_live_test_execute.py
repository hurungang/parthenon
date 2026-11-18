"""Agent Runtime — approved live-test runner (``POST /internal/live-test/run``).

This is the only place a live test actually contacts real integrations, and a
live test is **one end-to-end run of the approved script** — never an
individual MCP tool call (MCP tools are assumed to work).

The handler must:

* check the script's statically extracted ``tools.call`` names against the
  **subject agent type's own** granted tools (its context is fetched unscoped by
  ``agent_type_id`` only) and start **no work** when any is not permitted;
* execute the approved source **once**, in the real sandbox, sequentially — the
  script's own ``tools.call(...)`` lines are the only egress;
* run those calls through the agent's normal CH tool route with the
  conversation id + subject agent type, so CH injects that agent's own identity,
  tagged ``provenance="live_test"``;
* stop on the first error without retrying;
* tag every recorded ``RuntimeToolCall`` with the ledger pointer
  (``optimization_live_test_request_id``);
* return **one** ``{kind: "script_run", …}`` record (result summary,
  per-``tools.call`` outcomes, telemetry, duration);
* enforce a per-run wall clock;
* touch no database (AR is a forward-only executor).
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.agent_runtime.api import live_test
from app.agent_runtime.comm_hub_client import CommHubToolClientError
from app.agent_runtime.scripts.runner import ScriptExecutionError
from app.agent_runtime.scripts.sandbox import SandboxViolationError

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PERMITTED_TOOL = "crm____searchCustomers"
SECOND_TOOL = "crm____createOrder"

SIMPLE_SCRIPT = (
    "def run(context, tools):\n"
    f"    customer = tools.call('{PERMITTED_TOOL}', {{'q': 'ada'}})\n"
    "    return {'customer': customer}\n"
)

TWO_CALL_SCRIPT = (
    "def run(context, tools):\n"
    f"    customer = tools.call('{PERMITTED_TOOL}', {{'q': 'ada'}})\n"
    f"    order = tools.call('{SECOND_TOOL}', {{'q': 'ada'}})\n"
    "    return {'customer': customer, 'order': order}\n"
)


class _FakeCertManager:
    is_loaded = True
    cert_path = "/tmp/ar-cert.pem"
    key_path = "/tmp/ar-key.pem"


class _NoCertManager:
    is_loaded = False
    cert_path = None
    key_path = None


class _RecordingToolClient:
    """CommHubToolClient double: records calls, returns canned results."""

    instances: list["_RecordingToolClient"] = []
    results: dict[str, Any] = {
        PERMITTED_TOOL: {"name": "Ada"},
        SECOND_TOOL: {"id": "o-1"},
    }
    error_at: dict[int, Exception] = {}

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.certificate: tuple | None = None
        _RecordingToolClient.instances.append(self)

    def set_certificate(self, cert_path, key_path) -> None:  # noqa: ANN001
        self.certificate = (cert_path, key_path)

    async def call_tool(
        self, tool_name, tool_args=None, **kwargs
    ) -> Any:  # noqa: ANN001
        self.calls.append(
            {"tool_name": tool_name, "arguments": tool_args, **kwargs}
        )
        index = len(self.calls)
        if index in self.error_at:
            raise self.error_at[index]
        return self.results.get(tool_name, {"tool": tool_name})


class _FakeRunner:
    """ScriptRunner double for the bound / sandbox-stop branches."""

    behaviour = "ok"
    calls: list[dict[str, Any]] = []

    def __init__(self, tool_client) -> None:  # noqa: ANN001
        self._tool_client = tool_client

    async def execute_python_source(self, source: str, **kwargs: Any) -> Any:
        _FakeRunner.calls.append({"source": source, **kwargs})
        out = kwargs.get("tool_calls_out")
        if isinstance(out, list):
            out.append(
                {
                    "tool_name": PERMITTED_TOOL,
                    "arguments": {"q": "ada"},
                    "duration_ms": 3,
                    "result_preview": '{"name": "Ada"}',
                    "error": None,
                }
            )
        if _FakeRunner.behaviour == "timeout":
            raise asyncio.TimeoutError()
        if _FakeRunner.behaviour == "sandbox":
            raise SandboxViolationError("blocked import")
        if _FakeRunner.behaviour == "script_error":
            raise ScriptExecutionError("tool call inside script failed")
        return {"ok": True, "__execution_telemetry__": {"tool_call_count": 1}}


def _data_client(*, allowed: list[str] | None = None):
    client = SimpleNamespace()
    client.get_agent_context = AsyncMock(
        return_value={
            "allowed_tools": (
                allowed if allowed is not None else [PERMITTED_TOOL, SECOND_TOOL]
            )
        }
    )
    client.record_tool_call = AsyncMock()
    return client


def _request(*, data_client=None, cert_manager=None) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                data_client=data_client if data_client is not None else _data_client(),
                certificate_manager=(
                    cert_manager if cert_manager is not None else _FakeCertManager()
                ),
            )
        )
    )


def _body(
    *,
    python_source: str = SIMPLE_SCRIPT,
    **overrides,
) -> live_test.LiveTestRunRequest:
    payload: dict[str, Any] = {
        "live_test_request_id": str(uuid.uuid4()),
        "conversation_session_id": str(uuid.uuid4()),
        "target_agent_type_id": str(uuid.uuid4()),
        "script_version_id": str(uuid.uuid4()),
        "script_name": "daily-refunds",
        "script_version_label": "v4",
        "python_source": python_source,
        "input_context": {"order_id": "o-1"},
    }
    payload.update(overrides)
    return live_test.LiveTestRunRequest(**payload)


@pytest.fixture(autouse=True)
def _fresh_instances():
    _RecordingToolClient.instances.clear()
    _RecordingToolClient.error_at.clear()
    _FakeRunner.calls.clear()
    _FakeRunner.behaviour = "ok"
    yield
    _RecordingToolClient.instances.clear()
    _RecordingToolClient.error_at.clear()
    _FakeRunner.calls.clear()


@pytest.fixture(autouse=True)
def _patch_tool_client(monkeypatch):
    monkeypatch.setattr(live_test, "CommHubToolClient", _RecordingToolClient)


@pytest.fixture
def fake_runner(monkeypatch):
    """Replace the sandbox runner with a controllable double."""

    def _install(behaviour: str = "ok") -> type[_FakeRunner]:
        _FakeRunner.behaviour = behaviour
        monkeypatch.setattr(live_test, "ScriptRunner", _FakeRunner)
        return _FakeRunner

    return _install


class TestCapabilityCheck:
    @pytest.mark.asyncio
    async def test_a_script_naming_an_out_of_grant_tool_starts_no_work(self):
        allowed = [PERMITTED_TOOL]
        source = (
            "def run(context, tools):\n"
            f"    a = tools.call('{PERMITTED_TOOL}', {{}})\n"
            f"    return tools.call('{SECOND_TOOL}', {{}})\n"
        )
        data_client = _data_client(allowed=allowed)

        response = await live_test.run_live_test(
            _body(python_source=source), _request(data_client=data_client)
        )

        assert response.status == "failed"
        assert response.error.startswith(live_test.ERROR_PERMISSION_DENIED)
        assert SECOND_TOOL in response.error
        # The run record says what was refused; no tool call was made.
        assert len(response.executed_operations) == 1
        record = response.executed_operations[0]
        assert record["kind"] == "script_run"
        assert record["status"] == "error"
        assert record["tool_calls"] == []
        assert all(instance.calls == [] for instance in _RecordingToolClient.instances)
        data_client.record_tool_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_context_is_fetched_unscoped_by_agent_type_only(self):
        data_client = _data_client()
        body = _body()

        await live_test.run_live_test(body, _request(data_client=data_client))

        kwargs = data_client.get_agent_context.await_args.kwargs
        assert str(kwargs["agent_type_id"]) == body.target_agent_type_id
        # Unscoped on purpose: the business grant envelope, not the
        # optimization-mode turn tool set.
        assert kwargs["conv_session_id"] is None

    @pytest.mark.asyncio
    async def test_an_unreadable_context_fails_closed(self):
        data_client = SimpleNamespace()
        data_client.get_agent_context = AsyncMock(side_effect=RuntimeError("cc down"))
        data_client.record_tool_call = AsyncMock()

        response = await live_test.run_live_test(
            _body(), _request(data_client=data_client)
        )

        assert response.status == "failed"
        assert "capability" in (response.error or "")
        assert all(instance.calls == [] for instance in _RecordingToolClient.instances)


class TestScriptExecution:
    @pytest.mark.asyncio
    async def test_the_script_runs_once_and_returns_one_run_record(self):
        data_client = _data_client()
        body = _body(python_source=TWO_CALL_SCRIPT)

        response = await live_test.run_live_test(body, _request(data_client=data_client))

        assert response.status == "executed", response.error
        assert response.error is None
        # ONE record for the whole run — there is no per-operation execution.
        assert len(response.executed_operations) == 1
        record = response.executed_operations[0]
        assert record["kind"] == "script_run"
        assert record["status"] == "success"
        assert record["script_version_id"] == body.script_version_id
        assert record["script_name"] == "daily-refunds"
        assert record["script_version_label"] == "v4"
        assert record["duration_ms"] is not None
        # Per-tools.call outcomes, in the script's own order.
        assert [call["tool_name"] for call in record["tool_calls"]] == [
            PERMITTED_TOOL,
            SECOND_TOOL,
        ]
        assert all(call["status"] == "success" for call in record["tool_calls"])
        # Bounded result summary + telemetry.
        assert "Ada" in (record["result_summary"] or "")
        assert "__execution_telemetry__" not in (record["result_summary"] or "")
        assert record["telemetry"]["tool_call_count"] == 2
        assert response.started_at and response.finished_at

    @pytest.mark.asyncio
    async def test_the_script_receives_the_reference_input_as_context(self):
        data_client = _data_client()
        source = "def run(context, tools):\n    return {'order': context.get('order_id')}\n"
        body = _body(python_source=source)

        response = await live_test.run_live_test(body, _request(data_client=data_client))

        assert response.status == "executed", response.error
        assert "o-1" in (response.executed_operations[0]["result_summary"] or "")

    @pytest.mark.asyncio
    async def test_calls_carry_the_conversation_and_the_subject_agent_type(self):
        data_client = _data_client()
        body = _body()

        await live_test.run_live_test(body, _request(data_client=data_client))

        calls = _RecordingToolClient.instances[0].calls
        assert len(calls) == 1
        assert calls[0]["session_id"] == body.conversation_session_id
        assert calls[0]["agent_type_id"] == body.target_agent_type_id
        # Provenance keeps live evidence out of the authoring capture buffer.
        assert calls[0]["provenance"] == "live_test"
        assert calls[0]["script_version"] == "v4"

    @pytest.mark.asyncio
    async def test_the_service_certificate_is_used_for_the_ch_hop(self):
        await live_test.run_live_test(_body(), _request())
        client = _RecordingToolClient.instances[0]
        assert client.certificate == ("/tmp/ar-cert.pem", "/tmp/ar-key.pem")

    @pytest.mark.asyncio
    async def test_a_missing_certificate_starts_no_work(self):
        response = await live_test.run_live_test(
            _body(), _request(cert_manager=_NoCertManager())
        )
        assert response.status == "failed"
        assert "certificate" in (response.error or "")
        assert all(instance.calls == [] for instance in _RecordingToolClient.instances)

    @pytest.mark.asyncio
    async def test_a_missing_script_source_is_refused(self):
        response = await live_test.run_live_test(
            _body(python_source=""), _request()
        )
        assert response.status == "failed"
        assert response.error.startswith(live_test.ERROR_SCRIPT_UNAVAILABLE)
        assert len(response.executed_operations) == 1
        assert response.executed_operations[0]["status"] == "error"

    @pytest.mark.asyncio
    async def test_a_malformed_request_is_refused(self):
        response = await live_test.run_live_test(
            _body(target_agent_type_id="not-a-uuid"), _request()
        )
        assert response.status == "failed"
        assert "Malformed" in (response.error or "")

    @pytest.mark.asyncio
    async def test_a_mid_script_tool_failure_stops_the_run(self):
        error = CommHubToolClientError("403 forbidden: permission denied")
        _RecordingToolClient.error_at[2] = error
        data_client = _data_client()

        response = await live_test.run_live_test(
            _body(python_source=TWO_CALL_SCRIPT), _request(data_client=data_client)
        )

        assert response.status == "failed"
        # The first call ran; the second failed and the script stopped there.
        calls = _RecordingToolClient.instances[0].calls
        assert [call["tool_name"] for call in calls] == [PERMITTED_TOOL, SECOND_TOOL]
        record = response.executed_operations[0]
        assert record["status"] == "error"
        assert [call["tool_name"] for call in record["tool_calls"]] == [
            PERMITTED_TOOL,
            SECOND_TOOL,
        ]
        statuses = [call["status"] for call in record["tool_calls"]]
        assert statuses == ["success", "error"]
        assert record["tool_calls"][1]["error"]

    @pytest.mark.asyncio
    async def test_a_script_runtime_error_is_terminal(self):
        source = "def run(context, tools):\n    return 1 / 0\n"
        data_client = _data_client()

        response = await live_test.run_live_test(
            _body(python_source=source), _request(data_client=data_client)
        )

        assert response.status == "failed"
        assert response.error
        assert len(response.executed_operations) == 1
        assert response.executed_operations[0]["status"] == "error"

    @pytest.mark.asyncio
    async def test_a_run_bound_breach_is_reported_and_bounded(self, fake_runner):
        fake_runner("timeout")
        data_client = _data_client()

        response = await live_test.run_live_test(
            _body(), _request(data_client=data_client)
        )

        assert response.status == "failed"
        assert response.error.startswith(live_test.ERROR_RUN_TIMEOUT)
        # Calls the script made before the bound fired stay in the run record.
        assert response.executed_operations[0]["tool_calls"][0]["tool_name"] == (
            PERMITTED_TOOL
        )

    @pytest.mark.asyncio
    async def test_a_sandbox_stop_is_reported(self, fake_runner):
        fake_runner("sandbox")
        response = await live_test.run_live_test(_body(), _request())
        assert response.status == "failed"
        assert "SandboxViolationError" in (response.error or "")

    @pytest.mark.asyncio
    async def test_a_script_execution_error_is_reported(self, fake_runner):
        fake_runner("script_error")
        response = await live_test.run_live_test(_body(), _request())
        assert response.status == "failed"
        assert "tool call inside script failed" in (response.error or "")


class TestLedgerPointer:
    @pytest.mark.asyncio
    async def test_every_live_call_carries_the_ledger_pointer(self):
        data_client = _data_client()
        body = _body(python_source=TWO_CALL_SCRIPT)

        await live_test.run_live_test(body, _request(data_client=data_client))

        recorded = data_client.record_tool_call.await_args_list
        assert len(recorded) == 2
        for call in recorded:
            kwargs = call.kwargs
            assert str(kwargs["optimization_live_test_request_id"]) == (
                body.live_test_request_id
            )
            assert str(kwargs["session_id"]) == body.conversation_session_id
            assert kwargs["session_kind"] == "conversation"
            assert kwargs["status"] == "success"

    @pytest.mark.asyncio
    async def test_recording_failures_never_break_the_run(self):
        data_client = _data_client()
        data_client.record_tool_call = AsyncMock(side_effect=RuntimeError("no log"))

        response = await live_test.run_live_test(_body(), _request(data_client=data_client))

        assert response.status == "executed"

    def test_the_run_bound_setting_is_used(self):
        """Structural: the per-run wall clock comes from the live-test setting
        and wraps the single sandbox execution."""
        source = Path(live_test.__file__).read_text()
        assert "optimizer_live_test_run_timeout_seconds" in source
        assert "asyncio.wait_for(" in source
        # The script is executed once, through the runner's whole-script entry point.
        assert "execute_python_source" in source


class TestSegregation:
    def test_the_runner_does_not_touch_the_database(self):
        source = Path(live_test.__file__).read_text()
        assert "app.db" not in source
        assert "AsyncSession" not in source
        assert "get_db" not in source

    def test_the_route_is_registered_on_the_agent_runtime_app(self):
        assert live_test.live_test_router.prefix == "/internal/live-test"
        paths = {route.path for route in live_test.live_test_router.routes}
        assert "/internal/live-test/run" in paths

    def test_the_route_requires_the_ch_service_certificate(self):
        """AR's global certificate middleware accepts only CH on ``/internal/*``
        (asserted structurally: the router is mounted under it in AR's app)."""
        main_source = (BACKEND_ROOT / "app" / "agent_runtime" / "main.py").read_text()
        assert "live_test_router" in main_source
        assert "ControlCenterCertificateMiddleware" in main_source
