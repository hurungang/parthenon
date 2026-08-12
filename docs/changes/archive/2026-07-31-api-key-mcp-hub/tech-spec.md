# Technical Specification: API Key MCP Hub

## Technical Overview

The Communication Hub is extended to accept API key authentication alongside its existing mTLS certificate authentication. API keys are generated, hashed (SHA-256), and stored in Control Center's PostgreSQL database. When an external agent presents an API key (via `Authorization: Bearer` header or `?apiKey=` query parameter), the Communication Hub hashes the key and calls a new internal mTLS-protected endpoint on Control Center for validation. Control Center resolves the key to its bound agent identity and role, decrypts the identity token from encrypted storage, resolves the full permission set, and returns all of this to the Communication Hub — which holds the token internally and injects it into proxied MCP tool calls without ever exposing it to the external agent.

A new `load_skills` system tool is exposed on the Communication Hub's MCP endpoint, allowing external agents to discover all skills (including SOPs) they are permitted to access. Skills now carry an `updated_at` timestamp exposed in the response, and a `since` parameter enables incremental sync.

The frontend gains an API Key management page under the Integrations section where platform administrators can create keys (bound to agent identity + role), view the key list with status filtering, and revoke keys. All frontend-to-backend communication uses existing JWT-authenticated REST endpoints.

**Critical architectural constraints enforced**:

- Only Control Center connects to the database — Communication Hub has no database access
- All CH→CC calls are mTLS-secured with service certificates
- Identity tokens are held exclusively by the Communication Hub — never reach external agents
- The existing certificate-based internal agent auth path is unchanged

## Component Breakdown

### Backend Components

#### AgentApiKey Model (Control Center)
**Responsibility**: Database entity representing an API key bound to an agent identity and role. Stores the SHA-256 hash of the key, a human-readable prefix, status (active/revoked), and audit timestamps. Enforces one active key per identity-role pair via unique constraint.

**File**: `backend/app/db/models/agent_api_key.py`

#### ApiKeyUsageLog Model (Control Center)
**Responsibility**: Append-only audit log recording every API key operation (validation, skill load, tool call). Captures action type, tool name, client IP, timestamp, and success/failure. Supports security monitoring and usage analytics.

**File**: `backend/app/db/models/agent_api_key.py`

#### ApiKeyService (Control Center)
**Responsibility**: Service layer for API key business logic: cryptographically random key generation with `phn_sk_` prefix, SHA-256 hashing, hash-based lookup, status management (activate/revoke), usage log creation, identity token decryption for bound identities.

**File**: `backend/app/services/api_key_service.py`

#### API Key Validation Endpoint (Control Center Internal API)
**Responsibility**: mTLS-protected internal endpoint. Receives a hashed key from the Communication Hub, validates it against the database, resolves the bound identity → identity token (decrypted) and role → permission set, logs the usage, and returns the token + permissions. Access is restricted to Communication Hub via service certificate verification.

**File**: `backend/app/api/v1/internal/validate_api_key.py`

#### Permission Resolution — API Key Entry Point (Control Center)
**Responsibility**: Extends the existing permission resolution engine to accept an API key as the root of the resolution chain. The chain is: API Key → bound agent identity → bound agent role → policy evaluation → allowed tools/skills/SOPs. Returns the identical permission set as an internal agent with the same role.

**File**: `backend/app/services/permission_resolution.py` (extended)

#### Skill Resolution Endpoint (Control Center Internal API)
**Responsibility**: Internal endpoint that resolves all skills accessible to a given agent role, including full tool definitions with input/output schemas and `updated_at` timestamps. Supports optional `since` parameter for incremental sync — only skills with `updated_at > since` are returned.

**File**: `backend/app/api/v1/internal/system_tools.py` (extended)

#### API Key Admin CRUD Endpoints (Control Center)
**Responsibility**: JWT-protected REST endpoints for platform administrators to list, create, and revoke API keys. Also provides endpoint to list agent identities with their available roles for dropdown population. Enforces business rules: unique active key per identity-role pair, key shown only once at creation.

