# PRD: Add Group Claim Mapper to Keycloak Provisioning

## Epic Overview

When users authenticate through Keycloak, the `JWTAuthMiddleware._sync_user_and_groups` mechanism auto-assigns them to Parthenon groups by matching JWT `groups` claims against Parthenon group `idp_claim_value` entries. However, the Keycloak OIDC client created during provisioning lacks a "Group Membership" protocol mapper — the JWT never includes a `groups` claim. This silently breaks permission inheritance for all non-admin users, who receive "User has no assigned roles" denials despite being members of the correct Parthenon groups.

## Business Goals

1. **Zero-touch group assignment**: Users logging in via Keycloak are automatically assigned to the correct Parthenon groups based on their IdP group memberships, without manual admin intervention
2. **Reliable permission inheritance**: Group-based role assignments flow through to every authenticated user, eliminating "Permission Denied" errors for correctly configured users
3. **Correct provisioning**: The identity bootstrap flow creates complete and correct Keycloak client configurations, not partial ones

## Users & Personas

- **Platform Administrators** — Set up the identity provider once via the setup wizard and expect users to get correct permissions automatically
- **All Platform Users** — Should receive role assignments through group membership without needing manual admin intervention
- **Test Users / Developers** — Need to validate permission configurations; currently blocked because their accounts never inherit group roles

## User Stories

1. **As a platform administrator**, I want users to be automatically assigned to the correct Parthenon groups when they first log in, so that I don't have to manually assign every new user
2. **As a platform user**, I want my Keycloak group memberships to grant me the correct Parthenon permissions, so that I can access the resources I need
3. **As a developer**, I want the permission system to work end-to-end, so that I can confidently test role-based access control

## Acceptance Criteria

1. The `parthenon-api-ui` Keycloak client includes a "Group Membership" protocol mapper after provisioning
2. The `groups` claim appears in JWT tokens issued to users who are members of Keycloak groups
3. `GroupClaimMapper.map_claims` successfully creates `UserGroup` records for users whose JWT `groups` claim matches a Parthenon group's `idp_claim_value`
4. Users who are members of Keycloak groups receive the corresponding Parthenon group roles on first login
5. The fix is applied to both new installations (provisioning) and existing installations (upgrade/fix path)
6. No regression in the existing authentication flow

## Out of Scope

- Creating or syncing Keycloak groups (groups must be created separately in Keycloak Admin)
- Full group lifecycle management (group creation, deletion, membership changes)
- Removing stale group memberships when JWT claims change
- Changes to the `GroupClaimMapper` itself (it works correctly when the claim exists)

## Dependencies & Constraints

- Requires access to the Keycloak Admin API during provisioning
- The `GroupClaimMapper` expects JWT claim name `groups` (Keycloak default for group membership mapper)
- Parthenon groups must have `idp_claim_value` set to match the Keycloak group name
- The Keycloak admin client credentials must have permission to manage clients and their protocol mappers
