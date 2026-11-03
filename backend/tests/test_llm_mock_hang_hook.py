"""FIX-20261031-091657 — test-only hang/delay hooks in the LLM mock provider.

Real-turn verification needs to simulate a hanging model through the live
stack: ``LLM_MOCK_DELAY_SECONDS`` delays every completion; ``LLM_MOCK_HANG=1``
blocks forever.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.services.agents.llm_mock_provider import MockChatModel, reset_mock_store


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.setenv("LLM_MOCK_MODE", "scripted")
    monkeypatch.setenv("LLM_MOCK_SCRIPTED_RESPONSES", '[{"match": "hello", "response": "hi there"}]')
    monkeypatch.delenv("LLM_MOCK_DELAY_SECONDS", raising=False)
    monkeypatch.delenv("LLM_MOCK_HANG", raising=False)
    reset_mock_store()
    yield
    reset_mock_store()


@pytest.mark.asyncio
async def test_mock_delay_hook_delays_completion(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MOCK_DELAY_SECONDS", "0.3")
    model = MockChatModel(model_identifier="test")
    started = time.monotonic()
    result = await model._agenerate([{"role": "user", "content": "hello"}])
    elapsed = time.monotonic() - started
    assert result.generations[0].message.content == "hi there"
    assert elapsed >= 0.25


@pytest.mark.asyncio
async def test_mock_hang_hook_blocks_forever(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MOCK_HANG", "1")
    model = MockChatModel(model_identifier="test")
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(model._agenerate([{"role": "user", "content": "hello"}]), timeout=0.3)
