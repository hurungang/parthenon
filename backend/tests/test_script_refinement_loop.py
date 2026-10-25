"""Tests for the sandbox capability contract and the generate → test →
refine loop (autocompile).

Covers:
- the capability contract builder content (pre-bound modules, injected
  variables/tools, output contract, resource caps);
- the refine loop converging on the FIRST passing authored script (no repair
  calls, one promotion);
- error-feedback repair converging on attempt 2 (typed failure fed back with
  the contract, repaired version tested and promoted);
- exhaustion (repair never converges) leaving NOTHING promoted, logged.
"""
from __future__ import annotations

import logging
from typing import Any

import pytest

from app.agent_runtime.scripts import autocompile, capture
from app.agent_runtime.scripts.sandbox import build_capability_contract

_AGENT_TYPE = "aaaaaaaa-0000-0000-0000-0000000000aa"
_SESSION = "bbbbbbbb-0000-0000-0000-0000000000bb"


class FakeScriptRegistry:
    def __init__(self) -> None:
        self.versions: dict[str, dict[str, Any]] = {}
        self.promoted: list[str] = []

    async def get_serving_version(
        self, agent_type_id: str, workflow_skill_id: str | None = None
    ) -> dict[str, Any] | None:
        return None

    async def submit_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        version_id = f"version-{len(self.versions) + 1}"
        self.versions[version_id] = payload
        return {"id": version_id}

    async def promote_version(self, version_id: str) -> dict[str, Any]:
        self.promoted.append(version_id)
        return {"id": version_id, "lifecycle_status": "compiled"}


class FakeDataClient:
    def __init__(self, plan: dict[str, Any] | None) -> None:
        self._plan = plan
        self._context = {
            "input_type": "structured_input",
            "output_type": "markdown",
        }

    async def get_agent_plan(self, agent_type_id: Any) -> dict[str, Any] | None:
        return self._plan

    async def get_agent_context(self, agent_type_id: Any) -> dict[str, Any]:
        return self._context


@pytest.fixture(autouse=True)
def _clean(autocompile_generator_reset):
    capture._captures.clear()
    yield
    capture._captures.clear()


@pytest.fixture()
def autocompile_generator_reset():
    def _reset() -> None:
        autocompile.set_script_repair_generator(None)

    _reset()
    yield _reset
    _reset()


def _record_run_sequence() -> None:
    capture.record_tool_call(
        _SESSION, "crm____getContact", {"id": "c-1"}, {"name": "Ada", "tier": "gold"}
    )


def _plan(segment_one: str) -> dict[str, Any]:
    return {
        "plan_id": "cccccccc-0000-0000-0000-0000000000cc",
        "plan_steps": [
            {
                "step_type": "tool_invocation",
                "tool_name": "crm____getContact",
                "python_source": segment_one,
                "scriptable": True,
                "output_mode": "deterministic",
                "output_template": "{{step1_crm____getContact.name}}",
            },
        ],
    }


_GOOD_SEGMENT = (
    "def run(context, tools):\n"
    "    contact = tools.call('crm____getContact', {'id': context.get('id')})\n"
    "    return {'name': contact.get('name', '')}\n"
)

# Compiles + validates, but fails the recorded-run TEST: it calls a tool
# that was never recorded.
_BROKEN_SEGMENT = (
    "def run(context, tools):\n"
    "    contact = tools.call('crm____unknownTool', {})\n"
    "    return {'name': contact.get('name', '')}\n"
)


# ── Capability contract ───────────────────────────────────────────────────────


def test_capability_contract_describes_the_sandbox():
    contract = build_capability_contract(
        output_format="markdown",
        tool_names=["crm____getContact"],
        available_variables=["step1_crm____getContact", "id"],
    )
    # Pre-bound modules.
    assert "json" in contract and "math" in contract and "statistics" in contract
    # No import statements.
    assert "import" in contract and "NOT allowed" in contract
    # Entry point + injected variables.
    assert "run(context, tools)" in contract
    assert "context" in contract and "step{N}_{tool_name}" in contract
    # MCP tool client is injected; tools replay recorded outputs in test.
    assert "tools.call" in contract and "INJECTED" in contract
    # Output contract: result must be the final user-facing value.
    assert "result" in contract and "FINAL" in contract
    assert "markdown" in contract
    # Resource caps.
    assert "30s" in contract and "512MB" in contract and "10s" in contract
    # Recorded tools + available variables are listed.
    assert "crm____getContact" in contract
    assert "step1_crm____getContact" in contract