**File**: `backend/app/api/v1/api_keys.py`

#### API Key Schemas (Control Center)
**Responsibility**: Pydantic v2 request/response models for API key CRUD operations and internal validation. Strongly typed with validation rules (name length limits, required fields, UUID format).

**File**: `backend/app/schemas/api_key.py`

#### API Key Auth Middleware (Communication Hub)
**Responsibility**: Middleware on the Communication Hub that detects API key authentication on incoming MCP requests. Checks `Authorization: Bearer` header first, then `?apiKey=` query parameter. Hashes the extracted key, calls Control Center's internal validation endpoint, stores the returned identity token and permission set on the request context, and rejects invalid/revoked keys with 401. Coexists with existing mTLS certificate auth — detects which method is in use and routes accordingly.

**File**: `backend/app/communication_hub/middleware/api_key_auth.py`

#### load_skills System Tool (Communication Hub)
**Responsibility**: MCP system tool registered on the Communication Hub that external agents invoke to discover accessible skills. Accepts optional `since` parameter for incremental sync. Calls Control Center's internal skill resolution endpoint, formats results as MCP-compliant tool definitions, and returns them with `updated_at` timestamps.

**File**: `backend/app/communication_hub/api/mcp_tools.py`

### Frontend Components

#### ApiKeyListPage (Frontend)
**Responsibility**: Main page for API key management. Displays a filterable, searchable table of API keys with columns for name, bound identity, bound role, status chip, key hint, creation date, last used date, and action buttons. Includes an informational change banner, empty state, loading state, and error state with retry.

**File**: `frontend/src/pages/api-keys/ApiKeyListPage.tsx`

#### CreateApiKeyDialog (Frontend)
**Responsibility**: Two-step modal dialog for creating a new API key. Step 1 collects key name, agent identity (dropdown), and agent role (filtered dropdown). Step 2 displays the generated key (masked by default with reveal toggle), a copy button, and summary information. Follows the project's Dialog Error Handling Standard.

**File**: `frontend/src/pages/api-keys/CreateApiKeyDialog.tsx`

#### RevokeApiKeyDialog (Frontend)
**Responsibility**: Confirmation dialog for revoking an API key. Displays a warning that the action is irreversible and agents using the key will immediately lose access. On confirm, calls the revoke API and refreshes the key list.

**File**: `frontend/src/pages/api-keys/RevokeApiKeyDialog.tsx`

#### API Key Types (Frontend)
**Responsibility**: TypeScript interfaces and enums for API key data structures, matching the Pydantic schemas on the backend. Strongly typed — no `any`.

**File**: `frontend/src/types/apiKeys.ts`

#### API Key Client (Frontend)
**Responsibility**: HTTP client functions for API key CRUD operations. Uses the existing `apiClient` for authenticated requests. Handles error responses per project conventions.

**File**: `frontend/src/api/apiKeysApi.ts`

#### useApiKeys Hook (Frontend)
**Responsibility**: React hook that encapsulates API key data fetching, loading state, error handling, and a refresh function. Used by the list page to reload data after create/revoke operations.

**File**: `frontend/src/hooks/useApiKeys.ts`

## API Changes

### New Control Center Internal API Endpoints (mTLS-protected)

| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/api/v1/internal/auth/validate-api-key` | Validate a hashed API key. Returns resolved agent identity, role, identity token, and full permission set. Rejects invalid/revoked keys with 401. Updates `last_used_at` on key and logs `ApiKeyUsageLog` entry. |
| `POST` | `/api/v1/internal/system-tools/skills/resolve` | Resolve all skills accessible to a given agent role. Includes full tool definitions with input/output schemas and `updated_at` timestamps. Supports optional `since` parameter for incremental sync. |

### New Control Center Admin API Endpoints (JWT-protected)

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/api/v1/api-keys` | List all API keys. Optional query param `?status=active\|revoked` for filtering. Returns key metadata only — never the key value. |
| `POST` | `/api/v1/api-keys` | Create a new API key bound to an agent identity and role. Returns the clear-text key once in the response. Enforces one active key per identity-role pair. |
| `POST` | `/api/v1/api-keys/{key_id}/revoke` | Revoke an API key. Idempotent — revoking an already-revoked key succeeds. |
| `GET` | `/api/v1/api-keys/identities-with-roles` | List all agent identities with their available roles and role names. Used to populate the create-key dialog dropdowns. |

