# Affected Spec Areas
- docs/master/product/ (resource management modules: agents, skills, MCP hubs, etc.)
- docs/master/qa/ (test plans for access control)
- docs/master/technology/ (error handling and permission enforcement references)

# New Capabilities
- Global backend enforcement of permissions for all resource management endpoints
- Standardized, descriptive permission error messages including resource type, action, resource ID, and actual error details
- UI for assigning roles to groups, allowing team leads/admins to add or remove roles for any group
- Audit logging of all permission check results

# Modified Capabilities
- Resource access endpoints now deny by default unless permission is granted
- Error responses for permission failures are now actionable and specific, not generic, and always display actual error context (not generic messages)
- Users can request access with all necessary context from error messages
- Group-role assignment UI updates group-role table automatically after changes (no page reload required)

# Removed Capabilities
- None (no existing capabilities are removed)

# Spec Update Instructions
- Update product spec in docs/master/product/ to require permission checks, descriptive errors, and a UI for assigning roles to groups
- Update QA test plans in docs/master/qa/ to include permission enforcement, error message validation (including actual error details), and group-role assignment UI behavior
- Update technology spec in docs/master/technology/ to document new error response format, audit logging requirements, and group-role assignment UI refresh behavior
