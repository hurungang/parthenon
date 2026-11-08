"""Communication Hub — third-party agent integration gateway (``/integrate/*``).

Public, client-credential-authenticated surface for invoking an agent type's
input interface. A client is NOT an identity: it grants access to one agent
type only, never to tools, the MCP hub, or an agent identity.

Endpoints:
- ``GET  /integrate/config``             — white-label widget/theme config
- ``POST /integrate/submit``             — typed request/response (async session)
- ``POST /integrate/chat``               — conversational turn (async session)
- ``GET  /integrate/sdk/parthenon-chat.js`` — minimal JS SDK bundle
- ``GET  /integrate/sdk/parthenon-python``  — Python SDK metadata
"""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.core.internal_http import internal_httpx_client
from app.core.ssl_context import get_ssl_context
from app.communication_hub.integration.client_auth import require_client

logger = logging.getLogger(__name__)

integration_router = APIRouter(prefix="/integrate", tags=["Integration Gateway"])


def _cc_url() -> str:
    return os.environ.get("CONTROL_CENTER_URL", "").rstrip("/")


async def _call_cc(path: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    """POST to a Control Center internal endpoint over mTLS."""
    cc_url = _cc_url()
    cert_manager = getattr(request.app.state, "certificate_manager", None)
    client_kwargs: dict[str, Any] = {"timeout": 30.0, "verify": get_ssl_context()}
    headers: dict[str, str] = {}
    if cert_manager and cert_manager.cert_path and cert_manager.key_path:
        if cc_url.startswith("https://"):
            client_kwargs["cert"] = (str(cert_manager.cert_path), str(cert_manager.key_path))
        else:
            headers["X-Client-Certificate"] = Path(cert_manager.cert_path).read_text().replace("\n", "\\n")

    async with internal_httpx_client(**client_kwargs) as client:
        resp = await client.post(f"{cc_url}{path}", json=payload, headers=headers)

    if resp.status_code >= 400:
        detail: Any = "error"
        try:
            detail = resp.json().get("detail", detail)
        except Exception:
            detail = resp.text or detail
        raise HTTPException(status_code=resp.status_code, detail=detail)
    return resp.json()


async def _get_cc(path: str, request: Request) -> dict[str, Any]:
    """GET a Control Center internal endpoint over mTLS."""
    cc_url = _cc_url()
    cert_manager = getattr(request.app.state, "certificate_manager", None)
    client_kwargs: dict[str, Any] = {"timeout": 30.0, "verify": get_ssl_context()}
    headers: dict[str, str] = {}
    if cert_manager and cert_manager.cert_path and cert_manager.key_path:
        if cc_url.startswith("https://"):
            client_kwargs["cert"] = (str(cert_manager.cert_path), str(cert_manager.key_path))
        else:
            headers["X-Client-Certificate"] = Path(cert_manager.cert_path).read_text().replace("\n", "\\n")

    async with internal_httpx_client(**client_kwargs) as client:
        resp = await client.get(f"{cc_url}{path}", headers=headers)

    if resp.status_code >= 400:
        detail: Any = "error"
        try:
            detail = resp.json().get("detail", detail)
        except Exception:
            detail = resp.text or detail
        raise HTTPException(status_code=resp.status_code, detail=detail)
    return resp.json()


class InvokeRequest(BaseModel):
    """Input payload for a client-invoked agent type."""

    input: dict[str, Any] = Field(default_factory=dict, description="Agent input payload")


class ChatBody(BaseModel):
    """A single user message within a stateful conversation."""

    message: str = Field(..., min_length=1)


@integration_router.get("/config")
async def get_config(
    request: Request,
    ctx: dict[str, Any] = Depends(require_client),
) -> dict[str, Any]:
    """Return the public white-label widget/theme config for the client."""
    return {
        "client_id": str(ctx.get("client_id")),
        "client_name": ctx.get("client_name"),
        "agent_type_id": str(ctx.get("agent_type_id")),
        "agent_type_name": ctx.get("agent_type_name"),
        "agent_type_input_type": ctx.get("agent_type_input_type"),
        "agent_type_input_schema": ctx.get("agent_type_input_schema"),
        "key_type": ctx.get("key_type"),
        "tenant_slug": ctx.get("tenant_slug"),
        "tenant_name": ctx.get("tenant_name"),
        "theme": ctx.get("white_label_theme") or {},
    }


@integration_router.post("/submit")
async def submit(
    body: InvokeRequest,
    request: Request,
    ctx: dict[str, Any] = Depends(require_client),
) -> dict[str, Any]:
    """Submit typed input to the client's **non-conversational** agent type.

    Conversational agent types must use the stateful conversation endpoints.
    Returns the execution session id (the platform executes agents
    asynchronously — poll the session for the validated typed result).
    """
    if ctx.get("agent_type_input_type") == "conversation":
        raise HTTPException(
            status_code=400,
            detail="This agent type is conversational — use POST /integrate/conversations.",
        )
    return await _call_cc(
        "/api/v1/internal/clients/invoke",
        {
            "agent_type_id": str(ctx.get("agent_type_id")),
            "input_data": body.input,
            # Provenance: which client credential triggered this invocation.
            "client_id": str(ctx.get("client_id")),
        },
        request,
    )


@integration_router.get("/session/{session_id}")
async def get_session(
    session_id: str,
    request: Request,
    ctx: dict[str, Any] = Depends(require_client),
) -> dict[str, Any]:
    """Return the current status/output of a client-invoked execution session.

    Clients poll this after ``/integrate/submit`` or a conversation
    ``/messages`` call until the session reaches ``completed`` (or ``failed``).
    """
    return await _get_cc(f"/api/v1/internal/clients/session/{session_id}", request)


@integration_router.post("/conversations")
async def start_conversation(
    request: Request,
    ctx: dict[str, Any] = Depends(require_client),
) -> dict[str, Any]:
    """Start a stateful conversation session for the client's conversational agent type."""
    return await _call_cc(
        "/api/v1/internal/clients/conversations",
        {
            "agent_type_id": str(ctx.get("agent_type_id")),
            # Provenance: which client credential created this conversation.
            "client_id": str(ctx.get("client_id")),
        },
        request,
    )


@integration_router.post("/conversations/{conversation_id}/messages")
async def send_conversation_message(
    conversation_id: str,
    body: ChatBody,
    request: Request,
    ctx: dict[str, Any] = Depends(require_client),
) -> dict[str, Any]:
    """Send a message within a stateful conversation and return the agent's reply.

    Mirrors the Control Center chat flow: prepare-turn (persist user message +
    build history) → Agent Runtime turn → append-turn (persist agent reply), so
    every message shares the same conversation context.
    """
    if ctx.get("agent_type_input_type") != "conversation":
        raise HTTPException(
            status_code=400,
            detail="This agent type is not conversational — use POST /integrate/submit.",
        )
    data_client = getattr(request.app.state, "data_client", None)
    if data_client is None:
        raise HTTPException(status_code=503, detail="Control Center data client unavailable")

    conv_uuid = uuid.UUID(conversation_id)
    prepared = await data_client.prepare_conversation_turn(conv_uuid, body.message)

    no_agent_message = prepared.get("no_agent_message")
    agent_type_id_raw = prepared.get("agent_type_id")
    messages = prepared.get("messages") or []

    if no_agent_message:
        reply = str(no_agent_message)
    elif agent_type_id_raw:
        from app.api.ws.chat import _delegate_conversation_turn_to_agent_runtime

        reply, _guardrail_usage, _status_events = await _delegate_conversation_turn_to_agent_runtime(
            app=request.app,
            conv_session_id=conv_uuid,
            agent_type_id=uuid.UUID(str(agent_type_id_raw)),
            messages=messages,
        )
    else:
        reply = "No model is configured for this agent."

    await data_client.append_conversation_turn(
        conv_session_id=conv_uuid,
        agent_reply=reply,
        is_first_message=False,
    )
    return {"conversation_id": conversation_id, "reply": reply}


@integration_router.post("/conversations/{conversation_id}/end")
async def end_conversation(
    conversation_id: str,
    request: Request,
    ctx: dict[str, Any] = Depends(require_client),
) -> dict[str, Any]:
    """End a stateful conversation session."""
    return await _call_cc(
        f"/api/v1/internal/clients/conversations/{conversation_id}/end",
        {},
        request,
    )


_JS_SDK = """/* Parthenon chat widget SDK (minimal, self-contained) */
(function (global) {
  function mount(selector, opts) {
    var el = document.querySelector(selector);
    if (!el) throw new Error('ParthenonChat: selector not found');
    var base = opts.baseUrl || '';
    var theme = opts.theme || {};
    var color = theme.color || '#6D28D9';
    el.innerHTML =
      '<div style="font-family:sans-serif;max-width:420px">' +
      '<div style="background:' + color + ';color:#fff;padding:10px 14px;border-radius:8px 8px 0 0;font-weight:600">' +
      (theme.name || 'Assistant') + '</div>' +
      '<div class="pc-log" style="border:1px solid #ddd;border-top:none;padding:12px;min-height:180px;max-height:320px;overflow:auto"></div>' +
      '<div style="display:flex;border:1px solid #ddd;border-top:none"><input class="pc-in" placeholder="Type a message…" style="flex:1;border:none;padding:10px;outline:none">' +
      '<button class="pc-send" style="border:none;background:' + color + ';color:#fff;padding:0 16px">Send</button></div></div>';
    var log = el.querySelector('.pc-log');
    var input = el.querySelector('.pc-in');
    function add(role, text) {
      var d = document.createElement('div');
      d.style.margin = '4px 0';
      d.textContent = (role === 'user' ? 'You: ' : 'Bot: ') + text;
      log.appendChild(d);
      log.scrollTop = log.scrollHeight;
    }
    function send() {
      var text = input.value.trim();
      if (!text) return;
      add('user', text);
      input.value = '';
      fetch(base + '/integrate/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + opts.publishableKey },
        body: JSON.stringify({ input: { message: text } })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) { add('bot', d.session_id ? '[' + (d.status || 'queued') + '] session ' + d.session_id : JSON.stringify(d)); })
        .catch(function (e) { add('bot', 'Error: ' + e.message); });
    }
    el.querySelector('.pc-send').addEventListener('click', send);
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter') send(); });
  }
  global.ParthenonChat = { mount: mount };
})(window);
"""


@integration_router.get("/sdk/parthenon-chat.js")
async def serve_js_sdk() -> PlainTextResponse:
    """Serve the minimal JavaScript SDK bundle."""
    return PlainTextResponse(_JS_SDK, media_type="application/javascript")


@integration_router.get("/sdk/parthenon-python")
async def serve_python_sdk_metadata() -> dict[str, Any]:
    """Advertise the Python SDK package (pip install parthenon-client)."""
    return {
        "package": "parthenon-client",
        "install": "pip install parthenon-client",
        "docs": "/integrate/config",
    }
