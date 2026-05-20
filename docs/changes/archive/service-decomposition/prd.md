# Service Decomposition — Product Requirements Document (PRD)

## Epic Overview
Split the Parthenon platform into three independently deployable services—Control Center, Agent Runtime, and Communication Hub—to improve security, scalability, and operational flexibility. This change addresses the need for strict data protection, clear service boundaries, and easier scaling and maintenance for enterprise customers.

## Business Goals
- Eliminate direct database access from Agent Runtime and Communication Hub; all data access flows through Control Center
- Enforce certificate-based authentication for all service-to-service communication
- Enable independent deployment, scaling, and maintenance of each service
- Strengthen data protection and compliance by centralizing sensitive operations in Control Center
- Reduce operational risk by isolating agent execution and messaging from core data management

## Users & Personas
- **DevOps Engineers**: Need to deploy, scale, and monitor services independently
- **Security Teams**: Require strict enforcement of data access controls and auditability
- **System Administrators**: Need to manage service certificates and monitor inter-service trust
- **Test/QA Engineers**: Need to automate validation of service-to-service interactions as part of the trusted ecosystem

## User Stories
 - As a DevOps engineer, I want to deploy and scale Agent Runtime, Communication Hub, and Control Center separately, so that I can optimize resources and minimize downtime
 - As a security team member, I want all service-to-service calls to use certificate-based authentication, so that only trusted services can access sensitive data
 - As a system administrator, I want to ensure Agent Runtime and Communication Hub cannot access the database directly, so that all data access is centrally controlled and auditable
 - As a system administrator, I want to manage and rotate service certificates from a single authority, so that trust boundaries are clear and enforceable
 - As a test engineer, I want the test suite to authenticate as a trusted service, so that I can automate validation of service-to-service interactions without manual setup
 - As a platform developer, I want all tool names to follow a unique `server____tool` convention so that tool names are globally unique across all MCP servers and system tools, and routing is deterministic.

## Acceptance Criteria
 - All tool names follow the `server____tool` format (4 underscores). `system` is reserved as the server name prefix for built-in tools (e.g., `system____save_result`, `system____send_notification`, `system____get_recipient_group`). MCP server names cannot contain `____`.
 - Agent Runtime and Communication Hub cannot connect to the database directly; all data access is mediated by Control Center
 - All service-to-service communication uses certificate-based authentication, with certificates issued and managed by Control Center
 - Communication Hub and Agent Runtime bootstrap by requesting certificates from Control Center using unique per-service bootstrap keys (not shared secrets)
 - Control Center can call Agent Runtime (to trigger execution) and Communication Hub (to send messages), with mutual certificate validation
 - Communication Hub and Agent Runtime validate Control Center certificates for all incoming calls
 - Agent Runtime treats all tools uniformly—no distinction between system tools and MCP tools in agent execution code. Communication Hub is responsible for routing each tool call to the correct handler.
 - The runtime does not automatically call `save_result` at agent completion. If an agent is instructed to save a result, it must call the tool explicitly. If not instructed, no result is saved.
 - After decomposition, each service can be deployed, scaled, and restarted independently
 - No user or agent can bypass Control Center to access or modify data
 - All inter-service calls are logged for auditability
 - Test suite can bootstrap with Control Center using a test service bootstrap key and obtain a service certificate
 - All integration tests can make authenticated calls to Control Center, Agent Runtime, and Communication Hub without mocking
 - Test suite validates full agent execution flow (CC → AR → CC → CH) with real service calls

## Out of Scope
- Changes to the user-facing Web UI or agent skill definitions
- Modifications to the database schema or entity models
- New agent types, skills, or SOPs
- Changes to OIDC/OAuth2 authentication for end users

## Dependencies & Constraints
- Requires updates to deployment scripts and orchestration (Docker Compose, Kubernetes/Helm)
- Relies on robust certificate authority and management in Control Center
- All services must support mTLS and certificate rotation
- Existing integrations must be updated to use new service endpoints
- Local development may require running multiple services simultaneously