# Identity Provider Setup — Group Membership Mapper Provisioning

## Epic Overview

Parthenon's identity bootstrap flow now automatically provisions a Group Membership protocol mapper on the Keycloak OIDC client during initial setup and reprovisioning. This ensures that JWT tokens issued by Keycloak include a `groups` claim, enabling the platform's group-based permission system to correctly assign roles to users based on their Keycloak group memberships — with no manual admin intervention required.

## Business Goals
- Eliminate silent permission failures caused by missing `groups` claims in JWT tokens
- Automate group membership mapper creation during identity provider provisioning
- Support reprovisioning for existing installations to retrofit the mapper
- Ensure idempotent mapper creation (safe to run multiple times)

## User Stories
- As a platform administrator, I want group membership mappers to be automatically provisioned during setup so that group-based role assignment works out of the box.
- As a platform administrator, I want to reprovision the identity provider to add mappers to existing clients without data loss.
- As an existing user, I want to receive correct group-based roles after reprovisioning on my next login.

## Key Capabilities

### Automatic Group Membership Mapper Creation

When a platform administrator provisions a bundled Keycloak identity provider (either via the setup wizard or CLI), the system now automatically adds a Group Membership protocol mapper to the `parthenon-api-ui` Keycloak client. This mapper instructs Keycloak to include the `groups` claim in every JWT access token, listing all Keycloak groups the authenticated user belongs to.

### Idempotent Mapper Creation

Mapper creation is safe to run multiple times. If the Group Membership mapper already exists on the client, the provisioning process detects it and skips creation — no duplicate mappers are created, and existing configurations are not altered.

### Reprovisioning Support

Administrators can reprovision the identity provider to add the Group Membership mapper to an existing client that was created before this capability was introduced. Running the reprovisioning step ensures that previously provisioned clients also receive the mapper, closing the gap for existing installations.

### End-to-End Group Claim Flow

With the mapper in place, the JWT `groups` claim flows end-to-end:

1. Keycloak includes the `groups` claim in JWT access tokens issued to authenticated users
2. `JWTAuthMiddleware` extracts the claim from the token
3. `GroupClaimMapper` matches `groups` claim values against Parthenon group `idp_claim_value` fields
4. Users are automatically assigned to the correct Parthenon groups and inherit their roles

No changes to the `GroupClaimMapper` or auth middleware were needed — they were already designed to process the `groups` claim correctly once it is present.

## Impact on Existing Setups

- **New installations**: Group membership mapping works out of the box after completing the setup wizard — no additional steps needed
- **Existing installations**: Administrators should reprovision the identity provider to add the mapper to their existing client. After reprovisioning, users will receive group-based role assignments on their next login
- **External identity providers (e.g., Azure EntraID)**: This capability applies only to the bundled Keycloak provider. Administrators using external providers must configure group claim mapping in their own identity provider

## Acceptance Criteria
- Group Membership mapper is automatically created on the Keycloak OIDC client during bundled Keycloak provisioning
- JWT tokens include `groups` claim after provisioning completes
- Group-based role assignment works on first login after setup
- Reprovisioning adds the mapper to existing clients without creating duplicates
- External OIDC providers are unaffected — group claim mapping is configured in the external provider

## Out of Scope
- Managing Keycloak groups from Parthenon (groups must be created in Keycloak Admin Console)
- Automatic group-to-role mapping configuration (administrators must set `idp_claim_value` on groups)
- Provisioning group membership mappers on external OIDC providers
- Migration of existing users between identity providers

## Prerequisites

- Parthenon groups must have their `idp_claim_value` set to match the Keycloak group name for role inheritance to work
- Keycloak groups must be created separately in the Keycloak Admin Console — group management is not handled by the provisioning flow
- The Keycloak admin credentials used during provisioning must have permissions to manage clients and their protocol mappers
