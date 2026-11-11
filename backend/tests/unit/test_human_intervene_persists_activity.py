"""Regression: conversation-scoped human_intervene must persist the activity state.

When the conversational assistant calls ``human_intervene`` (confirm-before-write),
the status is persisted as ``waiting_for_human`` on the ``ConversationActivity``
record so the processing bubble can be reconstructed from the authoritative
persisted state (reload/reconnect/failover) — not just the transient
``intervene_request`` WebSocket event.
"""
import uuid

import pytest

from app.api.v1.internal.system_tools import SystemToolRequest, human_intervene_tool
from app.core.tenant_context import TenantContext
from app.db.models.conversation_activity import ActivityState
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.services.conversations.activity_store import ConversationActivityStore


@pytest.mark.asyncio
async def test_human_intervene_persists_waiting_for_human(db_session, monkeypatch):
    # No-op the CH dispatch (and notification send is already best-effort).
    from app.services.control_center import comm_hub_client as cc_client

    async def _noop_dispatch(self, **kwargs):
        return None

    monkeypatch.setattr(cc_client.CommunicationHubClient, "dispatch_message", _noop_dispatch)

    agent_type_id = uuid.uuid4()
    conv = ConversationSession(status=ConversationStatus.active, agent_type_id=agent_type_id)
    db_session.add(conv)
    await db_session.flush()

    body = SystemToolRequest(
        session_id=str(conv.id),  # no AgentJob -> resolves via conversation_session_id
        agent_type_id=str(agent_type_id),
        tool_args={"intervention_type": "approval", "reason": "Please confirm this change"},
        conversation_session_id=str(conv.id),
    )
    tenant_ctx = TenantContext(tenant_id=uuid.uuid4(), slug="test-tenant", name="test-tenant")

    response = await human_intervene_tool(body, tenant_ctx, db_session)

    request_id = response.result["request_id"]
    activity = await ConversationActivityStore().get(conv.id, db_session)
    assert activity is not None
    assert activity.state == ActivityState.waiting_for_human
    assert activity.pending_intervene_request_id == uuid.UUID(request_id)
    assert activity.is_terminal is False
