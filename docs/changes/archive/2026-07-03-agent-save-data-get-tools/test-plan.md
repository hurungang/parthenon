# Test Plan: agent-save-data-get-tools

## 1. Test Strategy

- Unit tests: validate tool naming, schema registration, filter validation logic, and LangChain tool binding changes (`save_result` removed, `save_data`/`get_data`/`get_output` added).
- Integration tests: validate end-to-end backend flow across Agent Runtime client -> Control Center internal APIs -> services -> PostgreSQL persistence/query.
- E2E tests: validate user-visible system-tool behavior in agent configuration/execution paths and output-history retrieval behavior from UI flows.
- Manual validation: perform targeted smoke checks on running stack to confirm no regression in final session output flow (`submit_result`) and no direct DB access from Agent Runtime.
- Security/architecture validation: ensure calls use internal service path with certificate enforcement and preserve top-priority segregation rule (Agent Runtime never accesses DB directly).

## 2. Coverage Areas

- Tool rename and retirement: `save_result` removed from active system tool path, `save_data` present and callable.
- New tool registration and schemas: `get_data` and `get_output` are discoverable in context/tool definitions.
- Persistence correctness: `save_data` stores multiple records per session with required metadata (`data_name`, `data_value`, `timestamp`, `agent_type`, `session_id`).
- Query correctness for saved data: `get_data` returns records matching filters (`data_name`, `agent_type`, `session_id`) with pagination behavior.
- Guardrail enforcement: `get_data` rejects unfiltered requests (at least one filter required).
- Output history query correctness: `get_output` returns `AgentOutput` records filtered by `agent_type`, `session_id`, and date range.
- Regression safety: existing final output completion path (`submit_result`) remains unchanged and functional.
- Inter-service routing integrity: Agent Runtime -> Control Center internal API path is used for all three tools.

## 3. Critical Scenarios

- WHEN an agent session invokes `save_data` multiple times with different `data_name` values THEN each call creates a distinct persisted record for the same session.
- WHEN `save_data` is called with valid `agent_type` and `session_id` THEN stored metadata includes those identifiers and a server-generated timestamp.
- WHEN `get_data` is called with `data_name` only THEN only records with that exact name are returned.
- WHEN `get_data` is called with `agent_type` only THEN records are constrained to that agent type across sessions.
- WHEN `get_data` is called with `session_id` only THEN records are constrained to that session.
- WHEN `get_data` is called with combined filters (`data_name` + `agent_type` + `session_id`) THEN results satisfy all provided filters.
- WHEN `get_data` is called without any filter THEN request is rejected with validation error and no query execution.
- WHEN `get_output` is called with `date_from` and `date_to` THEN only outputs inside the requested time window are returned.
- WHEN `get_output` is called with `agent_type` and date range THEN only outputs for that agent type within the window are returned.
- WHEN an agent context is built after this change THEN `save_data`, `get_data`, and `get_output` are present and `save_result` is absent.
- WHEN an existing workflow submits final output through `submit_result` THEN final output persistence still succeeds exactly as before.

## 4. Edge Cases & Risks

- Unbounded query risk: missing `get_data` filter guard may trigger full-table scans.
- Naming regression risk: legacy `save_result` references may still appear in tool allowlists, schemas, seeded defaults, or prompts.
- Contract drift risk: LangChain tool args or internal API params may not match, causing runtime failures.
- Date filtering risk: timezone boundary mismatches may include/exclude unexpected `get_output` records.
- Pagination risk: `limit`/`offset` behavior may be inconsistent between service and API layers.
- Metadata integrity risk: `agent_type` or `session_id` may be omitted/null unexpectedly in stored `AgentData` rows.
- Security risk: internal endpoints must remain certificate-protected and inaccessible from non-service callers.
- Architecture risk: accidental DB access from Agent Runtime would violate top-priority rules.

## 5. Acceptance Criteria Checklist

- [ ] Terminology and behavior expose `save_data`; legacy `save_result` is not available to end users in active tool path.
- [ ] Agent sessions can save 0..N named records; each record is retrievable with required metadata.
- [ ] `get_data` supports one-or-more filters (`data_name`, `agent_type`, `session_id`) and returns correctly filtered results.
- [ ] `get_data` rejects requests that provide no filters.
- [ ] `get_output` supports `agent_type`, `session_id`, and date-range filtering with correct results.
- [ ] Product behavior clearly distinguishes optional intermediate saved data from final session output artifact.
- [ ] Existing final output workflows using `submit_result` show no regression.
- [ ] Runtime routing remains compliant: Agent Runtime -> Control Center internal API -> database.

## 6. Test File References

- Backend
  - [backend/tests/unit/test_agent_data_service.py](../../../backend/tests/unit/test_agent_data_service.py)
  - [backend/tests/unit/test_agent_save_data_tools.py](../../../backend/tests/unit/test_agent_save_data_tools.py)
  - [backend/tests/integration/test_system_tool_endpoints.py](../../../backend/tests/integration/test_system_tool_endpoints.py)
  - [backend/tests/integration/test_system_tool_schemas.py](../../../backend/tests/integration/test_system_tool_schemas.py)
  - [backend/tests/service-decomposition/test_issue_2_system_tool_naming.py](../../../backend/tests/service-decomposition/test_issue_2_system_tool_naming.py)
  - [backend/tests/integration/test_skill_system_tools.py](../../../backend/tests/integration/test_skill_system_tools.py)
  - [backend/tests/integration/test_agent_session_lifecycle.py](../../../backend/tests/integration/test_agent_session_lifecycle.py)
  - [backend/tests/test_agent_outputs_api.py](../../../backend/tests/test_agent_outputs_api.py)
  - [backend/tests/test_query_result_tool.py](../../../backend/tests/test_query_result_tool.py)

- Frontend
  - [frontend/src/__tests__/system-tools-naming.test.ts](../../../frontend/src/__tests__/system-tools-naming.test.ts)

- E2E
  - [e2e/tests/agent-save-data-get-tools.spec.ts](../../../e2e/tests/agent-save-data-get-tools.spec.ts)
  - [e2e/tests/agent-outputs-query.spec.ts](../../../e2e/tests/agent-outputs-query.spec.ts)
  - [e2e/tests/skills-system-tools.spec.ts](../../../e2e/tests/skills-system-tools.spec.ts)
  - [e2e/tests/service-decomposition/simple-agent.spec.ts](../../../e2e/tests/service-decomposition/simple-agent.spec.ts)
  - [e2e/tests/auth-required/communication-hub-auth.spec.ts](../../../e2e/tests/auth-required/communication-hub-auth.spec.ts)
  - [e2e/tests/service-segregation-security-audit.spec.ts](../../../e2e/tests/service-segregation-security-audit.spec.ts)
