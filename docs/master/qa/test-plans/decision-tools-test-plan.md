# Decision Tools Test Plan

## What to Test

- Decision tool data types resolve by strict `(tenant, name)` matching — no `tenant_id IS NULL OR tenant_id = own` fallback remains
- Cross-tenant name collisions never route a decision-tool query to another tenant's data type
- Full decision-tool journey: query through Communication Hub to Control Center with the bound tenant

## strict-tenant-isolation Update (2026-10)

Change `strict-tenant-isolation` made decision-tool data-type resolution strict: legacy rows adopted into the root tenant (migration `b8c9d0e1f2a3`), `tenant_id` NOT NULL, and lookups match the exact session tenant only.

Test files added (verified present):

- `backend/tests/integration/test_decision_tool_full_journey.py` — end-to-end decision-tool journey with tenant-bound resolution through the full service chain
- `backend/tests/integration/test_system_tools_tenant_containment.py` — decision-tool strict `(tenant, name)` matching: data types with identical names in two tenants resolve within the calling tenant only; fail-closed scope miss

E2E: N/A — backend-only change, no UI changes.

## Related

Provider/model management and decision-execution governance added by `decision-model-providers` are covered in `decision-model-providers-test-plan.md`.
