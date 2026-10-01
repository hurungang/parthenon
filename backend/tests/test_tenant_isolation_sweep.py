"""Systematic tenant-isolation sweep — EVERY entity, no exceptions.

Guarantee under test (FIX-20260928-121317, "Expected Behavior"): every
SQLAlchemy entity is either

(a) **tenant-scoped** — carries a ``tenant_id`` column and is therefore
    constrained by the ``do_orm_execute`` choke point
    (``app.db.tenant_scoping``) on any tenant-bound session, or
(b) **consciously registered** in ``TENANT_AGNOSTIC_REGISTRY`` below
    with a documented scoping strategy (platform-level entity, or a
    join/child table that inherits scope via its scoped parents).

Three test groups:

1. ``TestRegistryCompleteness`` — registry is complete and honest: every
   model without ``tenant_id`` MUST be registered (new unregistered
   models fail here until their strategy is consciously documented);
   every registry key must reference a real table; every entry must
   carry a strategy note.
2. ``TestScopedSweep`` — parametrized over EVERY ``tenant_id``-bearing
   model: one row is inserted in each of two tenants, then a tenant-A
   scoped session must (i) see ONLY tenant A's row via ``select`` and
   (ii) get ``None`` for tenant B's row id via ``get`` (404 semantics).
3. ``TestTenantAgnosticStrategyPlatformUser`` — asserts the documented
   strategy for the highest-value agnostic entity, ``PlatformUser``
   ("membership-join"): a tenant-A scoped user query must return only
   users with an ACTIVE membership in tenant A.  **This FAILS pre-fix**
   — it is the ORM-layer reproduction of the user leak; the endpoint
   level lives in ``backend/tests/test_tenant_user_leak.py``.

Tests are deterministic and self-contained: each parametrized case gets
a fresh in-memory engine, seeds its own tenants, and asserts isolation
through the same choke point the ``get_db`` dependency uses.
"""
from __future__ import annotations

import os
import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

import app.db.models  # noqa: F401,E402 — import ALL models so the registry is populated
from app.db.models.access_request import AccessRequest  # noqa: E402
from app.db.models.access_request_batch import AccessRequestBatch  # noqa: E402
from app.db.models.agent_api_key import AgentApiKey  # noqa: E402
from app.db.models.agent_data import AgentData  # noqa: E402
from app.db.models.agent_data_type import AgentDataType  # noqa: E402
from app.db.models.agent_output import AgentOutput  # noqa: E402
from app.db.models.agent_run_relationship import AgentRunRelationship  # noqa: E402
from app.db.models.agents import (  # noqa: E402
    AgentA2ASession,
    AgentIdentity,
    AgentInstance,
    AgentJob,
    AgentRole,
    AgentType,
    ModelConfig,
)
from app.db.models.conversations import ConversationSession  # noqa: E402
from app.db.models.group import Group  # noqa: E402
from app.db.models.guardrail_threshold_event import GuardrailThresholdEvent  # noqa: E402
from app.db.models.identity import Identity, Role  # noqa: E402
from app.db.models.identity_provider_config import IdentityProviderConfig  # noqa: E402
from app.db.models.identity_provider_config_audit import IdentityProviderConfigAudit  # noqa: E402
from app.db.models.intervene import InterveneRequest  # noqa: E402
from app.db.models.mcp_hub import McpServer  # noqa: E402
from app.db.models.model_availability import ModelAvailability  # noqa: E402
from app.db.models.model_guardrail_configuration import ModelGuardrailConfiguration  # noqa: E402
from app.db.models.model_guardrail_evaluation import (  # noqa: E402
    ModelGuardrailEvaluation,
    ModelGuardrailEvaluationOutcome,
)
from app.db.models.model_usage_posture import ModelUsagePosture  # noqa: E402
from app.db.models.notifications import (  # noqa: E402
    NotificationChannel,
    NotificationEvent,
    NotificationLog,
    RecipientGroup,
    SourceType,
)
from app.db.models.platform_user import PlatformUser  # noqa: E402
from app.db.models.policy_action import PolicyAction  # noqa: E402
from app.db.models.policy_resource import PolicyResource  # noqa: E402
from app.db.models.policy_statement import PolicyStatement  # noqa: E402
from app.db.models.results import ResultRecord  # noqa: E402
from app.db.models.scheduling import ScheduledJob  # noqa: E402
from app.db.models.session_logs import ExecutionLogEntry  # noqa: E402
from app.db.models.skills import Skill, Sop  # noqa: E402
from app.db.models.tag_definition import TagDefinition, TagScope  # noqa: E402
from app.db.models.tenant import Tenant  # noqa: E402
from app.db.models.tenant_audit_event import (  # noqa: E402
    TenantAuditActorType,
    TenantAuditEvent,
    TenantAuditEventType,
)
from app.db.models.tenant_invitation import TenantInvitation  # noqa: E402
from app.db.models.tenant_license import LicenseTier, TenantLicense  # noqa: E402
from app.db.models.tenant_membership import TenantUserMembership  # noqa: E402
from app.db.models.tenant_quota_usage import QuotaType, TenantQuotaUsage  # noqa: E402
from app.db.models.termination_request import TerminationRequest  # noqa: E402
from app.db.models.tool_calls import RuntimeToolCall  # noqa: E402
from app.db.session import Base  # noqa: E402
from app.db.tenant_scoping import apply_tenant_scope, register_tenant_scope_listener  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
# TENANT_AGNOSTIC_REGISTRY
#
# Every mapped model WITHOUT a tenant_id column must appear here, keyed by
# table name, with its documented isolation strategy.  A new model without
# tenant_id fails TestRegistryCompleteness until it is consciously added.
# ══════════════════════════════════════════════════════════════════════════════

