"""Provider-agnostic System One client interface + TypeSafe Jev implementation.

Vendor registry
---------------
``get_system_one_client(provider_type)`` returns the client implementation for
a configured provider type. To add a new vendor:

1. Implement the ``SystemOneClient`` protocol (an ``async evaluate(...)``).
2. Register the class in ``_SYSTEM_ONE_CLIENTS`` below, keyed by the
   ``SystemOneProviderType`` value.

The TypeSafe Jev API contract:
- POST ``{base_url}`` — the configured value is the FULL endpoint URL, used
  VERBATIM (default ``https://api.typesafe.ai/v1/systemone``; proxies: the
  proxy's complete URL). No path segments are appended or stripped.
- Header: ``Authorization: Bearer <api_key>``
- Body: ``{"state": {...}, "model": "jev-latest", "questions": {"<id>": {"type":
  "choice"|"score"|"noul", "instructions": ..., "criteria": ...}}}``
- Response: ``{"model": ..., "answers": {"<id>": {"type": ..., "choice"|"score"|"noul":
  value, "probabilities": {...}, "confidence": 0-1, "legend": {...}?}}, "usage": {...}}``

The HTTP transport is injected so the client is unit-testable without network.
The API key is injected at call time only — never stored on the client instance
and never logged (responses are logged without headers).
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx

from app.db.models.decision_tools import DecisionQuestionType
from app.db.models.system_one_provider_config import SystemOneProviderType

logger = logging.getLogger(__name__)

#: Full default endpoint URL for the TypeSafe System One API (used verbatim).
TYPESAFE_DEFAULT_BASE_URL = "https://api.typesafe.ai/v1/systemone"
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
        # base_url is the FULL endpoint URL — used verbatim, no suffix appended.
        url = base_url
        payload = {"state": state, "model": model, "questions": questions}
        headers = {"Authorization": f"Bearer {api_key}"}
        logger.info(
            "System One dispatch: endpoint=%s model=%s questions=%d",
            url,
            model,
            len(questions),
        )
        logger.debug(
            "System One request body (sanitized, no auth material): %s",
            payload,
        )
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=timeout_seconds
            ) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            logger.error("TypeSafe Jev request failed (endpoint=%s): %s", url, exc)
            raise SystemOneClientError(f"TypeSafe Jev request failed: {exc}") from exc

        logger.info(
            "System One response: endpoint=%s status=%d",
            url,
            response.status_code,
        )
        if response.status_code >= 400:
            # Log status + body (never headers — they carry the API key).
            logger.error(
                "TypeSafe Jev error response: endpoint=%s status=%d body=%s",
                url,
                response.status_code,
                response.text[:500],
            )
            raise SystemOneClientError(
                f"TypeSafe Jev returned HTTP {response.status_code} for {url}: "
                f"{response.text[:500]}"
            )
        try:
            parsed = response.json()
        except ValueError as exc:
            raise SystemOneClientError(
                f"TypeSafe Jev returned invalid JSON: {exc}"
            ) from exc
        logger.debug(
            "System One raw response body: %s",
            response.text[:2000],
        )
        logger.info(
            "System One answers summary: %s",
            {
                key: (
                    answer.get("choice")
                    if answer.get("choice") is not None
                    else answer.get("score")
                    if answer.get("score") is not None
                    else answer.get("noul")
                )
                for key, answer in (parsed.get("answers") or {}).items()
            },
        )
        return parsed


#: Vendor registry — provider_type value → client implementation.
#: To add a vendor: implement SystemOneClient, then register it here.
_SYSTEM_ONE_CLIENTS: dict[str, type] = {
    SystemOneProviderType.typesafe.value: TypeSafeJevClient,
}


def get_system_one_client(
    provider_type: str | SystemOneProviderType,
) -> SystemOneClient:
    """Return the client implementation for a registered provider type.

    Each call instantiates a FRESH client for the specific provider —
    credentials are never stored on the client; the API key is injected
    per ``evaluate`` call, decrypted only inside Control Center at
    vendor-call time.

    Raises ``ValueError`` for unknown types so misconfiguration fails
    loudly instead of silently falling back to another vendor's client.
    """
    key = (
        provider_type.value
        if isinstance(provider_type, SystemOneProviderType)
        else provider_type
    )
    try:
        return _SYSTEM_ONE_CLIENTS[key]()
    except KeyError:
        raise ValueError(
            f"Unsupported System One provider type: '{key}'. "
            f"Registered types: {sorted(_SYSTEM_ONE_CLIENTS)}"
        ) from None


def derive_models_url(base_url: str) -> str:
    """Derive the vendor model-listing URL from a configured ``base_url``.

    The configured ``base_url`` may be the FULL evaluation endpoint
    (e.g. ``https://api.typesafe.ai/v1/systemone``), an API root
    (``.../v1``), a models URL (``.../v1/models``), or a bare host. The
    listing URL must always resolve to ``<origin>/v1/models``:

    - path already ends with ``/models`` → kept as-is;
    - path ends with ``/v1`` → ``/models`` appended;
    - path contains a trailing endpoint segment after ``/v1``
      (e.g. ``/v1/systemone``) → the segment is stripped so the result
      is origin + ``/v1/models``;
    - bare host (no ``/v1`` path) → ``/v1/models`` appended.
    """
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(base_url)
    path = parts.path.rstrip("/")
    if path.endswith("/models"):
        derived = path
    elif path.endswith("/v1"):
        derived = f"{path}/models"
    elif "/v1/" in path:
        # Strip the trailing endpoint segment after the /v1 root
        # (e.g. /v1/systemone → /v1/models).
        derived = f"{path[: path.rindex('/v1') + 3]}/models"
    else:
        derived = f"{path}/v1/models"
    return urlunsplit((parts.scheme, parts.netloc, derived, "", ""))


async def list_vendor_models(
    *,
    base_url: str,
    api_key: str,
    timeout_seconds: float = 15.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[str]:
    """Discover the vendor's model catalogue via its model-listing
    endpoint (bearer auth), derived from ``base_url`` by
    :func:`derive_models_url` (always ``<origin>/v1/models``).

    Accepts the TypeSafe shape ``{"models": [{"name": ...}, ...]}``
    (primary — https://docs.typesafe.ai/models), the OpenAI shape
    ``{"data": [{"id": ...}, ...]}`` (fallback for other vendors), and
    the plain-array variants ``["id", ...]`` / ``[{"id"|"name": ...}]``.
    Returns the model names. Raises ``SystemOneClientError`` with an
    actionable message on HTTP errors, unreachable hosts, invalid JSON,
    or unexpected shapes. The API key is used for this call only —
    never logged or returned.
    """
    url = derive_models_url(base_url)
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(
            transport=transport, timeout=timeout_seconds
        ) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        logger.error("Vendor model listing failed (endpoint=%s): %s", url, exc)
        raise SystemOneClientError(
            f"Could not reach the vendor's model catalogue at {url}: {exc}"
        ) from exc

    if response.status_code >= 400:
        # Log status + body (never headers — they carry the API key).
        logger.error(
            "Vendor model listing error: endpoint=%s status=%d body=%s",
            url,
            response.status_code,
            response.text[:500],
        )
        hint = (
            "the API key was rejected"
            if response.status_code in (401, 403)
            else "the vendor endpoint does not support model listing"
            if response.status_code in (404, 405)
            else "the vendor returned an error"
        )
        raise SystemOneClientError(
            f"Vendor model listing returned HTTP {response.status_code} "
            f"for {url} — {hint}"
        )
    try:
        parsed = response.json()
    except ValueError as exc:
        raise SystemOneClientError(
            f"The vendor endpoint at {url} is not OpenAI-compatible "
            f"(invalid JSON response)"
        ) from exc

    entries: list[Any]
    if isinstance(parsed, dict):
        # TypeSafe primary shape: {"models": [{"name": ...}, ...]}
        entries = parsed.get("models")
        if entries is None:
            # OpenAI-compatible fallback: {"data": [{"id": ...}, ...]}
            entries = parsed.get("data") or []
    elif isinstance(parsed, list):
        entries = parsed
    else:
        raise SystemOneClientError(
            f"The vendor endpoint at {url} returned an unexpected response "
            "shape (expected a models list)"
        )

    models: list[str] = []
    for entry in entries:
        if isinstance(entry, dict):
            model_id = entry.get("name") or entry.get("id")
        else:
            model_id = entry
        if isinstance(model_id, str) and model_id:
            models.append(model_id)
    if not models:
        raise SystemOneClientError(
            f"The vendor endpoint at {url} returned no models — verify the "
            "base URL points at the vendor's API root"
        )
    return list(dict.fromkeys(models))


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
