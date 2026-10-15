"""Single global egress mechanism for internal service-to-service calls.

Agent Runtime and Communication Hub make many outbound calls to internal
service endpoints (AR→CC data plane, CH→AR execution forwarding,
CH→CC authorization/data plane).  Multi-tenancy requires every such call
to forward the CC-signed tenant header set the service received and
verified — previously done with a manual ``headers.update(
forward_tenant_headers())`` at each of ~29 call sites, each one a fresh
opportunity to forget the merge (four shipped bugs).

This module replaces ALL of that with one request event hook wired into
one client factory:

- :func:`attach_forwarded_tenant_headers` — httpx request event hook that
  merges :func:`app.core.tenant_signature.forward_tenant_headers` into the
  outgoing request.  Set-add semantics: existing headers (client-cert,
  ``X-Client-Certificate``, ``Authorization``, content-type) are never
  removed or overwritten except where the same tenant header is re-added
  with the bound value — forwarded tenant headers are additive and coexist
  with transport-level headers.
- :func:`internal_httpx_client` — the ONLY approved way to build an
  ``httpx.AsyncClient`` for internal service calls in CH/AR.  It wires the
  hook and passes everything else through (``timeout``, ``verify``,
  ``cert``, ``base_url``, ``transport``, ...).

Receiver purity (CS-20): this module only READS the already-verified
header set via ``forward_tenant_headers()`` — it never imports any
signing capability.  Single-tenant traffic: ``forward_tenant_headers()``
returns ``{}`` so the hook is a no-op and the wire bytes are unchanged.

Exempt from this mechanism (by design, enforced by the egress scan in
``tests/communication_hub/test_internal_http_egress.py``):

- ``certificate_manager.py`` (both services) — pre-tenancy certificate
  bootstrap/renewal, headerless by design (no tenant exists yet).
- ``main.py`` startup health probes — no tenant exists at startup.
- ``app/api/ws/chat.py`` — CC-side ORIGIN: it *signs* fresh sets per hop
  (``_signed_tenant_forwarding``), a different concern.
- Anything in Control Center itself — CC is the signing origin.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.core.tenant_signature import forward_tenant_headers

__all__ = ["attach_forwarded_tenant_headers", "internal_httpx_client"]


def attach_forwarded_tenant_headers(request: httpx.Request) -> None:
    """Merge the bound signed tenant header set into an outgoing request.

    httpx request event hook.  Additive only: headers already on the
    request (mTLS cert header, Authorization, ...) are preserved; the
    forwarded tenant set is set-added on top.  Nothing bound
    (single-tenant) → no-op, byte-for-byte unchanged.
    """
    for name, value in forward_tenant_headers().items():
        request.headers[name] = value


def internal_httpx_client(**kwargs: Any) -> httpx.AsyncClient:
    """Build an httpx AsyncClient that forwards tenant context on egress.

    THE approved factory for internal service-to-service clients in
    Agent Runtime / Communication Hub.  Wires the
    :func:`attach_forwarded_tenant_headers` request hook (prepending any
    caller-supplied ``event_hooks``) and passes all other kwargs straight
    through to ``httpx.AsyncClient`` (``timeout``, ``verify``, ``cert``,
    ``headers``, ``base_url``, ``transport``, ...).
    """
    caller_hooks = kwargs.pop("event_hooks", None) or {}
    hooks: dict[str, list[Any]] = {k: list(v) for k, v in caller_hooks.items()}
    request_hooks = hooks.get("request", [])

    async def _attach(request: httpx.Request) -> None:
        # AsyncClient event hooks must be coroutines; the merge itself is
        # sync so the same helper also works for sync clients.
        attach_forwarded_tenant_headers(request)

    hooks["request"] = [_attach, *request_hooks]
    return httpx.AsyncClient(event_hooks=hooks, **kwargs)
