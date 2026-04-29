# Database Migrations — Reference Log

Canonical record of all Alembic migration revisions applied to the Parthenon database. Update this document whenever a migration is promoted to production.

Migration scripts live in `backend/alembic/versions/`. Apply them with `alembic upgrade head` from the `backend/` directory. Verify the active revision with `alembic current` or by querying the `alembic_version` table.

---

## Migration History

| Revision | File | Description | Tables Added / Modified | Production Date |
|----------|------|-------------|------------------------|-----------------|
| `001_baseline` | `001_baseline.py` | Baseline schema — all platform tables as of initial release | All initial platform tables | — |
| `002_identity_bootstrap_models` | `002_identity_bootstrap_models.py` | Keycloak identity bootstrap — `IdentityProviderConfig`, `IdentityProviderSetupState`, `idp_subject` column on `User` | `identity_provider_config`, `identity_provider_setup_state`; `User.idp_subject` column | — |
| `d736a85c26fd` | `d736a85c26fd_user_permission_management.py` | User permission management — introduces the Permission Engine, Tag Registry, User Cache, Group Claim Mapper, and Access Request Service tables | `tag_definitions`, `tag_values`, `roles`, `policy_statements`, `policy_actions`, `policy_resources`, `policy_tag_conditions`, `platform_users`, `user_roles`, `groups`, `group_roles`, `user_groups`, `access_requests` | 2026-04-25 |

---

## Notes

- All migrations to date are **purely additive** — no existing table or column has been dropped or renamed.
- The `d736a85c26fd` migration must be verified to contain no `op.drop_table` or `op.drop_column` calls before applying to production. See `docs/changes/user-permission-management/deployment.md` Step 1 for the full verification checklist.
- For new environment bootstraps, run `alembic upgrade head` once after the database is initialised (see [first-time-deployment.md](first-time-deployment.md) Step 3). The head revision is automatically determined from the migration chain.
