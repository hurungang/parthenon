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
    }
    assert required <= ids
    assert get_entry_count() >= len(required)


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
