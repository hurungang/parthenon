# Decision Tools Test Plan

## system-one-decision-skills Update

Change `system-one-decision-skills` introduced decision tools (renamed from decision skills): TypeSafe provider config with encrypted keys, per-tenant decision tool CRUD with auto-generated descriptions, execution engine with confidence gating (act/confirm/escalate), MCP exposure with `decision:` prefix, and a skills revert (no decision skill type).

### Coverage Areas

- Provider config CRUD + encrypted key storage (ciphertext at rest, write-only key, `system::system_one` permission enforcement, preset non-editable base URL, test-connection endpoint with no key material in responses)
- Decision tool CRUD + per-tenant name uniqueness (same name in two tenants / duplicate within one tenant rejected)
- Auto-generated tool description (derived from AgentDataType definitions, regenerated on update)
- Per-type question authoring validation (Choice/Score/Noul), authoring gate (no enabled model → blocked)
- Execution engine keyed to tools: state preset, single dispatch, typed answers, persisted `DecisionExecutionResult`, tenant isolation of tools and results, confidence gate boundaries
- MCP bridge: `decision:`-prefixed tools in `tools/list` and `tools/call` routing; reserved slug "decision" rejected with 409
- AI generate endpoint + state placeholder auto-detection (backtick paths)
- Skills revert regression: no `skill_type` column, original editor/executor restored

### Test Files (verified present)

Backend (`backend/tests/`):

- `backend/tests/integration/test_system_one_decision_tools.py` — migration verification, provider encryption-at-rest, tool CRUD + tenant uniqueness, execution + result persistence, tenant isolation, permissions, MCP bridge
- `backend/tests/integration/test_system_one_provider_config.py` — provider config routes, status, test-connection, preset base URL
- `backend/tests/integration/test_skills_regression.py` — skills revert regression
- `backend/tests/integration/test_decision_tool_data_types.py` — AgentDataType references, deletion blocking, description derivation
- `backend/tests/integration/test_decision_tool_ai_generate.py` — AI generate endpoint + `extract_state_placeholders` units
- `backend/tests/integration/test_reserved_slugs.py` — reserved "decision"/"system" slugs, virtual decision server, `decision____<name>` MCP listing
- `backend/tests/unit/test_decision_engine.py` — confidence gate boundaries, state preset mapping, normalization, description generation

Frontend (`frontend/src/__tests__/`):

- `frontend/src/__tests__/SystemOneProviderConfigPage.test.tsx` — write-only key, read-only preset base URL, Test connection button
- `frontend/src/__tests__/DecisionToolsPage.test.tsx` — tool list, configured-model gate, CRUD flows
- `frontend/src/__tests__/DecisionToolForm.test.tsx` — per-type question builder, field order, View dialogs, mapping auto-populate, placeholder auto-detect, AI generate flow
- `frontend/src/__tests__/DecisionToolQuestionEditor.test.tsx` — per-type editing validation
- `frontend/src/__tests__/DecisionResultView.test.tsx` — answers/probabilities/confidence/gate rendering
- `frontend/src/__tests__/decisionStatePaths.test.ts` — placeholder detection + `decision____` naming
- `frontend/src/__tests__/SkillEditor.test.tsx` — regression: original editor restored; decision tools in skill-authoring tool registry

E2E (`e2e/tests/`):

- `e2e/tests/system-one-decision-tools.spec.ts` — mocked authoring/execution/provider journeys incl. round-2 form journey and Test connection
- `e2e/tests/system-one-real-backend.spec.ts` — real-backend: two tenants, identical tool names, real execution + DB persistence, tenant isolation, MCP listing, reserved slug 409, unauthenticated denial

Manual (per change test plan): live TypeSafe API round-trip, MCP `tools/list` per tenant, i18n coverage.

## strict-tenant-isolation Update (2026-10)

Decision-tool data types resolve by strict `(tenant, name)` matching — no `tenant_id IS NULL OR tenant_id = own` fallback remains; cross-tenant name collisions never route a decision-tool query to another tenant's data type; full journey: query through Communication Hub to Control Center with the bound tenant.

Change `strict-tenant-isolation` made decision-tool data-type resolution strict: legacy rows adopted into the root tenant (migration `b8c9d0e1f2a3`), `tenant_id` NOT NULL, and lookups match the exact session tenant only.

Test files added (verified present):

- `backend/tests/integration/test_decision_tool_full_journey.py` — end-to-end decision-tool journey with tenant-bound resolution through the full service chain
- `backend/tests/integration/test_system_tools_tenant_containment.py` — decision-tool strict `(tenant, name)` matching: data types with identical names in two tenants resolve within the calling tenant only; fail-closed scope miss

E2E: N/A — backend-only change, no UI changes.

## Related

Provider/model management and decision-execution governance added by `decision-model-providers` are covered in `decision-model-providers-test-plan.md`.