def test_capability_contract_resolves_auto_to_markdown():
    contract = build_capability_contract(output_format="auto")
    assert "Required output format: markdown" in contract


# ── Loop converges on the first pass ─────────────────────────────────────────


async def test_loop_passes_first_attempt_without_repair(autocompile_generator_reset):
    _record_run_sequence()
    repair_calls: list[Any] = []

    async def generator(*args: Any) -> None:
        repair_calls.append(args)
        return None

    autocompile.set_script_repair_generator(generator)
    registry = FakeScriptRegistry()

    await autocompile._run_autocompile(
        session_id=_SESSION,
        agent_type_id=_AGENT_TYPE,
        data_client=FakeDataClient(_plan(_GOOD_SEGMENT)),
        registry_client=registry,
        tool_client=object(),
    )

    assert repair_calls == [], "a passing first script must never trigger repair"
    assert len(registry.promoted) == 1
    version = registry.versions[registry.promoted[0]]
    assert version["sandbox_validation_status"] == "passed"


# ── Error-feedback repair converges on attempt 2 ──────────────────────────────


async def test_error_feedback_repair_converges_on_second_attempt(
    autocompile_generator_reset, caplog
):
    _record_run_sequence()
    registry = FakeScriptRegistry()
    feedbacks: list[tuple[str, str]] = []

    async def generator(
        contract: str, error: str, segments: dict[str, str], attempt: int
    ) -> dict[str, str]:
        feedbacks.append((error, bool(contract)))
        assert attempt == 1
        # The contract travels with every repair request.
        assert "run(context, tools)" in contract
        return {"step1_crm____getContact": _GOOD_SEGMENT}

    autocompile.set_script_repair_generator(generator)

    with caplog.at_level(logging.INFO, logger="app.agent_runtime.scripts.autocompile"):
        await autocompile._run_autocompile(
            session_id=_SESSION,
            agent_type_id=_AGENT_TYPE,
            data_client=FakeDataClient(_plan(_BROKEN_SEGMENT)),
            registry_client=registry,
            tool_client=object(),
        )

    # Exactly one failure was fed back (attempt 1), then the repaired version
    # passed on attempt 2 and was the ONLY promotion.
    assert len(feedbacks) == 1
    error, has_contract = feedbacks[0]
    assert has_contract
    assert "crm____unknownTool" in error  # humanized typed failure detail
    assert len(registry.promoted) == 1
    version = registry.versions[registry.promoted[0]]
    assert _GOOD_SEGMENT in version["python_source"]
    assert _BROKEN_SEGMENT not in version["python_source"]
    # All attempts logged humanized.
    assert any("attempt 1/3" in r.message for r in caplog.records)
    assert any("attempt 2/3" in r.message for r in caplog.records)


# ── Exhaustion: nothing promoted ──────────────────────────────────────────────


async def test_exhaustion_leaves_nothing_promoted_and_logs(
    autocompile_generator_reset, caplog
):
    _record_run_sequence()
    registry = FakeScriptRegistry()

    async def generator(
        contract: str, error: str, segments: dict[str, str], attempt: int
    ) -> dict[str, str]:
        # Repair that never converges: keeps returning the broken segment.
        return {"step1_crm____getContact": _BROKEN_SEGMENT}

    autocompile.set_script_repair_generator(generator)

    with caplog.at_level(logging.WARNING, logger="app.agent_runtime.scripts.autocompile"):
        await autocompile._run_autocompile(
            session_id=_SESSION,
            agent_type_id=_AGENT_TYPE,
            data_client=FakeDataClient(_plan(_BROKEN_SEGMENT)),
            registry_client=registry,
            tool_client=object(),
        )

    assert registry.versions == {} and registry.promoted == []
    assert any("exhausted" in r.message for r in caplog.records)
    assert any("nothing" in r.message.lower() for r in caplog.records)


async def test_exhaustion_without_generator_leaves_nothing_promoted(
    autocompile_generator_reset,
):
    _record_run_sequence()
    registry = FakeScriptRegistry()

    await autocompile._run_autocompile(
        session_id=_SESSION,
        agent_type_id=_AGENT_TYPE,
        data_client=FakeDataClient(_plan(_BROKEN_SEGMENT)),
        registry_client=registry,
        tool_client=object(),
    )

    assert registry.versions == {} and registry.promoted == []
