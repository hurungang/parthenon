# Keycloak Identity Bootstrap — Product Requirements Document

## Overview
Parthenon currently requires manual and complex configuration of an external identity provider, making first-time setup difficult for new users. This change introduces a bundled Keycloak identity provider with a guided setup wizard, YAML-based configuration, and CLI support, streamlining onboarding and ongoing identity management.

## Problem Statement
The Parthenon platform does not include a built-in identity provider, requiring users to manually configure OIDC settings via environment variables and set up an external provider. This creates friction for new deployments, increases setup time, and can lead to misconfiguration or security gaps. A seamless, guided identity setup is needed to improve user experience and adoption.

## Goals
- Enable first-time users to easily set up authentication with a bundled Keycloak provider or connect to an existing provider
- Provide a guided setup wizard on first run to simplify identity configuration
- Allow OIDC/identity settings to be managed via a YAML config file, supporting version control and team sharing
- Support identity provider setup and switching via a backend CLI tool
- Ensure start/stop scripts manage the lifecycle of the bundled Keycloak service

## Non-Goals
- Supporting identity providers other than Keycloak and Azure EntraID
- Advanced Keycloak customization beyond automated Parthenon realm and client setup
- Migration of existing user data between identity providers
- In-depth Keycloak management UI within Parthenon

## User Stories
- As a new admin, I want to be guided through identity provider setup on first launch so that I can secure my Parthenon instance without manual configuration.
- As a team lead, I want to manage OIDC settings in a YAML file so that I can easily share and version-control identity configuration.
- As an admin, I want to use a CLI tool to reconfigure or switch identity providers so that I am not dependent on the UI wizard for changes.
- As a user, I want to log in using a secure, pre-configured identity provider so that my access is managed and auditable.

## Acceptance Criteria
1. On first application start, the user is prompted to set up the identity provider via a setup wizard.
2. The user can choose to install a bundled Keycloak instance or connect to an existing provider (Keycloak or Azure EntraID).
3. If Keycloak is selected, the system automatically provisions and configures it, including a Parthenon realm and admin user with a user-provided password.
4. OIDC/identity settings are stored in a YAML config file and can be overridden by environment variables.
5. The backend application can be run in CLI mode to set up or switch identity providers without using the UI.
6. Start/stop scripts manage the lifecycle of the Keycloak container when it is in use.

## Dependencies
- Docker (for running the bundled Keycloak service)
- Existing OIDC authentication module in Parthenon
- Docker Compose for service orchestration
- YAML configuration file support
