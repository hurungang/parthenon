# Module: api-keys — Tech Spec

## Overview

The API Key management module provides an alternative authentication mechanism for external agents connecting to the Communication Hub, alongside the existing mTLS certificate authentication. API keys are generated, SHA-256 hashed, and stored in Control Center's PostgreSQL database. Platform administrators manage keys through the frontend UI, while validation occurs at runtime when the Communication Hub receives an API key from an external agent and validates it against Control Center's internal API.

**Critical architectural constraints:**

- Only Control Center connects to the database — Communication Hub has no database access
- All CH→CC calls are mTLS-secured with service certificates
- Identity tokens are held exclusively by the Communication Hub — never reach external agents
- The existing certificate-based internal agent auth path is unchanged
- Key names are unique; any number of keys may exist per identity-role pair
- Keys may optionally carry an `expires_at` timestamp (NULL = never expires); expired keys are rejected at authentication

---

## Key Components

### Backend Components

#### AgentApiKey & ApiKeyUsageLog Models (Control Center)

| Component | Description |
|-----------|-------------|
| `AgentApiKey` | SQLAlchemy model storing the SHA-256 hash of each API key, a human-readable prefix, status (active/revoked), an optional `expires_at` timestamp, and audit timestamps. Bound to an agent identity and role via foreign keys. Key names are unique; any number of keys per identity-role pair. |
| `ApiKeyUsageLog` | Append-only audit log recording every API key operation (validation, skill load, tool call). Captures action type, tool name, client IP, timestamp, and success/failure. |

**File**: `backend/app/db/models/agent_api_key.py`

#### ApiKeyService (Control Center)

| Component | Description |
|-----------|-------------|
| `ApiKeyService` | Service layer for API key business logic: cryptographically random key generation with `phn_sk_` prefix, SHA-256 hashing, hash-based lookup, status management (activate/revoke), usage log creation, identity token decryption for bound identities. |
| `generate_api_key` | Generates a cryptographically random API key with `phn_sk_` prefix |
| `hash_api_key` | SHA-256 hashes a raw API key for storage and lookup |
| `validate_api_key_from_hash` | Looks up key by hash, checks status, returns key record or raises |
| `create_api_key_usage_log` | Creates an `ApiKeyUsageLog` entry for audit trail |
| `resolve_identity_token` | Decrypts and returns the identity token for a given agent identity |
| `resolve_allowed_tools` | Resolves all tool names accessible to a given agent role |
| `update_last_used_at` | Updates the `last_used_at` timestamp on an API key record |
| `is_key_expired` | Returns `True` when a key's `expires_at` is in the past (a `NULL` value never expires) |
| `check_duplicate_name` | Checks whether an API key with the given name already exists; raises 409 if so |

**File**: `backend/app/services/api_key_service.py`

#### API Key Validation Endpoint (Control Center Internal API)

| Component | Description |
|-----------|-------------|
| `validate_api_key_internal` | mTLS-protected internal POST endpoint at `/api/v1/internal/auth/validate-api-key`. Receives a hashed key from Communication Hub, validates it against the database, resolves the bound identity → identity token (decrypted) and role → permission set, logs usage, and returns token + permissions. Access restricted to Communication Hub via service certificate verification. |
| `InternalAuthRouter` | FastAPI APIRouter for internal auth endpoints, protected by `require_service_certificate` |

**File**: `backend/app/api/v1/internal/validate_api_key.py`

#### Permission Resolution — API Key Entry Point (Control Center)

| Component | Description |
|-----------|-------------|
| `resolve_permissions_from_api_key` | Extends the existing permission resolution engine to accept an API key as the root of the resolution chain: API Key → bound agent identity → bound agent role → policy evaluation → allowed tools/skills/SOPs. Returns identical permission set as an internal agent with the same role. |

**File**: `backend/app/services/permission_resolution.py`

#### API Key Admin CRUD Endpoints (Control Center)

