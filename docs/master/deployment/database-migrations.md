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
| `df2225d787c5` | `df2225d787c5_agent_runtime_with_gateway.py` | Agent Runtime with Gateway — creates `agent_role`, `agent_role_sop`, `agent_role_skill`, `agent_identity`, and `agent_session` tables; extends `agent_type` with `identity_id`, `role_id`, `system_instruction`, `input_type`, `input_schema`, `output_type`, `output_schema` columns; removes `sop_id`, `identity_subject`, `system_prompt`, and `mode` columns from `agent_type`; drops the `agent_skill_assignment` table | `agent_role`, `agent_role_sop`, `agent_role_skill`, `agent_identity`, `agent_session` (added); `agent_type` (columns added and removed); `agent_skill_assignment` (dropped) | — |

---

## Notes

- Migrations `001_baseline` through `d736a85c26fd` are **purely additive** — no existing table or column was dropped or renamed.
- Migration `df2225d787c5` is the first **destructive migration**: it removes columns from `agent_type` (`sop_id`, `identity_subject`, `system_prompt`, `mode`) and drops the `agent_skill_assignment` table. Complete the AgentType data backfill (Step 2 of the change deployment doc) before applying to production. Reverting this migration via `alembic downgrade -1` will drop all new tables and data.
- The `d736a85c26fd` migration must be verified to contain no `op.drop_table` or `op.drop_column` calls before applying to production. See `docs/changes/user-permission-management/deployment.md` Step 1 for the full verification checklist.
- For new environment bootstraps, run `alembic upgrade head` once after the database is initialised (see [first-time-deployment.md](first-time-deployment.md) Step 3). The head revision is automatically determined from the migration chain.
