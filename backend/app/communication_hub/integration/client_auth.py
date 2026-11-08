"""Communication Hub — client credential authentication for /integrate/*.

Detects a client credential (Bearer or ``?apiKey=``), hashes it (SHA-256), and
validates it with Control Center over mTLS. Enforces the per-client origin
allowlist (secondary control) and rate limit, then binds the CC-signed tenant
context for downstream internal calls.

A client is NOT an identity: validation returns the target agent type + config,
never an agent identity token.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from app.core.internal_http import internal_httpx_client
from app.core.ssl_context import get_ssl_context
from app.communication_hub.integration.rate_limit import is_rate_limited

logger = logging.getLogger(__name__)

_BEARER_PREFIX = "Bearer "
_QUERY_PARAM_NAME = "apiKey"


def _get_control_center_url() -> str:
    return os.environ.get("CONTROL_CENTER_URL", "").rstrip("/")


def _extract_credential(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith(_BEARER_PREFIX):
        value = auth[len(_BEARER_PREFIX):].strip()
        if value:
            return value
    return request.query_params.get(_QUERY_PARAM_NAME)


def _build_mtls_client(request: Request) -> tuple[dict[str, Any], dict[str, str]]:
    cert_manager = getattr(request.app.state, "certificate_manager", None)
    cc_url = _get_control_center_url()
    client_kwargs: dict[str, Any] = {"timeout": 10.0, "verify": get_ssl_context()}
    headers: dict[str, str] = {}

    if cert_manager and cert_manager.cert_path and cert_manager.key_path:
        if cc_url.startswith("https://"):
            client_kwargs["cert"] = (str(cert_manager.cert_path), str(cert_manager.key_path))
        else:
            cert_content = Path(cert_manager.cert_path).read_text()
            headers["X-Client-Certificate"] = cert_content.replace("\n", "\\n")
        return client_kwargs, headers

    environment = os.environ.get("ENVIRONMENT", "").strip().lower()
    opt_in = os.environ.get("ALLOW_INSECURE_INTERNAL_CALL_FALLBACK", "").strip().lower()
    if environment == "development" and opt_in in {"1", "true", "yes", "on"}:
        logger.warning("Client auth using insecure internal fallback (development only)")
        return client_kwargs, headers

    raise RuntimeError("Communication Hub service certificate is required for client validation")


async def _validate_client_with_cc(request: Request, key_hash: str) -> dict[str, Any]:
    cc_url = _get_control_center_url()
    if not cc_url:
        return {"valid": False, "reason": "control_center_url_not_configured"}
    try:
        client_kwargs, headers = _build_mtls_client(request)
        async with internal_httpx_client(**client_kwargs) as client:
            response = await client.post(
                f"{cc_url}/api/v1/internal/clients/validate",
                json={"key_hash": key_hash},
                headers=headers,
            )
        if response.status_code == 200:
            return response.json()
        detail = "Unknown error"
        try:
            detail = response.json().get("detail", detail)
        except Exception:
            detail = response.text or detail
        return {"valid": False, "reason": detail, "status_code": response.status_code}
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to contact Control Center for client validation: %s", exc)
        return {"valid": False, "reason": f"control_center_unavailable: {exc}"}


def _origin_allowed(origin: str, allowed: list[str]) -> bool:
    """Return True when *origin* matches an allowlist entry.

    Supports ``*`` wildcards, e.g. ``https://*.acme.com`` matches
    ``https://app.acme.com`` (``*`` never crosses ``/``, so a path cannot be
    smuggled into an origin match). A bare ``*`` allows all origins.
    """
    for pattern in allowed:
        if pattern == "*" or pattern == origin:
            return True
        if "*" in pattern:
            regex = re.escape(pattern).replace(r"\*", "[^/]+")
            if re.fullmatch(regex, origin):
                return True
    return False


async def require_client(request: Request) -> dict[str, Any]:
    """FastAPI dependency: authenticate a client credential on ``/integrate/*``."""
    credential = _extract_credential(request)
    if not credential:
        raise HTTPException(status_code=401, detail="Missing client credential")

    key_hash = hashlib.sha256(credential.encode("utf-8")).hexdigest()
    validation = await _validate_client_with_cc(request, key_hash)
    if not validation.get("valid", False):
        raise HTTPException(
            status_code=validation.get("status_code", 401),
            detail=f"Authentication failed: {validation.get('reason', 'invalid credential')}",
        )

    # Origin allowlist — a secondary control (anti-abuse/branding), not auth.
    # A publishable (browser-facing) client MUST have an allowlist and the
    # request MUST come from an allowlisted origin — an empty allowlist or a
    # missing Origin would let anyone invoke the agent.
    key_type = validation.get("key_type")
    allowed_origins = validation.get("allowed_origins") or []
    origin = request.headers.get("Origin")
    if key_type == "publishable":
        if not allowed_origins:
            raise HTTPException(
                status_code=403,
                detail="Publishable client has no allowed origins configured",
            )
        if not origin or not _origin_allowed(origin, allowed_origins):
            raise HTTPException(status_code=403, detail="Origin not allowed")
    elif allowed_origins and origin and not _origin_allowed(origin, allowed_origins):
        raise HTTPException(status_code=403, detail="Origin not allowed")

    # Per-client rate limit.
    client_id = str(validation.get("client_id"))
    if is_rate_limited(client_id, validation.get("rate_limit"), validation.get("rate_limit_window")):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    # Bind the CC-signed tenant context so internal CC calls this request makes
    # carry the client tenant's signed headers verbatim (CH never signs).
    tenant_headers = validation.get("tenant_headers")
    if tenant_headers:
        from app.core.tenant_signature import bind_forwarded_tenant_headers

        bind_forwarded_tenant_headers(dict(tenant_headers))

    request.state.client_context = validation
    return validation
