"""mTLS-authenticated HTTP client helper for Communication Hub → Control Center calls.

The Communication Hub has no direct database access. Every call this package
makes to Control Center is authenticated with the CH service certificate
(over HTTPS) or a client-certificate header (development fallback), mirroring
the existing internal tool-routing and skill-resolution code paths.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from app.core.ssl_context import get_ssl_context

logger = logging.getLogger(__name__)


def get_control_center_url() -> str:
    """Return the Control Center base URL without a trailing slash."""
    return os.environ.get("CONTROL_CENTER_URL", "").rstrip("/")


def _allow_insecure_internal_fallback() -> bool:
    environment = os.environ.get("ENVIRONMENT", "").strip().lower()
    opt_in = os.environ.get("ALLOW_INSECURE_INTERNAL_CALL_FALLBACK", "").strip().lower()
    return environment == "development" and opt_in in {"1", "true", "yes", "on"}


def build_cc_client(request: Any, cc_base: str) -> tuple[dict[str, Any], dict[str, str]]:
    """Build transport kwargs and headers for an authenticated CH → CC call.

    Returns ``(client_kwargs, headers)`` suitable for ``httpx.AsyncClient``.
    Uses the CH service certificate when available; otherwise falls back to a
    development-only insecure path (explicitly opted in via env var).
    """
    cert_manager = getattr(request.app.state, "certificate_manager", None)
    client_kwargs: dict[str, Any] = {
        "timeout": 30.0,
        "verify": get_ssl_context(),
    }
    headers: dict[str, str] = {}

    if cert_manager and cert_manager.cert_path and cert_manager.key_path:
        if cc_base.startswith("https://"):
            client_kwargs["cert"] = (str(cert_manager.cert_path), str(cert_manager.key_path))
        else:
            cert_content = Path(cert_manager.cert_path).read_text()
            headers["X-Client-Certificate"] = cert_content.replace("\n", "\\n")
        return client_kwargs, headers

    if _allow_insecure_internal_fallback():
        logger.warning("MCP protocol server using insecure internal fallback (development only)")
        return client_kwargs, headers

    raise RuntimeError("Communication Hub service certificate is required for Control Center internal calls")