TENANT_AGNOSTIC_REGISTRY: dict[str, str] = {
    # ── Platform-level entities (no tenant attribution by design) ────────────
    "platform_users": (
        "DUAL strategy (FIX-20260929-221449): DATA PLANE — membership-join: "
        "tenant-context user queries must filter through the ACTIVE "
        "TenantUserMembership of the requesting tenant (list + detail + all "
        "/platform-users sub-resources); IDENTITY PLANE — PlatformUser-by-sub "
        "resolution and JIT provisioning are tenant-scope-EXEMPT via "
        "execute_unscoped() (identity resolution must see the user record "
        "without a membership; membership + RBAC then gate access — "
        "no_access_to_workspace without one). PlatformUser itself has no tenant_id"
    ),
    "permissions": (
        "global catalogue, read-only reference data — permission definitions "
        "are platform vocabulary, not tenant business rows"
    ),
    "identity_provider_setup_state": (
        "platform-level setup state — one-time OIDC setup wizard completion flag"
    ),
    "tenants": (
        "the tenant entity itself — resolution/registry metadata; tenants are "
        "addressed explicitly, never filtered by the scope choke point"
    ),
    "platform_settings": (
        "platform-level key/value settings (incl. the tenancy switch); cached "
        "reads via PlatformSettingsService"
    ),
    "certificate_revocation_entries": (
        "platform-level CA revocation list — certificates are issued by the "
        "single platform CA, not per tenant"
    ),
    "certificate_validation_logs": (
        "platform-level certificate validation audit trail (mTLS boundary "
        "telemetry, attributed to services not tenants)"
    ),
    # ── Join/child tables — inherit scope via their tenant-scoped parents ────
    "agent_instance_certificates": "join/child table — inherits scope via agent_types (agent_type_id)",
    "agent_plans": "join/child table — inherits scope via agent_types (agent_type_id)",
    "execution_logs": "join/child table — inherits scope via agent_jobs (session_id)",
    "agent_role_identities": "join table — inherits scope via agent_roles (role_id)",
    "agent_role_mcp_sessions": "join table — inherits scope via agent_roles (role_id) / mcp_servers (server_id)",
    "agent_role_sops": "join table — inherits scope via agent_roles (role_id)",
    "agent_role_skills": "join table — inherits scope via agent_roles (role_id)",
    "agent_type_skill_bindings": "join table — inherits scope via agent_types (agent_type_id)",
    "agent_type_sop_bindings": "join table — inherits scope via agent_types (agent_type_id)",
    "api_key_usage_logs": "join/child table — inherits scope via agent_api_keys (api_key_id)",
    "channel_properties": "join/child table — inherits scope via notification_channels (channel_id)",
    "conversation_turns": "join/child table — inherits scope via conversation_sessions (session_id)",
    "group_channel_mappings": "join table — inherits scope via recipient_groups / notification_channels",
    "group_roles": "join table — inherits scope via groups (group_id) / roles (role_id)",
    "intervene_responses": "join/child table — inherits scope via intervene_requests (request_id)",
    "job_executions": "join/child table — inherits scope via scheduled_jobs (job_id)",
    "mcp_sessions": "join/child table — inherits scope via mcp_servers (server_id)",
    "mcp_tools": "join/child table — inherits scope via mcp_servers (server_id)",
    "policy_tag_conditions": "join/child table — inherits scope via policy_statements (policy_statement_id)",
    "role_permissions": "join table — inherits scope via roles (role_id); permission side is global catalogue",
    "skill_tool_bindings": "join table — inherits scope via skills (skill_id) → mcp_servers (tool_id)",
    "sop_recursion_validation_checks": "join/child table — inherits scope via agent_types (checked_agent_type_id)",
    "sop_recursion_validation_findings": "join/child table — inherits scope via sop_recursion_validation_checks",
    "sop_steps": "join/child table — inherits scope via sops (sop_id)",
    "tag_values": "join/child table — inherits scope via tag_definitions (tag_definition_id)",
    "termination_cascade_outcomes": "join/child table — inherits scope via termination_requests",
    "token_refresh_logs": "join/child table — inherits scope via agent_identities (agent_identity_id)",
    "tool_call_records": "join/child table — inherits scope via conversation_turns (turn_id)",
    "tool_permissions": "join table — inherits scope via roles (role_id) → mcp_servers (tool_id)",
    "user_groups": "join table — inherits scope via groups (group_id); user side via membership-join strategy",
    "user_roles": "join table — inherits scope via roles (role_id); user side via membership-join strategy",
}


