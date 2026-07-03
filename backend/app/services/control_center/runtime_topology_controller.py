"""RuntimeTopologyController — active runtime topology projection for the runtime control dashboard.

Control Center authority for active session and delegation tree queries.
All persistence access is scoped to Control Center only.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import (
    AgentInstance,
    AgentInstanceStatus,
    AgentJob,
    AgentJobStatus,
    AgentType,
)
from app.db.models.agent_run_relationship import AgentRunRelationship
from app.db.models.conversations import ConversationSession, ConversationStatus

logger = logging.getLogger(__name__)


# Map ConversationStatus values onto the synthetic topology "status"
# string.  Conversation sessions don't have an AgentJobStatus (they
# use their own lifecycle: active/closed/archived/error), so we
# surface the literal ConversationStatus value and let the frontend
# render it directly.  The kind="conversation" tag distinguishes
# these from real AgentJob nodes.
_CONVERSATION_STATUS_VALUES = {
    ConversationStatus.active,
    ConversationStatus.closed,
    ConversationStatus.archived,
    ConversationStatus.error,
}


@dataclass
class TopologyNode:
    """A single active run node in the runtime topology projection."""

    session_id: uuid.UUID
    agent_type_id: uuid.UUID
    agent_type_name: str | None
    status: str
    depth_from_root: int
    parent_session_id: uuid.UUID | None
    started_at: datetime | None
    created_at: datetime
    termination_category: str | None
    # Phase 3.13: distinguishes agent runs from conversation
    # sessions.  Defaults to "agent" so existing call sites and
    # serialisers continue to behave the same.
    kind: str = "agent"
    # Optional human-friendly title for conversation nodes
    # (typically the auto-generated conversation name).
    title: str | None = None


@dataclass
class TopologyEdge:
    """A delegation edge between two active run nodes."""

    parent_session_id: uuid.UUID
    child_session_id: uuid.UUID
    depth_from_root: int


@dataclass
class RuntimeTopologyProjection:
    """Complete active topology view for the runtime control dashboard."""

    nodes: list[TopologyNode] = field(default_factory=list)
    edges: list[TopologyEdge] = field(default_factory=list)
    root_session_ids: list[uuid.UUID] = field(default_factory=list)


class RuntimeTopologyController:
    """
    Builds active runtime topology projections from Control Center persistence.

    Queries AgentJob and AgentRunRelationship to reconstruct parent-child trees
    of currently active or recently started sessions.
    """

    async def get_active_topology(
        self,
        db: AsyncSession,
        *,
        include_statuses: list[AgentJobStatus] | None = None,
        max_nodes: int = 200,
        include_conversations: bool = True,
        include_instances: bool = True,
    ) -> RuntimeTopologyProjection:
        """Return topology projection of active (and optionally recently terminal) runs.

        Args:
            db: Async database session (Control Center DB only).
            include_statuses: Which job statuses to include. Defaults to [queued, running].
            max_nodes: Safety cap on total nodes returned (avoids unbounded queries).
            include_conversations: If True (default), active
                ``ConversationSession`` rows are merged into the
                projection as ``kind="conversation"`` nodes so they
                are visible in the runtime control dashboard.
            include_instances: If True (default), live
                ``AgentInstance`` rows (status in
                {created, active, error}) are merged into the
                projection as ``kind="instance"`` nodes.  These
                represent persistent agent connections/sessions
                that exist independently of any individual job run.

        Returns:
            RuntimeTopologyProjection with nodes, edges, and root session IDs.
        """
        if include_statuses is None:
            include_statuses = [AgentJobStatus.queued, AgentJobStatus.running]

        # Fetch active sessions
        active_jobs_result = await db.execute(
            select(AgentJob)
            .where(AgentJob.status.in_(include_statuses))
            .order_by(AgentJob.created_at.desc())
            .limit(max_nodes)
        )
        active_jobs: list[AgentJob] = list(active_jobs_result.scalars().all())

        # Phase 3.16: include live AgentInstance rows.  An
        # AgentInstance represents a persistent agent
        # connection/session (separate from any individual
        # AgentJob execution).  Include created/active/error
        # states; closed instances are surfaced only when
        # ``include_terminal`` is True.
        active_instances: list[AgentInstance] = []
        if include_instances:
            instance_statuses = [AgentInstanceStatus.created, AgentInstanceStatus.active]
            if include_statuses and AgentJobStatus.failed in include_statuses:
                instance_statuses.append(AgentInstanceStatus.error)
            if include_statuses and AgentJobStatus.completed in include_statuses:
                instance_statuses.append(AgentInstanceStatus.closed)
            remaining = max(0, max_nodes - len(active_jobs))
            if remaining > 0:
                inst_result = await db.execute(
                    select(AgentInstance)
                    .where(AgentInstance.status.in_(instance_statuses))
                    .order_by(AgentInstance.created_at.desc())
                    .limit(remaining)
                )
                active_instances = list(inst_result.scalars().all())

        # Phase 3.13: optionally merge in active conversation
        # sessions.  Conversations are independent of AgentJob (they
        # may not have a backing AgentJob row at all) so they get
        # their own kind="conversation" tags.
        #
        # Phase 3.14: A conversation's *runtime* status is
        # distinct from its database status.  The database status
        # (active/closed/archived/error) reflects whether the
        # session is still open.  The runtime status reflects
        # whether an AgentJob is *currently* driving it:
        #   - "active" — a backing AgentJob exists AND is in
        #     {queued, running}.  The agent is actively producing
        #     output for this conversation.
        #   - "sleep" — the session is open (DB status=active) but
        #     no agent is currently driving it.  This happens when
        #     the user opens a session in the UI without sending a
        #     message, or when the previous turn's agent has
        #     finished and the user hasn't sent the next message.
        #   - "closed" / "archived" / "error" — terminal DB
        #     statuses, surfaced as-is.
        active_convs: list[ConversationSession] = []
        if include_conversations:
            conv_statuses = [ConversationStatus.active]
            if include_statuses and AgentJobStatus.completed in include_statuses:
                conv_statuses.extend(
                    [ConversationStatus.closed, ConversationStatus.archived]
                )
            if include_statuses and AgentJobStatus.failed in include_statuses:
                conv_statuses.append(ConversationStatus.error)
            remaining = max(0, max_nodes - len(active_jobs))
            if remaining > 0:
                conv_result = await db.execute(
                    select(ConversationSession)
                    .where(ConversationSession.status.in_(conv_statuses))
                    .order_by(ConversationSession.created_at.desc())
                    .limit(remaining)
                )
                active_convs = list(conv_result.scalars().all())

        if (
            not active_jobs
            and not active_convs
            and not active_instances
        ):
            return RuntimeTopologyProjection()

        active_job_ids = {j.id for j in active_jobs}
        # Map of conversation session ID -> its backing agent job ID
        # (if any).  Used to attach the conversation as a child of
        # its agent run for visualisation.
        conv_to_agent_job: dict[uuid.UUID, uuid.UUID] = {
            c.id: c.agent_job_id for c in active_convs if c.agent_job_id is not None
        }

        # Fetch agent type names for all involved agent_type_ids
        agent_type_ids: set[uuid.UUID] = {j.agent_type_id for j in active_jobs}
        for c in active_convs:
            if c.agent_type_id is not None:
                agent_type_ids.add(c.agent_type_id)
        for i in active_instances:
            agent_type_ids.add(i.agent_type_id)
        agent_type_names: dict[uuid.UUID, str | None] = {}
        if agent_type_ids:
            at_result = await db.execute(
                select(AgentType.id, AgentType.name).where(AgentType.id.in_(agent_type_ids))
            )
            for at_id, at_name in at_result.fetchall():
                agent_type_names[at_id] = at_name

        # Fetch delegation edges that involve at least one active job
        edges_result = await db.execute(
            select(AgentRunRelationship).where(
                AgentRunRelationship.parent_agent_job_id.in_(active_job_ids)
                | AgentRunRelationship.child_agent_job_id.in_(active_job_ids)
            )
        )
        raw_edges: list[AgentRunRelationship] = list(edges_result.scalars().all())

        # Build parent map: child_id -> parent_id and depth
        child_to_parent: dict[uuid.UUID, tuple[uuid.UUID, int]] = {}
        for edge in raw_edges:
            child_to_parent[edge.child_agent_job_id] = (
                edge.parent_agent_job_id,
                edge.depth_from_root,
            )

        # Determine root sessions (active jobs/convs/instances that are not children)
        all_node_ids: set[uuid.UUID] = (
            active_job_ids
            | {c.id for c in active_convs}
            | {i.id for i in active_instances}
        )
        root_session_ids: list[uuid.UUID] = [
            nid for nid in all_node_ids if nid not in child_to_parent
        ]

        # Build topology edges from raw relationships
        topology_edges: list[TopologyEdge] = [
            TopologyEdge(
                parent_session_id=e.parent_agent_job_id,
                child_session_id=e.child_agent_job_id,
                depth_from_root=e.depth_from_root,
            )
            for e in raw_edges
        ]

        # Build node list (agent jobs first, then conversations, then instances)
        nodes: list[TopologyNode] = []
        for job in active_jobs:
            parent_info = child_to_parent.get(job.id)
            parent_session_id = parent_info[0] if parent_info else None
            depth = parent_info[1] if parent_info else 0

            termination_cat = None
            if hasattr(job, "termination_category") and job.termination_category:
                termination_cat = (
                    job.termination_category.value
                    if hasattr(job.termination_category, "value")
                    else str(job.termination_category)
                )

            nodes.append(
                TopologyNode(
                    session_id=job.id,
                    agent_type_id=job.agent_type_id,
                    agent_type_name=agent_type_names.get(job.agent_type_id),
                    status=job.status.value,
                    depth_from_root=depth,
                    parent_session_id=parent_session_id,
                    started_at=job.started_at,
                    created_at=job.created_at,
                    termination_category=termination_cat,
                    kind="agent",
                )
            )

        # Phase 3.13: add conversation nodes.  If the conversation
        # has a backing agent_job_id that is also in the active set,
        # treat the conversation as a child of that agent run.
        # Otherwise, the conversation is a root node.
        #
        # Phase 3.14: Compute the runtime status.  An "active"
        # conversation with no live backing agent_job is "sleep" —
        # the session is open but no agent is currently driving
        # it.  This is the common case when a user opens a
        # conversation in the UI without sending a message.
        active_live_statuses = {AgentJobStatus.queued, AgentJobStatus.running}
        for conv in active_convs:
            parent_session_id = conv_to_agent_job.get(conv.id)
            if parent_session_id and parent_session_id not in active_job_ids:
                # The backing agent job is not active — treat the
                # conversation as a root (and reset to "sleep" since
                # there's no live agent driving it).
                parent_session_id = None

            # Compute runtime status.
            if conv.status == ConversationStatus.active:
                # Look up the backing agent_job's status.
                backing_job_id = conv.agent_job_id
                backing_job = (
                    next((j for j in active_jobs if j.id == backing_job_id), None)
                    if backing_job_id
                    else None
                )
                if backing_job and backing_job.status in active_live_statuses:
                    runtime_status = "active"
                else:
                    runtime_status = "sleep"
            else:
                # Closed/archived/error — surface the literal
                # ConversationStatus value.
                runtime_status = conv.status.value

            depth = 1 if parent_session_id else 0

            nodes.append(
                TopologyNode(
                    session_id=conv.id,
                    agent_type_id=conv.agent_type_id or uuid.UUID(int=0),
                    agent_type_name=(
                        agent_type_names.get(conv.agent_type_id)
                        if conv.agent_type_id is not None
                        else None
                    ),
                    status=runtime_status,
                    depth_from_root=depth,
                    parent_session_id=parent_session_id,
                    started_at=conv.created_at,
                    created_at=conv.created_at,
                    termination_category=None,
                    kind="conversation",
                    title=conv.title,
                )
            )

        # Phase 3.16: add AgentInstance nodes.  Instances are
        # persistent agent connections that exist independently
        # of any individual job run.  The status is the literal
        # ``AgentInstanceStatus`` value (created/active/closed/
        # error).
        for inst in active_instances:
            nodes.append(
                TopologyNode(
                    session_id=inst.id,
                    agent_type_id=inst.agent_type_id,
                    agent_type_name=agent_type_names.get(inst.agent_type_id),
                    status=inst.status.value,
                    depth_from_root=0,
                    parent_session_id=None,
                    started_at=inst.created_at,
                    created_at=inst.created_at,
                    termination_category=None,
                    kind="instance",
                    title=None,
                )
            )

        return RuntimeTopologyProjection(
            nodes=nodes,
            edges=topology_edges,
            root_session_ids=root_session_ids,
        )

    async def get_subtree_session_ids(
        self,
        root_session_id: uuid.UUID,
        db: AsyncSession,
        *,
        max_depth: int = 20,
    ) -> list[uuid.UUID]:
        """Return all session IDs in the subtree rooted at root_session_id (inclusive).

        Traverses AgentJob.parent_job_id edges breadth-first to collect descendants.
        """
        visited: list[uuid.UUID] = [root_session_id]
        frontier: list[uuid.UUID] = [root_session_id]
        depth = 0

        while frontier and depth < max_depth:
            children_result = await db.execute(
                select(AgentJob.id).where(
                    AgentJob.parent_job_id.in_(frontier)
                )
            )
            child_ids = [row[0] for row in children_result.fetchall()]
            new_children = [c for c in child_ids if c not in visited]
            visited.extend(new_children)
            frontier = new_children
            depth += 1

        return visited
