
# Spec Change: User Permission Management

## Affected Spec Areas

| Area | File | Change Type |
|------|------|-------------|
| Foundation Platform product spec | [docs/master/product/features/foundation-platform.md](../../../master/product/features/foundation-platform.md) | Major extension |
| Identity & Access entities | [docs/master/data-model/modules/identity/entities.md](../../../master/data-model/modules/identity/entities.md) | New and modified entities |
| System architecture overview | [docs/master/architecture/system-overview.md](../../../master/architecture/system-overview.md) | New user-permission-management module |

---

## New Capabilities




### Resource Types and Actions
- Admins select from a predefined list of resource types and allowed actions when creating or editing user policies.
- The available resource types and actions are consistent across the platform, ensuring clarity for both admins and users.


### Permission Denied Feedback
- When a user is denied access to a feature or resource, they receive clear feedback indicating what permission is missing and what action was attempted.
- Users are guided on how to request access or contact an admin for help.


### User Tag System
- Admins can define and manage reusable labels (user tags) that help categorize resources and control access.
- User tags can be global (used across the platform) or specific to certain resource types.
- When creating user policies, admins can add conditions based on these tags using dropdowns, ensuring only valid values are selected.
- User tags can be assigned to resources through the admin interface, supporting flexible access control.


### User Role & Policy Management
- Admins can create named user roles and define policies that specify what actions users can perform on which resources.
- Policies can include conditions based on user tags, allowing for fine-grained access control.
- Admins select resources and actions from lists, and can use patterns to cover groups of resources where appropriate.
- The previous static role types (user, agent, both) are still available for classification but do not determine permissions by themselves.


### User Group Management
- Admins can create user groups, assign roles to them, and designate group owners.
- User groups can be linked to identity provider attributes, so users are automatically assigned to groups based on their profile when they sign in.


### User Management
- All users who have signed in are visible in a user list with relevant details.
- Admins can assign or remove roles and group memberships for users directly from the admin interface, without needing user action.


### Self-Service User Group Request & Approval
- Users who are not automatically assigned to any groups can view a list of available user groups and request to join them.
- Users can submit one or more join requests at a time, including a justification for their request.
- Group owners are notified of requests and can approve or reject them, providing reasons as appropriate.
- Users can track the status of their requests (pending, approved, rejected) from their dashboard.

---

## Modified Capabilities


### User Role Model (Foundation Platform)
- **Before**: User roles were limited to three static types with fixed permissions.
- **After**: Admins can create custom user roles with flexible policies, allowing for more granular and adaptable permission management. Role types are still available for filtering but do not control permissions directly.


### User Onboarding (Sign-in Flow)
- **Before**: Users were assigned roles based on static configuration, with no concept of user groups.
- **After**: Users are automatically assigned to groups based on their profile attributes when they sign in. If no group matches, users can request access to groups through a self-service flow.


### Foundation Platform product spec (Key Concepts section)
- **Before**: Key Concepts included only basic role management and permission enforcement.
- **After**: Key Concepts now include user tag management, flexible policy authoring, user group management, mapping of identity provider attributes to groups, and a self-service group request/approval process.

---

## Removed Capabilities

- **Static permission-set configuration** — The current model where user permission sets are defined in platform configuration files (not by admins at runtime) is replaced by the dynamic user policy authoring UI. No capability is removed from end-users; the change is in how user permissions are defined.

---

## Spec Update Instructions

### `docs/master/product/features/foundation-platform.md`
- Expand **What It Does** to include: user tag management, policy-based user role authoring, user group creation and IdP claim binding, user caching and direct user role assignment, and the self-service user group request/approval flow.
- Expand **Key Concepts** with entries for: User Tag, User Policy Statement, User Group, IdP Claim Mapping, User Group Request.
- Expand **Who Uses It** to add User Group Owner persona and their primary responsibility.
- Expand **Acceptance Criteria** to include all new capabilities from this change (user tag CRUD, user policy authoring, user group lifecycle, user list, user group request/approval flow).


### `docs/master/data-model/modules/identity/entities.md`
- Update to reflect new business concepts: user tags, user policies, user groups, and flexible role assignments. Remove references to static permission sets and highlight the new, admin-driven permission model.


### `docs/master/architecture/system-overview.md`
- Add a User Permission Management module to the system overview, showing how user access is managed and evaluated at sign-in and when accessing resources. Focus on the user and admin experience, not technical flows.
