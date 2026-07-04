# Tech Spec: Add Group Claim Mapper to Keycloak Provisioning

## 1. Technical Overview

The `KeycloakAdminClient` gains a new idempotent method `create_group_membership_mapper` that adds a "Group Membership" protocol mapper to an OIDC client. The `IdentityBootstrapService.provision_bundled_keycloak` flow calls this method after creating the `{client_id}-ui` (public) client. The mapper causes Keycloak to include a `groups` claim in JWT tokens, which the existing `GroupClaimMapper` in the auth middleware already consumes.

No new API endpoints. No database changes. No frontend changes. Backend-only service layer change.

## 2. Component Breakdown

### 2.1 Modified: `KeycloakAdminClient`

**File**: `backend/app/services/identity/keycloak_admin_client.py`

**New method**: `create_group_membership_mapper(token, realm_name, client_id)` — async, idempotent

**Responsibility**: Adds the OIDC group membership protocol mapper to a Keycloak client. Checks for existing mapper first to avoid duplication.

**Mapper configuration**:
| Config Key | Value | Purpose |
|---|---|---|
| `full.path` | `false` | Use short group name, not full path |
| `id.token.claim` | `true` | Include in ID token |
| `access.token.claim` | `true` | Include in access token |
| `userinfo.token.claim` | `true` | Include in userinfo response |
| `claim.name` | `groups` | JWT claim name (consumed by GroupClaimMapper) |

### 2.2 Modified: `IdentityBootstrapService`

**File**: `backend/app/services/identity/bootstrap_service.py`

**Method**: `provision_bundled_keycloak`

**Change**: After creating the `{client_id}-ui` public client, add a call to `kc.create_group_membership_mapper(token, realm_name, f"{client_id}-ui")`. Wrapped in try-except so mapper failure does not fail the entire provisioning.

### 2.3 Unchanged Components

- `GroupClaimMapper` — Already maps `groups` claim correctly; no changes needed
- `JWTAuthMiddleware._sync_user_and_groups` — Already extracts `groups` claim; no changes needed
- `PermissionEngine` — Already resolves group-inherited roles correctly; no changes needed

## 3. Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `create_group_membership_mapper` | method | Adds OIDC group membership mapper to a Keycloak client (idempotent) | `backend/app/services/identity/keycloak_admin_client.py` |
| `_get_client_uuid` | private method | Helper to fetch Keycloak internal UUID for a client by clientId | `backend/app/services/identity/keycloak_admin_client.py` |
| `provision_bundled_keycloak` | method | Calls create_group_membership_mapper after client creation | `backend/app/services/identity/bootstrap_service.py` |
| `GroupClaimMapper.map_claims` | method | Maps JWT group claims to UserGroup records (unchanged) | `backend/app/services/permissions/group_claim_mapper.py` |
| `JWTAuthMiddleware._sync_user_and_groups` | method | Extracts groups claim from JWT and delegates to GroupClaimMapper (unchanged) | `backend/app/middleware/auth.py` |
