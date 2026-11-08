"""Parthenon Python SDK client.

A *client* credential grants access to one agent type's input interface only.
Use a ``secret`` credential server-side (never in a browser). The credential is
NOT an identity and never grants tool access.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class ParthenonError(Exception):
    """Raised when a Parthenon API call fails."""


class Client:
    """Client for a Parthenon third-party agent-integration credential."""

    def __init__(self, base_url: str, credential: str, timeout: float = 30.0) -> None:
        if not base_url:
            raise ParthenonError("base_url is required")
        if not credential:
            raise ParthenonError("credential is required")
        self.base_url = base_url.rstrip("/")
        self.credential = credential
        self.timeout = timeout

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.credential}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - network path
            detail = exc.read().decode("utf-8", errors="replace")
            raise ParthenonError(f"{exc.code}: {detail}") from exc

    def config(self) -> dict[str, Any]:
        """Return the client's white-label widget/theme config."""
        return self._request("GET", "/integrate/config")

    def submit(self, input: dict[str, Any]) -> dict[str, Any]:
        """Submit typed input to a non-conversational agent type."""
        return self._request("POST", "/integrate/submit", {"input": input})

    def start_conversation(self) -> dict[str, Any]:
        """Start a stateful conversation session (conversational agent types)."""
        return self._request("POST", "/integrate/conversations")

    def send_message(self, conversation_id: str, message: str) -> dict[str, Any]:
        """Send a message within a stateful conversation and get the reply."""
        return self._request(
            "POST",
            f"/integrate/conversations/{conversation_id}/messages",
            {"message": message},
        )

    def end_conversation(self, conversation_id: str) -> dict[str, Any]:
        """End a stateful conversation session."""
        return self._request("POST", f"/integrate/conversations/{conversation_id}/end")