| Component | Description |
|-----------|-------------|
| `AdminApiKeyRouter` | FastAPI APIRouter for JWT-protected admin-facing API key CRUD endpoints |
| `list_api_keys` | `GET /api/v1/api-keys` — List all API keys with optional `?status=active|revoked` filter |
| `create_api_key` | `POST /api/v1/api-keys` — Create a new API key bound to an agent identity and role; accepts optional `expires_at`; returns the clear-text key once |
| `revoke_api_key` | `POST /api/v1/api-keys/{key_id}/revoke` — Revoke an API key (idempotent) |
| `delete_api_key` | `DELETE /api/v1/api-keys/{key_id}` — Permanently delete an API key (usage logs cascade) |
| `list_identities_with_roles` | `GET /api/v1/api-keys/identities-with-roles` — List all agent identities with their available roles |

**File**: `backend/app/api/v1/api_keys.py`

#### API Key Schemas (Control Center)

| Component | Description |
|-----------|-------------|
| `ApiKeyCreate` | Pydantic schema for API key creation request (name, identity_id, role_id, optional expires_at) |
| `ApiKeyCreateResponse` | Pydantic schema for API key creation response (includes clear-text key shown once + expires_at) |
| `ApiKeyRead` | Pydantic schema for API key data with optional identity/role name fields |
| `ApiKeyListItem` | Pydantic schema for API key list items with denormalized identity/role names (metadata only, never includes secret) |
| `ApiKeyRevokeResponse` | Pydantic schema for revoke response (status confirmation) |
| `ApiKeyDeleteResponse` | Pydantic schema for delete response (status confirmation) |
| `ApiKeyValidateRequest` | Pydantic schema for internal validation request (hashed key) |
| `ApiKeyValidateResponse` | Pydantic schema for internal validation response (identity token + permissions) |
| `SkillWithVersion` | Pydantic schema extending skill with `updated_at` and tool definitions |
| `RoleItem` | Pydantic schema for a role item in identity-with-roles responses |
| `ToolDefinition` | Pydantic schema for a resolved tool definition with input/output schemas |

**File**: `backend/app/schemas/api_key.py`

### Frontend Components

#### ApiKeyListPage

| Component | Description |
|-----------|-------------|
| `ApiKeyListPage` | Main API key management page. Displays a filterable, searchable table of API keys with columns for name, bound identity, bound role, status chip, key hint, creation date, last used date, expiration, and action buttons (revoke + delete). Includes an informational banner, a collapsible "Connection help" guide (MCP endpoint + client config), empty state, loading state, and error state with retry. |

**File**: `frontend/src/pages/api-keys/ApiKeyListPage.tsx`

#### CreateApiKeyDialog

| Component | Description |
|-----------|-------------|
| `CreateApiKeyDialog` | Two-step modal dialog for creating a new API key. Step 1 collects key name, agent identity (dropdown), agent role (filtered dropdown), and an optional expiration date (checkbox + datetime, default no expiration). Step 2 displays the generated key (masked by default with reveal toggle), a copy button, summary information, and a collapsed MCP connection guide. Follows the project's Dialog Error Handling Standard. |

**File**: `frontend/src/pages/api-keys/CreateApiKeyDialog.tsx`

#### RevokeApiKeyDialog

| Component | Description |
|-----------|-------------|
| `RevokeApiKeyDialog` | Confirmation dialog for revoking an API key. Displays a warning that the action is irreversible and agents using the key will immediately lose access. On confirm, calls the revoke API and refreshes the key list. |

**File**: `frontend/src/pages/api-keys/RevokeApiKeyDialog.tsx`

#### DeleteApiKeyDialog

| Component | Description |
|-----------|-------------|
| `DeleteApiKeyDialog` | Confirmation dialog for permanently deleting an API key. Displays a warning that deletion removes the key and its usage history and cannot be undone. On confirm, calls the delete API and refreshes the key list. |

**File**: `frontend/src/pages/api-keys/DeleteApiKeyDialog.tsx`

#### McpConnectionGuide

| Component | Description |
|-----------|-------------|
| `McpConnectionGuide` | Collapsible guide showing the MCP endpoint URL, auth header (`Authorization: Bearer` / `?apiKey=`), and copyable Copilot/Claude client configs (`http` and `sse`). Collapsed by default (shows only the endpoint URL); expands to show the full instructions. |

**File**: `frontend/src/pages/api-keys/RevokeApiKeyDialog.tsx`

#### API Key Types & Client