def _scoped_model_classes() -> list[type]:
    """Every non-inherited mapped class carrying a direct tenant_id column."""
    classes = set()
    for mapper in Base.registry.mappers:
        if mapper.inherits or mapper.local_table is None:
            continue
        if "tenant_id" in mapper.local_table.columns.keys():
            classes.add(mapper.class_)
    return sorted(classes, key=lambda c: c.__name__)


SCOPED_MODEL_CLASSES = _scoped_model_classes()


# ══════════════════════════════════════════════════════════════════════════════
# Minimal-valid-row construction for every scoped model (Test 2 helpers).
#
# ``_OWN_KWARGS[cls]`` returns the model's OWN scalar kwargs (no FKs);
# ``_PARENT_FKS[cls]`` resolves the required FK kwargs by first ensuring the
# parent rows exist in the same tenant context.  Seeding always runs on an
# UNSCOPED session with an explicit tenant_id.
# ══════════════════════════════════════════════════════════════════════════════

_OWN_KWARGS = {
    # ── Independent roots (no required FK parents) ───────────────────────────
    Role: lambda t, s: {"name": f"role-{s}"},
    Group: lambda t, s: {"name": f"group-{s}"},
    AgentRole: lambda t, s: {"name": f"arole-{s}"},
    AgentIdentity: lambda t, s: {"name": f"aid-{s}", "identity_type": "realm_user"},
    AgentType: lambda t, s: {"name": f"atype-{s}"},
    AgentA2ASession: lambda t, s: {
        "requester_instance_id": f"inst-req-{s}",
        "receiver_instance_id": f"inst-recv-{s}",
        "session_link_id": f"link-{s}",
    },
    ConversationSession: lambda t, s: {},
    Identity: lambda t, s: {"subject": f"subj-{s}", "identity_type": "user"},
    IdentityProviderConfig: lambda t, s: {
        "provider_scope": f"sweep-{s}",
        "provider_type": "oidc",
        "display_name": f"idp-{s}",
        "issuer_url": f"https://issuer-{s}.example.test",
        "client_id": f"client-{s}",
    },
    IdentityProviderConfigAudit: lambda t, s: {
        "changed_by": "sweep",
        "change_type": "create",
        "changed_fields": {"scope": "before"},
    },
    McpServer: lambda t, s: {
        "name": f"mcp-{s}",
        "slug": f"mcp-{s}",
        "base_url": f"https://mcp-{s}.example.test",
    },
    ModelConfig: lambda t, s: {"display_name": f"mconf-{s}", "provider_type": "openai"},
    NotificationChannel: lambda t, s: {"name": f"nchan-{s}", "channel_type": "SMTP"},
    RecipientGroup: lambda t, s: {"name": f"rgroup-{s}", "slug": f"rg-{s}"},
    Skill: lambda t, s: {"name": f"skill-{s}"},
    Sop: lambda t, s: {"name": f"sop-{s}"},
    TagDefinition: lambda t, s: {"key": f"tagkey-{s}", "scope": TagScope.global_scope},
    TenantAuditEvent: lambda t, s: {
        "event_type": TenantAuditEventType.tenant_created,
        "actor_type": TenantAuditActorType.system,
    },
    TenantInvitation: lambda t, s: {
        "tenant_id": t,
        "email": f"invite-{s}@example.test",
        "tenant_role": "member",
    },
    TenantLicense: lambda t, s: {
        "tenant_id": t,
        "tier": LicenseTier.free,
        "max_users": 10,
        "max_agent_types": 5,
        "monthly_agent_executions": 100,
    },
    TenantQuotaUsage: lambda t, s: {
        "tenant_id": t,
        "quota_type": QuotaType.monthly_executions,
        "period_start": date.today(),
    },
    ScheduledJob: lambda t, s: {
        "name": f"sched-{s}",
        "cron_expression": "0 0 * * *",
        "target_type": "agent",
        "target_id": uuid.uuid4(),
    },
    RuntimeToolCall: lambda t, s: {
        "session_id": uuid.uuid4(),
        "session_kind": "agent",
        "tool_name": f"tool-{s}",
        "route_type": "system",
        "status": "success",
    },
    AgentData: lambda t, s: {"data_name": f"data-{s}", "data_value": {"sweep": s}},
    AgentDataType: lambda t, s: {"name": f"adtype-{s}", "slug": f"adtype-{s}", "fields": []},
    ResultRecord: lambda t, s: {"payload": {"sweep": s}},
    # ── Models with required FK parents (own scalars only) ──────────────────
    PlatformUser: lambda t, s: {
        "sub": f"sub-{s}",
        "email": f"u-{s}@example.test",
        "display_name": f"User {s}",
    },
    TenantUserMembership: lambda t, s: {"tenant_id": t, "tenant_role": "member"},
    AccessRequestBatch: lambda t, s: {"justification": "sweep"},
    AccessRequest: lambda t, s: {"status": "pending"},
    AgentApiKey: lambda t, s: {
        "name": f"akey-{s}",
        "key_hash": "a" * 64,
        "key_prefix": f"pk_{s}",
    },
    AgentInstance: lambda t, s: {},
    AgentJob: lambda t, s: {},
    AgentOutput: lambda t, s: {"validation_status": "valid"},
    AgentRunRelationship: lambda t, s: {"relationship_type": "delegation"},
    ExecutionLogEntry: lambda t, s: {"event_type": "sweep", "message": "sweep"},
    PolicyStatement: lambda t, s: {"effect": "allow", "module": "system::permissions"},
    PolicyAction: lambda t, s: {"action": "read"},
    PolicyResource: lambda t, s: {"resource_type": "system::permissions"},
    ModelAvailability: lambda t, s: {"model_name": f"model-{s}"},
    ModelGuardrailConfiguration: lambda t, s: {
        "model_name": f"gmodel-{s}",
        "period": "day",
        "limit_value": 100,
    },
    ModelGuardrailEvaluation: lambda t, s: {
        "policy_name": "sweep",
        "evaluated_period": "day",
        "policy_mode": "terminate",
        "evaluation_outcome": ModelGuardrailEvaluationOutcome.pass_,
        "threshold_value": 10,
        "observed_value": 1,
        "posture_state": "within_limit",
    },
    GuardrailThresholdEvent: lambda t, s: {
        "event_type": "observe_only_threshold_reached",
        "severity": "info",
        "display_message": "sweep",
    },
    ModelUsagePosture: lambda t, s: {
        "posture_period": "day",
        "usage_value": 1,
        "limit_value": 100,
        "posture_state": "within_limit",
    },
    NotificationEvent: lambda t, s: {"body": "sweep"},
    NotificationLog: lambda t, s: {"source_type": SourceType.AGENT, "body": "sweep"},
    InterveneRequest: lambda t, s: {
        "intervention_type": "approval",
        "reason": "sweep",
    },
    TerminationRequest: lambda t, s: {
        "termination_scope": "node_only",
        "permission_evaluation_outcome": "allowed",
        "request_status": "accepted",
    },
}


