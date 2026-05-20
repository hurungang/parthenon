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
| `5c2910c238a8` | `5c2910c238a8_add_passthrough_to_mcp_session_auth_type.py` | Passthrough Sessions — adds `passthrough` value to the `mcp_session_auth_type_enum` PostgreSQL enum type | `mcp_session_auth_type_enum` (enum value added) | — |
| `385c4ae051f6` | `385c4ae051f6_agent_runtime_security_segregation.py` | Agent Runtime Security Segregation — introduces certificate authority infrastructure, instance certificate management, certificate revocation, and encrypted token refresh tracking; adds nullable columns to `agent_identities` and copies existing `refresh_token` values to `encrypted_refresh_token` via data migration | `agent_instance_certificates`, `certificate_revocation_entries`, `token_refresh_logs`, `certificate_validation_logs` (added); `agent_identities` (`encrypted_refresh_token`, `last_token_refresh_at`, `token_status` columns added) | 2026-05-13 |

---

## Notes

- Migrations `001_baseline` through `d736a85c26fd` are **purely additive** — no existing table or column was dropped or renamed.
- Migration `df2225d787c5` is the first **destructive migration**: it removes columns from `agent_type` (`sop_id`, `identity_subject`, `system_prompt`, `mode`) and drops the `agent_skill_assignment` table. Complete the AgentType data backfill (Step 2 of the change deployment doc) before applying to production. Reverting this migration via `alembic downgrade -1` will drop all new tables and data.
- The `d736a85c26fd` migration must be verified to contain no `op.drop_table` or `op.drop_column` calls before applying to production. See `docs/changes/user-permission-management/deployment.md` Step 1 for the full verification checklist.
- Migration `5c2910c238a8` adds a PostgreSQL enum value (`passthrough`) using `ALTER TYPE … ADD VALUE`. PostgreSQL does not support removing enum values, so the `downgrade()` function for this migration is a **no-op** — rolling back Alembic to the prior revision (`fcbe5b250e08`) will not remove the `passthrough` value from the `mcp_session_auth_type_enum` type. This is safe: the previous code ignores unknown enum values at the application layer. See [rollback.md](rollback.md) Step 3 for the full implication.
- For new environment bootstraps, run `alembic upgrade head` once after the database is initialised (see [first-time-deployment.md](first-time-deployment.md) Step 3). The head revision is automatically determined from the migration chain.
- Migration `385c4ae051f6` is **additive with a safe data migration**: new tables are created, all new columns on `agent_identities` are nullable, and existing `refresh_token` values are copied to `encrypted_refresh_token` during upgrade. Old code that does not reference the new columns continues to work. Rolling back via `alembic downgrade -1` drops all new tables and removes the three `agent_identities` columns; the copied data in `encrypted_refresh_token` is lost. The Control Center will re-initialise the Certificate Authority on next startup if the tables are absent.