### New Communication Hub MCP System Tool

| Tool Name | Description |
|-----------|-------------|
| `load_skills` | Discover all skills (including SOPs) accessible to the authenticated agent. Returns full tool definitions with input/output schemas and `updated_at` timestamps. Accepts optional `since` parameter (ISO 8601 timestamp) for incremental sync — only skills updated after the given timestamp are returned. |

### Modified/Extended Endpoints

| Method | Route | Change |
|--------|-------|--------|
| N/A | Internal skill/permission resolution | Extended to support resolution from an API key as the root of the chain (same underlying logic, new entry point). Skill responses now include `updated_at` timestamp. |

### Public Paths (No Auth Required)

No endpoints are made public by this change. All new endpoints require either service certificate (internal) or JWT (admin).

## State Management

### Frontend State

The API Key management page uses local component state with a custom React hook (`useApiKeys`):

- **`useApiKeys` hook** — Manages the API key list with states: `keys` (ApiKey[]), `loading` (boolean), `error` (Error | null). Exposes `refresh()` to reload after mutations. Used by `ApiKeyListPage`.
- **Filter state** — Local `useState` in `ApiKeyListPage`: `statusFilter` (string: 'all' | 'active' | 'revoked'), `searchTerm` (string). Filtering is client-side on the loaded key list.
- **Dialog state** — Local `useState` in each dialog: `open` (boolean), `dialogError` (unknown | null) per the Dialog Error Handling Standard, form field values, form validation errors.
- **No global store needed** — The API key list is isolated to its own page and does not need cross-component sharing. No changes to `AuthContext`, `authStore`, or other global stores.

### Backend State

No new server-side state beyond what the database models provide. API key validation responses are cached per-request on the Communication Hub (lifetime of the HTTP request only) — no persistent or cross-request caching.

## Data Access Patterns

### Client-Side (Frontend→CC)

- **Reads**: All API key data is fetched from Control Center REST endpoints. The frontend never accesses the database directly.
- **Writes**: Create and revoke operations go through Control Center REST endpoints. The clear-text key is only ever in the POST response — never persisted in frontend state after the dialog is closed.
- **Why server-side**: API keys contain secrets. The frontend only ever sees the clear-text key at creation time. All filtering and searching happen server-side through the `GET /api/v1/api-keys` endpoint.

### Server-Side (CH→CC)

- **API Key Validation**: Communication Hub calls Control Center's internal validation endpoint. The hashed key is sent over mTLS — the raw key is never transmitted between services. CC decrypts the identity token from encrypted database storage and returns it to CH for the request lifetime.
- **Skill Resolution**: CH calls CC to resolve skills for a role. Results are used to populate the `load_skills` MCP response. No caching beyond the request lifetime.
- **Why server-side**: Identity tokens are encrypted at rest in CC's database. Only CC has the decryption keys. CH holds the decrypted token in memory only for the duration of the authenticated request — it is never persisted or exposed.

### Database Access