async def _parent_fks(db, ctx, cls, tenant_id, suffix) -> dict:
    """Required FK kwargs for *cls*, ensuring parent rows exist first
    (within the same tenant context)."""

    async def parent(model_cls, slot: str | None = None):
        return await _ensure(db, ctx, model_cls, tenant_id, suffix, slot=slot)

    if cls is TenantUserMembership:
        return {"user_id": (await parent(PlatformUser)).id}
    if cls is AccessRequestBatch:
        return {"user_id": (await parent(PlatformUser)).id}
    if cls is AccessRequest:
        batch = await parent(AccessRequestBatch)
        return {"batch_id": batch.id, "user_id": batch.user_id}
    if cls is AgentApiKey:
        return {
            "agent_identity_id": (await parent(AgentIdentity)).id,
            "agent_role_id": (await parent(AgentRole)).id,
        }
    if cls in (AgentInstance, AgentJob):
        return {"agent_type_id": (await parent(AgentType)).id}
    if cls is AgentOutput:
        return {
            "data_type_id": (await parent(AgentDataType)).id,
            "agent_type_id": (await parent(AgentType)).id,
            "execution_session_id": (await parent(AgentJob)).id,
        }
    if cls is AgentRunRelationship:
        # Needs TWO distinct agent jobs (parent/child of the delegation).
        return {
            "parent_agent_job_id": (await parent(AgentJob, slot="parent")).id,
            "child_agent_job_id": (await parent(AgentJob, slot="child")).id,
        }
    if cls is ExecutionLogEntry:
        return {"session_id": (await parent(AgentJob)).id}
    if cls is PolicyStatement:
        return {"role_id": (await parent(Role)).id}
    if cls in (PolicyAction, PolicyResource):
        return {"policy_statement_id": (await parent(PolicyStatement)).id}
    if cls is ModelAvailability:
        return {"vendor_model_config_id": (await parent(ModelConfig)).id}
    if cls is ModelGuardrailConfiguration:
        return {"model_id": (await parent(ModelConfig)).id}
    if cls is ModelGuardrailEvaluation:
        return {
            "model_guardrail_configuration_id": (await parent(ModelGuardrailConfiguration)).id,
            "agent_job_id": (await parent(AgentJob)).id,
        }
    if cls is GuardrailThresholdEvent:
        return {
            "model_guardrail_evaluation_id": (await parent(ModelGuardrailEvaluation)).id,
            "agent_job_id": (await parent(AgentJob)).id,
        }
    if cls is ModelUsagePosture:
        return {
            "model_guardrail_configuration_id": (await parent(ModelGuardrailConfiguration)).id,
            "model_id": (await parent(ModelConfig)).id,
        }
    if cls in (NotificationEvent, NotificationLog):
        return {"channel_id": (await parent(NotificationChannel)).id}
    if cls is InterveneRequest:
        return {
            "agent_session_id": (await parent(AgentJob)).id,
            "agent_type_id": (await parent(AgentType)).id,
        }
    if cls is IdentityProviderConfigAudit:
        return {"config_id": (await parent(IdentityProviderConfig)).id}
    if cls is TerminationRequest:
        return {
            "requested_by_user_id": (await parent(Identity)).id,
            "target_agent_job_id": (await parent(AgentJob)).id,
        }
    return {}


