"""Internal CC↔AR API for the LLM Mock Layer (Phase 4).

Service-certificate-only endpoints (agent-instance certificates are blocked
from ``/internal/*`` by the CC middleware). Agent Runtime submits and
retrieves ``LLMMockRecording`` rows here in record/replay modes — it never
touches the database. Payloads carry prompt + response + usage metadata
only; API keys and identity tokens are rejected.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.api.deps import require_internal_tenant_context, require_service_certificate
from app.core.tenant_context import TenantContext
from app.db.models.llm_mocking import LLMMockRecording, MockInteractionKind
from app.db.session import DbSession

logger = logging.getLogger(__name__)

InternalLLMMockRouter = APIRouter(
    prefix="/internal/llm-mock",
    tags=["internal"],
    dependencies=[
        Depends(require_service_certificate),
        Depends(require_internal_tenant_context),
    ],
)

TenantCtx = Annotated[TenantContext, Depends(require_internal_tenant_context)]


def _validate_payload(payload: dict[str, Any]) -> None:
    """Fail closed on credential/token-shaped fields (SEC3, PRD N4)."""
    forbidden = (
        "api_key", "apikey", "secret", "password", "authorization",
        "credential", "access_token", "id_token", "refresh_token",
    )

    def _scan(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if str(key).lower() in forbidden:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Mock recording payload contains forbidden "
                        f"field '{key}' — recordings never hold credentials",
                    )
                _scan(value)
        elif isinstance(obj, list):
            for item in obj:
                _scan(item)

    _scan(payload)


@InternalLLMMockRouter.post("/recordings", status_code=201)
async def upsert_recordings(
    body: dict[str, Any],
    db: DbSession,
    tenant_ctx: TenantCtx,
) -> dict[str, Any]:
    """Batch upsert recordings from AR record mode (4.2).

    Body: ``{"recordings": [ {recording_key, model_identifier,
    interaction_kind, request_payload, response_payload, usage_metadata,
    recorded_by, session_id?}, ... ]}``. Idempotent per
    (tenant, recording_key, model_identifier).
    """
    items = body.get("recordings")
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=422, detail="recordings[] required")

    saved = 0
    for item in items:
        _validate_payload(item)
        try:
            kind = MockInteractionKind(item.get("interaction_kind"))
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"invalid interaction_kind '{item.get('interaction_kind')}'",
            )
        key = item.get("recording_key")
        model_identifier = item.get("model_identifier")
        if not key or not model_identifier:
            raise HTTPException(
                status_code=422,
                detail="recording_key and model_identifier are required",
            )
        stmt = select(LLMMockRecording).where(
            LLMMockRecording.recording_key == key,
            LLMMockRecording.model_identifier == model_identifier,
        )
        if tenant_ctx.tenant_id is not None:
            stmt = stmt.where(LLMMockRecording.tenant_id == tenant_ctx.tenant_id)
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing is None:
            existing = LLMMockRecording(
                tenant_id=tenant_ctx.tenant_id,
                recording_key=key,
                model_identifier=model_identifier,
            )
            db.add(existing)
        existing.interaction_kind = kind
        existing.request_payload = item.get("request_payload")
        existing.response_payload = item.get("response_payload")
        existing.usage_metadata = item.get("usage_metadata")
        existing.recorded_by = item.get("recorded_by")
        if item.get("session_id"):
            existing.session_id = item["session_id"]
        saved += 1
    await db.flush()
    logger.info("LLM mock recordings upserted: %d (tenant %s)", saved,
                tenant_ctx.tenant_id)
    return {"saved": saved}


@InternalLLMMockRouter.get("/recordings")
async def get_recording(
    db: DbSession,
    tenant_ctx: TenantCtx,
    recording_key: str = Query(..., min_length=8),
    model_identifier: str | None = Query(default=None),
) -> dict[str, Any] | None:
    """Replay-mode lookup by ``recording_key`` within the tenant (4.3)."""
    stmt = select(LLMMockRecording).where(
        LLMMockRecording.recording_key == recording_key
    )
    if tenant_ctx.tenant_id is not None:
        stmt = stmt.where(LLMMockRecording.tenant_id == tenant_ctx.tenant_id)
    if model_identifier:
        stmt = stmt.where(LLMMockRecording.model_identifier == model_identifier)
    recording = (await db.execute(stmt)).scalars().first()
    if recording is None:
        return None
    return {
        "recording_key": recording.recording_key,
        "model_identifier": recording.model_identifier,
        "interaction_kind": recording.interaction_kind.value,
        "request_payload": recording.request_payload,
        "response_payload": recording.response_payload,
        "usage_metadata": recording.usage_metadata,
        "recorded_by": recording.recorded_by,
    }
