# Module: identity — Tech Spec

## Overview
The identity module covers five interconnected concerns: the platform's internal RBAC layer, the namespaced resource type system, the identity provider bootstrap subsystem, the OIDC integration refinement (DB-backed provider configs and multi-tier auth pipeline), and the User Permission Management system.

**RBAC layer**: REST endpoints for creating, reading, updating, and deleting Roles, Permissions, and Identity records, plus a public setup endpoint for seeding the first administrator on initial deployment. Roles carry permission sets that control what actions a human user, AI agent, or service account may perform.

**Identity provider bootstrap**: Detection and provisioning of the OIDC identity provider (bundled Keycloak, external Keycloak, or Azure EntraID). The backend service orchestrates Keycloak realm/client creation and persists resolved OIDC settings to the database. Once provisioning completes, the OIDC client reloads live and normal auth flow resumes with no process restart. Pre-auth provider configuration via the frontend setup wizard has been REMOVED (obsolete with multi-tenancy — OIDC is configured post-sign-in via System Config / Tenant Settings; the backend `/setup/*` endpoints and the `setup/` CLI tool remain).

**OIDC integration refinement**: Moves OIDC identity provider configuration from a static YAML file into a database-backed system with a web UI (System Config). The Control Center gains a three-tier authentication pipeline (super admin credentials, OIDC per-provider JWT validation, public fallback), an OIDC Provider Registry that hot-reloads configs and caches JWKS per provider, and a multi-provider OIDC client that validates tokens against independent user and agent identity providers. A built-in super admin account bootstrapped from environment variables provides guaranteed access for disaster recovery. The frontend adds Identity Provider Config forms, super admin management, and OIDC connectivity/login test modals. The login page dynamically adapts to show/hide the super admin credential form based on discovered provider state. A one-time migration service reads existing `config/identity.yaml` into the database on upgrade.

**Namespaced resource type system**: The platform's resource type identifiers were upgraded from 15 flat strings (e.g. `agent`, `role`, `conversation`) to two-layer namespace identifiers (`agent::management`, `agent::roles`, `agent::trails`) using `::` as the delimiter, organised into module groups (`agent`, `integration`, `system`, plus the later `platform` and `tenant` groups) mirroring the sidebar navigation. The `ResourceTypeManifest` in `backend/app/core/resource_types.py` serves as the single source of truth with exported `RT_*` Final constants, `MODULE_GROUPS` dict, and helper functions (`get_module_from_resource_type`, `is_valid_wildcard`). The `PermissionEngine`'s module matching was extended to handle three wildcard levels (`*::*`, `module::*`, exact match). All 198+ `require_permission()` call sites across 20 router files use the new namespaced constants. The frontend mirrors the manifest in `frontend/src/constants/resourceTypes.ts` with `RESOURCE_TYPE_MANIFEST`, `MODULE_GROUPS`, and lookup helpers. Policy editing moved from an inline-expand pattern to a dedicated `RolePolicyDialog` with Form/JSON editing modes (including a JSON source code editor with syntax validation), FreeSolo autocomplete selectors for resource type and action wildcard input, and a batch save endpoint (`PUT /user-roles/{role_id}/policies/batch`) that replaces all role policies atomically in a single transaction. A one-time Alembic data migration transforms legacy flat values to namespaced equivalents.

**User Permission Management**: An IAM-style policy-based access control layer for human users, distinct from the existing flat agent RBAC model. Provides a User Permission Engine for policy evaluation with tag-based conditions, a Tag Registry, a User Cache for OIDC-authenticated principals, a Group Claim Mapper for automatic group assignment via JWT claims, a User Access Request Service for self-service group join workflows, and a User Notification Hook for owner/requester alerts. Exposed through five API router groups (`/user-tags`, `/user-roles`, `/user-groups`, `/platform-users`, `/user-access-requests`) and a five-page admin UI module at `/user-permissions`.

> **Namespace note**: The platform has two distinct permission systems — the existing agent permission system (controls AI agent access) and the user permission system (controls human user access). All user permission API routes use the `/user-*` prefix; frontend routes use `/user-permissions` as the base path.

---

## Spec Pages

| Page | Covers |
|---|---|
| **[RBAC, permissions & resource types](rbac-and-permissions.md)** | Roles, permissions, tags, user groups, platform users, access requests, the Permission Engine and the namespaced `module::submodule` resource-type system |
| **[Identity providers & OIDC](identity-provider-oidc.md)** | Identity bootstrap (bundled Keycloak, external Keycloak, Azure EntraID), the database-backed OIDC provider registry, the three-tier auth pipeline, super admin, and the setup endpoints |

Larger changes belong on the page that owns the affected area. Keep this hub for cross-cutting material only: infrastructure components and tenant-isolation invariants.

---

## Components — Infrastructure

| Component | Description |
|-----------|-------------|
| `keycloak` (Docker Compose service) | Official `quay.io/keycloak/keycloak` image with health-check on `/health/ready`; backend `depends_on` this service being healthy; mounts `infra/keycloak/realm-import/` for dev-time realm pre-import |
| `parthenon-realm.json` | Minimal Keycloak realm definition for dev-time import; includes the `parthenon-api-ui` OIDC client |

---

## Strict Tenant Isolation
Identity provider configuration is strictly per-tenant — the tenant-less "shared slot" as a fallback-wide is retired in favour of exact tenant matching:

- `OIDCProviderRegistry` resolution remains own `(tenant, scope)` → shared `(None, scope)` → root tenant slot, but none of the slots widens across tenants: token validation for a tenant-bound login context only accepts providers resolvable for that exact tenant.
- `get_default_provider` resolves the default provider within the bound tenant (root tenant when multi-tenancy is off) — never a platform-global default.
- `OIDCConfigService` enforces per-tenant scope uniqueness on `identity_provider_configs` (migration `c9d0e1f2a3b4`).
- Signed tenant headers (`X-Internal-Tenant-*`) carry the resolved identity context on all internal hops; see the [multi-tenancy spec](../multi-tenancy/tech-spec.md).

---

### Strict Tenant Isolation — Code Reference Map
| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `OIDCProviderRegistry` | class | Strict per-tenant provider cache: own → shared → root resolution, no tenant widening | `backend/app/services/oidc_provider_registry.py` |
| `OIDCProviderRegistry.get_default_provider` | method | Default provider resolution within the bound tenant (root tenant when tenancy off) | `backend/app/services/oidc_provider_registry.py` |
| `OIDCConfigService` | class | Per-tenant provider CRUD with strict per-tenant scope uniqueness | `backend/app/services/oidc_config_service.py` |
| `_multi_tenancy_on` / `_root_tenant_id` | functions | Tenancy-switch and root-tenant helpers for config scoping | `backend/app/services/oidc_config_service.py` |
| Per-tenant IdP scope uniqueness | migration | Unique tenant scope on `identity_provider_configs` | `backend/alembic/versions/c9d0e1f2a3b4_unique_tenant_scope_on_identity_provider_configs.py` |

---

## Code Reference Map — cross-cutting

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `keycloak` service | Docker Compose | Keycloak container definition with health check and realm-import volume | `docker-compose.yml` |
| `parthenon-realm.json` | Keycloak config | Dev-time realm definition with `parthenon-api-ui` OIDC client | `infra/keycloak/realm-import/parthenon-realm.json` |