| Component | Description |
|-----------|-------------|
| `ApiKey` | TypeScript interface for API key list item (includes `expires_at`) |
| `ApiKeyCreateRequest` | TypeScript interface for API key creation form data (includes optional `expires_at`) |
| `ApiKeyCreateResponse` | TypeScript interface for API key creation response (includes one-time key + `expires_at`) |
| `ApiKeyStatus` | TypeScript enum: `active` / `revoked` |
| `ApiKeyDeleteResponse` | TypeScript interface for delete response |
| `IdentityWithRoles` | TypeScript interface for identity with available roles (dropdown data) |

**File**: `frontend/src/types/apiKeys.ts`

| Component | Description |
|-----------|-------------|
| `fetchApiKeys` | HTTP GET `/api/v1/api-keys` — fetches key list with optional status filter |
| `createApiKey` | HTTP POST `/api/v1/api-keys` — creates a new API key (optional `expires_at`) |
| `revokeApiKey` | HTTP POST `/api/v1/api-keys/{key_id}/revoke` — revokes an API key |
| `deleteApiKey` | HTTP DELETE `/api/v1/api-keys/{key_id}` — permanently deletes an API key |
| `fetchIdentitiesWithRoles` | HTTP GET `/api/v1/api-keys/identities-with-roles` — dropdown data for create dialog |

**File**: `frontend/src/api/apiKeysApi.ts`

#### useApiKeys Hook

| Component | Description |
|-----------|-------------|
| `useApiKeys` | React hook: fetches API key list with loading/error state, exposes `refresh()` for reloading after create/revoke/delete operations |

**File**: `frontend/src/hooks/useApiKeys.ts`

---

## API Endpoints

### Control Center Internal API (mTLS-protected)

| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/api/v1/internal/auth/validate-api-key` | Validate a hashed API key. Returns resolved agent identity, role, identity token, and full permission set. Rejects invalid/revoked keys with 401. Updates `last_used_at` on key and logs `ApiKeyUsageLog` entry. |
| `POST` | `/api/v1/internal/system-tools/skills/resolve` | Resolve all skills accessible to a given agent role. Includes full tool definitions with input/output schemas and `updated_at` timestamps. Supports optional `since` parameter for incremental sync. |

### Control Center Admin API (JWT-protected)

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/api/v1/api-keys` | List all API keys. Optional query param `?status=active\|revoked` for filtering. Returns key metadata (including `expires_at`) only — never the key value. |
| `POST` | `/api/v1/api-keys` | Create a new API key bound to an agent identity and role, with an optional `expires_at`. Returns the clear-text key once in the response. Enforces unique key names. |
| `POST` | `/api/v1/api-keys/{key_id}/revoke` | Revoke an API key. Idempotent — revoking an already-revoked key succeeds. |
| `DELETE` | `/api/v1/api-keys/{key_id}` | Permanently delete an API key (usage logs cascade). |
| `GET` | `/api/v1/api-keys/identities-with-roles` | List all agent identities with their available roles and role names. Used to populate create-key dialog dropdowns. |

---

## Data Access Patterns

### Client-Side (Frontend→CC)

- **Reads**: All API key data is fetched from Control Center REST endpoints. The frontend never accesses the database directly.
- **Writes**: Create and revoke operations go through Control Center REST endpoints. The clear-text key is only ever in the POST response — never persisted in frontend state after the dialog is closed.
- **Why server-side**: API keys contain secrets. The frontend only sees the clear-text key at creation time. All filtering and searching happen server-side through the `GET /api/v1/api-keys` endpoint.

### Server-Side (CH→CC)

- **API Key Validation**: Communication Hub calls Control Center's internal validation endpoint. The hashed key is sent over mTLS — the raw key is never transmitted between services. CC decrypts the identity token from encrypted database storage and returns it to CH for the request lifetime.
- **Skill Resolution**: CH calls CC to resolve skills for a role. Results are used to populate the `load_skills` MCP response. No caching beyond the request lifetime.

### Database Access

- **Only Control Center** can connect to the PostgreSQL database.
- Communication Hub has zero database access — all data retrieval goes through CC internal APIs.
- External agents (the end users of this feature) have zero database access and never receive database credentials.

---

## Code Reference Map

