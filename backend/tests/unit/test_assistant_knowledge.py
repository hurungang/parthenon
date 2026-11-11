"""Unit tests for the assistant knowledge corpus (Enhancement 2).

The corpus is deterministic (no LLM), tenant-agnostic platform knowledge.
"""
from __future__ import annotations

import pytest

from app.services.agents.assistant_knowledge import get_entry_count, search_knowledge


def _all_rule_text() -> str:
    from app.services.agents.assistant_knowledge import _KNOWLEDGE_ENTRIES

    return " ".join(e["rule_text"] for e in _KNOWLEDGE_ENTRIES).lower()


@pytest.mark.parametrize(
    "query,expected_fragment",
    [
        # Agent-type composition → skills-first rule
        ("how do I attach MCP tools to an agent type", "never"),
        ("agent type composition", "skill"),
        ("required skill does not exist", "created first"),
        # FIX-20261102-100704: generic principles
        ("how do I make an agent work", "complete"),
        ("what must exist before creating a skill", "prerequisite"),
        ("why can't my agent access this tool", "grant"),
        # Role/identity assignment chain
        ("how are identities assigned to roles", "many-to-many"),
        # Model availability rule
        ("model not available", "enabled"),
        ("which models can my agent use", "model config"),
        # No-delete boundary
        ("delete this skill for me", "deletion is not supported"),
        # Permission parity
        ("why was my tool call denied", "permission"),
        # Naming uniqueness
        ("name already exists", "409"),
        # MCP hub
        ("mcp server slug", "unique per tenant"),
        # Role MCP session mappings (task 4.5)
        ("why don't the MCP tools work for my agent", "mcp session"),
        ("which session should the role use on supabase", "passthrough"),
        ("mcp_session_mappings", "additive"),
        # Role permission vs agent-type visibility (corrected semantics)
        ("agent can't see an expected tool", "visibility"),
        ("router role only sees its delegated agents", "agent type"),
    ],
)
def test_relevant_rule_returned(query: str, expected_fragment: str) -> None:
    results = search_knowledge(query, top_k=5)
    assert results, f"no results for query: {query!r}"
    combined = " ".join(r["rule_text"] for r in results).lower()
    assert expected_fragment.lower() in combined, (
        f"query {query!r} did not surface a rule containing {expected_fragment!r}; "
        f"got topics {[r['topic'] for r in results]}"
    )


def test_empty_query_returns_no_results() -> None:
    assert search_knowledge("") == []
    assert search_knowledge("   ") == []


def test_top_k_caps_results() -> None:
    results = search_knowledge("skill sop agent role model tool", top_k=2)
    assert len(results) <= 2


def test_result_shape() -> None:
    for entry in search_knowledge("agent type composition"):
        assert set(entry.keys()) == {"id", "topic", "rule_text", "score"}
        assert entry["score"] > 0


def test_corpus_covers_required_topics() -> None:
    """Every knowledge entry mandated by the change spec must exist."""
    from app.services.agents.assistant_knowledge import _KNOWLEDGE_ENTRIES

    ids = {e["id"] for e in _KNOWLEDGE_ENTRIES}
    required = {
        "agent-type-composition",
        "skills-first-prerequisite",
        "role-identity-chain",
        "model-availability",
        "io-types",
        "mcp-hub-basics",
        "naming-uniqueness",
        "no-delete-boundary",
        "permission-parity",
        # FIX-20261102-100704 — generic principle entries.
        "resource-completeness",
        "prerequisite-ordering",
        "reuse-first",
        # Task 2.7 / 4.4 — SOP steps parity.
        "sop-composition",
        "sop-steps-replace-semantics",
        # SOP-only router roles (delegation + direct-grant warning guidance).
        "sop-only-router-roles",
        # SOPs must never mention/instruct direct MCP-tool calls.
        "sop-no-raw-tool-mentions",
    }
    assert required <= ids
    assert get_entry_count() >= len(required)


def test_sop_steps_knowledge_covers_authoring_contract() -> None:
    """Task 4.4: the SOP steps knowledge teaches id-or-name references, the
    replace semantics, and the ordered-step preview shape."""
    from app.services.agents.assistant_knowledge import _KNOWLEDGE_ENTRIES

    by_id = {e["id"]: e for e in _KNOWLEDGE_ENTRIES}
    text = by_id["sop-steps-replace-semantics"]["rule_text"]
    assert "skill_invocation" in text and "agent_delegation" in text
    assert "skill_id" in text and "target_agent_type_id" in text
    assert "REPLACE" in text.upper()
    assert "omitted" in text.lower() and "delet" in text.lower()
    assert "1. skill_invocation:" in text
    preview = by_id["confirmation-preview-format"]["rule_text"]
    assert "skill_invocation" in preview  # steps shown in the canonical table
    composition = by_id["sop-composition"]["rule_text"]
    assert "skill_id" in composition and "target_agent_type_id" in composition


