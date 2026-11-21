# Test Plan: CC Assistant Management Tool Coverage

## Test Strategy

This change modifies the Control Center internal management-tool handlers, the system tool registry (typed per-family parameter schemas), and serializers — with no frontend changes, no schema changes (`has_db_changes: false`), and no changes to CH routing or the confirm-before-write flow. Testing is therefore backend-heavy:

- **Backend unit tests** — registry invariants (typed schemas per family, no-delete verb, stable UUIDs, unchanged parity map), validator/normalizer behavior (enum coercion, id-or-name resolution, required/unknown-field rules, structured error payloads), serializer parity and credential-non-exposure.
- **Backend API/integration tests** — per-family field parity through `POST /internal/management-tools/{tool_name}` (create/update/list/get), structured validation errors, permission parity (positive + negative), duplicate-name 409, additive-merge binding semantics, resolve-before-write / no-partial-write.
- **Backend E2E** — one assistant-conversation scenario: full agent-type update via preview → `human_intervene` approval → CH routing → persisted record; rejection/timeout → no write.
- **E2E (Playwright)** — a mocked WS/API-layer UI-journey variant of the agent-type update scenario (`e2e/tests/control-center-chatbot-agent-type-update.spec.ts`, clearly labeled as mocked): canonical preview rendered in the conversation history → approval sent from the intervention inbox → Agent Types list reflects the updated persisted state. The web UI forms remain the parity baseline; the UI itself is unchanged.
- **Manual/E2E regression** — existing assistant capabilities for already-supported families (skill, SOP, schedule, model config, MCP server, data type) continue working unchanged.

**Database migration checklist does not apply** — `has_db_changes: false`; no Alembic migrations, no schema verification tests.

## Coverage Areas

1. **Field parity per resource family** (the core of this epic): for each of the 9 families, every field editable in the corresponding web UI create/update form must be accepted through the tool path and persisted. Priority families with known gaps:
   - `agent_type` — `identity_id`, `role_id`, `input_type`, `input_schema`, `output_type`, `output_schema`, `output_data_type_id`, all guardrail fields; `skill_ids`/`sop_ids` additive merge.
   - `agent_identity` — `status` (create + update), `role_ids` (update, additive merge).
   - `agent_role` — `description`, `skill_ids`/`sop_ids` grants.
   - `model_config` — `name`/`display_name`, `provider_type`, `api_key` (write-accepted, encrypted, never echoed), `enabled_models`, `api_base_url`, `is_disabled`.
   - `schedule` — update-time `cron_expression`, `payload`, `target_type`, `target_id` with scheduler re-registration.
   - `data_type` — update-time `description`; typed `fields`; immutable slug.
   - `mcp_server` — unchanged field set, now typed; per-tenant slug uniqueness.
   - `skill` / `sop` — full field sets typed; zero-binding warning preserved.
   - Critical because today's handlers silently drop or reject UI-supported fields, producing capability dead ends.
2. **Structured validation errors**: missing/invalid args return structured payloads (error code, per-field problems, remedy hint with valid enum values / resolution guidance) the assistant can self-correct from — including the known "slug is required" failure mode and unknown-field rejection.
3. **Permission parity**: every tool call enforces the same `resource_type:action` pair as the equivalent REST endpoint, including negative cases (user lacking permission → clear 403 denial; `integration::control_center` visibility gating).
4. **Confirm-before-write**: canonical preview expresses ALL changed fields (including newly supported ones such as `role_id`, `input_type`, `output_type`, guardrails); approval writes; rejection or timeout writes nothing.
5. **No-delete invariant**: no delete verb exists anywhere in the toolset, registry, or seeder entries.
6. **Read parity**: list/get serializers return UI-detail-level data (guardrails, role assignments, grant lists, field definitions, output data type name) and never echo credentials, tokens, or API keys.
7. **Invariant preservation**: stable tool UUIDs, stable `mcp_hub_id`s, parity map unchanged, seeder-owned `cc` entity, service segregation (only CC writes DB), tenant scoping of all id-or-name resolution.
8. **Regression**: existing assistant capabilities for previously supported families work unchanged; REST API behavior unchanged.

## Critical Scenarios

### Field Parity — agent_type
- **WHEN** an assistant `update_agent_type` call supplies `role_id` (as id or as name), `input_type`, `output_type`, `output_data_type_id`, and guardrail fields, with approval granted
  **THEN** all fields are persisted exactly as approved; the serialized result reflects the new values; no "missing capability" error occurs.
