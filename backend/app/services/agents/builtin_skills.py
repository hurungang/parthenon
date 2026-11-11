"""Built-in inherent skills (FIX-20261101-120618 Work Item 2).

Every agent must know its own context and be able to optimise its own work
WITHOUT user configuration and WITHOUT per-agent ``AgentTypeSkillBinding``
rows.  This module defines the small registry-derived set of INHERENT
skills that ``GET /internal/data/agent-context`` injects dynamically into
every agent's execution context (both the role'd and role-less branches).

Properties:
  - Zero configuration: nothing to seed, nothing for a user to grant.
  - Idempotent + cheap: definitions derive from ``SystemToolRegistry`` at
    request time — no database rows are created.
  - Canonical names: all inherent tools are ``general``-category system
    tools, so they surface as ``system____<name>`` (per the FIX-000319
    scope decision — general-agent utilities, not management wrappers).
  - No confirmation/HITL: these are system tools, not management wrapper
    calls; ``execute_script`` remains AR-sandboxed per config conventions.
  - The RuntimeGuardrailState iteration budget still applies to every call.

The skills are documented via their descriptions (surfaced through tool
schemas and the skills summary) so agents discover them in their context.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.services.agents.system_tool_registry import SystemToolRegistry


@dataclass(frozen=True)
class InherentSkillDefinition:
    """A built-in skill granted to every agent by default."""

    name: str
    description: str
    tool_names: tuple[str, ...]


#: Deterministic skill ids (uuid5, stable across processes and tenants).
_INHERENT_SKILL_NAMESPACE = uuid.UUID("00000000-0000-0000-0000-000000001206")

#: Registry-derived inherent skill set.  Order matters for display only.
INHERENT_SKILL_DEFINITIONS: tuple[InherentSkillDefinition, ...] = (
    InherentSkillDefinition(
        name="self-context",
        description=(
            "Built-in skill (granted to every agent automatically): read your "
            "own implementation plan (get_implementation_plan / "
            "get_optimized_implementation_plan), your authored script "
            "definitions (get_scripts) and your recent execution history "
            "(get_execution_log) to understand and reflect on your work."
        ),
        tool_names=(
            "get_implementation_plan",
            "get_optimized_implementation_plan",
            "get_scripts",
            "get_execution_log",
        ),
    ),
    InherentSkillDefinition(
        name="workflow-optimization",
        description=(
            "Built-in skill (granted to every agent automatically): optimise "
            "your own workflow via the Optimize & Verify loop — author "
            "optimized plans (generate_optimized_plan), write sandbox-"
            "validated scripts (generate_script), verify them by real sandbox "
            "execution (execute_script), and inspect existing scripts "
            "(list_scripts / get_script) for reuse or repair.  Use the "
            "self-context tools to review the current state first."
        ),
        tool_names=(
            "generate_optimized_plan",
            "generate_script",
            "execute_script",
            "list_scripts",
            "get_script",
            "get_implementation_plan",
            "get_optimized_implementation_plan",
            "get_scripts",
        ),
    ),
)

#: Names of the inherent skills, in display order.
INHERENT_SKILL_NAMES: tuple[str, ...] = tuple(
    definition.name for definition in INHERENT_SKILL_DEFINITIONS
)

#: Skill name of the gated inherent skill.
WORKFLOW_OPTIMIZATION_SKILL_NAME = "workflow-optimization"
SELF_CONTEXT_SKILL_NAME = "self-context"

#: Bare tool names of the workflow-optimization AUTHORING tools — these load
#: ONLY on user-confirmed optimization runs (opt-in dialog → optimize-and-verify
#: command).  ``execute_script`` is intentionally NOT here: it is the inherent
#: iteration-saver and stays available on every run by design.
WORKFLOW_OPTIMIZATION_AUTHORING_TOOLS: frozenset[str] = frozenset({
    "generate_optimized_plan",
    "generate_script",
    "list_scripts",
    "get_script",
})


def get_inherent_skill_definitions() -> tuple[InherentSkillDefinition, ...]:
    """Return the built-in inherent skill definitions (registry-derived)."""
    return INHERENT_SKILL_DEFINITIONS


def get_inherent_tool_names() -> frozenset[str]:
    """Union of the inherent tools' bare names, validated against the registry.

    Raises ``RuntimeError`` if a configured inherent tool is not registered —
    this keeps the inherent set in lock-step with ``SystemToolRegistry``.
    """
    names: set[str] = set()
    for definition in INHERENT_SKILL_DEFINITIONS:
        names.update(definition.tool_names)
    unknown = names - SystemToolRegistry.get_names()
    if unknown:
        raise RuntimeError(
            f"Inherent skill tools not registered in SystemToolRegistry: "
            f"{sorted(unknown)}"
        )
    return frozenset(names)


def get_inherent_tool_names_for(optimization_enabled: bool) -> frozenset[str]:
    """Inherent bare tool names for a run, gated on user-confirmed optimization.

    When ``optimization_enabled`` is ``False`` (the default for every run that
    did not go through the opt-in optimize dialog — including conversational
    sessions), the workflow-optimization AUTHORING tools are excluded while
    ``execute_script`` and all self-context tools remain (iteration-saver by
    design).
    """
    if optimization_enabled:
        return get_inherent_tool_names()
    return get_inherent_tool_names() - WORKFLOW_OPTIMIZATION_AUTHORING_TOOLS


def get_inherent_skill_summaries_for(
    optimization_enabled: bool,
) -> list[tuple[uuid.UUID, str]]:
    """Inherent ``(skill_id, skill_name)`` summaries, gated on optimization.

    Mirrors :func:`get_inherent_skill_summaries` but omits the
    ``workflow-optimization`` skill when the run is not a user-confirmed
    optimization run.
    """
    return [
        (skill_id, name)
        for skill_id, name in get_inherent_skill_summaries()
        if optimization_enabled or name != WORKFLOW_OPTIMIZATION_SKILL_NAME
    ]


def get_inherent_skill_summaries() -> list[tuple[uuid.UUID, str]]:
    """Return ``[(skill_id, skill_name)]`` for the context skills summary.

    Ids are deterministic uuid5 values (never database ids — the skills are
    not rows in the ``skills`` table).
    """
    return [
        (
            uuid.uuid5(_INHERENT_SKILL_NAMESPACE, definition.name),
            definition.name,
        )
        for definition in INHERENT_SKILL_DEFINITIONS
    ]


def get_inherent_canonical_tool_names() -> frozenset[str]:
    """Canonical ``system____<bare>`` names of the inherent tools.

    All inherent tools are ``general``-category, so the canonical server
    slug is ``system`` (asserted for safety in case a future entry is
    mis-categorised).
    """
    canonical: set[str] = set()
    for bare in get_inherent_tool_names():
        tool = SystemToolRegistry.get(bare)
        assert tool is not None and tool.server_slug == "system", bare
        canonical.add(f"system____{bare}")
    return frozenset(canonical)


def get_inherent_canonical_tool_names_for(
    optimization_enabled: bool,
) -> frozenset[str]:
    """Canonical ``system____<bare>`` names, gated on optimization runs.

    Gated (``optimization_enabled=False``) set excludes the workflow-
    optimization AUTHORING tools but keeps ``execute_script`` and the
    self-context tools (see :func:`get_inherent_tool_names_for`).
    """
    canonical: set[str] = set()
    for bare in get_inherent_tool_names_for(optimization_enabled):
        tool = SystemToolRegistry.get(bare)
        assert tool is not None and tool.server_slug == "system", bare
        canonical.add(f"system____{bare}")
    return frozenset(canonical)
