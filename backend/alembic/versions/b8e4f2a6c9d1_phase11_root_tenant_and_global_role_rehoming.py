"""Phase 11: root tenant identity + legacy global role re-homing

Revision ID: b8e4f2a6c9d1
Revises: a1f2c3d4e5b6
Create Date: 2026-10-01

Data migration for the "platform as root tenant" refinement:

1. The system tenant row (``is_system_tenant = true``) is renamed in
   place to name ``Root`` / slug ``root`` (created when absent — fresh
   deployments).  Resolution is by slug lookup, so runtime references
   follow the row.  The Python flag ``is_system_tenant`` is KEPT (58
   files exceeded the rename threshold) and documents the design's
   ``is_root_tenant`` alias.
2. Every tenant-less business ``Role`` row (NULL ``tenant_id``) is
   re-homed into the root tenant together with its policy linkage:
   ``PolicyStatement`` rows are linked by ``role_id`` (actions/resources/
   tag-conditions ride the statement FK) and get their own ``tenant_id``
   stamped to root.  The global ``Permission`` catalogue is untouched.
3. A root-scoped ``Platform Admin`` role (``platform::*`` wildcard
   policy) is seeded and assigned to users holding an ACTIVE
   ``platform_admin`` membership in the root tenant — required by
   permission containment (membership alone no longer unlocks the
   platform console).

Reversible: the downgrade restores the legacy identity (``System`` /
``system``), deletes the seeded ``Platform Admin`` role and moves the
re-homed legacy roles (system-flagged roles whose names are not one of
the four default tenant presets) back to NULL ``tenant_id``.
"""
from alembic import op
import sqlalchemy as sa

