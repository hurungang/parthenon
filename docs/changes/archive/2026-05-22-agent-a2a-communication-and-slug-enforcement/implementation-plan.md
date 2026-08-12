## Overview
This change adds A2A agent communication through Communication Hub with dynamic receiver provisioning, enforces slug-safe identifiers across agent and MCP naming flows, and extends existing SOP/plan surfaces to derive and visualize agent delegation without redesigning SOP management UI structure. The implementation is split into backend protocol/runtime work, step-definition-driven policy derivation, and plan/diagram preview enhancements.

## Task Checklist — STATUS AFTER REPOSITORY REVIEW (May 20, 2026)

### Phase 1 — A2A Core Flow and Runtime Lifecycle ✅ IMPLEMENTED
- [x] 1.1 — Define A2A request contract for target agent type slug and conversation metadata
- [x] 1.2 — Implement Communication Hub target resolution with runtime fallback creation when target unavailable
- [x] 1.3 — Implement shared-session link lifecycle for requester and dynamic receiver
- [x] 1.4 — Implement disconnect and dynamic receiver cleanup semantics
**STATUS**: `backend/app/communication_hub/api/a2a.py` implements A2A request/disconnect handling, dynamic receiver/session-link creation, and existing-session reuse. `backend/app/services/skills/sop_orchestrator.py` executes `agent_delegation` steps through the hub.

### Phase 2 — Permission Controls and Policy Wiring ✅ IMPLEMENTED
- [x] 2.1 — Derive SOP A2A allowed target agent type slugs from delegation step definitions ✅
- [x] 2.2 — Wire permission checks into A2A request path before routing ✅
- [x] 2.3 — Expose allowed agent type previews in agent role editing API responses ✅
**STATUS**: Permission derivation fully functional; API endpoint working; role preview rendering.

### Phase 3 — Slug Enforcement and Validation Hardening ✅ IMPLEMENTED
- [x] 3.1 — Enforce slug validation for agent type create/update paths ✅
- [x] 3.2 — Enforce slug validation for agent naming paths ✅
- [x] 3.3 — Enforce slug validation for MCP server naming paths ✅
- [x] 3.4 — Add client-side validation hints and server error mapping for slug violations ✅
**STATUS**: Backend slug validation is present in `backend/app/schemas/agents.py`, and focused frontend validation coverage exists for the affected naming flows.

### Phase 4 — Existing SOP and Preview Surface Enhancements ✅ IMPLEMENTED
- [x] 4.1 — Keep existing SOP editor flow and map delegation step definitions to derived A2A associations and permissions ✅
- [x] 4.2 — Extend plan preview to render agent-delegation steps in plan list and topology diagram ✅
- [x] 4.3 — Add allowed agent type slug preview panel in agent role edit dialog ✅
**STATUS**: All surfaces working; no SOP UI redesign needed.

### Phase 5 — Test, Observability, and Regression Protection ✅ IMPLEMENTED
- [x] 5.1 — Add backend unit/integration coverage for A2A permission and dynamic receiver lifecycle
- [x] 5.2 — Add frontend component tests for dialog flow, slug validation, and role preview
- [x] 5.3 — Add E2E scenarios for unavailable-target auto-provision, session continuity, and cleanup
- [x] 5.4 — Validate audit/log trace points for A2A create/connect/disconnect/remove events
**STATUS**: Backend coverage exists in `backend/tests/unit/test_a2a_core_flow.py` and `backend/tests/unit/test_a2a_communication.py`. Focused frontend suites for `AgentRoleDialog`, `PlanPreviewModal`, `TopologyDiagramRenderer`, and slug validation are present and passing in `frontend/vitest_phase5_frontend.json`. `e2e/tests/agent-a2a-communication.spec.ts` is passing with 5 expected, 0 unexpected, and 0 flaky results as recorded in `e2e/e2e_a2a_tests_run.json`.

## Phase 1 — A2A Core Flow and Runtime Lifecycle
### Task 1.1 — Define A2A request contract for target agent type slug and conversation metadata
- Align request payload fields across hub and runtime boundaries.
- Define lifecycle event names for create, attach, disconnect, remove.
Done when:
- Contract is documented in code-facing interfaces and accepted by all touched components.

### Task 1.2 — Implement Communication Hub target resolution with runtime fallback creation when target unavailable
- Resolve active receiver by target agent type slug.
- Request runtime provisioning when receiver is not currently available.
Done when:
- Hub returns successful routing for both already-available and newly-provisioned receiver paths.

### Task 1.3 — Implement shared-session link lifecycle for requester and dynamic receiver
- Persist and track requester-receiver session link metadata.
- Ensure both agents exchange messages in same session context.
Done when:
- Session records demonstrate continuity across multi-turn A2A exchanges.

### Task 1.4 — Implement disconnect and dynamic receiver cleanup semantics
- Process requester finish signal and trigger receiver decommission workflow.
- Remove link records and mark lifecycle completion in logs.
Done when:
- Receiver instances created dynamically are removed after disconnect and no orphan links remain.

## Phase 2 — Permission Controls and Policy Wiring
### Task 2.1 — Extend SOP permission model to include explicit allowed target agent type slugs
- Derive A2A allow associations from SOP steps where `step_type = agent_delegation`.
- Persist generated associations in the same lifecycle as existing SOP skill/tool derivation outputs.
Done when:
- SOP save/update produces and stores allowed target agent type associations directly from delegation step definitions.

