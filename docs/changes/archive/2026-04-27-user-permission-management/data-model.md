# User Permission Management — Data Model

**Context:** This data model defines entities for the **user permission system** which controls what human users can access and do in the Parthenon platform. This is distinct from the existing **agent permission system** which controls what AI agents can access. All API endpoints for this system use the `/api/v1/user-*` prefix to avoid conflicts.

## 1. New Entities

### Entity Relationship Diagram

```mermaid
erDiagram
    TagDefinition ||--o{ TagValue : has
    Role ||--o{ PolicyStatement : contains
    PolicyStatement ||--o{ PolicyAction : includes
    PolicyStatement ||--o{ PolicyResource : scopes
    PolicyStatement ||--o{ PolicyTagCondition : conditions
    PlatformUser }o--o{ Role : assigned_via_UserRole
    PlatformUser }o--o{ Group : member_via_UserGroup
    Group }o--o{ Role : assigned_via_GroupRole
    Group }o--|| PlatformUser : owned_by
    AccessRequestBatch }o--|| PlatformUser : submitted_by
    AccessRequest }o--|| AccessRequestBatch : part_of
    AccessRequest }o--|| Group : for
    AccessRequest }o--|| PlatformUser : requested_by

    TagDefinition {
      string id
      string key
      string scope
      string resource_type
      string description
      date created_at
    }
    TagValue {
      string id
      string value
      date created_at
    }
    Role {
      string id
      string name
      string description
      enum role_type
      date created_at
      date updated_at
    }
    PolicyStatement {
      string id
      string effect
      string module
      date created_at
    }
    PolicyAction {
      string id
      string action
    }
    PolicyResource {
      string id
      string resource_type
      string resource_id
    }
    PolicyTagCondition {
      string id
      string tag_key
      string tag_value
    }
    PlatformUser {
      string id
      string oidc_sub
      string email
      string display_name
      date first_seen_at
      date last_seen_at
    }
    UserRole {
      date assigned_at
      string assigned_by
    }
    Group {
      string id
      string name
      string description
      string owner
      string idp_claim_value
      date created_at
    }
    GroupRole {
      date assigned_at
    }
    UserGroup {
      date joined_at
      string join_reason
    }
    AccessRequestBatch {
      string id
      string justification
      date submitted_at
    }
    AccessRequest {
      string id
      string status
      date requested_at
      date reviewed_at
      string reviewed_by
      string reviewer_reason
    }
```

### Entity List
- **TagDefinition** — Defines a tag key with allowed values and scope
- **TagValue** — Allowed values for a tag definition
- **Role** — A named permission role
- **PolicyStatement** — A permission statement belonging to a role
- **PolicyAction** — Actions within a policy statement
- **PolicyResource** — Resources scoped by a policy statement
- **PolicyTagCondition** — Tag-based conditions on a policy statement
- **PlatformUser** — Cached user from OIDC sign-in
- **UserRole** — Direct role assignment to a user (junction)
- **Group** — A named group of users
- **GroupRole** — Roles assigned to a group (junction)
- **UserGroup** — Users belonging to a group (junction)
- **AccessRequestBatch** — A user's submission requesting access to one or more groups (holds justification)
- **AccessRequest** — A request for access to a single group within a batch (holds status, reviewer, reviewer_reason)

## 2. Modified Entities
- **Role** — Added `role_type` field (enum: `system` | `user_defined`). Distinguishes system-managed roles (cannot be edited or deleted by users) from user-defined roles. Default value for all existing roles: `user_defined`.
- **AccessRequestBatch** — New entity for multi-group access request submissions
- **AccessRequest** — Now references AccessRequestBatch, justification moved to batch, reviewer_reason added

## 3. Removed Entities/Fields
- **None.** No entities or fields are removed.

## 4. Schema File References
- Modify existing model file:
  - `backend/app/db/models/role.py` — add `role_type` column (enum: `system` | `user_defined`; default `user_defined`)
- Create new model files in `backend/app/db/models/` for each entity:
  - `tag_definition.py`
  - `tag_value.py`
  - `role.py`
  - `policy_statement.py`
  - `policy_action.py`
  - `policy_resource.py`
  - `policy_tag_condition.py`
  - `platform_user.py`
  - `user_role.py`
  - `group.py`
  - `group_role.py`
  - `user_group.py`
  - `access_request_batch.py`
  - `access_request.py`

## 5. Master Data Model Update Instructions
- Add all new entities and their relationships to the master data model in `docs/master/data-model/overview.md`.
- Add references to these entities in the appropriate module subfolders under `docs/master/data-model/modules/` (e.g., `identity/`, `agents/`, etc.) as relevant to their usage.
