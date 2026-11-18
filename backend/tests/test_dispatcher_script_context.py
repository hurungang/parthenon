"""Regression: serving scripts must receive the session input as ``context``.

The Script-First Dispatcher originally called the sandbox runner without
``initial_context``, so every script saw an empty ``context`` dict and read
all input fields as ``None`` (e.g. a flight-search script rejecting valid
3-letter airport codes). These tests pin the input→context binding for both
the whole-``python_source`` path and the declarative step-graph path.
"""
from __future__ import annotations

import pytest

from app.agent_runtime.scripts import dispatch


class _FakeDataClient:
    def __init__(self) -> None:
        self._cert_manager = None
        self.completed: list[tuple[str, object]] = []

    async def mark_session_completed(self, session_id: str, result: object) -> None:
        self.completed.append((session_id, result))


class _FakeController:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def run_with_fallback(self, run, **kwargs: object):
        # The real controller passes the run closure's return value through —
        # `_run` returns ``(result, telemetry)``. The dispatcher must unpack it
        # so the telemetry never becomes the stored output.
        return await run()


def _serving() -> dispatch._ServingScript:
    return dispatch._ServingScript(
        script_definition_id="def-1",
        script_definition_name="optimized-abc",
        script_version_id="ver-1",
        script_version_label="v1",
        graph_json={"name": "g", "steps": []},
        python_source="def run(context, tools):\n    return {'result': 'ok'}\n",
        fully_scripted=True,
        is_optimized_artifact=True,
    )


@pytest.mark.asyncio
async def test_sandboxed_script_receives_session_input_as_context(monkeypatch):
    captured: dict = {}

    class _FakeRunner:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def execute_python_source(self, source, **kwargs):
            captured["source"] = source
            captured.update(kwargs)
            return {"result": "ok"}

    async def _noop_report(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(dispatch, "ScriptRunner", _FakeRunner)
    monkeypatch.setattr(dispatch, "FallbackController", _FakeController)
    monkeypatch.setattr(dispatch, "_report_success_execution", _noop_report)
    monkeypatch.setattr(dispatch, "_script_log_shipper", lambda *a, **k: None)

    async def run_llm() -> None:
        raise AssertionError("LLM path must not run for a successful script")

    input_data = {
        "origin": "MEL",
        "destination": "SYD",
        "travel_date": "2026-11-15",
    }
    data_client = _FakeDataClient()
    await dispatch._run_sandboxed_script_path(
        session_id="sess-1",
        agent_type_id="at-1",
        data_client=data_client,
        registry_client=object(),
        serving=_serving(),
        run_llm=run_llm,
        input_data=input_data,
    )

    assert captured["initial_context"] == input_data
    assert data_client.completed == [("sess-1", {"result": "ok"})]


@pytest.mark.asyncio
async def test_execute_script_receives_input_context(monkeypatch):
    captured: dict = {}

    class _FakeRunner:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def execute(self, graph, **kwargs):
            captured.update(kwargs)
            return {"result": "ok"}

    monkeypatch.setattr(dispatch, "ScriptRunner", _FakeRunner)

    input_data = {
        "origin": "MEL",
        "destination": "SYD",
        "travel_date": "2026-11-15",
    }
    await dispatch._execute_script(
        object(),  # graph is opaque to the fake runner
        tool_client=None,
        session_id="sess-1",
        agent_type_id="at-1",
        version_label="v1",
        input_data=input_data,
    )

    assert captured["initial_context"] == input_data
