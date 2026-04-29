

# PRD: User Permission Management

## Epic Overview

Parthenon introduces a dedicated, clearly namespaced user permission management system for human users, distinct from the agent permission system. This epic delivers a complete user permission management layer—including user roles, user groups, user policies, and user tags—with all endpoints, types, and terminology consistently prefixed with "user-" (e.g., `/user-roles`, `/user-groups`, `/user-tags`, `/user-access-requests`). This enables enterprises to define fine-grained, policy-driven access for human users, organize them into user groups, and automate access assignment based on identity provider claims, all with clear separation from agent permissions.

## Business Goals

1. **Reduce admin overhead** — Auto-assign users to user groups via IdP claim mapping, eliminating manual user role assignments for 80%+ of onboarding scenarios.
2. **Enable least-privilege access** — Fine-grained user policy conditions (user tag-based) allow teams to limit user access to exactly what each user role requires.
3. **Accelerate user onboarding** — New users are assigned user roles within minutes of first sign-in, either automatically (IdP claim) or via a lightweight approval flow.
4. **Improve auditability** — All user permission assignments (direct user role, user group membership, user group requests) are traceable to a specific admin action or IdP event.
5. **Support multi-tenant governance** — Organizations managing multiple environments (e.g., `env:prod`, `env:test`) can enforce environment-scoped user access without separate platform instances.

## Users & Personas

| Persona | Role in Platform | Primary Need |
|---------|-----------------|--------------|
| **Platform Admin** | Manages all users, user roles, user groups, and user tags | Create and maintain the user permission model; audit which users have access to what |
| **User Group Owner** | Owns one or more user groups; approves membership requests | Review and approve/reject join requests from users in their user group |
| **Business User** | Human end-user accessing the Web UI | Know what they can access; request access to additional user groups when needed |
| **Enterprise IT/SSO Owner** | Manages the IdP (Keycloak/EntraID) | Bind IdP group claims to platform user groups without manual re-configuration |

## User Stories

	- As an admin, I want to manage all policies for a role in a single comprehensive dialog, so that I have a complete view of permissions without navigating multiple screens.
	- As a user who receives a permission denied error, I want to see exactly which permission I'm missing (resource type, action, and resource ID), so that I can request the specific access I need.

## Acceptance Criteria

**System Admin Role:**

**Policy Management UI:**
	- All policies for a user role are managed in a single dialog, matching the approved prototype design (no multi-screen navigation for policy editing).

**Resource Type Manifest:**
	- There is a centralized manifest or constant that defines all resource types and their allowed actions.
	- The manifest is the single source of truth for both the UI and permission checking logic.

**Structured Permission Error Messages:**
	- When a user is denied access due to insufficient permissions, the error message (403) includes structured details: resource type, action required, and resource ID.
	- Users can see which permission is missing and request access accordingly.

**User Group Requests:**
- User group owners can approve or reject membership requests, and requesting users are notified of the outcome
- All users who have authenticated via OIDC are visible in the Users list with their current user roles and user group memberships
- Admins can assign or remove direct user roles and user group memberships for any user
- On first sign-in, users with JWT claims matching platform user groups are auto-assigned to those groups
- If no matching claims exist, users can request access to available user groups, providing justification
- Submitted requests display their status (pending / approved / rejected) to the requesting user

## Out of Scope

- **System role management by users** — System roles cannot be created, modified, or deleted by users; only user-defined roles are user-manageable.

## Dependencies & Constraints

- **OIDC token claims** — JWT group claims must be available in the token at sign-in time; this requires IdP configuration (Keycloak realm or EntraID app roles) to include group membership in the token payload.
- **OIDC integration** — The user permission management feature must integrate seamlessly with the existing Keycloak/EntraID authentication flow; no disruption to current authentication processes is permitted.
- **Notification system** — User group request/approval notifications depend on the platform's existing notification integration; at minimum, in-platform notifications are required.
- **Existing User Role model** — Current user role and user permission records in the data model must be extended; backward compatibility with existing user role assignments must be maintained.
- **Admin-only access** — User tag management, user role authoring, and user group administration are restricted to platform admin roles; the existing RBAC enforcement layer must gate these pages.
## Business Goals
