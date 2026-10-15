"""Decision tools REST API router.

CRUD for tenant-scoped user-definable decision tools plus the
auto-generated-description endpoint. All routes are JWT-protected,
permission-checked against ``system::decision_tools``, and tenant-scoped:
names are unique WITHIN a tenant and every lookup/mutation resolves within
the caller's tenant.

Creating/updating a tool requires a configured System One model — a
structured "no System One model configured" error is returned otherwise.
"""
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

from app.api.deps import require_permission
from app.core.resource_types import RT_SYSTEM_DECISION_TOOLS
from app.core.tenant_context import get_tenant_context
from app.db.models.agent_data_type import AgentDataType
from app.db.session import DbSession
from app.schemas.decision_tools import (
    DecisionToolCreate,
    DecisionToolDescriptionRead,
    DecisionToolGenerateRequest,
    DecisionToolGenerateResponse,
    DecisionToolRead,
    DecisionToolUpdate,
)
from app.schemas.system_one import DecisionEnabledModelRead
from app.services.agents.workflow_authoring_service import WorkflowAuthoringError
from app.services.agents.workflow_generation_settings import (
    get_workflow_generation_model_id,
)
from app.services.system_one.decision_authoring_service import generate_decision_draft
from app.services.system_one.decision_model_availability_service import (
    DecisionModelCatalogueService,
)
from app.services.system_one.decision_tool_service import (
    DecisionToolNameConflictError,
    DecisionToolService,
    DecisionToolValidationError,
)
from app.services.system_one.provider_config_service import (
    SystemOneProviderConfigService,
)

logger = logging.getLogger(__name__)

DecisionToolsRouter = APIRouter(prefix="/decision-tools", tags=["Decision Tools"])

_service = DecisionToolService()
_provider_service = SystemOneProviderConfigService()
_catalogue = DecisionModelCatalogueService(_provider_service)


def _tenant_id(request: Request) -> uuid.UUID | None:
    """Resolve the caller's tenant id from the request tenant context.

    ``None`` means multi-tenancy is off (single-tenant / root deployment).
    """
    context = get_tenant_context(request)
    return context.tenant_id if context.is_set else None


async def _require_system_one_configured(
    db: DbSession, tenant_id: uuid.UUID | None
) -> None:
    """Configured-model gate: decision tool authoring requires an enabled
    provider within the caller's tenant."""
    status_info = await _provider_service.get_status(db, tenant_id)
    if not status_info.configured:
        raise HTTPException(
            status_code=422,
            detail=(
                "No Decision Model provider is configured. Configure a "
                "Decision Model provider before creating decision tools."
            ),
        )


async def _model_identity_map(
    db: DbSession, tools: list
) -> dict[uuid.UUID, dict]:
    """Provider/model identity per availability id for Read enrichment
    (identity only — never credential material)."""
    from app.db.models.decision_model_availability import DecisionModelAvailability
    from app.db.models.system_one_provider_config import SystemOneProviderConfig

    ids = {
        t.decision_model_availability_id
        for t in tools
        if t.decision_model_availability_id is not None
    }
    if not ids:
        return {}
    rows = await db.execute(
        select(DecisionModelAvailability).where(
            DecisionModelAvailability.id.in_(ids)
        )
    )
    by_id = {row.id: row for row in rows.scalars().all()}
    provider_ids = {row.decision_model_provider_id for row in by_id.values()}
    prow = await db.execute(
        select(SystemOneProviderConfig).where(
            SystemOneProviderConfig.id.in_(provider_ids)
        )
    )
    providers = {p.id: p for p in prow.scalars().all()}
    identity: dict[uuid.UUID, dict] = {}
    for availability_id, row in by_id.items():
        provider = providers.get(row.decision_model_provider_id)
        if provider is None:
            continue
        identity[availability_id] = {
            "provider_type": provider.provider_type.value,
            "provider_display_name": provider.display_name,
            "model_name": row.model_name,
        }
    return identity


def _apply_model_identity(
    read: "DecisionToolRead", identity: dict
) -> "DecisionToolRead":
    if read.decision_model_availability_id is not None:
        info = identity.get(read.decision_model_availability_id) or {}
        read.provider_type = info.get("provider_type")
        read.provider_display_name = info.get("provider_display_name")
        read.model_name = info.get("model_name")
    else:
        # Legacy tools (pre-migration) carry the free-text provider model.
        read.model_name = read.provider_model
    return read


@DecisionToolsRouter.get("", response_model=list[DecisionToolRead])
async def list_decision_tools(
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_DECISION_TOOLS, "read")),
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[DecisionToolRead]:
    """List decision tools within the caller's tenant, filterable by status."""
    tools = await _service.list(db, _tenant_id(request), status=status_filter)
    identity = await _model_identity_map(db, tools)
    return [
        _apply_model_identity(DecisionToolRead.model_validate(t), identity)
        for t in tools
    ]


