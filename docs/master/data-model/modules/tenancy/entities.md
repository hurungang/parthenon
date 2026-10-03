# Tenancy — Entities

Multi-tenant core (opt-in, disabled by default via the `multi_tenancy_enabled` switch in `PlatformSetting`). The former system tenant is the **root tenant** (workspace name/address `root`, `is_root_tenant = true`): it adopts pre-existing data at migration and hosts platform staff as ordinary members with platform roles.

```mermaid
erDiagram
    Tenant {
        uuid id
        string name "editable unique alias (root-editable)"
        string slug "immutable unique tenant address"
        enum status "active | suspended | deleted"
        enum admin_contact_role "JIT default tenant role for first admin"
        boolean is_root_tenant "exactly one: root tenant (workspace 'root')"
        boolean is_onboarded
        string admin_contact_name
        string admin_contact_email
        datetime created_at
        datetime updated_at
    }
    PlatformUser {
        uuid id
        string sub "OIDC subject or platform-issued identifier"
        string display_name
        string email
        string password_credential "platform-issued for self-serve accounts"
    }
    TenantUserMembership {
        uuid id
        uuid tenant_id
        uuid user_id
        enum tenant_role "platform_admin | tenant_admin | member"
        enum status "active | suspended | removed"
        boolean is_root "immutable owner; exactly one per tenant, at most one per user"
        boolean is_default
        datetime created_at
        datetime updated_at
    }
    TenantInvitation {
        uuid id
        uuid tenant_id
        uuid invited_by_id
        string email
        enum tenant_role "tenant_admin | member"
        enum status "pending | accepted | expired | revoked"
        boolean is_single_use
        datetime expires_at
        datetime created_at
        datetime updated_at
    }
    TenantAuditEvent {
        uuid id
        uuid tenant_id "platform-level events attribute to the root tenant"
        enum event_type
        enum actor_type
        uuid actor_id
        string target_resource
        json detail
        boolean is_security_relevant
        datetime created_at
    }
    PlatformSetting {
        uuid id
        string key "e.g. multi_tenancy_enabled (default false)"
        json value
        string description
        enum category
        boolean is_tenant_agnostic
        datetime created_at
        datetime updated_at
    }

    Tenant ||--o{ TenantUserMembership : "grants membership in"
    PlatformUser ||--o{ TenantUserMembership : "joins tenants via"
    Tenant ||--o{ TenantInvitation : "receives invitations for"
    TenantUserMembership ||--o{ TenantInvitation : "sends invitations"
    Tenant ||--o{ TenantAuditEvent : "records audit events for"
    PlatformSetting ||..o{ Tenant : "governs tenancy mode for"
```

| Entity | Description | Source |
|---|---|---|
| `Tenant` | Organization workspace; `name` is the editable unique alias, `slug` the immutable address; exactly one tenant has `is_root_tenant = true` (the root tenant, workspace `root`); `admin_contact_role` is the JIT default role granted to the first admin | `backend/app/db/models/tenant.py` |
| `TenantUserMembership` | A user's presence in a tenant with a tenant-scoped role; `is_root` marks the immutable owner (one per tenant, at most one owned tenant per user, root implies all tenant permissions, alterations rejected and audited) | `backend/app/db/models/tenant_membership.py` |
| `TenantInvitation` | Pending user onboarding into a tenant; carries target tenant role, single-use flag, and expiry | `backend/app/db/models/tenant_invitation.py` |
| `TenantAuditEvent` | Tenant-attributed audit trail for lifecycle, registration, root-protection, licensing, and quota events; platform-level events attribute to the root tenant | `backend/app/db/models/tenant_audit_event.py` |
| `PlatformSetting` | Tenant-agnostic platform configuration store; home of the `multi_tenancy_enabled` switch (default `false`) | `backend/app/db/models/platform_setting.py` |
| `PlatformUser` | Tenant-agnostic real-world person; tenant presence via memberships; platform-issued email + password credential for self-serve accounts | `backend/app/db/models/platform_user.py` |

**Self-serve registration:** one all-or-nothing action creates `PlatformUser` + `Tenant` + the creator's root `TenantUserMembership` (`is_root = true`), then lands the root user in guided onboarding; a user who already owns a tenant is blocked (one owned tenant per user).
