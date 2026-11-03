"""FIX-20261102-100704 — assistant knowledge/instruction must be GENERIC.

The user requirement: "the fix is generic, not specific for this use case where
we need to create skill first, then assign access then create agent. The
instruction should be generic so the LLM can make right decisions."

So the knowledge corpus must be PRINCIPLES + REFERENCE FACTS (no imperative
case scripts), and the always-on instruction must not encode a fixed sequence
of operations while still carrying the accurate platform facts.
"""
from __future__ import annotations

import pytest

from app.services.agents.assistant_knowledge import (
    _KNOWLEDGE_ENTRIES,
    get_entry_count,
    search_knowledge,
)
from app.services.agents.assistant_seeder import (
    ASSISTANT_SYSTEM_INSTRUCTION,
    MANAGEMENT_SKILL_INSTRUCTIONS,
)

# ── Principle entries exist and are retrievable ─────────────────────────────


def test_generic_principle_entries_exist() -> None:
    ids = {e["id"] for e in _KNOWLEDGE_ENTRIES}
    assert {"resource-completeness", "prerequisite-ordering"} <= ids
    assert get_entry_count() >= 20


@pytest.mark.parametrize(
    "query,entry_id",
    [
        # "How do I make an agent work" → completeness principle / agent facts
        ("how do I make an agent work", "resource-completeness"),
        ("why is my agent not working", "resource-completeness"),
        # "What must exist before creating X" → prerequisite ordering
        ("what must exist before creating a skill", "prerequisite-ordering"),
        ("what has to exist before I create an agent type", "prerequisite-ordering"),
        # Pre-existing facts still retrievable
        ("what does an agent need to work", "agent-creation-completeness"),
        ("why can't my agent access this tool", "role-grant-workflow"),
    ],
)
def test_principle_retrieval(query: str, entry_id: str) -> None:
    results = search_knowledge(query, top_k=5)
    ids = [r["id"] for r in results]
    assert entry_id in ids, f"query {query!r} → {ids}"


def test_completeness_entry_is_a_principle_not_a_script() -> None:
    entry = next(
        e for e in _KNOWLEDGE_ENTRIES if e["id"] == "resource-completeness"
    )
    text = entry["rule_text"].lower()
    topic = entry["topic"].lower()
    # States the principle generically across resource types.
    assert "every resource" in text or "every resource type" in text
    assert "complete" in text and "functional" in text
    assert "principle" in topic
    # Derived, not a hardcoded create-skill-first recipe.
    assert "create skill first" not in text
    assert "then create agent" not in text


def test_prerequisite_entry_is_a_principle_not_a_script() -> None:
    entry = next(
        e for e in _KNOWLEDGE_ENTRIES if e["id"] == "prerequisite-ordering"
    )
    text = entry["rule_text"].lower()
    assert "principle" in entry["topic"].lower()
    assert "derive" in text
    assert "dependency" in text
    # No fixed global sequence.
    assert "create skill first, then" not in text
    assert "sequence:" not in text


# ── Corpus carries no imperative case scripts ───────────────────────────────


FORBIDDEN_SCRIPT_PHRASES = (
    "sequence: (1)",
    "first create the skill",
    "create skill first, then",
    "then create the agent",
    "step 1: create",
)


@pytest.mark.parametrize("entry", _KNOWLEDGE_ENTRIES, ids=lambda e: e["id"])
def test_no_entry_encodes_a_fixed_sequence(entry) -> None:
    text = entry["rule_text"].lower()
    for phrase in FORBIDDEN_SCRIPT_PHRASES:
        assert phrase not in text, f"{entry['id']} encodes a fixed sequence: {phrase!r}"


# ── Instruction: generic principles, fixed sequence removed ─────────────────


def test_instruction_has_generic_principles() -> None:
    text = ASSISTANT_SYSTEM_INSTRUCTION
    lowered = text.lower()
    for marker in (
        "completeness principle",
        "prerequisite ordering",
        "grant at the right level",
        "reuse-first",
        "derive",
    ):
        assert marker in lowered, f"instruction missing generic principle {marker!r}"


def test_instruction_has_discovery_pointers() -> None:
    text = ASSISTANT_SYSTEM_INSTRUCTION
    for tool in (
        "list_management_tools",
        "get_mcp_server",
        "search_assistant_knowledge",
        "get_management_tool_schema",
    ):
        assert tool in text, f"instruction missing discovery pointer {tool!r}"


@pytest.mark.parametrize(
    "fixed_sequence",
    [
        "create the skill first",
        "first discover the tool",
        "sequence: (1)",
        "step 1",
    ],
)
def test_instruction_no_longer_scripts_the_sequence(fixed_sequence: str) -> None:
    assert fixed_sequence not in ASSISTANT_SYSTEM_INSTRUCTION.lower()


def test_instruction_keeps_key_platform_facts() -> None:
    """Facts stay accurate — they are reference facts, not a workflow."""
    text = ASSISTANT_SYSTEM_INSTRUCTION
    lowered = text.lower()
    for fact in (
        "never raw mcp tools",
        "model config",
        "enabled models",
        "conversational",
        "unique per tenant",
        "cc____",
        "system____",
        "non-functional",
        "human_intervene",
        "| field | value |",
    ):
        assert fact in lowered, f"instruction lost reference fact {fact!r}"


def test_management_skill_digest_is_generic_and_complete() -> None:
    text = MANAGEMENT_SKILL_INSTRUCTIONS
    lowered = text.lower()
    assert "principle" in lowered
    # Facts stay.
    for fact in (
        "skills wrap mcp tools",
        "roles grant skills",
        "agent types bind skills/sops",
        "model config",
        "human_intervene",
        "| field | value |",
    ):
        assert fact in lowered, f"digest lost reference fact {fact!r}"
    # No scripted sequence.
    assert "create skill first" not in lowered
    assert "composition chain:" not in lowered