async def _ensure(
    db, ctx: dict, cls: type, tenant_id: uuid.UUID, suffix: str, slot: str | None = None
):
    """Build (once per tenant context) and return an instance of *cls*."""
    key = (cls, slot)
    if key in ctx:
        return ctx[key]
    kwargs = dict(_OWN_KWARGS[cls](tenant_id, suffix))
    # Only tenant-scoped models carry the column (PlatformUser, used as a
    # parent here, is deliberately tenant-agnostic).
    if "tenant_id" in cls.__table__.columns.keys():
        kwargs["tenant_id"] = tenant_id
    kwargs.update(await _parent_fks(db, ctx, cls, tenant_id, suffix))
    obj = cls(**kwargs)
    db.add(obj)
    await db.flush()
    ctx[key] = obj
    return obj


@pytest_asyncio.fixture
async def sweep_engine():
    """Fresh in-memory engine per test — no cross-test pollution."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # SQLite renders the Postgres-partial unique index as a FULL unique
        # index — drop it (same accommodation as test_tenant_scoping.py).
        await conn.exec_driver_sql("DROP INDEX IF EXISTS uq_roles_global_name")
    register_tenant_scope_listener()  # idempotent
    yield engine
    await engine.dispose()


async def _seed_pair(engine, model_cls) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert one row of *model_cls* in each of two tenants (plus parent
    chains); return (row_id_tenant_a, row_id_tenant_b)."""
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as db:
        tenant_a = Tenant(name="Sweep A", slug="sweep-a")
        tenant_b = Tenant(name="Sweep B", slug="sweep-b")
        db.add_all([tenant_a, tenant_b])
        await db.flush()
        row_a = await _ensure(db, {}, model_cls, tenant_a.id, "a")
        row_b = await _ensure(db, {}, model_cls, tenant_b.id, "b")
        await db.commit()
        return row_a.id, row_b.id


