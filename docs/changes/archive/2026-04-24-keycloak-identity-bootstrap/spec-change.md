# Keycloak Identity Bootstrap — Spec Delta

## What is Being Added
- Bundled Keycloak identity provider, automatically provisioned and configured when selected during setup
- First-run setup wizard that guides the user through identity provider selection and configuration
- YAML-based identity configuration file (`config/identity.yaml`) for managing OIDC settings
- Backend CLI mode for identity provider setup and switching, independent of the UI
- Automated management of the Keycloak container lifecycle via updated start/stop scripts

## What is Being Changed
- OIDC/identity configuration moves from environment variables only to a YAML config file, with environment variables as overrides
- Start and stop scripts are updated to include lifecycle management for the bundled Keycloak service
- The initial user experience now includes a setup wizard for identity provider configuration

## What Stays the Same
- Existing OIDC integration remains fully supported
- Support for external identity providers, including Azure EntraID, is unchanged
- Users can continue to configure OIDC via environment variables if preferred
- No changes to the core authentication flow for end users once the identity provider is configured
