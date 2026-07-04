# Auth Infrastructure & Provisioning Test Plan

## What to Test
- Keycloak realm and client auto-configuration (bundled provider)
- Keycloak admin client operations: realm creation, client creation, protocol mapper creation
- Group membership mapper provisioning and idempotency
- Identity bootstrap service: setup state detection, provider provisioning flows
- External OIDC provider registration
- First-run setup wizard: from discovery to config persistence
- Bootstrap certificate issuance (agent-instance and service certs)

## Critical Scenarios

### Keycloak Admin Client
- Admin token acquisition succeeds with valid credentials
- Admin token acquisition fails gracefully with invalid credentials or unreachable server
- Client creation is idempotent — calling twice does not duplicate
- Realm creation is idempotent — calling twice does not error
- Protocol mapper creation is idempotent — skips POST when mapper already exists
- Protocol mapper creation creates the mapper when it does not exist yet
- Protocol mapper creation raises error when target client does not exist
- Protocol mapper creation raises error when Keycloak API returns non-2xx

### Group Claim Mapper Provisioning
- First-time provisioning: the `{client_id}-ui` client receives a "group_membership" protocol mapper
- Reprovisioning (idempotent): when provisioning runs again on an already-configured client, the mapper is NOT duplicated (skip if already exists)
- Mapper failure does not block provisioning: when the Keycloak API returns an error for mapper creation, provisioning continues (mapper failure is non-fatal)
- Existing installations: when an existing installation is reprovisioned (force_reconfigure=true), the mapper is added to the existing client
- JWT includes groups: when a user who is a member of a Keycloak group authenticates, the JWT includes a `groups` claim with the group names

### Bootstrap Service
- `check_setup_state` returns NOT_CONFIGURED when no DB row exists and identity_setup_complete=False
- `check_setup_state` returns CONFIGURED when DB row has is_setup_complete=True
- `check_setup_state` returns NOT_CONFIGURED when DB row has is_setup_complete=False (aborted setup)
- `provision_bundled_keycloak` returns error when keycloak_url is missing
- `provision_bundled_keycloak` returns error when Keycloak is unreachable
- `provision_external_oidc` returns error when client_id is missing
- Group claim mapper is configured during bundled Keycloak provisioning
- Force reconfigure updates existing realm/client configuration

### User-Facing Auth Flows
- OIDC login flow (bundled Keycloak and external provider)
- JWT validation and token expiry handling
- JWT `groups` claim triggers automatic group assignment via GroupClaimMapper
- GroupClaimMapper creates UserGroup records for matching claims
- Users receive group roles on first login
- No regression in existing auth flow after group claim mapper provisioning changes

## Edge Cases & Risks
- **Empty groups**: Users with no Keycloak group memberships get an empty `groups` array — GroupClaimMapper returns no assignments (existing correct behavior)
- **Client UUID not found**: If the client doesn't exist, mapper creation fails gracefully
- **Keycloak version compatibility**: The `oidc-group-membership-mapper` protocol mapper is available in Keycloak 18+
- **Keycloak unreachable mid-session**: OIDC callback failures are handled gracefully with user-facing error message
- **Stale group claim assignments**: When a user's `idp_claim_value` changes, re-login updates group membership
- **First-run setup interruption**: Aborted setup (DB row with is_setup_complete=False) returns NOT_CONFIGURED, allowing restart
- **Auth middleware failures**: User Cache or Group Claim Mapper exceptions are caught and logged without crashing the request
- **Token expiry mid-session**: Refresh flow is triggered; user is not logged out silently

## Acceptance Criteria Checklist
- [x] Protocol mapper is created during provisioning
- [x] JWT includes `groups` claim after mapper is added
- [x] `GroupClaimMapper` creates UserGroup records for matching claims
- [x] Users receive group roles on first login
- [x] Idempotent — reprovisioning does not duplicate mappers
- [x] No regression in existing auth flow
- [x] Bootstrap certificate issuance continues to work (agent-instance and service certs)

## Test File References

### Backend Unit Tests
| File | Purpose |
|---|---|
| `backend/tests/services/identity/test_keycloak_admin_client.py` | Unit tests for `KeycloakAdminClient`, including `create_group_membership_mapper` idempotency, creation, error handling |
| `backend/tests/services/identity/test_bootstrap_service.py` | Unit tests for `IdentityBootstrapService`: setup state detection, bundled Keycloak provisioning, external OIDC provisioning |
| `backend/tests/unit/test_group_claim_mapper.py` | Unit tests for `GroupClaimMapper`: matching claims to groups, empty claims, multi-group assignment |
| `backend/tests/unit/test_bootstrap.py` | Unit tests for certificate bootstrap endpoint: agent-instance and service cert issuance, auth validation, CN format |
| `backend/tests/security/test_bootstrap_security.py` | Security tests for bootstrap: unauthorized access, key validation, deny-by-default enforcement |

### Backend Integration Tests
| File | Purpose |
|---|---|
| `backend/tests/integration/test_identity_setup_flow.py` | Integration tests for identity setup flow against real database: setup wizard → realm/client creation → state persistence |

### E2E Tests
| File | Purpose |
|---|---|
| `e2e/tests/auth-required/auth.spec.ts` | E2E auth flow: OIDC login, token handling, session management |
| `e2e/tests/auth-required/group-claim-mapper.spec.ts` | E2E verification of JWT groups claim flow (planned — not yet implemented) |
| `e2e/tests/auth-required/oidc-callback.spec.ts` | E2E verification of OIDC callback handling and user profile creation |

### Related Test Plans
- **Identity & Auth user-facing flows**: `docs/master/qa/test-plans/identity-test-plan.md` — covers role/permission enforcement, user group management, access requests, policy management. The auth infrastructure tests in this plan complement the user-facing identity tests in that plan.
