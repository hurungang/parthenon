"""Agent Client demo app — a thin UI over the Parthenon `/integrate/*` gateway.

The user pastes a **client secret** (`phn_cl_sk_…`) or **publishable key**
(`phn_cl_pk_…`); this app proxies the request to the Communication Hub's
integration gateway.

Security note: the browser `Origin` is NOT user-editable here. For a real
browser widget the browser sets `Origin` automatically (JS cannot override it).
This demo is a server-side proxy, so it sets `Origin` to its own deployment
origin (``DEMO_ORIGIN``, default ``http://localhost:7002``) — the same value an
operator must add to a publishable client's allowed-origins list.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

STATIC_DIR = Path(__file__).parent.parent / "static"

app = FastAPI(title="Parthenon Agent Client Demo", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _ch_base(base_url: str | None) -> str:
    return (base_url or os.environ.get("CH_BASE_URL", "http://localhost:8002")).rstrip("/")


def _demo_origin() -> str:
    """This demo's own origin — set by deployment, never by the user."""
    return os.environ.get("DEMO_ORIGIN", "http://localhost:7002").rstrip("/")


def _secret(secret: str | None) -> str:
    if not secret:
        raise HTTPException(status_code=400, detail="Missing X-Client-Secret header")
    return secret


async def _ch_request(
    method: str,
    base: str,
    path: str,
    secret: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {secret}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.request(method, f"{base}{path}", headers=headers, json=body)
    if resp.status_code >= 400:
        try:
            detail: Any = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise HTTPException(status_code=resp.status_code, detail=detail)
    return resp.json()


class ChatBody(BaseModel):
    message: str = Field(..., min_length=1)


class SubmitBody(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "agent-client-demo-app", "origin": _demo_origin()}


@app.get("/api/config")
async def get_config(
    x_ch_base_url: str | None = Header(None, alias="X-CH-Base-Url"),
    x_client_secret: str | None = Header(None, alias="X-Client-Secret"),
) -> dict[str, Any]:
    return await _ch_request(
        "GET", _ch_base(x_ch_base_url), "/integrate/config", _secret(x_client_secret)
    )


# ── Stateful conversation (conversational agent types) ───────────────────────


@app.post("/api/conversations")
async def start_conversation(
    x_ch_base_url: str | None = Header(None, alias="X-CH-Base-Url"),
    x_client_secret: str | None = Header(None, alias="X-Client-Secret"),
) -> dict[str, Any]:
    return await _ch_request(
        "POST", _ch_base(x_ch_base_url), "/integrate/conversations", _secret(x_client_secret)
    )


@app.post("/api/conversations/{conversation_id}/messages")
async def conversation_message(
    conversation_id: str,
    body: ChatBody,
    x_ch_base_url: str | None = Header(None, alias="X-CH-Base-Url"),
    x_client_secret: str | None = Header(None, alias="X-Client-Secret"),
) -> dict[str, Any]:
    return await _ch_request(
        "POST",
        _ch_base(x_ch_base_url),
        f"/integrate/conversations/{conversation_id}/messages",
        _secret(x_client_secret),
        {"message": body.message},
    )


@app.post("/api/conversations/{conversation_id}/end")
async def end_conversation(
    conversation_id: str,
    x_ch_base_url: str | None = Header(None, alias="X-CH-Base-Url"),
    x_client_secret: str | None = Header(None, alias="X-Client-Secret"),
) -> dict[str, Any]:
    return await _ch_request(
        "POST",
        _ch_base(x_ch_base_url),
        f"/integrate/conversations/{conversation_id}/end",
        _secret(x_client_secret),
        {},
    )


# ── One-shot request/response (non-conversational agent types) ───────────────


@app.post("/api/submit")
async def submit(
    body: SubmitBody,
    x_ch_base_url: str | None = Header(None, alias="X-CH-Base-Url"),
    x_client_secret: str | None = Header(None, alias="X-Client-Secret"),
) -> dict[str, Any]:
    return await _ch_request(
        "POST", _ch_base(x_ch_base_url), "/integrate/submit", _secret(x_client_secret),
        {"input": body.input},
    )


@app.get("/api/session/{session_id}")
async def session(
    session_id: str,
    x_ch_base_url: str | None = Header(None, alias="X-CH-Base-Url"),
    x_client_secret: str | None = Header(None, alias="X-Client-Secret"),
) -> dict[str, Any]:
    return await _ch_request(
        "GET", _ch_base(x_ch_base_url), f"/integrate/session/{session_id}", _secret(x_client_secret)
    )