- **WHEN** an assistant sets `output_data_type_id` on an agent type whose `input_type` is `conversation`
  **THEN** a structured validation error identifies the conflict and states the remedy; nothing is written.
- **WHEN** `update_agent_type` supplies `skill_ids` including already-bound skills
  **THEN** the merge is additive and idempotent; existing bindings are never removed.

### Field Parity — agent_identity
- **WHEN** an assistant updates an agent identity's `role_ids` (mix of ids and names) with approval
  **THEN** assignments change exactly as approved; the serialized identity lists the new role assignments.
- **WHEN** an assistant sets `status` on create or update
  **THEN** the enum value is coerced and persisted; an invalid value yields a structured error listing valid values.

### Field Parity — other families
- **WHEN** an assistant creates a model config with `provider_type` and `api_key`
  **THEN** the config is created with the credential stored encrypted and the key value absent from the tool result and all serializers.
- **WHEN** an assistant updates a schedule's `cron_expression` / `target_id`
  **THEN** the change persists and the scheduler re-registers the job with the new definition.
- **WHEN** an assistant updates a data type's `fields` and `description` but also supplies a changed `slug`
  **THEN** `fields`/`description` are validated and applied; the slug immutability attempt produces a structured error.
- **WHEN** an assistant creates an MCP server without a `slug`
  **THEN** the structured error explicitly states slug is required with guidance (the known failure mode is now self-correctable); with a duplicate slug, a structured 409 is returned.
- **WHEN** an assistant updates a role's `description` and grants `skill_ids`/`sop_ids`
  **THEN** both are applied additively with resolve-before-write; unknown skill name yields a structured error and no partial write.

### Structured Validation Errors
- **WHEN** any create/update call omits a required field
  **THEN** the response is a structured payload (error code, field, problem, remedy), not a bare 400 string.
- **WHEN** a call supplies an unknown field not in the family schema
  **THEN** a structured error names the unknown field; nothing is written.
- **WHEN** a call supplies an unresolvable id-or-name FK value
  **THEN** the structured error identifies the field and gives resolution guidance; no partial write occurs (resolve-before-write).
- **WHEN** the assistant retries after receiving a structured validation error with corrected values
  **THEN** the operation completes without user intervention.

### Permission Parity
- **WHEN** a permitted user invokes any management tool
  **THEN** the same `(resource_type, action)` pair is enforced as the equivalent REST endpoint and the operation proceeds.
- **WHEN** a user lacking `manage` permission on a family invokes its create/update tool
  **THEN** a clear structured denial (403) is returned; the assistant cannot perform the write and nothing is persisted.
- **WHEN** a user lacks `integration::control_center` visibility
  **THEN** cc-entity tools are not in their permitted set at `/resolve`.

### Confirm-Before-Write
- **WHEN** an assistant proposes an update touching newly supported fields (`role_id`, `input_type`, `output_type`, guardrails)
  **THEN** the canonical preview lists ALL changed fields with old → new values.
- **WHEN** the user rejects the preview, or the approval intervention times out
  **THEN** nothing is written; the record retains its prior state.
- **WHEN** the user approves
  **THEN** the write executes exactly once with the approved values.

### No-Delete Invariant
- **WHEN** the registry, seeder entries, and routing map are inspected
  **THEN** no delete verb exists for any family; binding/grant operations are additive-merge only and never remove rows.

### Assistant End-to-End Scenario
- **WHEN** an administrator asks the assistant in conversation to update an agent type's role assignment and input/output configuration, and approves the preview
  **THEN** the full flow completes (preview → approval → CH routing → CC handler → persisted record) with no capability gap and no "finish in the UI" fallback; the assistant confirms the applied changes using serialized post-write data.
- **WHEN** the same conversation includes an initially invalid update attempt
  **THEN** the assistant self-corrects from the structured error and completes the operation without human troubleshooting.

## Edge Cases & Risks

