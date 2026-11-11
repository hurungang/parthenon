"""CH data-client activity methods (CH -> CC internal data API).

CH must never write the database; these methods are the only CH->CC activity
calls and must use the standard egress path (``internal_httpx_client`` inside
``_put``/``_get``) with the CC URL prefix.
"""
import uuid

import pytest

from app.communication_hub.data_client import ControlCenterDataClient, ControlCenterDataError


def _client() -> ControlCenterDataClient:
    return ControlCenterDataClient(cert_manager=None, control_center_url="https://cc.test")


class TestUpsertConversationActivity:
    @pytest.mark.asyncio
    async def test_upsert_posts_full_payload_to_activity_path(self):
        client = _client()
        captured = {}

        async def fake_put(path, body):
            captured["path"] = path
            captured["body"] = body
            return {"state": body["state"]}

        client._put = fake_put  # type: ignore[assignment]
        conv_id = uuid.uuid4()
        turn_id = uuid.uuid4()

        result = await client.upsert_conversation_activity(
            conv_id,
            "using_tool",
            current_turn_id=turn_id,
            tool_name="cc____list_agents",
            detail={"agent_type": "assistant"},
        )

        assert result == {"state": "using_tool"}
        assert captured["path"] == f"/internal/data/conversations/{conv_id}/activity"
        assert captured["body"]["state"] == "using_tool"
        assert captured["body"]["current_turn_id"] == str(turn_id)
        assert captured["body"]["tool_name"] == "cc____list_agents"
        assert captured["body"]["detail"] == {"agent_type": "assistant"}

    @pytest.mark.asyncio
    async def test_upsert_omits_none_optional_fields(self):
        client = _client()
        captured = {}

        async def fake_put(path, body):
            captured["body"] = body
            return {"state": body["state"]}

        client._put = fake_put  # type: ignore[assignment]
        await client.upsert_conversation_activity(uuid.uuid4(), "thinking")
        assert captured["body"] == {"state": "thinking"}


class TestGetConversationActivity:
    @pytest.mark.asyncio
    async def test_get_returns_persisted_record(self):
        client = _client()
        conv_id = uuid.uuid4()

        async def fake_get(path):
            assert path == f"/internal/data/conversations/{conv_id}/activity"
            return {"state": "waiting_for_human", "is_terminal": False}

        client._get = fake_get  # type: ignore[assignment]
        result = await client.get_conversation_activity(conv_id)
        assert result == {"state": "waiting_for_human", "is_terminal": False}

    @pytest.mark.asyncio
    async def test_get_returns_none_on_404(self):
        client = _client()

        async def fake_get(path):
            raise ControlCenterDataError(f"CC GET {path} returned 404: not found")

        client._get = fake_get  # type: ignore[assignment]
        assert await client.get_conversation_activity(uuid.uuid4()) is None

    @pytest.mark.asyncio
    async def test_get_reraises_non_404(self):
        client = _client()

        async def fake_get(path):
            raise ControlCenterDataError(f"CC GET {path} returned 500: boom")

        client._get = fake_get  # type: ignore[assignment]
        with pytest.raises(ControlCenterDataError):
            await client.get_conversation_activity(uuid.uuid4())
