"""Agent Runtime Metadata Client — requests agent configuration from Control Center.

Authenticates using mutual TLS (client certificate).  Explicitly verifies that
the response does NOT contain identity tokens or sensitive credentials.

Usage::

    client = MetadataClient(certificate_manager)
    metadata = await client.request_metadata()
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

from app.agent_runtime.certificate_manager import CertificateLoadError, CertificateManager

logger = logging.getLogger(__name__)

# Sensitive fields that must NEVER appear in metadata responses
_FORBIDDEN_FIELDS = frozenset({
    "access_token",
    "identity_token",
    "refresh_token",
    "token",
    "bearer_token",
    "id_token",
    "oauth_token",
    "credentials",
    "secret",
    "password",
    "api_key",
})

# Retry settings for transient failures
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # seconds


class MetadataClientError(Exception):
    """Raised when metadata retrieval fails."""


class IdentityTokenLeakError(SecurityError if False else Exception):
    """Raised when a metadata response contains identity tokens (security violation)."""


def verify_no_identity_tokens(data: Any, path: str = "") -> None:
    """Recursively verify that a response dict contains no identity tokens.

    Raises IdentityTokenLeakError if any sensitive field is found.

    Args:
        data: Response data to inspect (dict, list, or scalar).
        path: JSON path for error reporting.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            key_lower = key.lower()
            if key_lower in _FORBIDDEN_FIELDS:
                raise IdentityTokenLeakError(
                    f"SECURITY VIOLATION: Metadata response contains forbidden field "
                    f"'{key}' at path '{path}.{key}'. "
                    "Agent Runtime must never receive identity tokens."
                )
            verify_no_identity_tokens(value, f"{path}.{key}")
    elif isinstance(data, list):
        for i, item in enumerate(data):
            verify_no_identity_tokens(item, f"{path}[{i}]")


class MetadataClient:
    """HTTP client for fetching agent metadata from Control Center via mTLS.

    The metadata endpoint returns only non-sensitive configuration:
    SOPs, skills, instructions, and model configs.  This client verifies
    that no identity tokens are present in the response.
    """

    def __init__(self, cert_manager: CertificateManager) -> None:
        self._cert_manager = cert_manager
        self._control_center_url = os.environ.get("CONTROL_CENTER_URL", "")

    async def request_metadata(self) -> dict[str, Any]:
        """Request agent metadata from Control Center using mutual TLS.

        Retries up to 3 times on transient failures (network errors, 5xx).
        Does NOT retry on 4xx (auth/not-found) responses.

        Returns:
            Metadata dict containing SOPs, skills, instructions, model_config.

        Raises:
            MetadataClientError: If all retries fail.
            IdentityTokenLeakError: If the response contains identity tokens.
            CertificateLoadError: If the certificate is not loaded.
        """
        if not self._cert_manager.is_loaded:
            raise CertificateLoadError("Certificate not loaded; cannot make metadata request")

        if not self._control_center_url:
            raise MetadataClientError("CONTROL_CENTER_URL not set")

        url = f"{self._control_center_url.rstrip('/')}/api/v1/agent/metadata"
        last_error: str = "unknown"

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with self._cert_manager.configure_mtls_client(timeout=30.0) as client:
                    response = await client.get(url)

                if response.status_code == 200:
                    data = response.json()

                    # Security check: verify no identity tokens in response
                    verify_no_identity_tokens(data)

                    logger.info(
                        "Metadata retrieved successfully (serial=%s)",
                        self._cert_manager.serial_number,
                    )
                    return data

                if 400 <= response.status_code < 500:
                    # Client errors — do not retry
                    raise MetadataClientError(
                        f"Metadata request rejected (HTTP {response.status_code}): {response.text[:200]}"
                    )

                # 5xx — retry
                last_error = f"HTTP {response.status_code}: {response.text[:100]}"
                logger.warning(
                    "Metadata request attempt %d failed with %s; retrying",
                    attempt,
                    response.status_code,
                )

            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                last_error = str(exc)
                logger.warning(
                    "Metadata request attempt %d failed (network): %s; retrying",
                    attempt,
                    exc,
                )

            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BASE_DELAY * (2 ** (attempt - 1)))

        raise MetadataClientError(
            f"Metadata retrieval failed after {_MAX_RETRIES} attempts: {last_error}"
        )