- **Only Control Center** can connect to the PostgreSQL database.
- Communication Hub has zero database access — all data retrieval goes through CC internal APIs.
- External agents (the end users of this feature) have zero database access and never receive database credentials.

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentApiKey` | class (model) | SQLAlchemy model for API keys (hashed storage, identity/role binding, status) | `backend/app/db/models/agent_api_key.py` |
| `ApiKeyUsageLog` | class (model) | SQLAlchemy model for immutable API key usage audit records | `backend/app/db/models/agent_api_key.py` |
| `ApiKeyService` | class (service) | Service layer for key generation, hashing, validation, and lifecycle management | `backend/app/services/api_key_service.py` |
| `generate_api_key` | function | Generates a cryptographically random API key with `phn_sk_` prefix | `backend/app/services/api_key_service.py` |
| `hash_api_key` | function | SHA-256 hashes a raw API key for storage and lookup | `backend/app/services/api_key_service.py` |
| `validate_api_key_from_hash` | function | Looks up key by hash, checks status, returns key record or raises | `backend/app/services/api_key_service.py` |
| `create_api_key_usage_log` | function | Creates an `ApiKeyUsageLog` entry for audit trail | `backend/app/services/api_key_service.py` |
| `resolve_identity_token` | function (async) | Decrypts and returns the identity token for a given agent identity | `backend/app/services/api_key_service.py` |
| `resolve_allowed_tools` | function (async) | Resolves all tool names accessible to a given agent role | `backend/app/services/api_key_service.py` |
| `update_last_used_at` | function (async) | Updates the `last_used_at` timestamp on an API key record | `backend/app/services/api_key_service.py` |
| `check_duplicate_active_key` | function (async) | Checks whether an active key already exists for an identity-role pair; raises 409 if so | `backend/app/services/api_key_service.py` |
| `resolve_permissions_from_api_key` | function (async) | Resolves agent permissions starting from an API key (key → identity → role → permissions) | `backend/app/services/permission_resolution.py` |
| `validate_api_key_internal` | function (endpoint) | Internal POST endpoint: validates hashed key, returns identity token + permissions | `backend/app/api/v1/internal/validate_api_key.py` |
| `resolve_skills_internal` | function (endpoint) | Internal POST endpoint: resolves skills for a role with optional `since` filter | `backend/app/api/v1/internal/system_tools.py` |
| `InternalAuthRouter` | class (router) | FastAPI APIRouter for internal auth endpoints, protected by `require_service_certificate` | `backend/app/api/v1/internal/validate_api_key.py` |
| `list_api_keys` | function (endpoint) | GET `/api/v1/api-keys` — list keys with optional status filter | `backend/app/api/v1/api_keys.py` |
| `create_api_key` | function (endpoint) | POST `/api/v1/api-keys` — create key, return clear-text once | `backend/app/api/v1/api_keys.py` |
| `revoke_api_key` | function (endpoint) | POST `/api/v1/api-keys/{key_id}/revoke` — set key status to revoked | `backend/app/api/v1/api_keys.py` |
| `list_identities_with_roles` | function (endpoint) | GET `/api/v1/api-keys/identities-with-roles` — identities and their available roles | `backend/app/api/v1/api_keys.py` |
| `AdminApiKeyRouter` | class (router) | FastAPI APIRouter for admin-facing API key CRUD endpoints | `backend/app/api/v1/api_keys.py` |
| `ApiKeyCreate` | class (schema) | Pydantic schema for API key creation request (name, identity_id, role_id) | `backend/app/schemas/api_key.py` |
| `ApiKeyCreateResponse` | class (schema) | Pydantic schema for API key creation response (includes clear-text key shown once) | `backend/app/schemas/api_key.py` |
| `ApiKeyRead` | class (schema) | Pydantic schema for API key data with optional identity/role name fields | `backend/app/schemas/api_key.py` |
| `ApiKeyListItem` | class (schema) | Pydantic schema for API key list items with denormalized identity/role names (metadata only, never includes secret) | `backend/app/schemas/api_key.py` |
| `ApiKeyRevokeResponse` | class (schema) | Pydantic schema for revoke response (status confirmation) | `backend/app/schemas/api_key.py` |
| `RoleItem` | class (schema) | Pydantic schema for a role item in identity-with-roles responses | `backend/app/schemas/api_key.py` |
| `ToolDefinition` | class (schema) | Pydantic schema for a resolved tool definition with input/output schemas | `backend/app/schemas/api_key.py` |
| `ApiKeyValidateRequest` | class (schema) | Pydantic schema for internal validation request (hashed key + optional `since`) | `backend/app/schemas/api_key.py` |
| `ApiKeyValidateResponse` | class (schema) | Pydantic schema for internal validation response (identity token + permissions) | `backend/app/schemas/api_key.py` |
| `SkillWithVersion` | class (schema) | Pydantic schema extending skill with `updated_at` and tool definitions | `backend/app/schemas/api_key.py` |
| `Skill` | class (model) | Updated: `updated_at` column promoted to version-tracking field exposed via MCP | `backend/app/db/models/skills.py` |
| `ApiKeyAuthMiddleware` | class (middleware) | CH middleware detecting API keys (Bearer/query param), validating via CC, enriching request context | `backend/app/communication_hub/middleware/api_key_auth.py` |
| `_extract_api_key` | function | Extracts API key from Authorization header or query parameter | `backend/app/communication_hub/middleware/api_key_auth.py` |
| `_validate_api_key_with_cc` | function (async) | Calls CC internal validation endpoint over mTLS, returns enriched response | `backend/app/communication_hub/middleware/api_key_auth.py` |
| `load_skills` | function (system tool) | MCP system tool: returns accessible skills with schemas, supports `since` for incremental sync | `backend/app/communication_hub/api/mcp_tools.py` |
| `mcp_router` | class (router) | FastAPI APIRouter for MCP-facing tool endpoints on Communication Hub | `backend/app/communication_hub/api/mcp_tools.py` |
| `ApiKeyListPage` | component | Main API key management page with table, filtering, search, empty/loading/error states | `frontend/src/pages/api-keys/ApiKeyListPage.tsx` |
| `CreateApiKeyDialog` | component | Two-step modal: form (identity+role selection) → key reveal with copy | `frontend/src/pages/api-keys/CreateApiKeyDialog.tsx` |
| `RevokeApiKeyDialog` | component | Confirmation modal for irreversible key revocation | `frontend/src/pages/api-keys/RevokeApiKeyDialog.tsx` |
| `useApiKeys` | hook | React hook: fetches API key list with loading/error state, exposes `refresh()` | `frontend/src/hooks/useApiKeys.ts` |
| `fetchApiKeys` | function | HTTP GET `/api/v1/api-keys` — fetches key list with optional status filter | `frontend/src/api/apiKeysApi.ts` |
| `createApiKey` | function | HTTP POST `/api/v1/api-keys` — creates a new API key | `frontend/src/api/apiKeysApi.ts` |
| `revokeApiKey` | function | HTTP POST `/api/v1/api-keys/{key_id}/revoke` — revokes an API key | `frontend/src/api/apiKeysApi.ts` |
| `fetchIdentitiesWithRoles` | function | HTTP GET `/api/v1/api-keys/identities-with-roles` — dropdown data for create dialog | `frontend/src/api/apiKeysApi.ts` |
| `ApiKey` | interface | TypeScript type for API key list item | `frontend/src/types/apiKeys.ts` |
| `ApiKeyCreateRequest` | interface | TypeScript type for API key creation form data | `frontend/src/types/apiKeys.ts` |
| `ApiKeyCreateResponse` | interface | TypeScript type for API key creation response (includes one-time key) | `frontend/src/types/apiKeys.ts` |
| `ApiKeyStatus` | enum | TypeScript enum: `active` / `revoked` | `frontend/src/types/apiKeys.ts` |
| `IdentityWithRoles` | interface | TypeScript type for identity with available roles (dropdown data) | `frontend/src/types/apiKeys.ts` |
| `require_service_certificate` | dependency | FastAPI dependency: ensures request comes from a valid service certificate (used on all internal endpoints) | `backend/app/api/deps.py` |
| `require_permission` | dependency | FastAPI dependency: ensures JWT-authenticated user has required permission (used on admin endpoints) | `backend/app/api/deps.py` |
| `AgentIdentity` | class (model) | Existing model referenced by API key via `agent_identity_id` FK | `backend/app/db/models/agents.py` |
| `AgentRole` | class (model) | Existing model referenced by API key via `agent_role_id` FK | `backend/app/db/models/role.py` |
| `PermissionResolutionService` | class (service) | Existing service extended with API-key-based resolution entry point | `backend/app/services/permission_resolution.py` |
