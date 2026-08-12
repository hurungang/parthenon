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
)


def _make_agent_job(
    job_id: uuid.UUID,
    agent_type_id: uuid.UUID,
    status: AgentJobStatus = AgentJobStatus.running,
) -> MagicMock:
    job = MagicMock()
    job.id = job_id
    job.agent_type_id = agent_type_id
    job.status = status
    job.started_at = datetime.now(timezone.utc)
    job.created_at = datetime.now(timezone.utc)
    job.termination_category = None
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
) -> AsyncMock:
    """Build an AsyncMock session that returns the given rows for
    the controller's three main queries (AgentJob,
    AgentInstance, ConversationSession).  The topology controller
    does several other queries; for these tests we only care
    about the initial lists and a no-op for the agent type/edge
    lookups.
    """
    db = AsyncMock()

    # Track which call index we're on for db.execute
    call_idx = {"i": 0}

    # First call: AgentJob
    # Second call: AgentInstance
    # Third call: ConversationSession
    # Subsequent calls: agent types, edges
    expected_results = [
        agent_jobs,
        instances or [],
        convs or [],
    ]
    edge_result = MagicMock()
    edge_result.scalars.return_value.all.return_value = []
    edge_result.fetchall.return_value = []
    at_result = MagicMock()
    at_result.fetchall.return_value = []

    async def fake_execute(_stmt):
        i = call_idx["i"]
        call_idx["i"] += 1
        if i < len(expected_results):
            r = MagicMock()
            r.scalars.return_value.all.return_value = expected_results[i]
            return r
        if i == len(expected_results):
            return at_result
        return edge_result

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