- **Enum/contract drift** between tool-path coercion and REST Pydantic schemas — a field valid via REST but rejected via tool (or vice versa) breaks parity; parity tests must compare against `backend/app/schemas/` baselines.
- **Guardrail contract complexity** — nine guardrail fields with cross-field rules (mirroring `_validate_guardrail_contract`); partial guardrail updates must not accidentally reset unspecified fields to defaults.
- **Additive-merge confusion** — users may expect `skill_ids` to be a full replacement; tests must document and assert additive semantics and that existing rows are never removed.
- **Idempotent re-binding** — re-approving the same binding set must not duplicate rows or error.
- **Conversational agent type conflicts** — `output_data_type_id` + `input_type=conversation` mutual exclusion must be enforced identically to REST.
- **Credential leakage** — serializers and error payloads must never echo `api_key`, tokens, or decrypted credentials, even in validation errors.
- **Scheduler re-registration failure** — a schedule update that persists but fails APScheduler re-registration leaves inconsistent state; test failure behavior.
- **Tenant scoping** — id-or-name resolution must be tenant-scoped; a name existing in another tenant must not resolve.
- **Stable identifiers** — accidental UUID or parity-map changes break deployed tool grants; registry invariant tests must lock these.
- **Flakiness risk in the E2E conversation test** — depends on LLM-mock layer determinism and `human_intervene` approval timing; use the established mock harness.
- **Regression risk** — schema shape changes (free-form `data` → typed) could break existing skill/SOP/schedule flows; regression suite covers all previously supported families.

## Acceptance Criteria Checklist

Maps to PRD acceptance criteria:

- [x] AC1: Agent type role + input/output config update applies fully via conversation; no missing-capability report (E2E scenario test).
- [x] AC2: Agent identity role assignments change exactly as approved via conversation.
- [x] AC3: For every assistant-managed family, every UI-editable field can be set through the tool path and persists (per-family parity tests).
- [x] AC4: List/get tool results carry UI-detail-level information; no credentials/tokens serialized.
- [x] AC5: Canonical preview shows all changed fields (old → new); rejection/timeout writes nothing.
- [x] AC6: No deletion capability exists in any management tool (registry/seeder invariant tests).
- [x] AC7: Invalid requests return specific, actionable structured errors; retry with corrected input succeeds without user intervention.
- [x] AC8: Operations run under the requesting user's permissions; unauthorized users receive clear denials on both positive and negative parity cases.
- [x] AC9: Assistant-performed writes appear in audit trails identically to web UI operations (audit parity asserted in integration tests).
- [x] AC10: Regression — existing capabilities (skill, SOP, schedule, model config, MCP server, data type) continue working unchanged.

## Test File References

Existing related tests (to extend/regression-run):

- `backend/tests/unit/test_management_mcp_tools.py` — management tool registry behavior
- `backend/tests/unit/test_management_tool_permission_parity.py` — permission parity pairs
- `backend/tests/unit/test_assistant_seeder.py` — cc entity/tool seeding invariants
- `backend/tests/unit/test_assistant_knowledge.py` — assistant knowledge corpus
- `backend/tests/unit/test_cc_tool_registry_bridge.py` / `test_tool_registry_bridge.py` — registry bridge
- `backend/tests/unit/test_skill_tool_bindings_management.py` — skill tool bindings
- `backend/tests/api/test_agents_api.py`, `test_agent_type_bindings_api.py`, `test_model_configs_api.py` — REST parity baselines
- `backend/tests/test_data_types_api.py`, `test_scheduling.py` — REST baselines for data types/schedules
- `backend/tests/e2e/test_agent_execution_e2e.py` — E2E harness/pattern reference

New test files from the implementation plan (actual locations — Phase 5):

- `backend/tests/unit/test_management_payload_validator.py` — task 5.1: validator/normalizer unit tests (16 tests): enum/bool/int coercion, slug pattern, required/unknown fields, structured error shape, and tenant-scoped id-or-name FK resolution (hit by name/id, miss → actionable 404, cross-tenant name → 404, resolve-before-write list semantics)
- `backend/tests/integration/test_management_tool_full_field_parity.py` — task 5.2: per-family field parity + structured errors + permission denial + sensitive-field non-echo + additive-merge semantics (24 tests, all 9 families)
- `backend/tests/unit/test_management_mcp_tools.py` — task 5.3: registry invariants — typed per-family schemas, frozen parity map, stable UUIDs, no-delete verb, enum mirroring, additive-merge documentation, bounded schema size (22 tests)
- `backend/tests/e2e/test_assistant_agent_type_update_e2e.py` — task 5.5 (API-level integration variant): assistant conversation loop — canonical old → new preview → `human_intervene` approval gate → `cc____update_agent_type` dispatched through the REAL CH `route_tool_call` → in-process Control Center handler → persisted record verified; rejection negative variant (zero dispatch, record untouched)
- `e2e/tests/control-center-chatbot-agent-type-update.spec.ts` — task 5.5 (UI journey variant, MOCKED WS/API layer, clearly labeled): canonical preview rendered in conversation history → approval sent from the intervention inbox (`approval_value: true` asserted) → Agent Types list reflects the updated persisted state
