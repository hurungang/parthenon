# Epic Overview
Parthenon currently lacks a unified, business-driven access control system across its management modules. This epic introduces global access control, ensuring that every resource management module (e.g., agents, skills, MCP hubs) enforces permissions at the backend. Users will receive clear, actionable error messages when access is denied, specifying the resource type, action, and resource ID. This empowers users to request the correct access and supports enterprise compliance requirements.

# Business Goals
- Ensure only authorized users can access or manage resources across all modules
- Provide clear, actionable permission error messages to reduce support burden
- Enable users to request access with precise context (resource, action, ID)
- Support enterprise compliance and auditability for access control
- Reduce risk of unauthorized data exposure

# Users & Personas
- Platform Administrators: Need to enforce and audit access policies
- Team Leads/Managers: Need to manage access for their teams, including assigning roles to groups
- End Users: Need to understand and request access when denied
- Security/Compliance Officers: Need evidence of robust access enforcement

# User Stories
- As an end user, I want to see exactly why access is denied, so that I can request the right permissions
- As an admin, I want all resource access to be permission-checked, so that unauthorized actions are blocked
- As a team lead, I want to manage my team’s access centrally, so that onboarding/offboarding is efficient
- As a team lead, I want to assign roles to groups using a clear UI, so that I can efficiently manage group permissions
- As a compliance officer, I want audit trails of permission checks, so that I can demonstrate regulatory compliance

# Acceptance Criteria
- All backend resource management endpoints enforce permission checks before returning data
- Permission errors specify resource type, action, and resource ID in the response
- Users denied access receive actionable error messages (not generic 403/401), including actual error details and context (e.g., which field or resource caused the error)
- Users can request access with all necessary context from the error message
- Audit logs capture permission check results for all resource access attempts
- No resource is accessible without explicit permission (deny by default)
- Existing functionality is not broken for users with correct permissions
- UI is provided for assigning roles to groups, allowing team leads/admins to add or remove roles for any group
- After assigning or removing a role from a group, the group-role table updates automatically without requiring a page reload
- All error messages throughout the UI and API display actual error context, not generic messages, to help users and admins resolve issues

# Out of Scope
- UI for managing permissions (covered by separate epic)
- Changes to the underlying role/permission model
- Non-resource endpoints (e.g., health checks, static content)

# Dependencies & Constraints
- Relies on existing OIDC authentication and role/permission model
- Requires backend changes in all resource management modules
- Must not degrade performance or user experience
- Error message format must be standardized across modules
