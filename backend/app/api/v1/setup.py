"""Setup router — initial admin seeding endpoint (public during first setup)."""
import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.db.session import DbSession
from app.db.models.identity import Identity, IdentityType, Role, RoleType
from app.schemas.identity import SetupInitResponse
from app.schemas.identity_bootstrap import (
    IdentityStatusResponse,
    ProviderSetupRequest,
    ProviderSetupResult,
    ProviderType,
    SetupState,
)
from app.services.identity.bootstrap_service import IdentityBootstrapService
from app.services.identity.keycloak_admin_client import KeycloakAdminError

logger = logging.getLogger(__name__)

SetupRouter = APIRouter(prefix="/setup", tags=["Setup"])

ADMIN_ROLE_NAME = "admin"


@SetupRouter.get("/identity-status", response_model=IdentityStatusResponse)
async def get_identity_status(db: DbSession) -> IdentityStatusResponse:
    """Return the current identity provider setup state.

    This endpoint is public — no JWT required.
    Returns NOT_CONFIGURED, CONFIGURED, or IN_PROGRESS.
    """
    service = IdentityBootstrapService()
    setup_state = await service.check_setup_state(db)

    provider_type: str | None = None
    oidc_provider_url: str | None = None

    if setup_state == SetupState.CONFIGURED:
        config = await service.get_current_config(db)
        if config:
            provider_type = config.provider_type
            oidc_provider_url = config.oidc_provider_url

    return IdentityStatusResponse(
        setup_state=setup_state,
        provider_type=provider_type,
        oidc_provider_url=oidc_provider_url,
    )


@SetupRouter.post("/identity", response_model=ProviderSetupResult)
async def provision_identity(
    request: ProviderSetupRequest,
    db: DbSession,
) -> ProviderSetupResult:
    """Provision the identity provider.

    This endpoint is public — no JWT required.
    Returns 409 if setup is already complete and force_reconfigure is False.
    Returns 502 if the Keycloak Admin API is unreachable.
    """
    service = IdentityBootstrapService()
    setup_state = await service.check_setup_state(db)

    if setup_state == SetupState.CONFIGURED and not request.force_reconfigure:
        raise HTTPException(
            status_code=409,
            detail="Identity provider is already configured. "
            "Set force_reconfigure=true to overwrite.",
        )

    try:
        if request.provider_type == ProviderType.KEYCLOAK_BUNDLED:
            result = await service.provision_bundled_keycloak(db, request)
        elif request.provider_type in (ProviderType.KEYCLOAK_EXTERNAL, ProviderType.AZURE_ENTRAID):
            result = await service.provision_external_oidc(db, request)
        else:
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported provider_type: {request.provider_type}",
            )
    except KeycloakAdminError as exc:
        logger.error("Keycloak Admin API error: %s", exc)
        raise HTTPException(
            status_code=502,
            detail={"error_code": exc.error_code, "detail": exc.detail},
        ) from exc

    if not result.success and result.error_code == "keycloak_unreachable":
        raise HTTPException(
            status_code=502,
            detail={"error_code": result.error_code, "detail": result.detail},
        )

    return result


@SetupRouter.post("/init", response_model=SetupInitResponse)
async def setup_init(db: DbSession) -> SetupInitResponse:
    """
    Seed the first admin role and identity idempotently.

    This endpoint is public — no JWT required.
    """
    # Check if admin role already exists
    existing_role_result = await db.execute(
        select(Role).where(Role.name == ADMIN_ROLE_NAME)
    )
    admin_role = existing_role_result.scalar_one_or_none()
    already_initialized = admin_role is not None

    if not admin_role:
        admin_role = Role(
            name=ADMIN_ROLE_NAME,
            description="Platform administrator with full access",
            role_type=RoleType.both,
        )
        db.add(admin_role)
        await db.flush()
        await db.refresh(admin_role)
        logger.info("Created admin role: %s", admin_role.id)

    # Check if admin identity already exists (look for system admin placeholder)
    existing_identity_result = await db.execute(
        select(Identity).where(Identity.subject == "system:admin")
    )
    admin_identity = existing_identity_result.scalar_one_or_none()

    if not admin_identity:
        admin_identity = Identity(
            subject="system:admin",
            display_name="Platform Administrator",
            identity_type=IdentityType.user,
            role_id=admin_role.id,
        )
        db.add(admin_identity)
        await db.flush()
        await db.refresh(admin_identity)
        logger.info("Created admin identity: %s", admin_identity.id)

    return SetupInitResponse(
        message="Setup complete" if not already_initialized else "Already initialized",
        admin_role_id=admin_role.id,
        admin_identity_id=admin_identity.id,
        already_initialized=already_initialized,
    )
