"""Mock LLM Provider — scripted / record / replay for zero-LLM test runs (Phase 4).

A ``BaseChatModel`` implementation registered in the model dispatch layer
(``LangChainModelFactory``). Selected via configuration/env — effective only
in test environments; production default is ``off``:

- ``LLM_MOCK_MODE``: ``off`` (default) | ``scripted`` | ``record`` | ``replay``
- ``LLM_MOCK_SCRIPTED_RESPONSES``: inline JSON or ``@/path/file.json`` —
  a list of ``{"match": "<substring>", "response": "<text>"}`` rules; the
  first rule whose ``match`` occurs in the prompt wins (deterministic).
- ``LLM_MOCK_RECORDINGS_FILE``: JSON file backing the default in-process
  record/replay store.

Replay matches calls by ``recording_key`` — a deterministic SHA-256 of the
serialized request (model + messages + tools); identical inputs replay
identically, unmatched calls fail loudly (test failure, never a silent
real call). Recordings carry prompt + response + usage metadata only —
never API keys or identity tokens (they are never accepted in payloads).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from typing import Any, Callable, List, Optional

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

logger = logging.getLogger(__name__)

# ── Mode configuration (4.4) ─────────────────────────────────────────────────

MODE_OFF = "off"
MODE_SCRIPTED = "scripted"
MODE_RECORD = "record"
MODE_REPLAY = "replay"
_VALID_MODES = {MODE_OFF, MODE_SCRIPTED, MODE_RECORD, MODE_REPLAY}


class LLMMockConfigurationError(Exception):
    """Misconfigured mock layer — fails fast (never silently calls a real LLM)."""


def get_mock_mode() -> str:
    """Read ``LLM_MOCK_MODE`` (default ``off``); unknown values fail fast."""
    mode = (os.environ.get("LLM_MOCK_MODE") or MODE_OFF).strip().lower()
    if mode not in _VALID_MODES:
        raise LLMMockConfigurationError(
            f"LLM_MOCK_MODE='{mode}' is invalid — expected one of "
            f"{sorted(_VALID_MODES)}"
        )
    return mode


def _load_scripted_rules() -> list[dict[str, str]]:
    raw = os.environ.get("LLM_MOCK_SCRIPTED_RESPONSES") or ""
    if raw.startswith("@"):
        path = raw[1:]
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    if not raw.strip():
        raise LLMMockConfigurationError(
            "LLM_MOCK_MODE=scripted requires LLM_MOCK_SCRIPTED_RESPONSES "
            "(inline JSON or @/path/file.json)"
        )
    data = json.loads(raw)
    if isinstance(data, dict):
        data = [{"match": k, "response": v} for k, v in data.items()]
    if not isinstance(data, list) or not all(
        isinstance(rule, dict) and "match" in rule and "response" in rule
        for rule in data
    ):
        raise LLMMockConfigurationError(
            "LLM_MOCK_SCRIPTED_RESPONSES must be a list of "
            '{"match": ..., "response": ...} rules'
        )
    return data


# ── Recording store (in-process default; CC persistence via AR client) ───────

_store_lock = threading.Lock()
_recordings: dict[str, dict[str, Any]] = {}

RecordSink = Callable[[dict[str, Any]], None]
ReplaySource = Callable[[str], dict[str, Any] | None]

_record_sink: RecordSink | None = None
_replay_source: ReplaySource | None = None


def set_record_sink(sink: RecordSink | None) -> None:
    """Register a persistence sink (e.g. AR CC-client batched submit)."""
    global _record_sink
    _record_sink = sink


def set_replay_source(source: ReplaySource | None) -> None:
    """Register a replay lookup (e.g. AR CC-client recording fetch)."""
    global _replay_source
    _replay_source = source


def reset_mock_store() -> None:
    """Clear the in-process store and custom sinks/sources (tests)."""
    global _record_sink, _replay_source
    with _store_lock:
        _recordings.clear()
    _record_sink = None
    _replay_source = None


def captured_recordings() -> list[dict[str, Any]]:
    """All in-process recordings (for tests / batched persistence)."""
    with _store_lock:
        return list(_recordings.values())


def _persist(recording: dict[str, Any]) -> None:
    with _store_lock:
        _recordings[recording["recording_key"]] = recording
    if _record_sink is not None:
        try:
            _record_sink(recording)
        except Exception as exc:  # persistence must not break the mocked run
            logger.warning("LLM mock recording sink failed: %s", exc)
    path = os.environ.get("LLM_MOCK_RECORDINGS_FILE") or ""
    if path:
        try:
            with _store_lock:
                blob = {k: v for k, v in _recordings.items()}
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(list(blob.values()), fh, default=str)
        except Exception as exc:
            logger.warning("LLM mock recording file write failed: %s", exc)


def _lookup(recording_key: str) -> dict[str, Any] | None:
    if _replay_source is not None:
        recording = _replay_source(recording_key)
        if recording is not None:
            return recording
    with _store_lock:
        return _recordings.get(recording_key)


def _load_file_recordings() -> None:
    """Seed the in-process store from ``LLM_MOCK_RECORDINGS_FILE`` (replay)."""
    path = os.environ.get("LLM_MOCK_RECORDINGS_FILE") or ""
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            items = json.load(fh)
        with _store_lock:
            for item in items or []:
                key = item.get("recording_key")
                if key:
                    _recordings.setdefault(key, item)
    except Exception as exc:
        raise LLMMockConfigurationError(
            f"Failed to load LLM_MOCK_RECORDINGS_FILE '{path}': {exc}"
        ) from exc


# ── Key computation & serialization ──────────────────────────────────────────


def _normalize_role(role: str) -> str:
    """Canonical role names so dict- and message-based requests key alike."""
    role = (role or "user").lower()
    if role in ("human", "user"):
        return "user"
    if role in ("ai", "assistant"):
        return "assistant"
    if role in ("system",):
        return "system"
    if role in ("tool", "function"):
        return "tool"
    return role


def serialize_messages(messages: list[Any]) -> list[dict[str, Any]]:
    """Deterministic request serialization (prompt + structure, no secrets)."""
    out: list[dict[str, Any]] = []
    for message in messages or []:
        if isinstance(message, BaseMessage):
            out.append({
                "type": _normalize_role(message.type),
                "content": message.content,
            })
        elif isinstance(message, dict):
            out.append({
                "type": _normalize_role(
                    str(message.get("role") or message.get("type") or "user")
                ),
                "content": str(message.get("content") or ""),
            })
        else:
            out.append({"type": "unknown", "content": str(message)})
    return out


def compute_recording_key(
    model_identifier: str,
    messages: list[Any],
    *,
    interaction_kind: str = "agent_loop",
) -> str:
    """Deterministic SHA-256 key over (kind, model, serialized messages)."""
    payload = json.dumps(
        {
            "kind": interaction_kind,
            "model": model_identifier,
            "messages": serialize_messages(messages),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:64]


# ── The mock model (4.1–4.3) ─────────────────────────────────────────────────


class MockChatModel(BaseChatModel):
    """Deterministic scripted/record/replay chat model (zero real LLM calls).

    - ``scripted``: returns the first scripted rule whose ``match`` occurs in
      the prompt; no match → loud failure (deterministic, hand-authored).
    - ``record``: returns the scripted response too (the recorded run is
      itself driven deterministically) and persists request/response pairs.
      Alternatively wraps ``wrapped_model`` for capture of REAL responses.
    - ``replay``: looks up ``recording_key``; unmatched calls raise loudly.
    """

    model_identifier: str = "mock"
    interaction_kind: str = "agent_loop"
    wrapped_model: Optional[Any] = None
    _scripted_rules: Optional[list[dict[str, str]]] = None
    _bound_tools: Optional[Any] = None

    @property
    def _llm_type(self) -> str:
        return "llm-mock"

    # ── Tool-call support ────────────────────────────────────────────────────
    #
    # LangChain agent loops (``langchain.agents.create_agent``) call
    # ``bind_tools`` on the model before invoking it. The base implementation
    # raises NotImplementedError, which made the mock layer unusable for any
    # tool-calling agent run. The mock accepts (and records) the bound tool
    # definitions and behaves identically to the unbound model — scripted
    # rules drive what is returned, including ``tool_calls``.

    def bind_tools(
        self,
        tools: Any,
        *,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> "MockChatModel":
        """Accept bound tool definitions and return ``self`` (deterministic).

        The bound tool schemas are stored for prompt-assertion purposes only;
        scripted rules decide the actual response, including emitted
        ``tool_calls``.
        """
        self._bound_tools = tools
        return self

    def _make_tool_calls(self, messages: list[Any]) -> list[dict[str, Any]]:
        """Extract scripted tool_calls from the matching rule, if any.

        A scripted rule may carry an optional ``tool_calls`` key:
        ``{"match": ..., "response": ..., "tool_calls":
        [{"name": "supabase____execute_sql", "args": {"query": "..."}}]}``.
        Deterministic ids are assigned so LangChain's tool-message pairing
        works without additional configuration.
        """
        rules = self._scripted_rules
        if rules is None:
            try:
                rules = _load_scripted_rules()
            except LLMMockConfigurationError:
                return []
        prompt_text = json.dumps(serialize_messages(messages), default=str)
        for rule in rules:
            if rule["match"] in prompt_text:
                raw = rule.get("tool_calls") or []
                out: list[dict[str, Any]] = []
                for i, tc in enumerate(raw):
                    if not isinstance(tc, dict) or "name" not in tc:
                        continue
                    out.append({
                        "name": str(tc["name"]),
                        "args": dict(tc.get("args") or {}),
                        "id": f"mock_call_{abs(hash(prompt_text)) % 10**8}_{i}",
                        "type": "tool_call",
                    })
                return out
        return []

    # ── Core generation ───────────────────────────────────────────────────

    def _generate(
        self,
        messages: List[Any],
        stop: Optional[list[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        key = compute_recording_key(
            self.model_identifier, messages,
            interaction_kind=self.interaction_kind,
        )
        mode = get_mock_mode()

        if mode == MODE_REPLAY:
            recording = _lookup(key)
            if recording is None:
                raise LLMMockConfigurationError(
                    "No LLM mock recording found for key "
                    f"{key[:12]}… (kind={self.interaction_kind}) — replay "
                    "requires a matching recording; re-record the run"
                )
            text = str((recording.get("response_payload") or {}).get("text") or "")
            return self._result(text, recording.get("usage_metadata"))

        if mode == MODE_RECORD and self.wrapped_model is not None:
            # Capture a REAL interaction (4.2) — then persist it.
            result = self.wrapped_model.invoke(messages)
            text = getattr(result, "content", None) or str(result)
            usage = getattr(result, "usage_metadata", None) or {}
            self._record(key, messages, text, usage)
            return self._result(text, usage)

        # scripted (and record-without-wrapped-model: the recording IS the
        # deterministic scripted run).
        text = self._scripted_response(messages)
        tool_calls = self._make_tool_calls(messages)
        if tool_calls:
            logger.debug(
                "MockChatModel scripted tool_calls: %s", tool_calls,
            )
        if mode == MODE_RECORD:
            self._record(key, messages, text, {"mocked": True})
        return self._result(text, tool_calls=tool_calls or None)

    async def _agenerate(
        self,
        messages: List[Any],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop=stop, **kwargs)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _result(self, text: str, usage: Any = None, tool_calls: Any = None) -> ChatResult:
        message = AIMessage(content=text, tool_calls=tool_calls or [])
        if usage:
            message.response_metadata["usage"] = usage
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _scripted_response(self, messages: list[Any]) -> str:
        rules = self._scripted_rules
        if rules is None:
            rules = _load_scripted_rules()
        prompt_text = json.dumps(serialize_messages(messages), default=str)
        for rule in rules:
            if rule["match"] in prompt_text:
                return rule["response"]
        raise LLMMockConfigurationError(
            "No scripted response matched the prompt — add a rule whose "
            f"'match' occurs in the prompt (kind={self.interaction_kind})"
        )

    def _record(
        self,
        key: str,
        messages: list[Any],
        text: str,
        usage: Any,
    ) -> None:
        _persist(
            {
                "recording_key": key,
                "model_identifier": self.model_identifier,
                "interaction_kind": self.interaction_kind,
                "request_payload": {"messages": serialize_messages(messages)},
                "response_payload": {"text": text},
                "usage_metadata": usage or {},
                "recorded_by": "llm-mock-layer",
            }
        )

    # ── Prompt-assertion support (4.6) ────────────────────────────────────

    def last_request_payload(self) -> dict[str, Any] | None:
        """The most recently seen request (serialized) — for assertions."""
        if not _recordings:
            return None
        recording = max(
            _recordings.values(),
            key=lambda r: r.get("recorded_at") or "",
        )
        return recording.get("request_payload")


# ── Dispatch-layer integration (4.1 / 4.4) ───────────────────────────────────


def maybe_mock_model(provider_key: str, model_id: str) -> MockChatModel | None:
    """Return a MockChatModel when the mock layer is active, else ``None``.

    Called from ``LangChainModelFactory.get_model`` before any real provider
    construction — production default (``LLM_MOCK_MODE`` unset/off) never
    enters this path.
    """
    mode = get_mock_mode()
    if mode == MODE_OFF:
        return None
    if mode == MODE_REPLAY:
        _load_file_recordings()
    return MockChatModel(model_identifier=f"{provider_key}/{model_id}")


# ── Semantic-bridge mocking (4.5) ────────────────────────────────────────────


def maybe_mock_semantic_bridge(user_message: str, model_identifier: str) -> str | None:
    """Mocked completion for the CC semantic-bridge endpoint, or ``None``.

    When the mock layer is inactive this returns ``None`` and the endpoint
    proceeds with the real model invocation (production path unchanged).
    """
    mode = get_mock_mode()
    if mode == MODE_OFF:
        return None
    key = compute_recording_key(
        model_identifier,
        [{"role": "user", "content": user_message}],
        interaction_kind="semantic_bridge",
    )
    if mode == MODE_REPLAY:
        _load_file_recordings()
        recording = _lookup(key)
        if recording is None:
            raise LLMMockConfigurationError(
                f"No semantic-bridge recording for key {key[:12]}… — re-record"
            )
        return str((recording.get("response_payload") or {}).get("text") or "")
    # scripted / record: deterministic scripted answer, recorded in record mode.
    model = MockChatModel(
        model_identifier=model_identifier,
        interaction_kind="semantic_bridge",
    )
    text = model._scripted_response([{"role": "user", "content": user_message}])
    if mode == MODE_RECORD:
        model._record(
            key, [{"role": "user", "content": user_message}], text,
            {"mocked": True},
        )
    return text


# ── Prompt-assertion helpers (4.6) ───────────────────────────────────────────


def get_prompt_payloads() -> list[dict[str, Any]]:
    """All recorded request payloads (messages), in insertion order."""
    with _store_lock:
        return [
            r.get("request_payload") or {}
            for r in _recordings.values()
        ]


def assert_prompt_contains(fragment: str) -> None:
    """Assert some recorded prompt contains ``fragment`` (deterministic)."""
    for payload in get_prompt_payloads():
        blob = json.dumps(payload, default=str)
        if fragment in blob:
            return
    raise AssertionError(
        f"No recorded prompt contains {fragment!r} "
        f"({len(get_prompt_payloads())} prompts recorded)"
    )


def assert_prompt_structure(min_messages: int = 1, kinds: list[str] | None = None) -> None:
    """Assert recorded prompts have the expected message structure."""
    payloads = get_prompt_payloads()
    assert payloads, "No prompts were recorded — the mock layer saw no calls"
    for payload in payloads:
        messages = payload.get("messages") or []
        assert len(messages) >= min_messages, (
            f"Prompt has {len(messages)} message(s); expected >= {min_messages}"
        )
        if kinds:
            for message in messages:
                assert message.get("type") in kinds, (
                    f"Unexpected message type {message.get('type')!r}; "
                    f"expected one of {kinds}"
                )
