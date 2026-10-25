"""Unit tests for the LLM Mock Layer (Phase 5.4).

Covers:
- Scripted mode: deterministic rule matching, unmatched prompts fail loudly
- Record mode: request/response capture with prompt+usage only
- Replay mode: deterministic replay by recording_key, unmatched → loud error
- Key matching: identical inputs → identical keys; different inputs differ
- Semantic-bridge endpoint mocking (4.5)
- Env/config selection (4.4): default off, invalid mode fails fast
- Prompt-assertion helpers (4.6)
- Dispatch-layer integration: LangChainModelFactory returns the mock provider
"""
from __future__ import annotations

import pytest

from app.services.agents import llm_mock_provider as mock_layer
from app.services.agents.llm_mock_provider import (
    LLMMockConfigurationError,
    MockChatModel,
    assert_prompt_contains,
    assert_prompt_structure,
    compute_recording_key,
    get_mock_mode,
    maybe_mock_model,
    maybe_mock_semantic_bridge,
    reset_mock_store,
)


@pytest.fixture(autouse=True)
def _clean_mock_env(monkeypatch):
    reset_mock_store()
    monkeypatch.delenv("LLM_MOCK_MODE", raising=False)
    monkeypatch.delenv("LLM_MOCK_SCRIPTED_RESPONSES", raising=False)
    monkeypatch.delenv("LLM_MOCK_RECORDINGS_FILE", raising=False)
    yield
    reset_mock_store()


SCRIPTED = [
    {"match": " quarterly sales report", "response": "Q3 sales: $1.2M (scripted)"},
    {"match": "hello", "response": "Hi there (scripted)"},
]


def _model(**kwargs) -> MockChatModel:
    return MockChatModel(model_identifier="openai/gpt-4o", **kwargs)


# ── Env/config selection (4.4) ───────────────────────────────────────────────


class TestModeSelection:
    def test_default_mode_is_off(self):
        assert get_mock_mode() == "off"
        assert maybe_mock_model("openai", "gpt-4o") is None

    def test_invalid_mode_fails_fast(self, monkeypatch):
        monkeypatch.setenv("LLM_MOCK_MODE", "yolo")
        with pytest.raises(LLMMockConfigurationError):
            get_mock_mode()

    def test_scripted_mode_requires_rules(self, monkeypatch):
        monkeypatch.setenv("LLM_MOCK_MODE", "scripted")
        with pytest.raises(LLMMockConfigurationError):
            _model().invoke([_user("anything")])


def _user(text: str):
    from langchain_core.messages import HumanMessage

    return HumanMessage(content=text)


# ── Scripted mode (4.1) ──────────────────────────────────────────────────────


class TestScriptedMode:
    def test_rule_matching_is_deterministic(self, monkeypatch):
        monkeypatch.setenv("LLM_MOCK_MODE", "scripted")
        monkeypatch.setenv(
            "LLM_MOCK_SCRIPTED_RESPONSES", __import__("json").dumps(SCRIPTED)
        )
        model = _model()
        first = model.invoke([_user("Generate the quarterly sales report for Q3")])
        second = model.invoke([_user("Generate the quarterly sales report for Q3")])
        assert first.content == second.content == "Q3 sales: $1.2M (scripted)"
        other = model.invoke([_user("hello there")])
        assert other.content == "Hi there (scripted)"

    def test_unmatched_prompt_fails_loudly(self, monkeypatch):
        monkeypatch.setenv("LLM_MOCK_MODE", "scripted")
        monkeypatch.setenv(
            "LLM_MOCK_SCRIPTED_RESPONSES", __import__("json").dumps(SCRIPTED)
        )
        with pytest.raises(LLMMockConfigurationError, match="No scripted"):
            _model().invoke([_user("completely unrelated prompt")])

    def test_factory_returns_mock_provider(self, monkeypatch):
        from app.services.agents.langchain_model_factory import LangChainModelFactory

        monkeypatch.setenv("LLM_MOCK_MODE", "scripted")
        monkeypatch.setenv(
            "LLM_MOCK_SCRIPTED_RESPONSES", __import__("json").dumps(SCRIPTED)
        )
        model = LangChainModelFactory().get_model(
            "openai", "gpt-4o", api_key="should-not-be-used"
        )
        assert isinstance(model, MockChatModel)


# ── Record → replay round trip (4.2 / 4.3) ───────────────────────────────────