### Task 2.2 — Wire permission checks into A2A request path before routing
- Evaluate SOP permission before runtime lookup/provisioning.
- Return clear deny reasons when target slug is not allowed.
Done when:
- Unauthorized A2A requests are blocked with deterministic permission errors.

### Task 2.3 — Expose allowed agent type previews in agent role editing API responses
- Include the slug list needed for role dialog preview.
- Keep response shape backward-compatible where needed.
Done when:
- Role edit UI can render allowed agent type slugs without extra ad hoc data joins.

## Phase 3 — Slug Enforcement and Validation Hardening
### Task 3.1 — Enforce slug validation for agent type create/update paths
- Validate slug constraints in backend request validation and service layer.
- Normalize and reject non-compliant values consistently.
Done when:
- Agent type endpoints reject spaces/special characters and preserve stable slugs.

### Task 3.2 — Enforce slug validation for agent naming paths
- Apply the same slug policy to agent name fields used in routing contexts.
- Ensure existing valid data remains compatible.
Done when:
- Agent naming APIs and forms consistently enforce slug-safe values.

### Task 3.3 — Enforce slug validation for MCP server naming paths
- Add backend and frontend validation alignment for MCP server slug/alias fields.
- Prevent duplicate/invalid namespaces.
Done when:
- MCP server creation and edit flows enforce slug policy and provide actionable validation feedback.

### Task 3.4 — Add client-side validation hints and server error mapping for slug violations
- Surface inline form guidance before submit.
- Display backend validation errors using standard dialog error handling patterns.
Done when:
- Users can identify and correct slug violations without ambiguous failures.

## Phase 4 — Existing SOP and Preview Surface Enhancements
### Task 4.1 — Keep existing SOP editor flow and map delegation step definitions to derived A2A associations and permissions
- Reuse current SOP step model and avoid introducing a new SOP editor interaction pattern.
- Generate target-agent associations and permission records from delegation steps during SOP save/update.
Done when:
- No SOP editor layout rewrite is required and A2A permission derivation works from step definitions.

### Task 4.2 — Extend plan preview to render agent-delegation steps in plan list and topology diagram
- Show agent-delegation steps as first-class entries in the ordered plan preview list.
- Render delegation nodes/edges in topology output with clear source and target semantics.
Done when:
- Plan list and diagram both include agent-delegation steps with stable ordering and labels.

### Task 4.3 — Add allowed agent type slug preview panel in agent role edit dialog
- Render all allowed agent type slugs associated to the role.
- Keep preview synchronized with role assignment changes.
Done when:
- Role dialog visibly lists allowed agent type slugs before save.

## Phase 5 — Test, Observability, and Regression Protection
### Task 5.1 — Add backend unit/integration coverage for A2A permission and dynamic receiver lifecycle
- Verify allow/deny behavior and dynamic instance create/remove transitions.
- Cover same-session continuity and disconnect cleanup.
Done when:
- Backend test suite includes passing tests for all lifecycle and permission branches.

### Task 5.2 — Add frontend component tests for SOP step derivation, plan/diagram rendering, slug validation, and role preview
- Validate existing SOP editor delegation steps produce derived A2A associations on save.
- Validate plan preview list and topology render delegation steps.
- Validate role dialog allowed-slug preview rendering.
Done when:
- Frontend tests pass for UI behavior introduced by this change.

### Task 5.3 — Add E2E scenarios for unavailable-target auto-provision, session continuity, and cleanup
- Exercise full A2A user flow and permission enforcement.
- Verify cleanup occurs after requester disconnect.
Done when:
- E2E tests prove the end-to-end behavior in realistic execution paths.

### Task 5.4 — Validate audit/log trace points for A2A create/connect/disconnect/remove events
- Confirm trace/log visibility for critical lifecycle events.
- Verify incident triage data is available for failures.
Done when:
- Observability checks confirm complete lifecycle traceability.

## Completion Checklist — CURRENT STATUS (May 20, 2026)
- [x] A2A request path routes by target agent type slug and auto-provisions receiver when needed ✅ DONE
- [x] Shared-session communication persists until explicit requester disconnect ✅ DONE
- [x] Dynamic receiver instances are cleaned up after disconnect without orphan state ✅ DONE
- [x] SOP A2A permissions are generated from delegation step definitions and enforced ✅ DONE
- [x] Slug enforcement is active for agent type, agent identity, and MCP server naming flows ✅ DONE
- [x] Existing SOP editor flow remains intact (no structural rewrite) ✅ DONE
- [x] Plan preview list and topology diagram both render agent-delegation steps ✅ DONE
- [x] Agent role dialog shows allowed agent type slug preview ✅ DONE
- [x] Backend, frontend, and E2E tests for this change are passing ✅ DONE (`e2e/tests/agent-a2a-communication.spec.ts`: 5 expected, 0 unexpected, 0 flaky in `e2e/e2e_a2a_tests_run.json`)
- [x] Logging and telemetry cover the implemented A2A lifecycle paths ✅ DONE

---

## Completion Note

Tester verification is complete, including E2E confirmation for `e2e/tests/agent-a2a-communication.spec.ts`, and Product Owner final approval is granted.

