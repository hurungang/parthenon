## Deployment Notes: agent-type-multi-sop-binding

## Environment Variables

No new environment variables required.

## Infrastructure Changes

No infrastructure changes. Existing database and services unchanged.

## Migration Steps

1. **Backend deployment**: Deploy the updated backend code first (new SQLAlchemy models, API endpoints, service layer).
2. **Database migration**: Run `alembic upgrade head` to apply the schema change (create two new tables, remove `primary_sop_id`, migrate existing data).
3. **Verify migration**: Run `alembic current` and confirm the new revision is active. Query `agent_type_sop_bindings` and `agent_type_skill_bindings` to confirm tables exist.
4. **Frontend deployment**: Deploy the updated frontend (new binding list UI component).
5. **Post-deploy verification**: Create a test AgentType with bindings via the UI, verify save and reload round-trips correctly.

## Ordering

Deploy backend → run migration → verify → deploy frontend → verify

## Rollback Procedure

1. If the rollback is needed before any new bindings are created:
   - `alembic downgrade -1` to revert the schema change
   - Restore the previous backend and frontend builds

2. If new bindings have been created:
   - The downgrade migration must create `primary_sop_id` from the first `agent_type_sop_bindings` row (order = 0) per AgentType
   - New `agent_type_skill_bindings` data is lost on rollback (rollback warning)
   - Verify: all AgentTypes that had primary_sop_id before the upgrade still have it after rollback

## Master Deployment Update Instructions

Update `docs/master/deployment/database-migrations.md`:
- Document the migration for this change: "Replace primary_sop_id with multi-SOP/skill bindings"
- Include the migration ordering and rollback considerations above

No changes needed to `docs/master/deployment/environment-variables.md`, `docs/master/deployment/services.md`, `docs/master/deployment/configuration-files.md`, or `docs/master/deployment/first-time-deployment.md`.
