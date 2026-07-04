# Spec Change: Add Group Claim Mapper to Keycloak Provisioning

## Affected Spec Areas

- `docs/master/product/features/identity-provider-setup.md` — Identity provider provisioning capability
- `docs/master/technology/modules/auth/tech-spec.md` — Auth middleware and group claim mapping

## New Capabilities

- **Group Membership Mapper Provisioning**: The identity bootstrap flow now adds a "Group Membership" protocol mapper to the `parthenon-api-ui` Keycloak client
- **Idempotent Mapper Creation**: Mapper creation is safe to run multiple times — existing mappers are not duplicated
- **Reprovisioning Support**: Administrators can reprovision the identity provider to add the mapper to an existing client

## Modified Capabilities

- **Keycloak Client Creation** (`KeycloakAdminClient.create_oidc_client`): Now also creates the group membership protocol mapper after client creation
- **Identity Bootstrap Service** (`IdentityBootstrapService.provision_bundled_keycloak`): The provisioning flow now includes mapper creation as a post-client-creation step

## Removed Capabilities

None

## Spec Update Instructions

1. Update `docs/master/product/features/identity-provider-setup.md` to note that group membership mappers are now created automatically
2. Update `docs/master/technology/modules/auth/tech-spec.md` Code Reference Map with new `add_group_membership_mapper` method