### Database Models

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentApiKey` | model | SQLAlchemy model for API keys (hashed storage, identity/role binding, status) | `backend/app/db/models/agent_api_key.py` |
| `ApiKeyUsageLog` | model | SQLAlchemy model for immutable API key usage audit records | `backend/app/db/models/agent_api_key.py` |
| `AgentIdentity` | model (existing) | Existing model referenced by API key via `agent_identity_id` FK | `backend/app/db/models/agents.py` |
| `AgentRole` | model (existing) | Existing model referenced by API key via `agent_role_id` FK | `backend/app/db/models/agents.py` |
| `Skill` | model (existing) | Updated: `updated_at` column promoted to version-tracking field exposed via MCP | `backend/app/db/models/skills.py` |

### API Key Service

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ApiKeyService` | class | Service layer for key generation, hashing, validation, and lifecycle management | `backend/app/services/api_key_service.py` |
| `generate_api_key` | function | Generates a cryptographically random API key with `phn_sk_` prefix | `backend/app/services/api_key_service.py` |
| `hash_api_key` | function | SHA-256 hashes a raw API key for storage and lookup | `backend/app/services/api_key_service.py` |
| `validate_api_key_from_hash` | function | Looks up key by hash, checks status, returns key record or raises | `backend/app/services/api_key_service.py` |
| `create_api_key_usage_log` | function | Creates an `ApiKeyUsageLog` entry for audit trail | `backend/app/services/api_key_service.py` |
| `resolve_identity_token` | function (async) | Decrypts and returns the identity token for a given agent identity | `backend/app/services/api_key_service.py` |
| `resolve_allowed_tools` | function (async) | Resolves all tool names accessible to a given agent role | `backend/app/services/api_key_service.py` |
| `update_last_used_at` | function (async) | Updates the `last_used_at` timestamp on an API key record | `backend/app/services/api_key_service.py` |
| `is_key_expired` | function | Returns `True` when a key's `expires_at` is in the past (NULL = never expires) | `backend/app/services/api_key_service.py` |
| `check_duplicate_name` | function (async) | Checks whether an API key with the given name already exists; raises 409 if so | `backend/app/services/api_key_service.py` |

### Permission Resolution

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `PermissionResolutionService` | class (existing) | Existing service extended with API-key-based resolution entry point | `backend/app/services/permission_resolution.py` |
| `resolve_permissions_from_api_key` | function (async) | Resolves agent permissions starting from an API key (key → identity → role → permissions) | `backend/app/services/permission_resolution.py` |

### Internal Endpoints

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `validate_api_key_internal` | endpoint | Internal POST endpoint: validates hashed key, returns identity token + permissions | `backend/app/api/v1/internal/validate_api_key.py` |
| `InternalAuthRouter` | router | FastAPI APIRouter for internal auth endpoints, protected by `require_service_certificate` | `backend/app/api/v1/internal/validate_api_key.py` |
| `resolve_skills_internal` | endpoint | Internal POST endpoint: resolves skills for a role with optional `since` filter | `backend/app/api/v1/internal/system_tools.py` |

### Admin API Endpoints

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AdminApiKeyRouter` | router | FastAPI APIRouter for admin-facing API key CRUD endpoints | `backend/app/api/v1/api_keys.py` |
| `list_api_keys` | endpoint | `GET /api/v1/api-keys` — list keys with optional status filter | `backend/app/api/v1/api_keys.py` |
| `create_api_key` | endpoint | `POST /api/v1/api-keys` — create key, return clear-text once | `backend/app/api/v1/api_keys.py` |
| `revoke_api_key` | endpoint | `POST /api/v1/api-keys/{key_id}/revoke` — set key status to revoked | `backend/app/api/v1/api_keys.py` |
| `delete_api_key` | endpoint | `DELETE /api/v1/api-keys/{key_id}` — permanently delete an API key | `backend/app/api/v1/api_keys.py` |
| `list_identities_with_roles` | endpoint | `GET /api/v1/api-keys/identities-with-roles` — identities and their available roles | `backend/app/api/v1/api_keys.py` |

### Schemas

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ApiKeyCreate` | schema | Pydantic schema for API key creation request (name, identity_id, role_id) | `backend/app/schemas/api_key.py` |
| `ApiKeyCreateResponse` | schema | Pydantic schema for API key creation response (includes clear-text key shown once) | `backend/app/schemas/api_key.py` |
| `ApiKeyRead` | schema | Pydantic schema for API key data with optional identity/role name fields | `backend/app/schemas/api_key.py` |
| `ApiKeyListItem` | schema | Pydantic schema for API key list items with denormalized identity/role names (metadata only, never includes secret) | `backend/app/schemas/api_key.py` |
| `ApiKeyRevokeResponse` | schema | Pydantic schema for revoke response (status confirmation) | `backend/app/schemas/api_key.py` |
| `ApiKeyDeleteResponse` | schema | Pydantic schema for delete response (status confirmation) | `backend/app/schemas/api_key.py` |
| `RoleItem` | schema | Pydantic schema for a role item in identity-with-roles responses | `backend/app/schemas/api_key.py` |
| `ToolDefinition` | schema | Pydantic schema for a resolved tool definition with input/output schemas | `backend/app/schemas/api_key.py` |
| `ApiKeyValidateRequest` | schema | Pydantic schema for internal validation request (hashed key) | `backend/app/schemas/api_key.py` |
| `ApiKeyValidateResponse` | schema | Pydantic schema for internal validation response (identity token + permissions) | `backend/app/schemas/api_key.py` |
| `SkillWithVersion` | schema | Pydantic schema extending skill with `updated_at` and tool definitions | `backend/app/schemas/api_key.py` |