# ══════════════════════════════════════════════════════════════════════════════
# Test 1 — Registry completeness ("ALL entities bound or registered")
# ══════════════════════════════════════════════════════════════════════════════


class TestRegistryCompleteness:
    def test_every_tenant_agnostic_model_is_registered_with_a_strategy(self):
        """Every mapped model WITHOUT tenant_id must be in
        TENANT_AGNOSTIC_REGISTRY — a new tenant-agnostic model fails here
        until its isolation strategy is consciously documented."""
        unclassified = []
        for mapper in Base.registry.mappers:
            if mapper.inherits or mapper.local_table is None:
                continue
            if "tenant_id" in mapper.local_table.columns.keys():
                continue
            table = mapper.local_table.name
            if table not in TENANT_AGNOSTIC_REGISTRY:
                unclassified.append(f"{mapper.class_.__name__} -> {table}")
        assert not unclassified, (
            "UNCLASSIFIED TENANT-AGNOSTIC MODELS — these models have no "
            "tenant_id and no documented isolation strategy; either add a "
            "tenant_id (preferred) or register a strategy in "
            f"TENANT_AGNOSTIC_REGISTRY: {unclassified}"
        )

    def test_registry_keys_reference_real_tables(self):
        stale = [k for k in TENANT_AGNOSTIC_REGISTRY if k not in Base.metadata.tables]
        assert not stale, f"registry keys referencing non-existent tables (stale entries): {stale}"

    def test_registry_entries_have_documented_strategy(self):
        empty = [k for k, v in TENANT_AGNOSTIC_REGISTRY.items() if not v.strip()]
        assert not empty, f"registry entries missing a strategy note: {empty}"