def test_sop_no_raw_tool_mentions_knowledge() -> None:
    """SOP authoring must never instruct direct MCP-tool calls — the corpus
    entry exists, states the hard rule, and is retrievable."""
    from app.services.agents.assistant_knowledge import _KNOWLEDGE_ENTRIES

    by_id = {e["id"]: e for e in _KNOWLEDGE_ENTRIES}
    entry = by_id["sop-no-raw-tool-mentions"]
    text = entry["rule_text"]
    assert "NEVER" in text.upper()
    assert "server____tool" in text
    assert "agent_delegation" in text and "skill_invocation" in text
    assert "SKILL" in text.upper()
    # Retrieval via the documented keywords.
    for query in ("sop tool mention", "mcp tool in sop", "sop step rule"):
        results = search_knowledge(query, top_k=5)
        assert any(r["id"] == "sop-no-raw-tool-mentions" for r in results), query


def test_sop_hard_rule_in_seeder_instruction() -> None:
    """The always-on assistant instruction carries the SOP no-raw-tool hard
    rule."""
    from app.services.agents.assistant_seeder import (
        ASSISTANT_SYSTEM_INSTRUCTION,
        MANAGEMENT_SKILL_INSTRUCTIONS,
    )

    combined = (
        f"{ASSISTANT_SYSTEM_INSTRUCTION}\n{MANAGEMENT_SKILL_INSTRUCTIONS}"
    ).lower()
    assert "never mention or instruct direct mcp-tool calls" in combined
    assert "server____tool" in combined
    assert "tool visibility flows only through" in combined


def test_seeder_instruction_teaches_sop_steps() -> None:
    """Task 4.4: the always-on assistant instruction covers the steps replace
    semantics and the ordered-step preview rows."""
    from app.services.agents.assistant_seeder import (
        ASSISTANT_SYSTEM_INSTRUCTION,
        MANAGEMENT_SKILL_INSTRUCTIONS,
    )

    combined = f"{ASSISTANT_SYSTEM_INSTRUCTION}\n{MANAGEMENT_SKILL_INSTRUCTIONS}"
    assert "REPLACES" in combined
    assert "skill_invocation" in combined and "agent_delegation" in combined
    assert "1. skill_invocation:" in combined
    assert "omitted steps are deleted" in combined


def test_role_permission_vs_agent_visibility_knowledge_and_seeder_guidance() -> None:
    """Corrected semantics: the knowledge corpus and seeder teach that a role
    controls PERMISSION only and the agent TYPE controls VISIBILITY (own
    SOP/skill bindings as a subset of the role grants); extra role grants not
    agent-type-associated are correctly invisible — never a warning."""
    from app.services.agents.assistant_knowledge import _KNOWLEDGE_ENTRIES
    from app.services.agents.assistant_seeder import (
        ASSISTANT_SYSTEM_INSTRUCTION,
        MANAGEMENT_SKILL_INSTRUCTIONS,
    )

    by_id = {e["id"]: e for e in _KNOWLEDGE_ENTRIES}
    text = by_id["sop-only-router-roles"]["rule_text"]
    assert "agent_delegation" in text
    assert "PERMISSION" in text.upper()
    assert "VISIBILITY" in text.upper()
    assert "SUBSET" in text.upper()
    # The wrong-model guidance must be gone.
    assert "unions" not in text.lower()
    assert "SOP-ONLY ROUTER RULE:" not in text

    combined = f"{ASSISTANT_SYSTEM_INSTRUCTION}\n{MANAGEMENT_SKILL_INSTRUCTIONS}"
    assert "ROLE-PERMISSION vs AGENT-VISIBILITY MODEL" in combined
    assert "associate the SOP/skill" in combined
    # Wrong-model phrases must be gone from the seeder too.
    assert "SOP-ONLY ROUTER RULE" not in combined
    assert "delegation steps AND direct skill grants" not in combined


def test_role_session_knowledge_never_pass_passthrough_as_session_name() -> None:
    """FIX (role→MCP-session mapping): the knowledge and seeder explicitly teach
    that 'passthrough' is an auth TYPE, never a session name."""
    from app.services.agents.assistant_knowledge import _KNOWLEDGE_ENTRIES
    from app.services.agents.assistant_seeder import (
        ASSISTANT_SYSTEM_INSTRUCTION,
        MANAGEMENT_SKILL_INSTRUCTIONS,
    )

    by_id = {e["id"]: e for e in _KNOWLEDGE_ENTRIES}
    text = by_id["role-mcp-session-mappings"]["rule_text"]
    lowered = text.lower()
    assert "never pass" in lowered and "session: 'passthrough'" in lowered
    assert "auth type" in lowered
    # Explicit mappings are for external credential sessions; passthrough-auth
    # servers need no explicit mapping.
    assert "'supabase', session: 'harry'" in text
    assert "no explicit mapping" in lowered

    combined = f"{ASSISTANT_SYSTEM_INSTRUCTION}\n{MANAGEMENT_SKILL_INSTRUCTIONS}"
    assert "NEVER" in combined and "session: 'passthrough'" in combined


def test_corpus_entries_are_principles_or_facts() -> None:
    """FIX-20261102-100704: no entry is a case-scripted workflow."""
    from app.services.agents.assistant_knowledge import _KNOWLEDGE_ENTRIES

    for entry in _KNOWLEDGE_ENTRIES:
        text = entry["rule_text"].lower()
        for phrase in ("sequence: (1)", "create skill first, then", "step 1"):
            assert phrase not in text, entry["id"]


def test_corpus_is_platform_knowledge_only() -> None:
    """No tenant-shaped data may appear in the corpus (tenant isolation)."""
    text = _all_rule_text()
    for forbidden in ("password", "api_key", "token=", "secret"):
        assert forbidden not in text
