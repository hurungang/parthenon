"""Reproduction tests for FIX-20261020-124500.

Chain under test: a **regenerated** plan carrying the model-authored
composition (per tech-spec.md / the composition-emitting prompt in
plan_generation_service.py — sandboxed Python script segments + LLM bridge
steps) → ``autocompile._run_autocompile`` → the promoted ``ScriptVersion``.

Expected (per tech-spec.md Composition Emission + compiler-as-validator):
the auto-compiled candidate must be built from the PLAN's composition
(``compile_from_plan``), so the promoted version carries the model-authored
``python_source`` with ``sandbox_validation_status='passed'`` — not the
legacy declarative tool-sequence graph with empty ``python_source`` and
``sandbox_validation_status='pending'`` (the live defect seen on promoted
version ``d8d44c09``).

Follows the fixture patterns of ``test_autocompile.py`` (fake registry /
data clients, capture-based tool-sequence recording).
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agent_runtime.scripts import autocompile, capture
from app.agent_runtime.scripts.compiler import ScriptValidator

_AGENT_TYPE = "aaaaaaaa-0000-0000-0000-0000000000aa"
_SESSION = "bbbbbbbb-0000-0000-0000-0000000000bb"

# Model-authored sandboxed Python (contract: run(context, tools) → dict).
_SEGMENT_ONE = (
    "def run(context, tools):\n"
    "    contact = tools.call('crm____getContact', {'id': context.get('id')})\n"
    "    return {'contact': contact}\n"
)
_SEGMENT_TWO = (
    "def run(context, tools):\n"
    "    contact = context['step1_crm____getContact']['contact']\n"
    "    return {'tier': contact.get('tier', 'standard')}\n"
)

# A regenerated plan as emitted by the composition prompt: scriptable steps
# carry python_source; the LLM bridge stays model-backed; the final step
# records the output decision.
_REGENERATED_PLAN = {
    "plan_id": "cccccccc-0000-0000-0000-0000000000cc",
    "plan_steps": [
        {
            "step_type": "tool_invocation",
            "tool_name": "crm____getContact",
            "description": "Fetch the contact",
            "python_source": _SEGMENT_ONE,
            "scriptable": True,
        },
        {
            "step_type": "tool_invocation",
            "tool_name": "crm____classifyTier",
            "description": "Classify the tier locally",
            "python_source": _SEGMENT_TWO,
            "scriptable": True,
        },
        {
            "step_type": "semantic_bridge",
            "description": "Summarize the contact for the user",
            "prompt_template": "Summarize: {{step2}}",
            "scriptable": False,
            "output_mode": "deterministic",
            "output_template": "# Summary\n{{step3.semantic_bridge.summary}}",
        },
    ],
}


def _record_run_sequence() -> None:
    capture.record_tool_call(
        _SESSION, "crm____getContact", {"id": "c-1"}, {"name": "Ada", "tier": "gold"}
    )
    capture.record_tool_call(
        _SESSION, "crm____classifyTier", {"tier": "gold"}, {"tier": "gold"}
    )


class FakeScriptRegistry:
    """CC script-registry test double mirroring candidate validation.

    Like the real registry: a candidate may carry a whole-script
    ``python_source`` or a declarative graph whose script segments embed
    ``python_source``; the version's ``sandbox_validation_status`` is derived
    by running the validator over the source (pending when there is none).
    """

    def __init__(self, serving: dict[str, Any] | None = None) -> None:
        self.serving = serving
        self.versions: dict[str, dict[str, Any]] = {}
        self.promoted: list[str] = []

    async def get_serving_version(
        self, agent_type_id: str, workflow_skill_id: str | None = None
    ) -> dict[str, Any] | None:
        return self.serving

    async def submit_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        graph = payload.get("declarative_step_graph") or {}
        source = payload.get("python_source") or "\n\n".join(
            step["python_source"]
            for step in graph.get("steps", [])
            if step.get("python_source")
        )
        if source:
            result = ScriptValidator().validate(source)
            status = result.status.value
        else:
            status = "pending"
        version_id = f"version-{len(self.versions) + 1}"
        self.versions[version_id] = {
            **payload,
            "python_source": source,
            "sandbox_validation_status": status,
        }
        return {"id": version_id}

    async def promote_version(self, version_id: str) -> dict[str, Any]:
        self.promoted.append(version_id)
        return {"id": version_id, "lifecycle_status": "compiled"}


class FakeDataClient:
    def __init__(self, plan: dict[str, Any] | None) -> None:
        self._plan = plan
        self._context = {"input_type": "structured_input"}

    async def get_agent_plan(self, agent_type_id: Any) -> dict[str, Any] | None:
        return self._plan

    async def get_agent_context(self, agent_type_id: Any) -> dict[str, Any]:
        return self._context


@pytest.fixture(autouse=True)
def _clean_capture():
    capture._captures.clear()
    yield
    capture._captures.clear()


async def test_regenerated_plan_autocompiles_to_sandboxed_python_version():
    """FIX-20261020-124500: auto-compiling a regenerated plan (model-authored
    composition) must promote a version with the model's python_source and
    sandbox_validation_status='passed' — not a declarative-only graph."""
    _record_run_sequence()
    registry = FakeScriptRegistry()

    await autocompile._run_autocompile(
        session_id=_SESSION,
        agent_type_id=_AGENT_TYPE,
        data_client=FakeDataClient(_REGENERATED_PLAN),
        registry_client=registry,
        tool_client=object(),
    )

    # A candidate must actually be compiled and promoted.
    assert len(registry.promoted) == 1, (
        "auto-compile must promote a candidate for a regenerated plan with "
        f"model-authored composition; promoted={registry.promoted}, "
        f"submitted={list(registry.versions)}"
    )
    version = registry.versions[registry.promoted[0]]
    # The promoted ScriptVersion must be a sandboxed Python version...
    assert version["python_source"], (
        "promoted version has empty python_source — auto-compile produced a "
        "legacy DECLARATIVE graph instead of compiling the plan's "
        "model-authored composition (live defect on version d8d44c09)"
    )
    # ...validated for the sandbox (not stuck at 'pending').
    assert version["sandbox_validation_status"] == "passed", (
        "promoted version sandbox_validation_status="
        f"{version['sandbox_validation_status']!r}, expected 'passed'"
    )
async def test_fully_scriptable_python_source_plan_promotes_sandboxed_version():
    """Even with zero model-backed steps, a regenerated plan whose scriptable
    steps carry python_source must compile via the plan's composition — the
    recorded-tool-sequence path ignores python_source and promotes a
    declarative graph with empty python_source / pending status (live defect
    on version d8d44c09)."""
    _record_run_sequence()
    registry = FakeScriptRegistry()
    plan = {
        "plan_id": "cccccccc-0000-0000-0000-0000000000cd",
        "plan_steps": [
            {
                "step_type": "tool_invocation",
                "tool_name": "crm____getContact",
                "python_source": _SEGMENT_ONE,
                "scriptable": True,
            },
            {
                "step_type": "tool_invocation",
                "tool_name": "crm____classifyTier",
                "python_source": _SEGMENT_TWO,
                "scriptable": True,
                "output_mode": "deterministic",
                "output_template": "Tier: {{step2_crm____classifyTier.tier}}",
            },
        ],
    }

    await autocompile._run_autocompile(
        session_id=_SESSION,
        agent_type_id=_AGENT_TYPE,
        data_client=FakeDataClient(plan),
        registry_client=registry,
        tool_client=object(),
    )

    assert len(registry.promoted) == 1, (
        f"expected one promoted candidate; promoted={registry.promoted}, "
        f"submitted={list(registry.versions)}"
    )
    version = registry.versions[registry.promoted[0]]
    assert version["python_source"], (
        "promoted version has empty python_source — auto-compile compiled the "
        "recorded tool sequence into a DECLARATIVE graph instead of the plan's "
        "model-authored python_source composition"
    )
    assert version["sandbox_validation_status"] == "passed", (
        f"sandbox_validation_status={version['sandbox_validation_status']!r}, "
        "expected 'passed'"
    )
    # The graph must carry the authored script segments, not raw tool calls.
    graph = version["declarative_step_graph"]
    assert any(s.get("python_source") for s in graph["steps"]), (
        "compiled graph has no script_segment steps with python_source: "
        f"kinds={[s.get('kind') for s in graph['steps']]}"
    )


# ── The composition serves the USER's output requirement ─────────────────────


class _FakeToolClient:
    """Minimal CommHubToolClient double for executing compiled graphs."""

    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self.results = results or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name, arguments, **kwargs: Any) -> Any:
        self.calls.append((tool_name, dict(arguments or {})))
        return self.results.get(tool_name, {"ok": True})


async def test_markdown_required_plan_output_is_markdown_with_zero_llm_steps():
    """A plan authored for a markdown-required agent: the python_source
    segments assemble the markdown themselves (deterministic output_mode +
    markdown output_template). The promoted script must run with ZERO
    model-backed steps and its deterministic output IS the markdown."""
    _record_run_sequence()
    registry = FakeScriptRegistry()
    md_segment_one = (
        "def run(context, tools):\n"
        "    contact = tools.call('crm____getContact', {'id': 'c-1'})\n"
        "    return {'contact': contact}\n"
    )
    md_segment_two = (
        "def run(context, tools):\n"
        "    c = context['step1_crm____getContact']['contact']\n"
        "    md = '# Contact Report\\n\\n'\n"
        "    md += '**Name:** ' + str(c.get('name', '')) + '\\n\\n'\n"
        "    md += '**Tier:** ' + str(c.get('tier', 'standard')) + '\\n'\n"
        "    return {'report': md}\n"
    )
    plan = {
        "plan_id": "cccccccc-0000-0000-0000-0000000000ce",
        "plan_steps": [
            {
                "step_type": "tool_invocation",
                "tool_name": "crm____getContact",
                "description": "Fetch the contact",
                "python_source": md_segment_one,
                "scriptable": True,
            },
            {
                "step_type": "tool_invocation",
                "tool_name": "crm____buildReport",
                "description": "Assemble the markdown report in Python",
                "python_source": md_segment_two,
                "scriptable": True,
                "output_mode": "deterministic",
                "output_template": "{{step2_crm____buildReport.report}}",
            },
        ],
    }

    await autocompile._run_autocompile(
        session_id=_SESSION,
        agent_type_id=_AGENT_TYPE,
        data_client=FakeDataClient(plan),
        registry_client=registry,
        tool_client=object(),
    )

    assert len(registry.promoted) == 1
    version = registry.versions[registry.promoted[0]]
    graph_json = version["declarative_step_graph"]

    # Zero LLM steps: the whole composition is deterministic.
    kinds = [s.get("kind") for s in graph_json["steps"]]
    assert "semantic_bridge" not in kinds and "decision" not in kinds, kinds

    # Execute the promoted graph: the result must BE the markdown.
    from app.agent_runtime.scripts.runner import ScriptRunner
    from app.agent_runtime.scripts.schemas import StepGraph

    graph = StepGraph.model_validate(graph_json)
    client = _FakeToolClient(results={"crm____getContact": {"name": "Ada", "tier": "gold"}})
    result = await ScriptRunner(tool_client=client).execute(
        graph, session_id=_SESSION, agent_type_id=_AGENT_TYPE
    )
    assert isinstance(result, str), f"expected markdown string output, got {type(result)}"
    assert result.startswith("# Contact Report")
    assert "**Name:** Ada" in result
    assert "**Tier:** gold" in result


async def test_open_ended_plan_compiles_llm_render_step():
    """When the required output genuinely needs generative writing, the plan
    marks the final step scriptable:false with output_mode llm_render — the
    promoted graph must carry the LLM bridge step (model-backed render)."""
    _record_run_sequence()
    registry = FakeScriptRegistry()
    plan = {
        "plan_id": "cccccccc-0000-0000-0000-0000000000cf",
        "plan_steps": [
            {
                "step_type": "tool_invocation",
                "tool_name": "crm____getContact",
                "python_source": _SEGMENT_ONE,
                "scriptable": True,
            },
            {
                "step_type": "semantic_bridge",
                "description": "Write an open-ended narrative summary of the contact",
                "prompt_template": "Write a narrative summary from: {{step1_crm____getContact}}",
                "scriptable": False,
                "output_mode": "llm_render",
            },
        ],
    }

    await autocompile._run_autocompile(
        session_id=_SESSION,
        agent_type_id=_AGENT_TYPE,
        data_client=FakeDataClient(plan),
        registry_client=registry,
        tool_client=object(),
    )

    assert len(registry.promoted) == 1
    graph = registry.versions[registry.promoted[0]]["declarative_step_graph"]
    kinds = [s.get("kind") for s in graph["steps"]]
    assert "semantic_bridge" in kinds, (
        f"open-ended plan must compile an LLM render (bridge) step; kinds={kinds}"
    )
