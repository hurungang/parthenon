"""Provider-agnostic System One client interface + TypeSafe Jev implementation.

The TypeSafe Jev API contract:
- POST ``{base_url}/systemone`` (default base ``https://api.typesafe.ai/v1``)
- Header: ``Authorization: Bearer <api_key>``
- Body: ``{"state": {...}, "model": "jev-latest", "questions": {"<id>": {"type":
  "choice"|"score"|"noul", "instructions": ..., "criteria": ...}}}``
- Response: ``{"model": ..., "answers": {"<id>": {"type": ..., "choice"|"score"|"noul":
  value, "probabilities": {...}, "confidence": 0-1, "legend": {...}?}}, "usage": {...}}``

The HTTP transport is injected so the client is unit-testable without network.
The API key is injected at call time only — never stored on the client instance.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx

from app.db.models.decision_tools import DecisionQuestionType

logger = logging.getLogger(__name__)

TYPESAFE_DEFAULT_BASE_URL = "https://api.typesafe.ai/v1"
TYPESAFE_DEFAULT_MODEL = "jev-latest"


class SystemOneClientError(Exception):
    """Raised when a System One provider call fails."""


class SystemOneClient(Protocol):
    """Provider-agnostic outbound client contract."""

    async def evaluate(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        state: dict[str, Any],
        questions: dict[str, dict[str, Any]],
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        """Dispatch one evaluation and return the parsed provider response."""
        ...


class TypeSafeJevClient:
    """TypeSafe Jev implementation of the System One client."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # Transport injection keeps the client unit-testable without network.
        self._transport = transport

    async def evaluate(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        state: dict[str, Any],
        questions: dict[str, dict[str, Any]],
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        url = f"{base_url.rstrip('/')}/systemone"
        payload = {"state": state, "model": model, "questions": questions}
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=timeout_seconds
            ) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            logger.error("TypeSafe Jev request failed: %s", exc)
            raise SystemOneClientError(f"TypeSafe Jev request failed: {exc}") from exc

        if response.status_code >= 400:
            # Never log headers (they carry the API key).
            raise SystemOneClientError(
                f"TypeSafe Jev returned HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise SystemOneClientError(
                f"TypeSafe Jev returned invalid JSON: {exc}"
            ) from exc


def build_questions_payload(
    question_type: DecisionQuestionType,
    instructions: str | None,
    criteria_options: Any,
) -> dict[str, Any]:
    """Build the per-question request body for the TypeSafe API."""
    body: dict[str, Any] = {"type": question_type.value}
    if instructions:
        body["instructions"] = instructions
    if question_type == DecisionQuestionType.choice:
        body["criteria"] = dict(criteria_options or {})
    elif question_type == DecisionQuestionType.score:
        body["criteria"] = list(criteria_options or [])
    # noul carries no criteria.
    return body
