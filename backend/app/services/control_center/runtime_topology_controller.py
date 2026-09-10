"""RuntimeTopologyController — active runtime topology projection for the runtime control dashboard.

Control Center authority for active session and delegation tree queries.
All persistence access is scoped to Control Center only.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import (
    AgentInstance,
    AgentInstanceStatus,
    AgentJob,
    AgentJobStatus,
    AgentType,
)
from app.db.models.agent_run_relationship import AgentRunRelationship
from app.db.models.conversations import (
    ConversationSession,
    ConversationStatus,
    ConversationTurn,
    ToolCallRecord,
)
from app.db.models.identity import Identity
from app.db.models.intervene import InterveneRequest, InterveneRequestStatus
from app.db.models.scheduling import JobExecution, ScheduledJob
from app.db.models.tool_calls import RuntimeToolCall, RuntimeToolCallRouteType
from app.services.agents.tool_naming import parse_tool_name

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

#: Cap on tool-call routes returned per node (latest-first).
_MAX_TOOL_CALLS_PER_NODE = 20

#: Terminal job statuses eligible for the recent-terminal visibility window.
_TERMINAL_JOB_STATUSES = (
    AgentJobStatus.completed,
    AgentJobStatus.failed,
    AgentJobStatus.terminated,
)


def _resolve_mcp_slug(tool_name: str) -> str:
    """Derive the MCP server slug from a namespaced tool name.

    Uses ``parse_tool_name`` on the canonical ``server____tool`` format.
    Bare legacy system-tool names (``save_data``) resolve to the reserved
    ``system`` slug via ``parse_tool_name`` itself.

    Fallback chain for names ``parse_tool_name`` rejects:

    1. OpenAI-sanitised ``server__tool`` (double-underscore separator —
       the sanitiser converts the canonical ``____`` to ``__`` before
       sending to OpenAI).  Split on the FIRST ``__``; older recorder
       rows stored the sanitised form, so this keeps their slug
       resolvable (``supabase__get_project`` → ``supabase``).  Splits
       with an empty component degrade to ``unknown``.
    2. Legacy slash form ``server/tool`` → server part.
    3. Otherwise ``unknown`` — unparseable names degrade gracefully
       instead of dropping the call.
    """
    try:
        server, _ = parse_tool_name(tool_name)
        return server
    except ValueError:
        pass

    # Sanitised-name fallback: ``server__tool`` (first double underscore).
    if "__" in tool_name:
        server, bare = tool_name.split("__", 1)
        if server and bare:
            return server
        return "unknown"

    if "/" in tool_name:
        return tool_name.split("/", 1)[0]
    return "unknown"


@dataclass
class ToolCallRoute:
    """A single tool call resolved to an MCP server slug for route drawing."""

    tool_name: str
    mcp_slug: str
    called_at: datetime | None
    # Routing path the call took (``RuntimeToolCall.route_type`` value:
    # system/mcp/a2a).  ``None`` for legacy chat-sourced ``ToolCallRecord``
    # rows, which predate the runtime tool-call store.
    route_type: str | None = None


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
    # Whether this node has a pending human-intervention request.
    # Resolved by ``get_active_topology`` from pending
    # ``InterveneRequest`` rows keyed by agent/conversation session.
    needs_intervention: bool = False
    # Trigger provenance: who/what triggered this node.
    #   "user"             — directly user-triggered
    #   "delegated"        — delegated child (inherits parent's trigger)
    #   "schedule"         — schedule-triggered (label is the schedule name)
    #   "unknown"          — no determinable trigger source
    trigger_source: str = "unknown"
    # Human-readable trigger source label (user display name or schedule name).
    trigger_source_label: str | None = None
    # Resolved USER behind the trigger — the chat user for direct/delegated
    # runs, the schedule CREATOR for schedule-triggered runs.  Lets the UI
    # render person entities (who triggered it) separately from schedule
    # entities (what triggered it).
    trigger_user_label: str | None = None
    # Identity id of that user (for fetching the user's own details).
    trigger_user_id: uuid.UUID | None = None
    # The schedule entity's own details (schedule-triggered nodes only).
    schedule_id: uuid.UUID | None = None
    schedule_cron: str | None = None
    schedule_description: str | None = None
    # Tool-call history for this node (latest first), each resolved to an
    # MCP server slug via ``parse_tool_name``.
    tool_calls: list["ToolCallRoute"] = field(default_factory=list)


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
        recent_minutes: int = 30,
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
            recent_minutes: Include terminal jobs (completed/failed/
                terminated) whose completion time — ``completed_at``,
                falling back to ``created_at`` — is within this many
                minutes, so just-finished runs stay visible on the live
                map (their children are pulled in by the existing
                terminal-direct-children logic).  ``0`` disables the
                window.  Skipped when ``include_statuses`` already
                contains terminal statuses (``include_terminal`` keeps
                its "all terminal, no window" meaning).

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

        # Phase 11: include recently-terminal jobs so a just-finished run
        # (e.g. a completed delegation root whose children recorded tool
        # calls) stays visible on the live map.  Live jobs take precedence
        # within the ``max_nodes`` budget; the existing terminal-direct-
        # children query below then pulls in their children.  When terminal
        # statuses are already in ``include_statuses`` (``include_terminal``
        # mode) the primary query already returns them regardless of age,
        # so the window is redundant and skipped.
        if recent_minutes > 0 and include_statuses and not any(
            s in include_statuses for s in _TERMINAL_JOB_STATUSES
        ):
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=recent_minutes)
            remaining = max(0, max_nodes - len(active_jobs))
            if remaining > 0:
                recent_result = await db.execute(
                    select(AgentJob)
                    .where(
                        AgentJob.status.in_(_TERMINAL_JOB_STATUSES),
                        # ``AgentJob`` has no ``updated_at`` column, so the
                        # completion fallback chain collapses to
                        # completed_at → created_at.
                        func.coalesce(AgentJob.completed_at, AgentJob.created_at) >= cutoff,
                    )
                    .order_by(AgentJob.created_at.desc())
                    .limit(remaining)
                )
                existing_job_ids = {j.id for j in active_jobs}
                for job in recent_result.scalars().all():
                    if job.id not in existing_job_ids:
                        active_jobs.append(job)
                        existing_job_ids.add(job.id)

        # Include terminal direct children of included jobs so delegation
        # relationships stay visible — e.g. a ``waiting_for_human`` parent
        # whose delegated attempts have already failed would otherwise show
        # no children and no edges.  Budget-capped by ``max_nodes``.
        if active_jobs:
            child_budget = max(0, max_nodes - len(active_jobs))
            if child_budget > 0:
                child_result = await db.execute(
                    select(AgentJob)
                    .where(AgentJob.parent_job_id.in_({j.id for j in active_jobs}))
                    .order_by(AgentJob.created_at.desc())
                    .limit(child_budget)
                )
                existing_job_ids = {j.id for j in active_jobs}
                for child in child_result.scalars().all():
                    if child.id not in existing_job_ids:
                        active_jobs.append(child)
                        existing_job_ids.add(child.id)

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

        # Conversation ↔ job linkage: delegated (A2A) jobs carry the source
        # conversation id in ``input_data.__conv_session_id``.  Chat turns
        # execute WITHOUT a backing AgentJob, so this is the only link
        # between a conversation node and the jobs it spawned.  ``input_data``
        # is a JSON column — parse defensively.
        conv_id_of_job: dict[uuid.UUID, uuid.UUID] = {}
        for j in active_jobs:
            raw = j.input_data
            if not isinstance(raw, dict):
                continue
            val = raw.get("__conv_session_id")
            if val is None:
                continue
            try:
                conv_id_of_job[j.id] = (
                    val if isinstance(val, uuid.UUID) else uuid.UUID(str(val))
                )
            except (ValueError, TypeError, AttributeError):
                continue

        # ── Delegation parent map from AgentJob.parent_job_id ────────────────
        # ``agent_run_relationships`` is not reliably populated, so the
        # parent_job_id column is the authoritative delegation edge source.
        # It is unioned with any AgentRunRelationship rows (deduped below).
        parent_of_job: dict[uuid.UUID, uuid.UUID] = {
            j.id: j.parent_job_id for j in active_jobs if j.parent_job_id is not None
        }

        # Ancestor chains may include non-active (filtered-out) parents.
        # Fetch their parent links level by level so depth_from_root can be
        # computed by walking the full parent chain.
        chain_parent: dict[uuid.UUID, uuid.UUID] = dict(parent_of_job)
        frontier: set[uuid.UUID] = set(parent_of_job.values())
        seen_ids: set[uuid.UUID] = set(parent_of_job.keys())
        hops = 0
        while frontier and hops < 20:
            frontier = {f for f in frontier if f not in seen_ids}
            if not frontier:
                break
            rows = await db.execute(
                select(AgentJob.id, AgentJob.parent_job_id).where(AgentJob.id.in_(frontier))
            )
            next_frontier: set[uuid.UUID] = set()
            for jid, pid in rows.fetchall():
                chain_parent[jid] = pid
                if pid is not None:
                    next_frontier.add(pid)
            seen_ids |= frontier
            frontier = next_frontier
            hops += 1

        def _chain_depth(start: uuid.UUID) -> int:
            """Count ancestors via parent_job_id links (incl. inactive jobs)."""
            depth = 0
            cur = start
            visited: set[uuid.UUID] = {start}
            while True:
                pid = chain_parent.get(cur)
                if pid is None or pid in visited:
                    break
                depth += 1
                visited.add(pid)
                cur = pid
            return depth

        # Fetch delegation edges recorded in agent_run_relationships that
        # involve at least one active job.
        edges_result = await db.execute(
            select(AgentRunRelationship).where(
                AgentRunRelationship.parent_agent_job_id.in_(active_job_ids)
                | AgentRunRelationship.child_agent_job_id.in_(active_job_ids)
            )
        )
        raw_edges: list[AgentRunRelationship] = list(edges_result.scalars().all())

        # ── Unified edge set (child -> parent) ────────────────────────────────
        # Priority order (first writer wins per child):
        #   1. AgentRunRelationship rows (existing contract)
        #   2. AgentJob.parent_job_id delegation edges
        #   3. conversation -> job edges (chat-spawned A2A jobs)
        #   4. agent job -> backing-conversation edges
        edge_parent_of_child: dict[uuid.UUID, uuid.UUID] = {}

        def _add_edge(parent: uuid.UUID, child: uuid.UUID) -> None:
            if parent == child:
                return
            edge_parent_of_child.setdefault(child, parent)

        for edge in raw_edges:
            _add_edge(edge.parent_agent_job_id, edge.child_agent_job_id)
        for j in active_jobs:
            pid = parent_of_job.get(j.id)
            if pid is not None:
                _add_edge(pid, j.id)
        active_conv_ids = {c.id for c in active_convs}
        for j in active_jobs:
            cid = conv_id_of_job.get(j.id)
            if cid is not None and cid in active_conv_ids:
                _add_edge(cid, j.id)
        for c in active_convs:
            backing = conv_to_agent_job.get(c.id)
            if backing is not None and backing in active_job_ids:
                _add_edge(backing, c.id)

        # Determine root sessions (active jobs/convs/instances that have no parent edge)
        all_node_ids: set[uuid.UUID] = (
            active_job_ids
            | {c.id for c in active_convs}
            | {i.id for i in active_instances}
        )
        root_session_ids: list[uuid.UUID] = [
            nid for nid in all_node_ids if nid not in edge_parent_of_child
        ]

        # depth_from_root by walking parent chains.  When the parent node is
        # not part of the projection (filtered out), fall back to the
        # parent_job_id chain length so delegated children keep a
        # meaningful depth.
        depth_memo: dict[uuid.UUID, int] = {}
        resolving: set[uuid.UUID] = set()

        def _resolve_depth(nid: uuid.UUID) -> int:
            if nid in depth_memo:
                return depth_memo[nid]
            if nid in resolving:
                # Cycle guard — degrade to the flat chain depth.
                depth_memo[nid] = _chain_depth(nid)
                return depth_memo[nid]
            resolving.add(nid)
            try:
                parent = edge_parent_of_child.get(nid)
                if parent is None:
                    depth_memo[nid] = 0
                elif parent not in all_node_ids:
                    depth_memo[nid] = _chain_depth(nid)
                else:
                    depth_memo[nid] = _resolve_depth(parent) + 1
            finally:
                resolving.discard(nid)
            return depth_memo[nid]

        # Build topology edges from the unified parent map.
        topology_edges: list[TopologyEdge] = [
            TopologyEdge(
                parent_session_id=parent,
                child_session_id=child,
                depth_from_root=_resolve_depth(child),
            )
            for child, parent in edge_parent_of_child.items()
        ]

        # Build node list (agent jobs first, then conversations, then instances)
        nodes: list[TopologyNode] = []
        for job in active_jobs:
            parent_session_id = edge_parent_of_child.get(job.id)
            depth = _resolve_depth(job.id)

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
        active_live_statuses = {
            AgentJobStatus.queued,
            AgentJobStatus.running,
            # A job paused for human intervention is still engaged — the
            # conversation must not degrade to "sleep" while HITL is pending.
            AgentJobStatus.waiting_for_human,
        }
        # Chat-spawned jobs linked via ``__conv_session_id`` also count as
        # live drivers of their source conversation.
        jobs_by_conv: dict[uuid.UUID, list[AgentJob]] = {}
        for j in active_jobs:
            cid = conv_id_of_job.get(j.id)
            if cid is not None:
                jobs_by_conv.setdefault(cid, []).append(j)
        for conv in active_convs:
            parent_session_id = conv_to_agent_job.get(conv.id)
            if parent_session_id and parent_session_id not in active_job_ids:
                # The backing agent job is not active — treat the
                # conversation as a root (and reset to "sleep" since
                # there's no live agent driving it).
                parent_session_id = None

            # Compute runtime status.  A conversation counts as "active"
            # when either its backing agent_job or any chat-spawned linked
            # job (``__conv_session_id``) is in a live state — including
            # ``waiting_for_human`` (paused for intervention).
            if conv.status == ConversationStatus.active:
                backing_job_id = conv.agent_job_id
                backing_job = (
                    next((j for j in active_jobs if j.id == backing_job_id), None)
                    if backing_job_id
                    else None
                )
                driving_jobs: list[AgentJob] = list(jobs_by_conv.get(conv.id, []))
                if backing_job is not None:
                    driving_jobs.append(backing_job)
                if any(j.status in active_live_statuses for j in driving_jobs):
                    runtime_status = "active"
                else:
                    runtime_status = "sleep"
            else:
                # Closed/archived/error — surface the literal
                # ConversationStatus value.
                runtime_status = conv.status.value

            depth = _resolve_depth(conv.id) if parent_session_id else 0

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

        # Resolve pending human-intervention state per node.  A node
        # ``needs_intervention`` when there is a pending
        # ``InterveneRequest`` whose ``agent_session_id`` or
        # ``conversation_session_id`` matches the node's
        # ``session_id``.  This is a read-only enrichment — we do not
        # create or modify any entity here.
        pending_result = await db.execute(
            select(
                InterveneRequest.agent_session_id,
                InterveneRequest.conversation_session_id,
            ).where(InterveneRequest.status == InterveneRequestStatus.pending)
        )
        intervention_session_ids: set[uuid.UUID] = set()
        for agent_sid, conv_sid in pending_result.fetchall():
            if agent_sid is not None:
                intervention_session_ids.add(agent_sid)
            if conv_sid is not None:
                intervention_session_ids.add(conv_sid)

        if intervention_session_ids:
            for node in nodes:
                node.needs_intervention = node.session_id in intervention_session_ids

        # ── Trigger provenance resolution ─────────────────────────────────────
        # Map node session id → triggering identity id.  Agent jobs carry
        # triggered_by_user_id directly; conversations carry their own
        # triggered_by_user_id; legacy instances have none.
        session_to_user: dict[uuid.UUID, uuid.UUID] = {}
        for job in active_jobs:
            if job.triggered_by_user_id is not None:
                session_to_user[job.id] = job.triggered_by_user_id
        for conv in active_convs:
            if conv.triggered_by_user_id is not None:
                session_to_user[conv.id] = conv.triggered_by_user_id

        # Resolve identity display names for all trigger users.
        identity_names: dict[uuid.UUID, str] = {}
        if session_to_user:
            id_result = await db.execute(
                select(Identity.id, Identity.display_name).where(
                    Identity.id.in_(session_to_user.values())
                )
            )
            for ident_id, display_name in id_result.fetchall():
                identity_names[ident_id] = display_name or ""

        # Detect schedule-triggered jobs: JobExecution.result stores the
        # launched {"session_id": ...} for agent-target schedules.  Resolve
        # the schedule (name + id + cron + description) so schedule-triggered
        # nodes can surface the schedule entity's own details.
        schedule_by_session: dict[uuid.UUID, tuple[str, uuid.UUID, str | None, str | None]] = {}
        exec_result = await db.execute(
            select(
                JobExecution.result,
                ScheduledJob.name,
                ScheduledJob.id,
                ScheduledJob.cron_expression,
                ScheduledJob.description,
            )
            .join(ScheduledJob, ScheduledJob.id == JobExecution.job_id)
            .where(JobExecution.result.isnot(None))
        )
        for (
            result_payload,
            schedule_name,
            schedule_id,
            schedule_cron,
            schedule_description,
        ) in exec_result.fetchall():
            if not isinstance(result_payload, dict):
                continue
            sid = result_payload.get("session_id")
            if not sid:
                continue
            try:
                session_uuid = uuid.UUID(str(sid))
            except (ValueError, TypeError):
                continue
            schedule_by_session[session_uuid] = (
                schedule_name,
                schedule_id,
                schedule_cron,
                schedule_description,
            )

        for node in nodes:
            if node.session_id in schedule_by_session:
                (
                    schedule_name,
                    schedule_id,
                    schedule_cron,
                    schedule_description,
                ) = schedule_by_session[node.session_id]
                node.trigger_source = "schedule"
                node.schedule_id = schedule_id
                node.schedule_cron = schedule_cron
                node.schedule_description = schedule_description
                # Label = schedule NAME (it identifies the schedule entity
                # itself); the resolved creator user (passed through at
                # dispatch as ``triggered_by_user_id``) goes to
                # ``trigger_user_label`` — null when the creator is unknown
                # (schedules created before creator tracking).  The schedule
                # name must NEVER appear as the user label: downstream
                # consumers render it as a person.
                node.trigger_source_label = schedule_name
                node.trigger_user_id = session_to_user.get(node.session_id)
                node.trigger_user_label = identity_names.get(
                    session_to_user.get(node.session_id)
                )
            elif node.kind == "conversation":
                # Conversations report their own chat user — a backing agent
                # job does NOT make the conversation "delegated".
                if node.session_id in session_to_user:
                    node.trigger_source = "user"
                    node.trigger_user_id = session_to_user[node.session_id]
                    node.trigger_source_label = identity_names.get(
                        session_to_user[node.session_id]
                    )
                    node.trigger_user_label = node.trigger_source_label
                else:
                    node.trigger_source = "unknown"
                    node.trigger_source_label = None
            elif node.parent_session_id is not None:
                # Delegated children inherit the original trigger user.
                node.trigger_source = "delegated"
                node.trigger_user_id = session_to_user.get(node.session_id)
                node.trigger_source_label = identity_names.get(
                    session_to_user.get(node.session_id)
                )
                node.trigger_user_label = node.trigger_source_label
            elif node.session_id in session_to_user:
                node.trigger_source = "user"
                node.trigger_user_id = session_to_user[node.session_id]
                node.trigger_source_label = identity_names.get(
                    session_to_user[node.session_id]
                )
                node.trigger_user_label = node.trigger_source_label
            else:
                node.trigger_source = "unknown"
                node.trigger_source_label = None

        # ── Tool-call history resolution ──────────────────────────────────────
        # Union of two sources, latest-first, capped per node:
        #   1. ``RuntimeToolCall`` rows recorded by Agent Runtime for every
        #      executed MCP/system/A2A tool call (keyed polymorphically by
        #      agent job id OR conversation id).
        #   2. ``ToolCallRecord`` via ConversationTurn → ConversationSession
        #      (legacy chat tool history; the ``chat_status`` pseudo-events
        #      are dropped as noise).
        node_ids: set[uuid.UUID] = {n.session_id for n in nodes}
        # Per-node accumulation (owner -> [(tool_name, called_at, route_type), ...])
        collected_by_node: dict[
            uuid.UUID, list[tuple[str, datetime | None, str | None]]
        ] = {n.session_id: [] for n in nodes}

        if node_ids:
            rtc_rows = await db.execute(
                select(
                    RuntimeToolCall.session_id,
                    RuntimeToolCall.tool_name,
                    RuntimeToolCall.route_type,
                    RuntimeToolCall.created_at,
                )
                .where(RuntimeToolCall.session_id.in_(node_ids))
                # A2A rows are agent-to-agent delegations, not tool
                # executions — delegation is already rendered as
                # delegation edges, so they must not pollute the
                # per-node tool-call history / MCP route drawing.
                .where(
                    RuntimeToolCall.route_type != RuntimeToolCallRouteType.a2a
                )
                .order_by(RuntimeToolCall.created_at.desc())
                .limit(max_nodes * _MAX_TOOL_CALLS_PER_NODE)
            )
            for session_id, tool_name, route_type, called_at in rtc_rows.fetchall():
                if session_id in collected_by_node:
                    collected_by_node[session_id].append(
                        (
                            tool_name,
                            called_at,
                            (
                                route_type.value
                                if hasattr(route_type, "value")
                                else str(route_type)
                            ),
                        )
                    )

            tool_rows = await db.execute(
                select(
                    ConversationSession.id,
                    ConversationSession.agent_job_id,
                    ToolCallRecord.tool_name,
                    ToolCallRecord.created_at,
                )
                .join(ConversationTurn, ConversationTurn.session_id == ConversationSession.id)
                .join(ToolCallRecord, ToolCallRecord.turn_id == ConversationTurn.id)
                .where(
                    (ConversationSession.agent_job_id.in_(node_ids))
                    | (ConversationSession.id.in_(node_ids))
                )
                .order_by(ToolCallRecord.created_at.desc())
            )
            for conv_id, agent_job_id, tool_name, called_at in tool_rows.fetchall():
                if tool_name == "chat_status":
                    # Chat pseudo-events are not real tool executions.
                    continue
                owner: uuid.UUID | None = None
                if agent_job_id is not None and agent_job_id in node_ids:
                    owner = agent_job_id
                elif conv_id in node_ids:
                    owner = conv_id
                if owner is None:
                    continue
                # Legacy chat-sourced rows predate the route-type store.
                collected_by_node[owner].append((tool_name, called_at, None))

        _EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
        for node in nodes:
            entries = collected_by_node.get(node.session_id, [])
            entries.sort(key=lambda e: e[1] or _EPOCH, reverse=True)
            node.tool_calls = [
                ToolCallRoute(
                    tool_name=tool_name,
                    mcp_slug=_resolve_mcp_slug(tool_name),
                    called_at=called_at,
                    route_type=route_type,
                )
                for tool_name, called_at, route_type in entries[:_MAX_TOOL_CALLS_PER_NODE]
            ]

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
