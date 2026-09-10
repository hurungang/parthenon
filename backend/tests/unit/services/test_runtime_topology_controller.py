"""Tests for RuntimeTopologyController — conversation session merging.

Phase 3.13: the runtime control dashboard previously only showed
``AgentJob`` rows.  Conversation sessions (which are independent
entities, optionally backed by an AgentJob) were invisible.  These
tests pin the new behaviour:

  * Active ``ConversationSession`` rows are merged into the
    projection as ``kind="conversation"`` nodes.
  * Conversation nodes carry the ``ConversationStatus`` value
    (active/closed/archived/error) in the ``status`` field, not
    ``AgentJobStatus``.
  * ``include_terminal`` propagates: closed/archived/error
    conversations appear alongside completed/failed agent jobs.
  * Conversations with a backing ``agent_job_id`` that's also in
    the active set are nested as children of that agent run.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models.agents import AgentInstance, AgentInstanceStatus, AgentJobStatus
from app.db.models.conversations import (
    ConversationSession,
    ConversationStatus,
)
from app.services.control_center.runtime_topology_controller import (
    RuntimeTopologyController,
    TopologyNode,
)


def _make_agent_job(
    job_id: uuid.UUID,
    agent_type_id: uuid.UUID,
    status: AgentJobStatus = AgentJobStatus.running,
    triggered_by_user_id: uuid.UUID | None = None,
    parent_job_id: uuid.UUID | None = None,
    input_data: dict | None = None,
) -> MagicMock:
    job = MagicMock()
    job.id = job_id
    job.agent_type_id = agent_type_id
    job.status = status
    job.started_at = datetime.now(timezone.utc)
    job.created_at = datetime.now(timezone.utc)
    job.termination_category = None
    job.triggered_by_user_id = triggered_by_user_id
    # Mirror real model defaults — the controller consumes these fields
    # (delegation edges + conversation linkage), so they must not be
    # MagicMock auto-attributes.
    job.parent_job_id = parent_job_id
    job.input_data = input_data
    job.delegation_depth = 0
    return job


def _make_conv(
    conv_id: uuid.UUID,
    agent_type_id: uuid.UUID,
    status: ConversationStatus = ConversationStatus.active,
    agent_job_id: uuid.UUID | None = None,
    title: str | None = None,
) -> MagicMock:
    conv = MagicMock()
    conv.id = conv_id
    conv.agent_type_id = agent_type_id
    conv.status = status
    conv.agent_job_id = agent_job_id
    conv.title = title
    conv.created_at = datetime.now(timezone.utc)
    return conv


def _make_instance(
    inst_id: uuid.UUID,
    agent_type_id: uuid.UUID,
    status: AgentInstanceStatus = AgentInstanceStatus.active,
) -> MagicMock:
    inst = MagicMock(spec=AgentInstance)
    inst.id = inst_id
    inst.agent_type_id = agent_type_id
    inst.status = status
    inst.created_at = datetime.now(timezone.utc)
    return inst


def _build_db(
    agent_jobs: list[MagicMock],
    convs: list[MagicMock] | None = None,
    instances: list[MagicMock] | None = None,
    pending_interventions: list[tuple[uuid.UUID | None, uuid.UUID | None]] | None = None,
    statements: list | None = None,
    *,
    identity_rows: list[tuple[uuid.UUID, str]] | None = None,
    schedule_rows: list[tuple[dict, str, uuid.UUID, str | None, str | None]] | None = None,
    tool_call_rows: list[tuple[uuid.UUID, uuid.UUID | None, str, datetime]] | None = None,
    runtime_tool_call_rows: list[
        tuple[uuid.UUID, str, str | None, datetime | None]
    ]
    | None = None,
    edge_rows: list[MagicMock] | None = None,
    child_jobs: list[MagicMock] | None = None,
    chain_rows: list[tuple[uuid.UUID, uuid.UUID | None]] | None = None,
) -> AsyncMock:
    """Build an AsyncMock session that returns rows for the controller's
    queries.

    The controller issues several queries, some of which are **conditional**
    (e.g. the identity-name lookup only runs when there is a trigger user;
    the schedule lookup always runs).  Rather than rely on positional order,
    this mock dispatches each ``db.execute`` call by inspecting the SQL
    statement it is given (matching substrings of the generated SQL).

    ==  ====================================================  =====================
    idx  query (matched by substring)                          result source
    ==  ====================================================  =====================
    —    ``FROM agent_jobs`` (status list)                     ``scalars().all()``
    —    ``FROM agent_jobs`` (``parent_job_id`` IN + ORDER BY)  ``scalars().all()``
         → terminal direct children fetch (``child_jobs``)
    —    ``FROM agent_jobs`` (``parent_job_id`` cols, no       ``fetchall()``
         ORDER BY) → ancestor chain lookup (``chain_rows``)
    —    ``FROM agent_instances``                              ``scalars().all()``
    —    ``FROM conversation_sessions`` (first, bare)          ``scalars().all()``
    —    agent type names (``FROM agent_types``)               ``fetchall()`` → []
    —    delegation edges (``FROM agent_run_relationships``)   ``scalars().all()``
    —    pending intervention (``FROM intervene_requests``)    ``fetchall()``
    —    identity names (``FROM identities``)                  ``fetchall()``
    —    schedule names (``FROM job_executions``)              ``fetchall()``
    —    AR tool-call history (``FROM runtime_tool_calls``)    ``fetchall()``
    —    chat tool-call history (``FROM tool_call_records``)   ``fetchall()``
    ==  ====================================================  =====================

    ``schedule_rows`` — ``(result_payload, schedule_name, schedule_id, cron, description)`` tuples: the
    controller reads ``JobExecution.result`` (a dict with ``{"session_id":
    ...}``) joined with ``ScheduledJob.name``.

    ``tool_call_rows`` — ``(conversation_session_id, agent_job_id,
    tool_name, called_at)`` tuples for the tool-call history lookup (the
    ``agent_job_id`` is the conversation's backing job FK).

    ``runtime_tool_call_rows`` — ``(session_id, tool_name, route_type,
    created_at)`` tuples for the ``RuntimeToolCall`` history lookup
    (polymorphic session key: agent job id OR conversation id; route_type is
    the ``RuntimeToolCall.route_type`` value — system/mcp/a2a).

    ``child_jobs`` — jobs returned by the terminal-direct-children fetch
    (``WHERE parent_job_id IN (<active ids>)``); the controller adds these
    to the projection so delegation edges to terminal children render.

    ``chain_rows`` — ``(job_id, parent_job_id)`` rows for the ancestor
    chain lookup used to compute ``depth_from_root``.

    ``statements`` (optional) captures every SQL statement passed to
    ``db.execute`` so tests can inspect a query's WHERE clause.
    """
    db = AsyncMock()

    # Plain-agent-jobs list is matched first; conversation_sessions appears in
    # multiple queries (the bare list + the two join queries), so we consume
    # it positionally for the first "FROM conversation_sessions" only.
    agent_job_result = MagicMock()
    agent_job_result.scalars.return_value.all.return_value = agent_jobs
    child_job_result = MagicMock()
    child_job_result.scalars.return_value.all.return_value = list(child_jobs or [])
    chain_result = MagicMock()
    chain_result.fetchall.return_value = list(chain_rows or [])
    instance_result = MagicMock()
    instance_result.scalars.return_value.all.return_value = instances or []
    conv_result = MagicMock()
    conv_result.scalars.return_value.all.return_value = convs or []

    at_result = MagicMock()
    at_result.fetchall.return_value = []
    edge_result = MagicMock()
    edge_result.scalars.return_value.all.return_value = list(edge_rows or [])
    intervention_result = MagicMock()
    intervention_result.fetchall.return_value = list(pending_interventions or [])
    identity_result = MagicMock()
    identity_result.fetchall.return_value = list(identity_rows or [])
    schedule_result = MagicMock()
    schedule_result.fetchall.return_value = list(schedule_rows or [])
    runtime_tool_result = MagicMock()
    runtime_tool_result.fetchall.return_value = list(runtime_tool_call_rows or [])
    tool_result = MagicMock()
    tool_result.fetchall.return_value = list(tool_call_rows or [])

    conv_consumed = {"used": False}

    async def fake_execute(stmt):
        if statements is not None:
            statements.append(stmt)
        sql = str(stmt)

        if "FROM agent_jobs" in sql or "FROM agents " in sql:
            if ".parent_job_id IN" in sql:
                # Terminal-direct-children fetch (budget-capped, ordered).
                # NOTE: every ``select(AgentJob)`` renders ``parent_job_id``
                # in its column list, so routing keys on the WHERE clause.
                return child_job_result
            if "parent_job_id" in sql and "ORDER BY" not in sql:
                # Ancestor chain-parent lookup (id, parent_job_id) rows.
                return chain_result
            return agent_job_result
        if "FROM agent_instances" in sql:
            return instance_result
        if "FROM agent_types" in sql:
            return at_result
        if "FROM agent_run_relationships" in sql:
            return edge_result
        if "FROM intervene_requests" in sql:
            return intervention_result
        if "FROM identities" in sql:
            return identity_result
        if "FROM job_executions" in sql:
            return schedule_result
        if "runtime_tool_calls" in sql:
            return runtime_tool_result
        if "tool_call_records" in sql:
            return tool_result
        # First bare conversation_sessions list query.
        if "FROM conversation_sessions" in sql and not conv_consumed["used"]:
            conv_consumed["used"] = True
            return conv_result
        # Any other/fallback query → empty.
        empty = MagicMock()
        empty.scalars.return_value.all.return_value = []
        empty.fetchall.return_value = []
        return empty

    db.execute = fake_execute
    return db


@pytest.mark.asyncio
async def test_conversation_node_appears_in_topology():
    """A standalone conversation (no backing agent job) is
    included as a ``kind="conversation"`` root node.  Since the
    conversation is open in the DB but has no live agent driving
    it, the runtime status is ``"sleep"`` (Phase 3.14).
    """
    conv_id = uuid.uuid4()
    conv = _make_conv(conv_id, uuid.uuid4(), status=ConversationStatus.active)

    db = _build_db(agent_jobs=[], convs=[conv])
    projection = await RuntimeTopologyController().get_active_topology(db)

    assert len(projection.nodes) == 1
    node = projection.nodes[0]
    assert node.session_id == conv_id
    assert node.kind == "conversation"
    assert node.status == "sleep"
    assert node.parent_session_id is None
    assert conv_id in projection.root_session_ids


@pytest.mark.asyncio
async def test_agent_and_conversation_nodes_coexist():
    """Agent jobs and conversations both appear in the same
    projection with the appropriate ``kind`` values.
    """
    job_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    at_id = uuid.uuid4()

    job = _make_agent_job(job_id, at_id, AgentJobStatus.running)
    conv = _make_conv(conv_id, at_id, status=ConversationStatus.active)

    db = _build_db(agent_jobs=[job], convs=[conv])
    projection = await RuntimeTopologyController().get_active_topology(db)

    kinds = {n.session_id: n.kind for n in projection.nodes}
    assert kinds[job_id] == "agent"
    assert kinds[conv_id] == "conversation"


@pytest.mark.asyncio
async def test_conversation_status_appears_literally():
    """The conversation node's status is the literal
    ``ConversationStatus`` value (e.g. 'sleep', 'closed'), not an
    ``AgentJobStatus``.  An "active" session without a live
    backing agent_job is shown as "sleep" (Phase 3.14).
    """
    conv_id = uuid.uuid4()
    conv = _make_conv(
        conv_id, uuid.uuid4(), status=ConversationStatus.active
    )
    db = _build_db(agent_jobs=[], convs=[conv])
    projection = await RuntimeTopologyController().get_active_topology(db)
    assert projection.nodes[0].status == "sleep"

    # And for the closed state
    conv.status = ConversationStatus.closed
    db = _build_db(agent_jobs=[], convs=[conv])
    projection = await RuntimeTopologyController().get_active_topology(
        db, include_statuses=[AgentJobStatus.completed]
    )
    assert projection.nodes[0].status == "closed"


@pytest.mark.asyncio
async def test_conversation_nested_under_active_agent_run():
    """A conversation that has a backing ``agent_job_id`` whose
    AgentJob is also in the active set is rendered as a child of
    that agent run.  Its runtime status is ``"active"`` because
    the backing agent_job is currently running.
    """
    job_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    at_id = uuid.uuid4()

    job = _make_agent_job(job_id, at_id, AgentJobStatus.running)
    conv = _make_conv(
        conv_id,
        at_id,
        status=ConversationStatus.active,
        agent_job_id=job_id,
    )
    db = _build_db(agent_jobs=[job], convs=[conv])
    projection = await RuntimeTopologyController().get_active_topology(db)

    conv_node = next(n for n in projection.nodes if n.session_id == conv_id)
    assert conv_node.parent_session_id == job_id
    assert conv_node.depth_from_root == 1
    assert conv_node.status == "active"


@pytest.mark.asyncio
async def test_conversation_orphaned_when_agent_job_terminal():
    """If the conversation's backing agent_job is NOT in the
    active set, the conversation is treated as a root node (it
    cannot be nested under a terminal agent run).
    """
    job_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    conv = _make_conv(
        conv_id,
        uuid.uuid4(),
        status=ConversationStatus.active,
        agent_job_id=job_id,  # references a job that's not active
    )
    db = _build_db(agent_jobs=[], convs=[conv])
    projection = await RuntimeTopologyController().get_active_topology(db)
    assert projection.nodes[0].parent_session_id is None


@pytest.mark.asyncio
async def test_closed_conversations_excluded_from_live_view():
    """Default ``include_statuses=[queued, running]`` does NOT
    include closed/archived/error conversations — they only show
    up under ``include_terminal=True``.
    """
    conv = _make_conv(
        uuid.uuid4(), uuid.uuid4(), status=ConversationStatus.closed
    )
    db = _build_db(agent_jobs=[], convs=[])  # controller must filter
    # Conversation with closed status must not be returned by
    # the controller's query at all.
    projection = await RuntimeTopologyController().get_active_topology(db)
    assert projection.nodes == []


@pytest.mark.asyncio
async def test_include_conversations_false_excludes_them():
    """``include_conversations=False`` opt-out keeps the legacy
    behaviour of agent-jobs-only.
    """
    conv_id = uuid.uuid4()
    conv = _make_conv(conv_id, uuid.uuid4(), status=ConversationStatus.active)
    db = _build_db(agent_jobs=[], convs=[])
    projection = await RuntimeTopologyController().get_active_topology(
        db, include_conversations=False
    )
    # Controller didn't query convs at all → no node
    assert projection.nodes == []


@pytest.mark.asyncio
async def test_conversation_title_propagated():
    """A conversation's auto-generated title is propagated to the
    topology node so the dashboard can show it.
    """
    conv_id = uuid.uuid4()
    conv = _make_conv(
        conv_id,
        uuid.uuid4(),
        status=ConversationStatus.active,
        title="Plan trip to Paris",
    )
    db = _build_db(agent_jobs=[], convs=[conv])
    projection = await RuntimeTopologyController().get_active_topology(db)
    assert projection.nodes[0].title == "Plan trip to Paris"


@pytest.mark.asyncio
async def test_open_conversation_without_live_agent_is_sleep():
    """An open conversation (DB status=active) without a backing
    agent_job OR with a backing agent_job that is not currently
    running/queued is shown as ``status="sleep"`` — the session
    is open but no agent is currently driving it.  This is the
    common case when a user opens a conversation in the UI
    without sending a message.
    """
    conv_id = uuid.uuid4()
    conv = _make_conv(
        conv_id, uuid.uuid4(), status=ConversationStatus.active
    )  # agent_job_id=None
    db = _build_db(agent_jobs=[], convs=[conv])
    projection = await RuntimeTopologyController().get_active_topology(db)
    assert projection.nodes[0].status == "sleep"


@pytest.mark.asyncio
async def test_open_conversation_with_running_agent_is_active():
    """An open conversation with a backing agent_job that is
    currently running is shown as ``status="active"`` — the
    agent is actively producing output for this conversation.
    """
    job_id = uuid.uuid4()
    at_id = uuid.uuid4()
    conv_id = uuid.uuid4()

    job = _make_agent_job(job_id, at_id, AgentJobStatus.running)
    conv = _make_conv(
        conv_id,
        at_id,
        status=ConversationStatus.active,
        agent_job_id=job_id,
    )
    db = _build_db(agent_jobs=[job], convs=[conv])
    projection = await RuntimeTopologyController().get_active_topology(db)

    conv_node = next(n for n in projection.nodes if n.session_id == conv_id)
    assert conv_node.status == "active"
    # The conversation is nested under its backing agent run.
    assert conv_node.parent_session_id == job_id


@pytest.mark.asyncio
async def test_open_conversation_with_queued_agent_is_active():
    """An open conversation with a backing agent_job that is
    currently queued (about to run) is shown as ``status="active"``
    — the agent is about to produce output.
    """
    job_id = uuid.uuid4()
    at_id = uuid.uuid4()
    conv_id = uuid.uuid4()

    job = _make_agent_job(job_id, at_id, AgentJobStatus.queued)
    conv = _make_conv(
        conv_id,
        at_id,
        status=ConversationStatus.active,
        agent_job_id=job_id,
    )
    db = _build_db(agent_jobs=[job], convs=[conv])
    projection = await RuntimeTopologyController().get_active_topology(db)

    conv_node = next(n for n in projection.nodes if n.session_id == conv_id)
    assert conv_node.status == "active"


@pytest.mark.asyncio
async def test_open_conversation_with_terminated_agent_is_sleep():
    """An open conversation whose backing agent_job has been
    operator-terminated is shown as ``status="sleep"`` — the
    session is still open, but the previous agent is gone.
    Resuming the session will spin up a new agent_job.
    """
    job_id = uuid.uuid4()
    at_id = uuid.uuid4()
    conv_id = uuid.uuid4()

    # A terminated agent job — NOT in the active set.
    conv = _make_conv(
        conv_id,
        at_id,
        status=ConversationStatus.active,
        agent_job_id=job_id,
    )
    db = _build_db(agent_jobs=[], convs=[conv])
    projection = await RuntimeTopologyController().get_active_topology(db)
    conv_node = projection.nodes[0]
    assert conv_node.status == "sleep"
    # The terminated agent job is not in the active set, so the
    # conversation is treated as a root.
    assert conv_node.parent_session_id is None


@pytest.mark.asyncio
async def test_closed_conversation_is_closed():
    """A closed conversation is shown as ``status="closed"`` (the
    literal ConversationStatus value) — distinct from both
    ``active`` and ``sleep``.
    """
    conv_id = uuid.uuid4()
    conv = _make_conv(
        conv_id, uuid.uuid4(), status=ConversationStatus.closed
    )
    db = _build_db(agent_jobs=[], convs=[conv])
    projection = await RuntimeTopologyController().get_active_topology(
        db, include_statuses=[AgentJobStatus.completed]
    )
    assert projection.nodes[0].status == "closed"


@pytest.mark.asyncio
async def test_error_conversation_is_error():
    """A conversation in error state is shown as
    ``status="error"``.
    """
    conv_id = uuid.uuid4()
    conv = _make_conv(
        conv_id, uuid.uuid4(), status=ConversationStatus.error
    )
    db = _build_db(agent_jobs=[], convs=[conv])
    projection = await RuntimeTopologyController().get_active_topology(
        db, include_statuses=[AgentJobStatus.failed]
    )
    assert projection.nodes[0].status == "error"


# Phase 3.16: AgentInstance nodes


@pytest.mark.asyncio
async def test_active_instance_appears_in_topology():
    """An ``AgentInstance`` with status=active is included as a
    ``kind="instance"`` node with status=active.
    """
    inst_id = uuid.uuid4()
    inst = _make_instance(inst_id, uuid.uuid4(), AgentInstanceStatus.active)
    db = _build_db(agent_jobs=[], instances=[inst])
    projection = await RuntimeTopologyController().get_active_topology(db)

    assert len(projection.nodes) == 1
    node = projection.nodes[0]
    assert node.session_id == inst_id
    assert node.kind == "instance"
    assert node.status == "active"
    assert node.parent_session_id is None
    assert inst_id in projection.root_session_ids


@pytest.mark.asyncio
async def test_created_instance_appears_in_topology():
    """An ``AgentInstance`` with status=created is included.
    """
    inst_id = uuid.uuid4()
    inst = _make_instance(inst_id, uuid.uuid4(), AgentInstanceStatus.created)
    db = _build_db(agent_jobs=[], instances=[inst])
    projection = await RuntimeTopologyController().get_active_topology(db)
    assert projection.nodes[0].status == "created"
    assert projection.nodes[0].kind == "instance"


@pytest.mark.asyncio
async def test_all_three_kinds_coexist():
    """AgentJob, AgentInstance, and ConversationSession can all
    appear in the same projection.
    """
    job_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    at_id = uuid.uuid4()

    job = _make_agent_job(job_id, at_id, AgentJobStatus.running)
    inst = _make_instance(inst_id, at_id, AgentInstanceStatus.active)
    conv = _make_conv(conv_id, at_id, ConversationStatus.active)

    db = _build_db(agent_jobs=[job], instances=[inst], convs=[conv])
    projection = await RuntimeTopologyController().get_active_topology(db)

    kinds = {n.session_id: n.kind for n in projection.nodes}
    assert kinds[job_id] == "agent"
    assert kinds[inst_id] == "instance"
    assert kinds[conv_id] == "conversation"


@pytest.mark.asyncio
async def test_include_instances_false_excludes_them():
    """``include_instances=False`` opt-out keeps the legacy
    behaviour of agent-jobs-and-conversations only.
    """
    inst_id = uuid.uuid4()
    inst = _make_instance(inst_id, uuid.uuid4())
    db = _build_db(agent_jobs=[], instances=[])
    projection = await RuntimeTopologyController().get_active_topology(
        db, include_instances=False
    )
    # Controller didn't query instances at all → no node
    assert projection.nodes == []


@pytest.mark.asyncio
async def test_closed_instance_only_included_with_terminal_flag():
    """A closed ``AgentInstance`` is excluded from the live
    (non-terminal) view but appears when ``include_terminal``
    propagates through the controller.
    """
    inst_id = uuid.uuid4()
    inst = _make_instance(inst_id, uuid.uuid4(), AgentInstanceStatus.closed)
    # Live view: no closed instances (mock returns empty)
    db = _build_db(agent_jobs=[], instances=[])
    projection = await RuntimeTopologyController().get_active_topology(db)
    assert projection.nodes == []
    # Terminal view: mock now returns the closed instance
    db = _build_db(agent_jobs=[], instances=[inst])
    projection = await RuntimeTopologyController().get_active_topology(
        db, include_statuses=[AgentJobStatus.completed]
    )
    assert any(n.session_id == inst_id for n in projection.nodes)


# ── needs_intervention resolution ───────────────────────────────────────────────


def test_topology_node_defaults_needs_intervention_false():
    """The projection dataclass carries ``needs_intervention`` with a
    safe default of ``False`` for backwards compatibility.
    """
    node = TopologyNode(
        session_id=uuid.uuid4(),
        agent_type_id=uuid.uuid4(),
        agent_type_name=None,
        status="running",
        depth_from_root=0,
        parent_session_id=None,
        started_at=None,
        created_at=datetime.now(timezone.utc),
        termination_category=None,
    )
    assert node.needs_intervention is False


@pytest.mark.asyncio
async def test_node_needs_intervention_true_for_pending_agent_request():
    """An agent node whose session has a pending ``InterveneRequest``
    (keyed by ``agent_session_id``) is flagged.
    """
    job_id = uuid.uuid4()
    at_id = uuid.uuid4()
    job = _make_agent_job(job_id, at_id, AgentJobStatus.running)
    db = _build_db(agent_jobs=[job], pending_interventions=[(job_id, None)])
    projection = await RuntimeTopologyController().get_active_topology(db)

    node = projection.nodes[0]
    assert node.session_id == job_id
    assert node.needs_intervention is True


@pytest.mark.asyncio
async def test_node_needs_intervention_true_for_pending_conversation_request():
    """A conversation node whose session has a pending
    ``InterveneRequest`` (keyed by ``conversation_session_id``) is
    flagged.
    """
    conv_id = uuid.uuid4()
    conv = _make_conv(conv_id, uuid.uuid4(), status=ConversationStatus.active)
    db = _build_db(agent_jobs=[], convs=[conv], pending_interventions=[(None, conv_id)])
    projection = await RuntimeTopologyController().get_active_topology(db)

    node = projection.nodes[0]
    assert node.kind == "conversation"
    assert node.needs_intervention is True


@pytest.mark.asyncio
async def test_node_needs_intervention_false_without_pending_request():
    """With no pending intervention rows the node stays ``False``.
    """
    job_id = uuid.uuid4()
    job = _make_agent_job(job_id, uuid.uuid4(), AgentJobStatus.running)
    db = _build_db(agent_jobs=[job])
    projection = await RuntimeTopologyController().get_active_topology(db)

    assert projection.nodes[0].needs_intervention is False


@pytest.mark.asyncio
async def test_needs_intervention_only_flags_matching_session():
    """Only the session referenced by the pending request is flagged;
    sibling nodes remain ``False``.
    """
    job_a = uuid.uuid4()
    job_b = uuid.uuid4()
    at_id = uuid.uuid4()
    a = _make_agent_job(job_a, at_id, AgentJobStatus.running)
    b = _make_agent_job(job_b, at_id, AgentJobStatus.running)
    db = _build_db(agent_jobs=[a, b], pending_interventions=[(job_a, None)])
    projection = await RuntimeTopologyController().get_active_topology(db)

    by_id = {n.session_id: n.needs_intervention for n in projection.nodes}
    assert by_id[job_a] is True
    assert by_id[job_b] is False


@pytest.mark.asyncio
async def test_intervention_query_filters_on_pending_status():
    """The pending-intervention lookup is scoped to
    ``InterveneRequest.status == pending`` so responded/cancelled/
    expired requests are never surfaced.
    """
    job_id = uuid.uuid4()
    job = _make_agent_job(job_id, uuid.uuid4(), AgentJobStatus.running)
    statements: list = []
    db = _build_db(agent_jobs=[job], statements=statements)
    await RuntimeTopologyController().get_active_topology(db)

    # Find the pending-intervention lookup among all queries issued.
    intervene_stmt = next(
        s for s in statements if "intervene_requests" in str(s).lower()
    )
    where = intervene_stmt.whereclause
    rhs = where.right
    rhs_value = getattr(rhs, "value", rhs)
    rhs_value = getattr(rhs_value, "value", rhs_value)
    assert str(rhs_value) == "pending"


# ── Trigger provenance resolution ───────────────────────────────────────────────


def test_topology_node_default_trigger_source_is_unknown():
    """The projection dataclass defaults ``trigger_source`` to ``"unknown"``
    and ``trigger_source_label`` to ``None`` for backwards compatibility.
    """
    node = TopologyNode(
        session_id=uuid.uuid4(),
        agent_type_id=uuid.uuid4(),
        agent_type_name=None,
        status="running",
        depth_from_root=0,
        parent_session_id=None,
        started_at=None,
        created_at=datetime.now(timezone.utc),
        termination_category=None,
    )
    assert node.trigger_source == "unknown"
    assert node.trigger_source_label is None
    assert node.tool_calls == []


@pytest.mark.asyncio
async def test_user_triggered_node_resolves_user_display_name():
    """A directly user-triggered agent node returns ``trigger_source="user"``
    with the triggering user's display name as the label.
    """
    job_id = uuid.uuid4()
    user_id = uuid.uuid4()
    job = _make_agent_job(job_id, uuid.uuid4(), triggered_by_user_id=user_id)
    db = _build_db(
        agent_jobs=[job],
        identity_rows=[(user_id, "Alice Operator")],
    )
    projection = await RuntimeTopologyController().get_active_topology(db)

    node = projection.nodes[0]
    assert node.trigger_source == "user"
    assert node.trigger_source_label == "Alice Operator"


@pytest.mark.asyncio
async def test_schedule_triggered_node_resolves_schedule_creator():
    """A schedule-triggered node returns ``trigger_source="schedule"`` with the
    schedule NAME as ``trigger_source_label`` and the schedule CREATOR's
    display name (the scheduler passes ``scheduled_by_user_id`` through as
    ``triggered_by_user_id``) as ``trigger_user_label``.

    Phase 13: the creator attribution NEVER falls back to the schedule name —
    the schedule name belongs only in ``trigger_source_label`` (it identifies
    the schedule entity), while ``trigger_user_label`` stays a HUMAN name or
    ``None`` so downstream UI never renders the schedule name as a person.
    """
    job_id = uuid.uuid4()
    job = _make_agent_job(job_id, uuid.uuid4(), triggered_by_user_id=uuid.uuid4())
    db = _build_db(
        agent_jobs=[job],
        identity_rows=[(job.triggered_by_user_id, "Alice Operator")],
        schedule_rows=[({"session_id": str(job_id)}, "nightly-cleanup", uuid.uuid4(), "0 2 * * *", "Nightly cleanup")],
    )
    projection = await RuntimeTopologyController().get_active_topology(db)

    node = projection.nodes[0]
    assert node.trigger_source == "schedule"
    # Label = schedule NAME; creator user goes to trigger_user_label.
    assert node.trigger_source_label == "nightly-cleanup"
    assert node.trigger_user_label == "Alice Operator"

    # Unknown creator (pre-provenance schedule / deleted identity) → the
    # user label is null while the schedule name stays on the source label.
    orphan_job_id = uuid.uuid4()
    orphan_job = _make_agent_job(orphan_job_id, uuid.uuid4(), triggered_by_user_id=None)
    db2 = _build_db(
        agent_jobs=[orphan_job],
        identity_rows=[],
        schedule_rows=[({"session_id": str(orphan_job_id)}, "nightly-cleanup", uuid.uuid4(), "0 2 * * *", None)],
    )
    projection2 = await RuntimeTopologyController().get_active_topology(db2)
    orphan_node = projection2.nodes[0]
    assert orphan_node.trigger_source == "schedule"
    assert orphan_node.trigger_source_label == "nightly-cleanup"
    assert orphan_node.trigger_user_label is None


@pytest.mark.asyncio
async def test_delegated_node_resolves_parent_trigger_source():
    """A delegated child (has a parent_sESSION edge) returns
    ``trigger_source="delegated"`` and inherits the original user's display
    name.
    """
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()
    user_id = uuid.uuid4()

    parent = _make_agent_job(parent_id, uuid.uuid4(), triggered_by_user_id=user_id)
    child = _make_agent_job(child_id, uuid.uuid4(), triggered_by_user_id=user_id)

    edge = MagicMock()
    edge.parent_agent_job_id = parent_id
    edge.child_agent_job_id = child_id
    edge.depth_from_root = 1

    db = _build_db(
        agent_jobs=[parent, child],
        identity_rows=[(user_id, "Alice Operator")],
        edge_rows=[edge],
    )
    projection = await RuntimeTopologyController().get_active_topology(db)

    child_node = next(n for n in projection.nodes if n.session_id == child_id)
    assert child_node.parent_session_id == parent_id
    assert child_node.trigger_source == "delegated"
    assert child_node.trigger_source_label == "Alice Operator"

    parent_node = next(n for n in projection.nodes if n.session_id == parent_id)
    assert parent_node.trigger_source == "user"


@pytest.mark.asyncio
async def test_node_without_trigger_stays_unknown():
    """A node with no determinable trigger source returns ``"unknown"`` with a
    ``None`` label (no exception).
    """
    job_id = uuid.uuid4()
    job = _make_agent_job(job_id, uuid.uuid4(), triggered_by_user_id=None)
    db = _build_db(agent_jobs=[job])
    projection = await RuntimeTopologyController().get_active_topology(db)

    node = projection.nodes[0]
    assert node.trigger_source == "unknown"
    assert node.trigger_source_label is None


# ── Tool-call history resolution ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_calls_resolved_with_mcp_slug_in_chronological_order():
    """An agent with recorded tool calls returns a per-node list with tool
    name + MCP slug + timestamp, latest-first (the controller sorts
    ``created_at`` descending).
    """
    job_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    job = _make_agent_job(job_id, uuid.uuid4())

    t1 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 6, 1, 12, 0, 5, tzinfo=timezone.utc)

    # The controller queries with ``ORDER BY created_at DESC``; the mock
    # returns rows in that order (latest first), mirroring the real DB.
    db = _build_db(
        agent_jobs=[job],
        tool_call_rows=[
            (conv_id, job_id, "github____create_issue", t2),
            (conv_id, job_id, "github____list_prs", t1),
        ],
    )
    projection = await RuntimeTopologyController().get_active_topology(db)

    node = next(n for n in projection.nodes if n.session_id == job_id)
    assert len(node.tool_calls) == 2
    # Latest first (t2 before t1).
    assert node.tool_calls[0].tool_name == "github____create_issue"
    assert node.tool_calls[0].mcp_slug == "github"
    assert node.tool_calls[0].called_at == t2
    assert node.tool_calls[1].tool_name == "github____list_prs"
    assert node.tool_calls[1].mcp_slug == "github"


@pytest.mark.asyncio
async def test_system_tool_call_preserved_with_system_slug():
    """A system tool call maps to the reserved ``system`` slug.
    """
    job_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    job = _make_agent_job(job_id, uuid.uuid4())

    db = _build_db(
        agent_jobs=[job],
        tool_call_rows=[(conv_id, job_id, "system____save_data", None)],
    )
    projection = await RuntimeTopologyController().get_active_topology(db)

    node = projection.nodes[0]
    assert len(node.tool_calls) == 1
    assert node.tool_calls[0].mcp_slug == "system"


@pytest.mark.asyncio
async def test_unparseable_tool_name_degrades_to_unknown_slug():
    """A tool name without a ``server____tool`` namespace still returns the
    entry with slug ``"unknown"`` (call not dropped, node not crashed).
    """
    job_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    job = _make_agent_job(job_id, uuid.uuid4())

    db = _build_db(
        agent_jobs=[job],
        tool_call_rows=[(conv_id, job_id, "bare_tool_name", None)],
    )
    projection = await RuntimeTopologyController().get_active_topology(db)

    node = projection.nodes[0]
    assert len(node.tool_calls) == 1
    assert node.tool_calls[0].mcp_slug == "unknown"


@pytest.mark.asyncio
async def test_no_tool_calls_returns_empty_list():
    """An agent with no tool calls returns an empty list (no error, no
    phantom route).
    """
    job_id = uuid.uuid4()
    job = _make_agent_job(job_id, uuid.uuid4())
    db = _build_db(agent_jobs=[job], tool_call_rows=[])
    projection = await RuntimeTopologyController().get_active_topology(db)

    node = projection.nodes[0]
    assert node.tool_calls == []


# ── Terminal direct children of included jobs (live-data round) ────────────────


@pytest.mark.asyncio
async def test_terminal_direct_children_of_active_job_appear_with_edge():
    """A terminal direct child (e.g. a failed delegated attempt) of an
    included job is added to the projection even though its own status is
    not in the included-status set — so the delegation edge renders.  This
    mirrors the live case: a ``waiting_for_human`` parent whose delegated
    children already failed would otherwise show no children and no edges.
    """
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()
    at_id = uuid.uuid4()

    parent = _make_agent_job(parent_id, at_id, AgentJobStatus.waiting_for_human)
    failed_child = _make_agent_job(
        child_id, uuid.uuid4(), AgentJobStatus.failed, parent_job_id=parent_id
    )

    # Live status list only includes the parent; the child fetch returns the
    # terminal child.
    db = _build_db(
        agent_jobs=[parent],
        child_jobs=[failed_child],
    )
    projection = await RuntimeTopologyController().get_active_topology(
        db,
        include_statuses=[
            AgentJobStatus.queued,
            AgentJobStatus.running,
            AgentJobStatus.waiting_for_human,
        ],
    )

    by_id = {n.session_id: n for n in projection.nodes}
    assert parent_id in by_id
    assert child_id in by_id, "terminal direct child must appear for edge visibility"

    child_node = by_id[child_id]
    assert child_node.kind == "agent"
    assert child_node.status == "failed"
    assert child_node.parent_session_id == parent_id
    assert child_node.depth_from_root == 1

    # The delegation edge parent → child is present.
    edge = next(
        e
        for e in projection.edges
        if e.child_session_id == child_id and e.parent_session_id == parent_id
    )
    assert edge.depth_from_root == 1

    # Parent remains a root; child is not a root.
    assert parent_id in projection.root_session_ids
    assert child_id not in projection.root_session_ids


@pytest.mark.asyncio
async def test_terminal_children_fetch_is_budget_capped():
    """The terminal-children fetch respects the remaining ``max_nodes``
    budget: with one active job and ``max_nodes=2`` the child query is
    capped at ``LIMIT 1``.
    """
    parent_id = uuid.uuid4()
    parent = _make_agent_job(parent_id, uuid.uuid4(), AgentJobStatus.running)

    statements: list = []
    db = _build_db(agent_jobs=[parent], statements=statements)
    await RuntimeTopologyController().get_active_topology(db, max_nodes=2)

    child_stmt = next(s for s in statements if ".parent_job_id IN" in str(s))
    limit_value = child_stmt._limit_clause.value
    assert limit_value == 1, (
        "child fetch must be capped by the remaining node budget (2 - 1 active), "
        f"got LIMIT {limit_value}"
    )


@pytest.mark.asyncio
async def test_terminal_children_fetch_skipped_without_budget():
    """When the active set already fills ``max_nodes`` no child query with
    a positive limit budget is meaningful — the controller must not issue a
    child fetch that could exceed the cap (budget = 0 → no fetch).
    """
    at_id = uuid.uuid4()
    jobs = [_make_agent_job(uuid.uuid4(), at_id, AgentJobStatus.running) for _ in range(2)]

    statements: list = []
    db = _build_db(agent_jobs=jobs, statements=statements)
    await RuntimeTopologyController().get_active_topology(db, max_nodes=2)

    assert not any(".parent_job_id IN" in str(s) for s in statements), (
        "no terminal-children fetch should run when the node budget is exhausted"
    )


# ── Conversation live-driver semantics (live-data round) ───────────────────────


@pytest.mark.asyncio
async def test_conversation_with_waiting_for_human_backing_job_is_active():
    """A conversation whose backing agent job is paused in
    ``waiting_for_human`` computes runtime status ``"active"`` — not
    ``"sleep"``.  A HITL-paused agent is still engaged with the
    conversation.
    """
    job_id = uuid.uuid4()
    at_id = uuid.uuid4()
    conv_id = uuid.uuid4()

    job = _make_agent_job(job_id, at_id, AgentJobStatus.waiting_for_human)
    conv = _make_conv(
        conv_id,
        at_id,
        status=ConversationStatus.active,
        agent_job_id=job_id,
    )
    db = _build_db(agent_jobs=[job], convs=[conv])
    projection = await RuntimeTopologyController().get_active_topology(db)

    conv_node = next(n for n in projection.nodes if n.session_id == conv_id)
    assert conv_node.status == "active"
    assert conv_node.parent_session_id == job_id


@pytest.mark.asyncio
async def test_conversation_counts_chat_spawned_linked_jobs_as_live_drivers():
    """Chat turns run WITHOUT a backing AgentJob — jobs spawned by the chat
    carry the source conversation id in ``input_data.__conv_session_id``.
    Such a linked, live job counts as a live driver: the conversation
    computes ``"active"`` (not ``"sleep"``) and an edge conversation → job
    is emitted so the spawned run renders under the conversation.
    """
    conv_id = uuid.uuid4()
    job_id = uuid.uuid4()
    at_id = uuid.uuid4()

    conv = _make_conv(conv_id, at_id, status=ConversationStatus.active)  # no backing job
    linked_job = _make_agent_job(
        job_id,
        uuid.uuid4(),
        AgentJobStatus.running,
        input_data={"__conv_session_id": str(conv_id)},
    )

    db = _build_db(agent_jobs=[linked_job], convs=[conv])
    projection = await RuntimeTopologyController().get_active_topology(db)

    conv_node = next(n for n in projection.nodes if n.session_id == conv_id)
    assert conv_node.status == "active", (
        "chat-spawned live job must keep the conversation active, not sleep"
    )
    # The conversation is a root; the spawned job is its child.
    assert conv_node.parent_session_id is None
    assert conv_id in projection.root_session_ids

    job_node = next(n for n in projection.nodes if n.session_id == job_id)
    assert job_node.parent_session_id == conv_id
    assert job_node.depth_from_root == 1
    assert any(
        e.parent_session_id == conv_id and e.child_session_id == job_id
        for e in projection.edges
    )


@pytest.mark.asyncio
async def test_conversation_with_terminal_linked_job_stays_sleep():
    """A conversation whose only linked job is terminal (e.g. failed) is
    NOT considered active — the linked-job driver only counts when the job
    is in a live state (queued/running/waiting_for_human).
    """
    conv_id = uuid.uuid4()
    job_id = uuid.uuid4()
    at_id = uuid.uuid4()

    conv = _make_conv(conv_id, at_id, status=ConversationStatus.active)
    failed_linked_job = _make_agent_job(
        job_id,
        uuid.uuid4(),
        AgentJobStatus.failed,
        input_data={"__conv_session_id": str(conv_id)},
    )

    db = _build_db(agent_jobs=[failed_linked_job], convs=[conv])
    projection = await RuntimeTopologyController().get_active_topology(db)

    conv_node = next(n for n in projection.nodes if n.session_id == conv_id)
    assert conv_node.status == "sleep"


# ── Phase 12: sanitised-name slug fallback + A2A exclusion ────────────────────


@pytest.mark.asyncio
async def test_sanitized_tool_name_resolves_mcp_slug():
    """A recorder row written with the OpenAI-SANITISED name (2-underscore
    separator — the sanitiser converts the canonical ``____`` to ``__``)
    resolves to the right MCP server slug instead of degrading to
    ``unknown`` (``supabase__get_project`` → ``supabase``).
    """
    job_id = uuid.uuid4()
    job = _make_agent_job(job_id, uuid.uuid4())

    db = _build_db(
        agent_jobs=[job],
        runtime_tool_call_rows=[(job_id, "supabase__get_project", "mcp", None)],
    )
    projection = await RuntimeTopologyController().get_active_topology(db)

    node = projection.nodes[0]
    assert len(node.tool_calls) == 1
    assert node.tool_calls[0].tool_name == "supabase__get_project"
    assert node.tool_calls[0].mcp_slug == "supabase"
    assert node.tool_calls[0].route_type == "mcp"


@pytest.mark.asyncio
async def test_bare_legacy_tool_name_stays_system_slug():
    """A bare legacy system tool name (no separator) still resolves to the
    reserved ``system`` slug — the fallback must not change that contract.
    """
    job_id = uuid.uuid4()
    job = _make_agent_job(job_id, uuid.uuid4())

    db = _build_db(
        agent_jobs=[job],
        runtime_tool_call_rows=[(job_id, "save_data", "system", None)],
    )
    projection = await RuntimeTopologyController().get_active_topology(db)

    assert projection.nodes[0].tool_calls[0].mcp_slug == "system"


@pytest.mark.asyncio
async def test_sanitized_name_with_empty_parts_degrades_to_unknown():
    """A sanitised-style name whose split yields an empty component (e.g.
    leading separator) degrades to ``unknown`` rather than crashing or
    producing a phantom empty slug.
    """
    job_id = uuid.uuid4()
    job = _make_agent_job(job_id, uuid.uuid4())

    db = _build_db(
        agent_jobs=[job],
        runtime_tool_call_rows=[(job_id, "__get_project", "mcp", None)],
    )
    projection = await RuntimeTopologyController().get_active_topology(db)

    assert projection.nodes[0].tool_calls[0].mcp_slug == "unknown"


@pytest.mark.asyncio
async def test_runtime_tool_calls_exclude_a2a_delegation_rows():
    """``RuntimeToolCall`` rows with ``route_type='a2a'`` are agent-to-agent
    delegations, not tool executions — the history query must filter them
    out so delegation calls never render as MCP routes.
    """
    job_id = uuid.uuid4()
    job = _make_agent_job(job_id, uuid.uuid4())

    statements: list = []
    db = _build_db(agent_jobs=[job], statements=statements)
    await RuntimeTopologyController().get_active_topology(db)

    rtc_stmt = next(s for s in statements if "runtime_tool_calls" in str(s))

    # Walk the WHERE clause tree and collect every literal bind value so the
    # ``route_type != 'a2a'`` exclusion can be asserted without depending on
    # the clause ordering produced by SQLAlchemy.
    literals: set[str] = set()

    def _collect(clause: object) -> None:
        value = getattr(clause, "value", None)
        if value is not None:
            raw = value
            # Unwrap param/enum wrappers until the plain literal; str-Enum
            # members ARE str instances, so exact-type check is required.
            while type(raw) is not str and hasattr(raw, "value"):
                raw = raw.value
            literals.add(str(raw))
        for side in ("left", "right"):
            child = getattr(clause, side, None)
            if child is not None and child is not clause:
                _collect(child)
        for sub in getattr(clause, "clauses", None) or []:
            _collect(sub)

    _collect(rtc_stmt.whereclause)
    assert "a2a" in literals, (
        "runtime tool-call history query must exclude route_type='a2a' rows"
    )


@pytest.mark.asyncio
async def test_tool_call_route_type_propagates():
    """The recorded ``route_type`` value is surfaced on each ``ToolCallRoute``
    so the API schema (and frontend) can distinguish system/mcp rows.
    """
    job_id = uuid.uuid4()
    job = _make_agent_job(job_id, uuid.uuid4())

    db = _build_db(
        agent_jobs=[job],
        runtime_tool_call_rows=[
            (job_id, "github____list_prs", "mcp", None),
            (job_id, "system____save_data", "system", None),
        ],
    )
    projection = await RuntimeTopologyController().get_active_topology(db)

    by_name = {c.tool_name: c for c in projection.nodes[0].tool_calls}
    assert by_name["github____list_prs"].route_type == "mcp"
    assert by_name["system____save_data"].route_type == "system"