revision = "b8e4f2a6c9d1"
down_revision = "a1f2c3d4e5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1a. Ensure a root tenant row exists (fresh deployments).
    conn.execute(sa.text(
        """
        INSERT INTO tenants (id, name, slug, status, admin_contact_role,
                             is_system_tenant, is_onboarded, created_at, updated_at)
        SELECT gen_random_uuid(), 'Root', 'root', 'active', 'platform_admin',
               true, true, now(), now()
        WHERE NOT EXISTS (SELECT 1 FROM tenants WHERE is_system_tenant = true)
        """
    ))

    # 1b. Rename the root tenant in place.  Guard: the canonical slug must
    # not be held by a DIFFERENT tenant (fail loudly — manual fix needed).
    conflict = conn.execute(sa.text(
        """
        SELECT name, id FROM tenants
        WHERE slug = 'root' AND is_system_tenant = false
        """
    )).first()
    if conflict is not None:
        raise RuntimeError(
            f"Slug 'root' is reserved for the root tenant but is held by "
            f"tenant '{conflict[0]}' (id={conflict[1]}); rename it first."
        )
    conn.execute(sa.text(
        "UPDATE tenants SET name = 'Root', slug = 'root', updated_at = now() "
        "WHERE is_system_tenant = true"
    ))

    # 2a. Stamp tenant-less policy statements to root (by role linkage),
    # BEFORE the roles themselves move (the JOIN needs NULL roles).
    conn.execute(sa.text(
        """
        UPDATE policy_statements ps
        SET tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true)
        WHERE ps.role_id IN (SELECT id FROM roles WHERE tenant_id IS NULL)
        """
    ))
    conn.execute(sa.text(
        """
        UPDATE policy_resources pr
        SET tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true)
        WHERE pr.policy_statement_id IN (SELECT id FROM policy_statements WHERE tenant_id IS NULL)
        """
    ))
    conn.execute(sa.text(
        """
        UPDATE policy_actions pa
        SET tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true)
        WHERE pa.policy_statement_id IN (SELECT id FROM policy_statements WHERE tenant_id IS NULL)
        """
    ))
    # 2b. Stamp orphaned child rows whose parent statement is already
    # root-scoped but whose own tenant reference is still NULL (e.g. a
    # partially-applied earlier state), then re-home the roles.
    conn.execute(sa.text(
        """
        UPDATE policy_actions
        SET tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true)
        WHERE tenant_id IS NULL
          AND policy_statement_id IN (
              SELECT id FROM policy_statements
              WHERE tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true))
        """
    ))
    conn.execute(sa.text(
        """
        UPDATE policy_resources
        SET tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true)
        WHERE tenant_id IS NULL
          AND policy_statement_id IN (
              SELECT id FROM policy_statements
              WHERE tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true))
        """
    ))
    conn.execute(sa.text(
        "UPDATE roles SET tenant_id = (SELECT id FROM tenants "
        "WHERE is_system_tenant = true) WHERE tenant_id IS NULL"
    ))

    # 3a. Seed the root Platform Admin role (platform::* wildcard policy).
    conn.execute(sa.text(
        """
        INSERT INTO roles (id, name, description, role_type, is_system,
                           is_active, tenant_id, created_at, updated_at)
        SELECT gen_random_uuid(), 'Platform Admin',
               'Platform administration (root tenant) — platform modules only; '
               'grants nothing inside any customer tenant.',
               'user', true, true,
               (SELECT id FROM tenants WHERE is_system_tenant = true),
               now(), now()
        WHERE NOT EXISTS (
            SELECT 1 FROM roles
            WHERE name = 'Platform Admin' AND is_system = true
              AND tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true)
        )
        """
    ))
    conn.execute(sa.text(
        """
        INSERT INTO policy_statements (id, tenant_id, role_id, effect, module, created_at)
        SELECT gen_random_uuid(),
               (SELECT id FROM tenants WHERE is_system_tenant = true),
               r.id, 'allow', 'platform::*', now()
        FROM roles r
        WHERE r.name = 'Platform Admin' AND r.is_system = true
          AND r.tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true)
          AND NOT EXISTS (
              SELECT 1 FROM policy_statements ps
              WHERE ps.role_id = r.id AND ps.module = 'platform::*'
                AND ps.effect = 'allow'
          )
        """
    ))
    conn.execute(sa.text(
        """
        INSERT INTO policy_actions (id, tenant_id, policy_statement_id, action)
        SELECT gen_random_uuid(),
               (SELECT id FROM tenants WHERE is_system_tenant = true),
               ps.id, '*'
        FROM policy_statements ps
        WHERE ps.module = 'platform::*' AND ps.effect = 'allow'
          AND NOT EXISTS (
              SELECT 1 FROM policy_actions pa WHERE pa.policy_statement_id = ps.id
          )
        """
    ))
    conn.execute(sa.text(
        """
        INSERT INTO policy_resources (id, tenant_id, policy_statement_id, resource_type, resource_id)
        SELECT gen_random_uuid(),
               (SELECT id FROM tenants WHERE is_system_tenant = true),
               ps.id, '*', '*'
        FROM policy_statements ps
        WHERE ps.module = 'platform::*' AND ps.effect = 'allow'
          AND NOT EXISTS (
              SELECT 1 FROM policy_resources pr WHERE pr.policy_statement_id = ps.id
          )
        """
    ))

    # 2c. Housekeeping: drop orphaned NULL-tenant policy children whose
    # parent statement no longer exists (e.g. interleaved with a running
    # server's seeding sweep).  Idempotent.
    conn.execute(sa.text(
        "DELETE FROM policy_actions WHERE tenant_id IS NULL AND "
        "policy_statement_id NOT IN (SELECT id FROM policy_statements)"
    ))
    conn.execute(sa.text(
        "DELETE FROM policy_resources WHERE tenant_id IS NULL AND "
        "policy_statement_id NOT IN (SELECT id FROM policy_statements)"
    ))

    # 3b. Assign the role to ACTIVE platform_admin members of the root
    # tenant who lack it.
    conn.execute(sa.text(
        """
        INSERT INTO user_roles (user_id, role_id, assigned_at)
        SELECT m.user_id, r.id, now()
        FROM tenant_user_memberships m
        JOIN roles r
          ON r.name = 'Platform Admin' AND r.is_system = true
         AND r.tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true)
        WHERE m.tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true)
          AND m.status = 'active' AND m.tenant_role = 'platform_admin'
          AND NOT EXISTS (
              SELECT 1 FROM user_roles ur
              WHERE ur.user_id = m.user_id AND ur.role_id = r.id
          )
        """
    ))