### Dependencies

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `require_service_certificate` | dependency | FastAPI dependency: ensures request comes from a valid service certificate (used on all internal endpoints) | `backend/app/api/deps.py` |
| `require_permission` | dependency | FastAPI dependency: ensures JWT-authenticated user has required permission (used on admin endpoints) | `backend/app/api/deps.py` |

### Frontend Components

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ApiKeyListPage` | component | Main API key management page with table, filtering, search, empty/loading/error states | `frontend/src/pages/api-keys/ApiKeyListPage.tsx` |
| `CreateApiKeyDialog` | component | Two-step modal: form (identity+role+optional expiration) → key reveal with copy | `frontend/src/pages/api-keys/CreateApiKeyDialog.tsx` |
| `RevokeApiKeyDialog` | component | Confirmation modal for irreversible key revocation | `frontend/src/pages/api-keys/RevokeApiKeyDialog.tsx` |
| `DeleteApiKeyDialog` | component | Confirmation modal for permanent key deletion | `frontend/src/pages/api-keys/DeleteApiKeyDialog.tsx` |
| `McpConnectionGuide` | component | Collapsible MCP endpoint + client config guide | `frontend/src/pages/api-keys/McpConnectionGuide.tsx` |

### Frontend Data Layer

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `useApiKeys` | hook | React hook: fetches API key list with loading/error state, exposes `refresh()` | `frontend/src/hooks/useApiKeys.ts` |
| `useDeleteApiKey` | hook | React mutation hook for permanently deleting an API key | `frontend/src/hooks/useApiKeys.ts` |
| `fetchApiKeys` | function | HTTP GET `/api/v1/api-keys` — fetches key list with optional status filter | `frontend/src/api/apiKeysApi.ts` |
| `createApiKey` | function | HTTP POST `/api/v1/api-keys` — creates a new API key | `frontend/src/api/apiKeysApi.ts` |
| `revokeApiKey` | function | HTTP POST `/api/v1/api-keys/{key_id}/revoke` — revokes an API key | `frontend/src/api/apiKeysApi.ts` |
| `deleteApiKey` | function | HTTP DELETE `/api/v1/api-keys/{key_id}` — permanently deletes an API key | `frontend/src/api/apiKeysApi.ts` |
| `fetchIdentitiesWithRoles` | function | HTTP GET `/api/v1/api-keys/identities-with-roles` — dropdown data for create dialog | `frontend/src/api/apiKeysApi.ts` |
| `ApiKey` | interface | TypeScript type for API key list item | `frontend/src/types/apiKeys.ts` |
| `ApiKeyCreateRequest` | interface | TypeScript type for API key creation form data | `frontend/src/types/apiKeys.ts` |
| `ApiKeyCreateResponse` | interface | TypeScript type for API key creation response (includes one-time key) | `frontend/src/types/apiKeys.ts` |
| `ApiKeyStatus` | enum | TypeScript enum: `active` / `revoked` | `frontend/src/types/apiKeys.ts` |
| `IdentityWithRoles` | interface | TypeScript type for identity with available roles (dropdown data) | `frontend/src/types/apiKeys.ts` |