# ══════════════════════════════════════════════════════════════════════════════
# Test 2 — Parametrized scoped sweep over EVERY tenant_id-bearing model
# ══════════════════════════════════════════════════════════════════════════════


class TestScopedSweep:
    @pytest.mark.parametrize(
        "model_cls", SCOPED_MODEL_CLASSES, ids=[c.__name__ for c in SCOPED_MODEL_CLASSES]
    )
    async def test_tenant_id_model_is_row_scoped(self, sweep_engine, model_cls):
        """A tenant-A-bound session must (i) select ONLY tenant A's row and
        (ii) get None for tenant B's row id (404 semantics)."""
        id_a, id_b = await _seed_pair(sweep_engine, model_cls)

        SessionLocal = async_sessionmaker(
            bind=sweep_engine, class_=AsyncSession, expire_on_commit=False
        )

        # Sanity: an unscoped session sees B's row (the seed really landed).
        async with SessionLocal() as unscoped:
            assert await unscoped.get(model_cls, id_b) is not None, (
                f"seed failed: {model_cls.__name__} row for tenant B missing"
            )
            tenant_a_id = (
                (await unscoped.execute(select(Tenant).where(Tenant.slug == "sweep-a")))
                .scalar_one()
                .id
            )

        async with SessionLocal() as scoped:
            apply_tenant_scope(scoped, tenant_a_id)

            rows = (await scoped.execute(select(model_cls))).scalars().all()
            tenants_seen = sorted({str(r.tenant_id) for r in rows})
            assert tenants_seen == [str(tenant_a_id)], (
                f"{model_cls.__name__}: scoped select returned rows of other "
                f"tenants: {tenants_seen}"
            )
            assert id_a in [r.id for r in rows], (
                f"{model_cls.__name__}: scoped select lost tenant A's own row"
            )

            foreign = await scoped.get(model_cls, id_b)
            assert foreign is None, (
                f"{model_cls.__name__}: scoped get() of another tenant's row id "
                "returned a row (no 404 semantics)"
            )