class TestRecordReplay:
    def test_record_then_replay_round_trip(self, monkeypatch):
        monkeypatch.setenv("LLM_MOCK_MODE", "record")
        monkeypatch.setenv(
            "LLM_MOCK_SCRIPTED_RESPONSES", __import__("json").dumps(SCRIPTED)
        )
        model = _model(interaction_kind="agent_loop")
        messages = [_user("hello agent")]
        first = model.invoke(messages)
        assert first.content == "Hi there (scripted)"
        recordings = mock_layer.captured_recordings()
        assert len(recordings) == 1
        recording = recordings[0]
        # Prompt + response + usage only — no credentials (N4).
        assert recording["request_payload"]["messages"][0]["content"] == "hello agent"
        assert recording["response_payload"]["text"] == "Hi there (scripted)"
        assert "api_key" not in __import__("json").dumps(recording)

        # Replay the identical request deterministically.
        monkeypatch.setenv("LLM_MOCK_MODE", "replay")
        replayed = _model(interaction_kind="agent_loop").invoke(messages)
        assert replayed.content == first.content

    def test_replay_unmatched_fails_loudly(self, monkeypatch):
        monkeypatch.setenv("LLM_MOCK_MODE", "replay")
        with pytest.raises(LLMMockConfigurationError, match="No LLM mock recording"):
            _model().invoke([_user("never recorded")])

    def test_key_matches_on_content_only(self):
        key_a = compute_recording_key("m", [{"role": "user", "content": "x"}])
        key_b = compute_recording_key("m", [{"role": "user", "content": "x"}])
        key_c = compute_recording_key("m", [{"role": "user", "content": "y"}])
        key_d = compute_recording_key(
            "m", [{"role": "user", "content": "x"}], interaction_kind="semantic_bridge"
        )
        assert key_a == key_b
        assert key_a != key_c
        assert key_a != key_d  # interaction kind is part of the key

    def test_replay_source_hook(self, monkeypatch):
        monkeypatch.setenv("LLM_MOCK_MODE", "replay")
        key = compute_recording_key(
            "openai/gpt-4o", [{"role": "user", "content": "x"}]
        )
        mock_layer.set_replay_source(
            lambda k: {"response_payload": {"text": "from CC"}}
            if k == key else None
        )
        result = _model().invoke([_user("x")])
        assert result.content == "from CC"


# ── Semantic-bridge endpoint mocking (4.5) ───────────────────────────────────


class TestSemanticBridgeMocking:
    def test_inactive_returns_none_production_path(self):
        assert maybe_mock_semantic_bridge("any prompt", "m") is None

    def test_scripted_bridge_response(self, monkeypatch):
        monkeypatch.setenv("LLM_MOCK_MODE", "scripted")
        monkeypatch.setenv(
            "LLM_MOCK_SCRIPTED_RESPONSES",
            __import__("json").dumps(
                [{"match": "Input data", "response": "BRIDGED"}]
            ),
        )
        text = maybe_mock_semantic_bridge("prompt\n\nInput data:\n{}", "m")
        assert text == "BRIDGED"

    def test_bridge_record_replay(self, monkeypatch):
        monkeypatch.setenv("LLM_MOCK_MODE", "record")
        monkeypatch.setenv(
            "LLM_MOCK_SCRIPTED_RESPONSES",
            __import__("json").dumps([{"match": "prompt", "response": "BRIDGED"}]),
        )
        message = "some prompt"
        assert maybe_mock_semantic_bridge(message, "m") == "BRIDGED"
        monkeypatch.setenv("LLM_MOCK_MODE", "replay")
        assert maybe_mock_semantic_bridge(message, "m") == "BRIDGED"


# ── Prompt-assertion helpers (4.6) ───────────────────────────────────────────


class TestPromptAssertions:
    def test_assert_prompt_contains(self, monkeypatch):
        monkeypatch.setenv("LLM_MOCK_MODE", "record")
        monkeypatch.setenv(
            "LLM_MOCK_SCRIPTED_RESPONSES", __import__("json").dumps(SCRIPTED)
        )
        _model().invoke([_user("hello recording world")])
        assert_prompt_contains("recording world")
        with pytest.raises(AssertionError):
            assert_prompt_contains("absent-fragment-xyz")

    def test_assert_prompt_structure(self, monkeypatch):
        monkeypatch.setenv("LLM_MOCK_MODE", "record")
        monkeypatch.setenv(
            "LLM_MOCK_SCRIPTED_RESPONSES", __import__("json").dumps(SCRIPTED)
        )
        _model().invoke([_user("hello again")])
        assert_prompt_structure(min_messages=1, kinds=["user"])
        with pytest.raises(AssertionError):
            assert_prompt_structure(min_messages=5)