@DecisionToolsRouter.get("/enabled-models", response_model=list[DecisionEnabledModelRead])
async def list_enabled_decision_models(
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_DECISION_TOOLS, "read")),
) -> list[DecisionEnabledModelRead]:
    """Enabled decision models for the authoring selector (provider enabled
    AND model enabled within the caller's tenant)."""
    enabled = await _catalogue.list_enabled_models(db, _tenant_id(request))
    return [
        DecisionEnabledModelRead(
            availability_id=m.availability_id,
            provider_id=m.provider_id,
            provider_type=m.provider_type,
            provider_display_name=m.provider_display_name,
            model_name=m.model_name,
        )
        for m in enabled
    ]


@DecisionToolsRouter.post(
    "",
    response_model=DecisionToolRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_decision_tool(
    body: DecisionToolCreate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_DECISION_TOOLS, "create")),
) -> DecisionToolRead:
    """Create a decision tool; enforces per-tenant name uniqueness.

    The auto-generated description is derived from the definition and
    returned in the response.
    """
    await _require_system_one_configured(db, _tenant_id(request))
    try:
        tool = await _service.create(db, body, _tenant_id(request))
    except DecisionToolNameConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.errors)
    except DecisionToolValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors)
    identity = await _model_identity_map(db, [tool])
    return _apply_model_identity(DecisionToolRead.model_validate(tool), identity)


@DecisionToolsRouter.post(
    "/generate", response_model=DecisionToolGenerateResponse
)
async def generate_decision_tool_draft(
    body: DecisionToolGenerateRequest,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_DECISION_TOOLS, "create")),
) -> DecisionToolGenerateResponse:
    """AI-assisted authoring: draft questions + state mapping.

    Reuses ``workflow_authoring_service.generate_workflow_text`` (the skill
    editor's generation mechanism) with a decision-tool-specific prompt;
    the draft is validated through the decision-tool question schemas.
    Permission-gated like tool creation.
    """
    model_id = get_workflow_generation_model_id()
    if not model_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "Workflow generation model is not configured. Configure it "
                "in system settings."
            ),
        )

    async def _resolve_type(
        type_id: uuid.UUID | None,
    ) -> AgentDataType | None:
        if type_id is None:
            return None
        # Strict tenant matching — the NULL shared slot is retired
        # (adoption migrated legacy rows into the root tenant).
        tenant_id = _tenant_id(request)
        result = await db.execute(
            select(AgentDataType).where(
                AgentDataType.id == type_id,
                AgentDataType.tenant_id == tenant_id,
            )
        )
        data_type = result.scalar_one_or_none()
        if data_type is None:
            raise HTTPException(
                status_code=422,
                detail=f"data type {type_id} not found or not visible to this tenant",
            )
        return data_type

    try:
        input_type = await _resolve_type(body.input_data_type_id)
        output_type = await _resolve_type(body.output_data_type_id)
        return await generate_decision_draft(
            db,
            description=body.description,
            model_id=model_id,
            input_data_type=input_type,
            output_data_type=output_type,
            existing_questions=body.existing_questions,
        )
    except WorkflowAuthoringError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@DecisionToolsRouter.get("/{tool_id}", response_model=DecisionToolRead)
async def get_decision_tool(
    tool_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_DECISION_TOOLS, "read")),
) -> DecisionToolRead:
    tool = await _service.get(db, tool_id, _tenant_id(request))
    if not tool:
        raise HTTPException(status_code=404, detail="Decision tool not found")
    identity = await _model_identity_map(db, [tool])
    return _apply_model_identity(DecisionToolRead.model_validate(tool), identity)


@DecisionToolsRouter.put("/{tool_id}", response_model=DecisionToolRead)
async def update_decision_tool(
    tool_id: uuid.UUID,
    body: DecisionToolUpdate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_DECISION_TOOLS, "update")),
) -> DecisionToolRead:
    """Update the definition; re-validates and regenerates the stored
    description."""
    try:
        tool = await _service.update(db, tool_id, body, _tenant_id(request))
    except DecisionToolValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors)
    identity = await _model_identity_map(db, [tool])
    return _apply_model_identity(DecisionToolRead.model_validate(tool), identity)


@DecisionToolsRouter.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_decision_tool(
    tool_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_DECISION_TOOLS, "delete")),
) -> None:
    """Remove a decision tool and its questions (results are cascade-deleted)."""
    try:
        await _service.delete(db, tool_id, _tenant_id(request))
    except DecisionToolValidationError as exc:
        raise HTTPException(status_code=404, detail=exc.errors)


@DecisionToolsRouter.get(
    "/{tool_id}/description", response_model=DecisionToolDescriptionRead
)
async def get_decision_tool_description(
    tool_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_DECISION_TOOLS, "read")),
) -> DecisionToolDescriptionRead:
    """Return the auto-generated tool description (also included in Read
    responses)."""
    tool = await _service.get(db, tool_id, _tenant_id(request))
    if not tool:
        raise HTTPException(status_code=404, detail="Decision tool not found")
    return DecisionToolDescriptionRead(
        tool_id=tool.id, name=tool.name, description=tool.description or ""
    )
