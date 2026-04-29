# Keycloak Identity Bootstrap

## Epic Overview
Parthenon now offers a bundled Keycloak identity provider with a guided setup wizard, YAML-based configuration, and CLI support. This streamlines onboarding and ongoing identity management, eliminating the need for complex manual configuration of external identity providers and reducing setup friction for new deployments.

## Business Goals
- Reduce time and errors in first-time identity provider setup
- Increase adoption by simplifying authentication configuration
- Enable version-controlled, team-friendly identity settings
- Support both UI and CLI-driven identity management
- Ensure secure, auditable user access from day one

## Users & Personas
- **New Admins:** Need a simple, guided way to secure their Parthenon instance
- **Team Leads:** Require version-controlled, shareable identity configuration
- **Operators:** Want to manage identity providers via CLI or scripts
- **End Users:** Expect secure, seamless login with managed access

## User Stories
- As a new admin, I want to be guided through identity provider setup on first launch so that I can secure my Parthenon instance without manual configuration.
- As a team lead, I want to manage OIDC settings in a YAML file so that I can easily share and version-control identity configuration.
- As an admin, I want to use a CLI tool to reconfigure or switch identity providers so that I am not dependent on the UI wizard for changes.
- As a user, I want to log in using a secure, pre-configured identity provider so that my access is managed and auditable.

## Acceptance Criteria
- On first application start, the user is prompted to set up the identity provider via a setup wizard
- The user can choose to install a bundled Keycloak instance or connect to an existing provider (Keycloak or Azure EntraID)
- If Keycloak is selected, the system automatically provisions and configures it, including a Parthenon realm and admin user with a user-provided password
- OIDC/identity settings are stored in a YAML config file and can be overridden by environment variables
- The backend application can be run in CLI mode to set up or switch identity providers without using the UI
- Start/stop scripts manage the lifecycle of the Keycloak container when it is in use

## Out of Scope
- Supporting identity providers other than Keycloak and Azure EntraID
- Advanced Keycloak customization beyond automated Parthenon realm and client setup
- Migration of existing user data between identity providers
- In-depth Keycloak management UI within Parthenon

## Dependencies & Constraints
- Docker and Docker Compose required for bundled Keycloak service
- Existing OIDC authentication module in Parthenon
- YAML configuration file support
- Environment variables remain as override mechanism