def downgrade() -> None:
    conn = op.get_bind()

    # Undo 3: delete the seeded Platform Admin role and its assignments.
    conn.execute(sa.text(
        """
        DELETE FROM policy_actions WHERE policy_statement_id IN (
            SELECT ps.id FROM policy_statements ps JOIN roles r ON r.id = ps.role_id
            WHERE r.name = 'Platform Admin' AND r.is_system = true
              AND r.tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true))
        """
    ))
    conn.execute(sa.text(
        """
        DELETE FROM policy_resources WHERE policy_statement_id IN (
            SELECT ps.id FROM policy_statements ps JOIN roles r ON r.id = ps.role_id
            WHERE r.name = 'Platform Admin' AND r.is_system = true
              AND r.tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true))
        """
    ))
    conn.execute(sa.text(
        """
        DELETE FROM policy_statements WHERE role_id IN (
            SELECT id FROM roles
            WHERE name = 'Platform Admin' AND is_system = true
              AND tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true))
        """
    ))
    conn.execute(sa.text(
        """
        DELETE FROM user_roles WHERE role_id IN (
            SELECT id FROM roles
            WHERE name = 'Platform Admin' AND is_system = true
              AND tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true))
        """
    ))
    conn.execute(sa.text(
        """
        DELETE FROM roles
        WHERE name = 'Platform Admin' AND is_system = true
          AND tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true)
        """
    ))

    # Undo 2: move re-homed LEGACY roles back to NULL tenant_id.  The four
    # seeded default preset names are native tenant roles and stay.
    conn.execute(sa.text(
        """
        UPDATE policy_resources
        SET tenant_id = NULL
        WHERE tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true)
          AND policy_statement_id IN (
              SELECT ps.id FROM policy_statements ps
              JOIN roles r ON r.id = ps.role_id
              WHERE r.tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true)
                AND r.is_system = true
                AND r.name NOT IN ('Tenant System Admin', 'Agent Manager',
                                   'Agent Executor', 'Agent Viewer'))
        """
    ))
    conn.execute(sa.text(
        """
        UPDATE policy_actions
        SET tenant_id = NULL
        WHERE tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true)
          AND policy_statement_id IN (
              SELECT ps.id FROM policy_statements ps
              JOIN roles r ON r.id = ps.role_id
              WHERE r.tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true)
                AND r.is_system = true
                AND r.name NOT IN ('Tenant System Admin', 'Agent Manager',
                                   'Agent Executor', 'Agent Viewer'))
        """
    ))
    conn.execute(sa.text(
        """
        UPDATE policy_statements ps
        SET tenant_id = NULL
        FROM roles r
        WHERE ps.role_id = r.id
          AND r.tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true)
          AND r.is_system = true
          AND r.name NOT IN ('Tenant System Admin', 'Agent Manager',
                             'Agent Executor', 'Agent Viewer')
        """
    ))
    conn.execute(sa.text(
        """
        UPDATE roles SET tenant_id = NULL
        WHERE tenant_id = (SELECT id FROM tenants WHERE is_system_tenant = true)
          AND is_system = true
          AND name NOT IN ('Tenant System Admin', 'Agent Manager',
                           'Agent Executor', 'Agent Viewer')
        """
    ))

    # Undo 1: restore the legacy identity.
    conn.execute(sa.text(
        "UPDATE tenants SET name = 'System', slug = 'system', updated_at = now() "
        "WHERE is_system_tenant = true"
    ))
