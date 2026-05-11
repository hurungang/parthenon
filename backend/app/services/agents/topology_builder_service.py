"""TopologyBuilderService — converts role→SOP→Skill→Tool graph into node-edge topology."""
import logging
from typing import Any

from opentelemetry import trace

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class TopologyBuilderService:
    """
    Converts the resolved role→SOP→Skill→Tool graph into a serialisable
    node-edge topology dict for frontend diagram rendering.

    Assigns deterministic node IDs (agent:<uuid>, identity:<uuid>, role:<uuid>,
    sop:<uuid>, skill:<uuid>, tool:<name>) so the frontend can render a consistent
    diagram across re-generations.
    """

    def build_topology(self, graph: dict[str, Any]) -> dict[str, Any]:
        """
        Build a topology dict from the resolved graph.

        Args:
            graph: Dict with keys:
                - agent: {"id": str, "name": str, "description": str|None} (optional)
                - identity: {"id": str, "name": str} | None (optional)
                - role: {"id": str, "name": str, "description": str|None}
                - sops: [{"id": str, "name": str, "description": str|None, "skill_ids": list[str]}]
                - skills: [{"id": str, "name": str, "description": str|None, "sop_ids": list[str]}]
                - tools: [{"name": str, "description": str|None, "skill_id": str}]

        Returns:
            Dict with keys:
                - nodes: [{"id": str, "type": str, "label": str, "meta": dict|None, "usage": str|None}]
                - edges: [{"source": str, "target": str, "label": str|None, "style": str|None}]
        """
        with tracer.start_as_current_span("topology_builder.build_topology") as span:
            nodes: list[dict[str, Any]] = []
            edges: list[dict[str, Any]] = []

            agent = graph.get("agent")
            identity = graph.get("identity")
            role = graph.get("role")
            sops: list[dict[str, Any]] = graph.get("sops", [])
            skills: list[dict[str, Any]] = graph.get("skills", [])
            tools: list[dict[str, Any]] = graph.get("tools", [])

            # Agent node (the top-level AI agent type)
            agent_node_id: str | None = None
            if agent:
                agent_node_id = f"agent:{agent['id']}"
                nodes.append({
                    "id": agent_node_id,
                    "type": "agent",
                    "label": agent["name"],
                    "meta": {"description": agent.get("description")},
                })

            # Identity node (OIDC credentials for the agent)
            if identity and agent_node_id:
                identity_node_id = f"identity:{identity['id']}"
                nodes.append({
                    "id": identity_node_id,
                    "type": "identity",
                    "label": identity["name"],
                    "meta": {},
                })
                edges.append({
                    "source": agent_node_id,
                    "target": identity_node_id,
                    "label": "runs as",
                })

            if not role:
                span.set_attribute("node_count", len(nodes))
                span.set_attribute("edge_count", len(edges))
                return {"nodes": nodes, "edges": edges}

            # Role node
            role_node_id = f"role:{role['id']}"
            nodes.append({
                "id": role_node_id,
                "type": "role",
                "label": role["name"],
                "meta": {"description": role.get("description")},
            })

            # Edge: agent → role
            if agent_node_id:
                edges.append({
                    "source": agent_node_id,
                    "target": role_node_id,
                    "label": "has role",
                })

            # SOP nodes and role→SOP edges
            sop_node_ids: dict[str, str] = {}  # sop_id -> node_id
            for sop in sops:
                sop_node_id = f"sop:{sop['id']}"
                sop_node_ids[sop["id"]] = sop_node_id
                nodes.append({
                    "id": sop_node_id,
                    "type": "sop",
                    "label": sop["name"],
                    "meta": {"description": sop.get("description")},
                })
                edges.append({
                    "source": role_node_id,
                    "target": sop_node_id,
                    "label": "uses SOP",
                })

            # Skill nodes and edges
            # Skills referenced by SOP steps are "used"; skills only directly assigned are "unused"
            skill_node_ids: dict[str, str] = {}  # skill_id -> node_id
            for skill in skills:
                skill_node_id = f"skill:{skill['id']}"
                skill_node_ids[skill["id"]] = skill_node_id
                parent_sop_ids: list[str] = skill.get("sop_ids", [])
                usage = "used" if parent_sop_ids else "unused"
                nodes.append({
                    "id": skill_node_id,
                    "type": "skill",
                    "label": skill["name"],
                    "meta": {"description": skill.get("description")},
                    "usage": usage,
                })
                if parent_sop_ids:
                    # Skill is invoked by one or more SOPs
                    for parent_sop_id in parent_sop_ids:
                        parent_sop_node_id = sop_node_ids.get(parent_sop_id)
                        if parent_sop_node_id:
                            edges.append({
                                "source": parent_sop_node_id,
                                "target": skill_node_id,
                                "label": "invokes",
                            })
                else:
                    # Directly assigned to role (unused by any SOP) — dashed edge
                    edges.append({
                        "source": role_node_id,
                        "target": skill_node_id,
                        "label": "uses skill",
                        "style": "dashed",
                    })

            # Tool nodes and skill→tool edges
            seen_tool_ids: set[str] = set()
            for tool in tools:
                tool_node_id = f"tool:{tool['name']}"
                if tool_node_id not in seen_tool_ids:
                    seen_tool_ids.add(tool_node_id)
                    nodes.append({
                        "id": tool_node_id,
                        "type": "tool",
                        "label": tool["name"],
                        "meta": {"description": tool.get("description")},
                    })
                # Create skill→tool edge
                skill_id = tool.get("skill_id", "")
                parent_skill_node_id = skill_node_ids.get(skill_id)
                if parent_skill_node_id:
                    edges.append({
                        "source": parent_skill_node_id,
                        "target": tool_node_id,
                        "label": "calls",
                    })

            span.set_attribute("node_count", len(nodes))
            span.set_attribute("edge_count", len(edges))
            logger.info(
                "Built topology: %d nodes, %d edges (role=%s)",
                len(nodes),
                len(edges),
                role["id"],
            )

            return {"nodes": nodes, "edges": edges}