class TestScopeSwitching:
    async def test_scope_binds_per_request_not_per_process(self, sweep_engine):
        """DEFECT (found by this sweep, FIX-20260928-121317 follow-up): the
        ``with_loader_criteria`` lambda in ``tenant_scoping._scope_options_
        for_select`` binds the tenant id as a default-arg (``lambda cls,
        _tid=tenant_id``), which SQLAlchemy's lambda-SQL cache cannot
        invalidate.  The compiled criteria is cached per lambda code object
        and REPLAYED for every later scoped query, permanently bound to the
        FIRST tenant seen since process start.

        Observed pre-fix: after tenant A runs a scoped SELECT, a
        tenant-B-scoped session receives tenant A's rows — a catastrophic
        cross-tenant leak in any multi-tenant deployment where more than
        one tenant is served by the same process.

        Must hold: A → B → A scoped sessions each see ONLY their own rows.
        """
        SessionLocal = async_sessionmaker(
            bind=sweep_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            tenant_a = Tenant(name="Switch A", slug="switch-a")
            tenant_b = Tenant(name="Switch B", slug="switch-b")
            db.add_all([tenant_a, tenant_b])
            await db.flush()
            db.add_all(
                [
                    Role(name="switch-role-a", tenant_id=tenant_a.id),
                    Role(name="switch-role-b", tenant_id=tenant_b.id),
                ]
            )
            await db.commit()
            ids = {t.slug: t.id for t in (tenant_a, tenant_b)}

        async def _visible(slug: str) -> list[str]:
            async with SessionLocal() as session:
                apply_tenant_scope(session, ids[slug])
                rows = (await session.execute(select(Role))).scalars().all()
                return [r.name for r in rows]

        seen_a_first = await _visible("switch-a")
        assert seen_a_first == ["switch-role-a"], f"first scope-A query broken: {seen_a_first}"

        seen_b = await _visible("switch-b")
        assert seen_b == ["switch-role-b"], (
            "STALE SCOPE CRITERIA: a tenant-B-scoped session received tenant A's "
            f"rows {seen_b} — the with_loader_criteria lambda cache is bound to "
            "the first tenant seen by the process (default-arg binding is not "
            "invalidated by SQLAlchemy's lambda-SQL cache; use a closure factory)"
        )

        seen_a_again = await _visible("switch-a")
        assert seen_a_again == ["switch-role-a"], f"scope-A re-query broken: {seen_a_again}"


# ══════════════════════════════════════════════════════════════════════════════
# Test 3 — Tenant-agnostic strategy: PlatformUser ("membership-join")
# ══════════════════════════════════════════════════════════════════════════════

class TestTenantAgnosticStrategyPlatformUser:
    @pytest_asyncio.fixture
    async def users_seeded_engine(self, sweep_engine):
        """Engine seeded with: tenant A (one ACTIVE member, one SUSPENDED
        member) and tenant B (one ACTIVE member) — as PlatformUser rows."""
        SessionLocal = async_sessionmaker(
            bind=sweep_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            tenant_a = Tenant(name="A", slug="a")
            tenant_b = Tenant(name="B", slug="b")
            db.add_all([tenant_a, tenant_b])
            await db.flush()

            active_a, suspended_a, member_b = (
                PlatformUser(sub="sub-aa", email="aa@example.test", display_name="Active A"),
                PlatformUser(sub="sub-asa", email="asa@example.test", display_name="Suspended A"),
                PlatformUser(sub="sub-bb", email="bb@example.test", display_name="Member B"),
            )
            db.add_all([active_a, suspended_a, member_b])
            await db.flush()
            db.add_all(
                [
                    TenantUserMembership(
                        tenant_id=tenant_a.id, user_id=active_a.id, tenant_role="member"
                    ),
                    TenantUserMembership(
                        tenant_id=tenant_a.id,
                        user_id=suspended_a.id,
                        tenant_role="member",
                        status="suspended",
                    ),
                    TenantUserMembership(
                        tenant_id=tenant_b.id, user_id=member_b.id, tenant_role="member"
                    ),
                ]
            )
            await db.commit()
            return {
                "tenant_a_id": tenant_a.id,
                "active_a_id": active_a.id,
                "member_b_id": member_b.id,
            }

    async def test_scoped_user_query_returns_only_active_members_of_scoped_tenant(
        self, sweep_engine, users_seeded_engine
    ):
        """Registry strategy for platform_users is 'membership-join': a
        tenant-A scoped user query must return ONLY users with an ACTIVE
        membership in tenant A.  FAILS PRE-FIX — PlatformUser has no
        tenant_id, so the scoping choke point never filters it."""
        SessionLocal = async_sessionmaker(
            bind=sweep_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as scoped:
            apply_tenant_scope(scoped, users_seeded_engine["tenant_a_id"])

            rows = (await scoped.execute(select(PlatformUser))).scalars().all()
            ids = {r.id for r in rows}
            assert ids == {users_seeded_engine["active_a_id"]}, (
                "PlatformUser membership-join strategy violated in tenant context: "
                f"scoped user query returned {sorted(str(i) for i in ids)} — expected "
                "only the single ACTIVE member of the scoped tenant "
                f"({users_seeded_engine['active_a_id']})"
            )

            foreign = await scoped.get(PlatformUser, users_seeded_engine["member_b_id"])
            assert foreign is None, (
                "PlatformUser membership-join strategy violated in tenant context: "
                "scoped get() resolved another tenant's user (no 404 semantics)"
            )
