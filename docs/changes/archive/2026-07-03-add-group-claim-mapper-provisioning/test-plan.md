# Test Plan: Add Group Claim Mapper to Keycloak Provisioning

## Test Strategy

Unit tests for the new `create_group_membership_mapper` method using mocked httpx, integration tests for the bootstrap service flow, and end-to-end verification against the running Keycloak container.

## Coverage Areas

1. **KeycloakAdminClient.create_group_membership_mapper** — Correct mapper creation, idempotency, error handling
2. **IdentityBootstrapService.provision_bundled_keycloak** — Mapper called during provisioning, failure handling
3. **End-to-end JWT flow** — Fresh provisioning produces JWT with groups claim

## Critical Scenarios

1. **First-time provisioning**: WHEN a new Keycloak setup is provisioned, THEN the `{client_id}-ui` client has a "group_membership" protocol mapper
2. **Reprovisioning (idempotent)**: WHEN provisioning runs again on an already-configured client, THEN the mapper is NOT duplicated (skip if already exists)
3. **Mapper failure does not block provisioning**: WHEN the Keycloak API returns an error for mapper creation, THEN provisioning continues (mapper failure is non-fatal)
4. **Existing installations**: WHEN an existing installation is reprovisioned (force_reconfigure=true), THEN the mapper is added to the existing client
5. **JWT includes groups**: WHEN a user who is a member of a Keycloak group authenticates, THEN the JWT includes a `groups` claim with the group names

## Edge Cases & Risks

- **Empty groups**: Users with no Keycloak group memberships get an empty `groups` array — GroupClaimMapper returns no assignments (existing correct behavior)
- **Client UUID not found**: If the client doesn't exist, mapper creation fails gracefully
- **Keycloak version compatibility**: The `oidc-group-membership-mapper` protocol mapper is available in Keycloak 18+

## Acceptance Criteria Checklist

- [x] Protocol mapper is created during provisioning
- [x] JWT includes `groups` claim after mapper is added
- [x] `GroupClaimMapper` creates UserGroup records for matching claims
- [x] Users receive group roles on first login
- [x] Idempotent — reprovisioning does not duplicate mappers
- [x] No regression in existing auth flow

## Test File References

| Test Layer | File | Purpose |
|---|---|---|
| Unit | `backend/tests/unit/test_keycloak_admin_client.py` | Test create_group_membership_mapper with mocked httpx |
| Integration | `backend/tests/integration/test_bootstrap_service.py` | Test provisioning flow includes mapper |
| E2E | `e2e/tests/auth-required/group-claim-mapper.spec.ts` | Verify JWT groups claim flow (future) |
