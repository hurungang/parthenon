"""Unit tests for TopologyBuilderService.

Covers:
- All four node types (role, sop, skill, tool) rendered
- Edges encode correct relationships
- Node IDs are deterministic (same graph → same IDs)
- Empty graph → empty nodes/edges (no error)
- Duplicate tools de-duplicated to one node; both skill→tool edges present
"""
from __future__ import annotations

import uuid

import pytest

from app.services.agents.topology_builder_service import TopologyBuilderService


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_role(role_id: str | None = None, name: str = "Test Role") -> dict:
    return {"id": role_id or str(uuid.uuid4()), "name": name, "description": "A test role"}


def _make_sop(sop_id: str | None = None, name: str = "Test SOP") -> dict:
    return {"id": sop_id or str(uuid.uuid4()), "name": name, "description": None}


def _make_skill(
    skill_id: str | None = None,
    name: str = "Test Skill",
    sop_ids: list[str] | None = None,
) -> dict:
    return {
        "id": skill_id or str(uuid.uuid4()),
        "name": name,
        "description": None,
        "sop_ids": sop_ids or [],
    }


def _make_tool(name: str, skill_id: str) -> dict:
    return {"name": name, "description": f"{name} description", "skill_id": skill_id}


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestTopologyBuilderService:
    """Tests for TopologyBuilderService.build_topology."""

    def setup_method(self):
        self.service = TopologyBuilderService()

    def test_empty_graph_returns_empty_nodes_and_edges(self):
        """Empty graph (no role) → empty nodes and edges list, no error."""
        graph = {"role": None, "sops": [], "skills": [], "tools": []}
        result = self.service.build_topology(graph)
        assert result == {"nodes": [], "edges": []}

    def test_all_four_node_types_rendered(self):
        """Graph with role, sop, skill, tool → all four node types present."""
        role_id = str(uuid.uuid4())
        sop_id = str(uuid.uuid4())
        skill_id = str(uuid.uuid4())

        graph = {
            "role": _make_role(role_id),
            "sops": [_make_sop(sop_id, "My SOP")],
            "skills": [_make_skill(skill_id, "My Skill", sop_ids=[sop_id])],
            "tools": [_make_tool("my_tool", skill_id)],
        }
        result = self.service.build_topology(graph)

        node_types = {n["type"] for n in result["nodes"]}
        assert "role" in node_types
        assert "sop" in node_types
        assert "skill" in node_types
        assert "tool" in node_types

    def test_node_count_matches_graph_dimensions(self):
        """1 role + 2 SOPs + 3 skills + 5 tools → 11 nodes total."""
        role_id = str(uuid.uuid4())
        sop_ids = [str(uuid.uuid4()) for _ in range(2)]
        skill_ids = [str(uuid.uuid4()) for _ in range(3)]

        sops = [_make_sop(sid, f"SOP {i}") for i, sid in enumerate(sop_ids)]
        skills = [
            _make_skill(kid, f"Skill {i}", sop_ids=[sop_ids[i % 2]])
            for i, kid in enumerate(skill_ids)
        ]
        tools = [_make_tool(f"tool_{i}", skill_ids[i % 3]) for i in range(5)]

        graph = {
            "role": _make_role(role_id),
            "sops": sops,
            "skills": skills,
            "tools": tools,
        }
        result = self.service.build_topology(graph)

        assert len([n for n in result["nodes"] if n["type"] == "role"]) == 1
        assert len([n for n in result["nodes"] if n["type"] == "sop"]) == 2
        assert len([n for n in result["nodes"] if n["type"] == "skill"]) == 3
        assert len([n for n in result["nodes"] if n["type"] == "tool"]) == 5
        assert len(result["nodes"]) == 11

    def test_role_to_sop_edges_present(self):
        """Each SOP gets a role→sop edge."""
        role_id = str(uuid.uuid4())
        sop_id_1 = str(uuid.uuid4())
        sop_id_2 = str(uuid.uuid4())

        graph = {
            "role": _make_role(role_id),
            "sops": [_make_sop(sop_id_1, "SOP 1"), _make_sop(sop_id_2, "SOP 2")],
            "skills": [],
            "tools": [],
        }
        result = self.service.build_topology(graph)

        role_node_id = f"role:{role_id}"
        sop_edges = [e for e in result["edges"] if e["source"] == role_node_id]
        assert len(sop_edges) == 2
        targets = {e["target"] for e in sop_edges}
        assert f"sop:{sop_id_1}" in targets
        assert f"sop:{sop_id_2}" in targets

    def test_sop_to_skill_edges_via_sop_ids(self):
        """Skills with sop_ids get sop→skill edges."""
        role_id = str(uuid.uuid4())
        sop_id = str(uuid.uuid4())
        skill_id = str(uuid.uuid4())

        graph = {
            "role": _make_role(role_id),
            "sops": [_make_sop(sop_id, "SOP")],
            "skills": [_make_skill(skill_id, "Skill", sop_ids=[sop_id])],
            "tools": [],
        }
        result = self.service.build_topology(graph)

        sop_skill_edges = [
            e for e in result["edges"]
            if e["source"] == f"sop:{sop_id}" and e["target"] == f"skill:{skill_id}"
        ]
        assert len(sop_skill_edges) == 1

    def test_directly_assigned_skill_links_to_role(self):
        """Skill with empty sop_ids (directly assigned) gets a role→skill edge."""
        role_id = str(uuid.uuid4())
        skill_id = str(uuid.uuid4())

        graph = {
            "role": _make_role(role_id),
            "sops": [],
            "skills": [_make_skill(skill_id, "Direct Skill", sop_ids=[])],
            "tools": [],
        }
        result = self.service.build_topology(graph)

        role_skill_edge = [
            e for e in result["edges"]
            if e["source"] == f"role:{role_id}" and e["target"] == f"skill:{skill_id}"
        ]
        assert len(role_skill_edge) == 1
        assert role_skill_edge[0]["label"] == "uses skill"

    def test_skill_to_tool_edges_present(self):
        """Each tool gets a skill→tool edge."""
        role_id = str(uuid.uuid4())
        skill_id = str(uuid.uuid4())

        graph = {
            "role": _make_role(role_id),
            "sops": [],
            "skills": [_make_skill(skill_id, "Skill", sop_ids=[])],
            "tools": [_make_tool("tool_a", skill_id), _make_tool("tool_b", skill_id)],
        }
        result = self.service.build_topology(graph)

        tool_edges = [e for e in result["edges"] if e["source"] == f"skill:{skill_id}"]
        assert len(tool_edges) == 2
        targets = {e["target"] for e in tool_edges}
        assert "tool:tool_a" in targets
        assert "tool:tool_b" in targets

    def test_node_ids_are_deterministic(self):
        """Same graph inputs produce identical node IDs on two calls."""
        role_id = str(uuid.uuid4())
        sop_id = str(uuid.uuid4())
        skill_id = str(uuid.uuid4())

        graph = {
            "role": _make_role(role_id),
            "sops": [_make_sop(sop_id)],
            "skills": [_make_skill(skill_id, sop_ids=[sop_id])],
            "tools": [_make_tool("my_tool", skill_id)],
        }

        result_1 = self.service.build_topology(graph)
        result_2 = self.service.build_topology(graph)

        ids_1 = {n["id"] for n in result_1["nodes"]}
        ids_2 = {n["id"] for n in result_2["nodes"]}
        assert ids_1 == ids_2

    def test_duplicate_tool_produces_one_node_and_two_edges(self):
        """Tool appearing via two skills → exactly one tool node, two skill→tool edges."""
        role_id = str(uuid.uuid4())
        skill_id_1 = str(uuid.uuid4())
        skill_id_2 = str(uuid.uuid4())

        graph = {
            "role": _make_role(role_id),
            "sops": [],
            "skills": [
                _make_skill(skill_id_1, "Skill A", sop_ids=[]),
                _make_skill(skill_id_2, "Skill B", sop_ids=[]),
            ],
            "tools": [
                _make_tool("shared_tool", skill_id_1),
                _make_tool("shared_tool", skill_id_2),  # same name → deduplicated
            ],
        }

        result = self.service.build_topology(graph)

        tool_nodes = [n for n in result["nodes"] if n["type"] == "tool"]
        assert len(tool_nodes) == 1, "Duplicate tool must produce exactly one node"
        assert tool_nodes[0]["id"] == "tool:shared_tool"

        tool_edges = [e for e in result["edges"] if e["target"] == "tool:shared_tool"]
        assert len(tool_edges) == 2, "Both skills must have an edge to the shared tool"

    def test_node_labels_match_names(self):
        """Node labels equal the entity names from the graph."""
        role_id = str(uuid.uuid4())
        sop_id = str(uuid.uuid4())
        skill_id = str(uuid.uuid4())

        graph = {
            "role": {"id": role_id, "name": "My Role", "description": None},
            "sops": [{"id": sop_id, "name": "My SOP", "description": None}],
            "skills": [{"id": skill_id, "name": "My Skill", "description": None, "sop_ids": []}],
            "tools": [{"name": "my_tool", "description": None, "skill_id": skill_id}],
        }

        result = self.service.build_topology(graph)

        label_map = {n["id"]: n["label"] for n in result["nodes"]}
        assert label_map[f"role:{role_id}"] == "My Role"
        assert label_map[f"sop:{sop_id}"] == "My SOP"
        assert label_map[f"skill:{skill_id}"] == "My Skill"
        assert label_map["tool:my_tool"] == "my_tool"

    def test_role_only_graph(self):
        """Graph with only a role produces one role node and no edges."""
        role_id = str(uuid.uuid4())
        graph = {"role": _make_role(role_id), "sops": [], "skills": [], "tools": []}
        result = self.service.build_topology(graph)
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["type"] == "role"
        assert result["edges"] == []

    def test_extra_fields_on_nodes_do_not_cause_errors(self):
        """Graph entries with unknown extra fields are handled gracefully."""
        role_id = str(uuid.uuid4())
        graph = {
            "role": {"id": role_id, "name": "Role", "description": None, "extra_field": "ignored"},
            "sops": [],
            "skills": [],
            "tools": [],
        }
        result = self.service.build_topology(graph)
        assert len(result["nodes"]) == 1

    # ── MCP Session Edge Label Tests ───────────────────────────────────────────

    def test_edge_label_shows_session_name_when_session_configured(self):
        """When tool has session_name, edge label shows 'via {session_name}'."""
        skill_id = str(uuid.uuid4())
        graph = {
            "role": _make_role(),
            "sops": [],
            "skills": [_make_skill(skill_id, "TestSkill", sop_ids=[])],
            "tools": [
                {
                    "name": "supabase/query",
                    "description": "Query database",
                    "skill_id": skill_id,
                    "session_name": "harry",
                    "auth_type": "api_key",
                }
            ],
        }

        result = self.service.build_topology(graph)

        skill_tool_edges = [
            e for e in result["edges"]
            if e["source"] == f"skill:{skill_id}" and e["target"] == "tool:supabase/query"
        ]
        assert len(skill_tool_edges) == 1
        assert skill_tool_edges[0]["label"] == "via harry"

    def test_edge_label_shows_agent_identity_for_passthrough(self):
        """When tool has passthrough auth (no session_name), edge label shows 'via agent identity'."""
        skill_id = str(uuid.uuid4())
        graph = {
            "role": _make_role(),
            "sops": [],
            "skills": [_make_skill(skill_id, "TestSkill", sop_ids=[])],
            "tools": [
                {
                    "name": "search/web",
                    "description": "Web search",
                    "skill_id": skill_id,
                    "auth_type": "passthrough",
                }
            ],
        }

        result = self.service.build_topology(graph)

        skill_tool_edges = [
            e for e in result["edges"]
            if e["source"] == f"skill:{skill_id}" and e["target"] == "tool:search/web"
        ]
        assert len(skill_tool_edges) == 1
        assert skill_tool_edges[0]["label"] == "via agent identity"

    def test_edge_label_shows_calls_for_platform_tools(self):
        """When tool has no session_name and no auth_type, edge label shows 'calls'."""
        skill_id = str(uuid.uuid4())
        graph = {
            "role": _make_role(),
            "sops": [],
            "skills": [_make_skill(skill_id, "TestSkill", sop_ids=[])],
            "tools": [
                {
                    "name": "platform/calculator",
                    "description": "Built-in calculator",
                    "skill_id": skill_id,
                }
            ],
        }

        result = self.service.build_topology(graph)

        skill_tool_edges = [
            e for e in result["edges"]
            if e["source"] == f"skill:{skill_id}" and e["target"] == "tool:platform/calculator"
        ]
        assert len(skill_tool_edges) == 1
        assert skill_tool_edges[0]["label"] == "calls"

    def test_multiple_tools_different_sessions(self):
        """Multiple tools with different session configs each get the correct edge label."""
        skill_id = str(uuid.uuid4())
        graph = {
            "role": _make_role(),
            "sops": [],
            "skills": [_make_skill(skill_id, "MultiSkill", sop_ids=[])],
            "tools": [
                {
                    "name": "db/query",
                    "description": "DB query",
                    "skill_id": skill_id,
                    "session_name": "dev-db",
                    "auth_type": "api_key",
                },
                {
                    "name": "api/call",
                    "description": "API call",
                    "skill_id": skill_id,
                    "session_name": "prod-api",
                    "auth_type": "oauth",
                },
                {
                    "name": "search/semantic",
                    "description": "Semantic search",
                    "skill_id": skill_id,
                    "auth_type": "passthrough",
                },
                {
                    "name": "platform/clock",
                    "description": "Platform clock",
                    "skill_id": skill_id,
                },
            ],
        }

        result = self.service.build_topology(graph)

        def _edge_label(tool_name: str) -> str:
            matches = [
                e for e in result["edges"]
                if e["source"] == f"skill:{skill_id}" and e["target"] == f"tool:{tool_name}"
            ]
            assert len(matches) == 1, f"Expected one edge for {tool_name}, got {len(matches)}"
            return matches[0]["label"]

        assert _edge_label("db/query") == "via dev-db"
        assert _edge_label("api/call") == "via prod-api"
        assert _edge_label("search/semantic") == "via agent identity"
        assert _edge_label("platform/clock") == "calls"
