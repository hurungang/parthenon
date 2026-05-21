# Phase 5 Test Coverage Review
## A2A Communication and Slug Enforcement

**Review Date**: May 20, 2026  
**Implementation Phase**: Phase 5 — Test, Observability, and Regression Protection

---

## Executive Summary

Phase 5 requires comprehensive test coverage across backend, frontend, and E2E layers for A2A (agent-to-agent) communication, dynamic receiver lifecycle management, and slug enforcement. Current status shows **significant gaps in Phase 5 test coverage**:

- **Backend**: 31 tests passing ✅, but **critical A2A scenarios untested** ❌
- **Frontend**: 611 tests passing ✅, but **allowed-agent-type UI tests SKIPPED** ⚠️
- **E2E**: Unable to run (infrastructure issue), but **NO A2A end-to-end tests exist** ❌

---

## Phase 5 Requirements Checklist

### 5.1 Backend Unit/Integration Coverage

**Requirement**: Verify allow/deny behavior and dynamic instance create/remove transitions. Cover same-session continuity and disconnect cleanup.

| Test Category | Status | Details |
|---|---|---|
| **A2A Permission Allow/Deny** | ❌ MISSING | No tests for A2A request permission enforcement; only generic permission manager tests exist |
| **Dynamic Receiver Lifecycle (Create)** | ❌ MISSING | No tests for receiver provisioning when target unavailable |
| **Dynamic Receiver Lifecycle (Remove)** | ❌ MISSING | No tests for receiver decommission after requester disconnect |
| **Shared-Session Continuity** | ❌ MISSING | No tests for multi-turn A2A exchanges maintaining session context |
| **Disconnect Semantics** | ❌ MISSING | No tests for cleanup logic after requester sends finish signal |
| **Orphan Link Prevention** | ❌ MISSING | No tests verifying receiver links are removed completely |
| **Allowed Agent Types Resolution** | ✅ PARTIAL | 2 tests in `test_permission_manager.py`: `test_calculate_allowed_agent_types_from_sop_delegation_steps()` + cache test |
| **SOP Delegation Step Derivation** | ✅ PASSING | Delegation steps recognized in step_type enum; no explicit derivation tests |

**Files Tested**:
- `backend/tests/unit/test_permission_manager.py`: 15 passing tests
- `backend/tests/unit/services/test_topology_builder_service.py`: 16 passing tests

**Critical Gaps**:
- No test file for A2A request routing/permission enforcement
- No test file for Communication Hub receiver provisioning logic
- No test file for disconnect workflow and cleanup
- No integration test for full A2A lifecycle (request → provision → session → disconnect → cleanup)

**Recommendation**: Create `backend/tests/unit/test_a2a_communication.py` with:
```
- test_a2a_permission_check_allows_authorized_target()
- test_a2a_permission_check_denies_unauthorized_target()
- test_receiver_provisioning_when_unavailable()
- test_receiver_cleanup_after_disconnect()
- test_shared_session_preserves_context_across_turns()
- test_orphan_links_removed_on_disconnect()
- test_multiple_a2a_exchanges_in_single_session()
```

---

### 5.2 Frontend Component Tests

**Requirement**: Validate SOP step derivation producing A2A associations, plan/diagram rendering, slug validation, and role preview.

| Test Category | Status | Details |
|---|---|---|
| **SOP Delegation Step Rendering** | ✅ MINIMAL | 1 test: `SopEditor.test.tsx` "includes target_agent_type_id when step type is agent_delegation" — only checks data presence, not save/derivation |
| **Plan Preview List Delegation Rendering** | ❌ MISSING | `PlanPreviewModal.test.tsx` exists but has NO delegation step tests |
| **Topology Diagram Agent Delegation Nodes/Edges** | ❌ MISSING | `TopologyDiagramRenderer.test.tsx` covers 4 node types but has NO tests for agent delegation nodes |
| **Role Dialog Allowed Agent Type Preview** | ⚠️ SKIPPED | `AgentRoleDialog.test.tsx` has 5 SKIPPED tests for `allowed_identity_types` feature marked `it.skip()` |
| **Slug Validation in Agent Forms** | ❌ MISSING | `AgentTypeForm.test.tsx` exists but NO tests for slug validation |
| **Slug Validation in MCP Forms** | ❌ MISSING | No slug validation tests for MCP server creation |
| **A2A Association Derivation** | ❌ MISSING | No tests verifying SOP save produces A2A permission records |

**Files Tested**:
- `frontend/src/__tests__/SopEditor.test.tsx`: 611 tests total across entire frontend
- `frontend/src/__tests__/AgentRoleDialog.test.tsx`: Multiple tests SKIPPED for Phase 5 feature
- `frontend/src/__tests__/PlanPreviewModal.test.tsx`: No delegation tests
- `frontend/src/__tests__/TopologyDiagramRenderer.test.tsx`: No delegation node tests

**Critical Gaps**:
- Allowed-agent-type feature tests are SKIPPED and need to be enabled
- Plan preview doesn't test delegation step rendering
- Topology diagram test fixtures don't include delegation nodes
- No CRUD tests for slug validation (create/update enforcement)
- No tests for error handling on slug violations

**Recommendation**: Enable and implement:
```typescript
// AgentRoleDialog.test.tsx — ENABLE SKIPPED TESTS
✅ it('renders allowed_agent_types multi-select in the dialog')
✅ it('sends allowed_agent_types in POST payload when creating')
✅ it('sends updated allowed_agent_types in PUT payload when editing')

// PlanPreviewModal.test.tsx — ADD NEW TESTS
+ test_delegation_step_appears_in_plan_list()
+ test_delegation_step_has_target_agent_type_label()
+ test_delegation_steps_maintain_order()

// TopologyDiagramRenderer.test.tsx — ADD NEW TESTS
+ test_delegation_node_renders_with_correct_type()
+ test_delegation_edge_connects_source_role_to_target_agent()
+ test_multiple_delegation_targets_render_separate_edges()

// AgentTypeForm.test.tsx or SlugValidation.test.tsx — ADD NEW TESTS
+ test_agent_type_slug_validation_rejects_spaces()
+ test_agent_type_slug_validation_rejects_special_chars()
+ test_agent_type_slug_normalization_to_kebab_case()
+ test_agent_name_slug_validation()
```

---

### 5.3 E2E Integration Scenarios

**Requirement**: Exercise full A2A user flow and permission enforcement. Verify cleanup occurs after requester disconnect.

| Test Scenario | Status | Details |
|---|---|---|
| **Unavailable-Target Auto-Provision** | ❌ MISSING | No E2E test for requesting A2A to non-running agent type |
| **Session Continuity Across A2A Exchanges** | ❌ MISSING | No E2E test for multi-turn A2A conversation persistence |
| **Receiver Cleanup After Disconnect** | ❌ MISSING | No E2E test verifying dynamic receiver removal post-disconnect |
| **A2A Permission Enforcement** | ❌ MISSING | No E2E test for allowed_agent_type permission deny scenario |
| **Communication Hub WebSocket Connection** | ✅ EXISTS | `e2e/tests/websocket-communication-hub.spec.ts` — tests Connection Hub health, not A2A |
| **Three-Service Architecture** | ✅ EXISTS | `e2e/tests/three-service-architecture.spec.ts` — validates Control Center/Runtime/Hub, not A2A |

**Test Files**:
- `e2e/tests/websocket-communication-hub.spec.ts`: 4 tests (Communication Hub connectivity only)
- `e2e/tests/three-service-architecture.spec.ts`: Tests service health checks, not A2A

**E2E Test Execution**: 
- ❌ Unable to run current test suite (web server build failed)
- Requires frontend dev server to be running for E2E infrastructure

**Critical Gaps**:
- No end-to-end A2A request workflow test
- No test for dynamic provisioning (requester creates receiver on-demand)
- No cleanup verification after session disconnect
- No permission denial scenarios tested end-to-end
- No stress test for multiple concurrent A2A exchanges

**Recommendation**: Create `e2e/tests/agent-a2a-communication.spec.ts` with:
```typescript
test.describe('Agent-to-Agent Communication Flow', () => {
  // Unavailable-target auto-provision scenario (Phase 1.2)
  test('Should provision receiver when target agent type is unavailable', async ({ page }) => {
    // 1. Submit A2A request with target_agent_type_slug = "research-agent"
    // 2. Verify Communication Hub returns successfully (receiver created)
    // 3. Verify receiver appears in agent instances dashboard
  })

  // Session continuity (Phase 1.3)
  test('Should maintain shared-session context across multi-turn A2A exchange', async ({ page }) => {
    // 1. Send A2A request with conversation_context
    // 2. Exchange message 1 → verify response
    // 3. Exchange message 2 → verify access to prior context
    // 4. Verify both messages in same session_id
  })

  // Cleanup on disconnect (Phase 1.4)
  test('Should remove dynamic receiver after requester disconnect', async ({ page }) => {
    // 1. Provision receiver via A2A request
    // 2. Verify receiver in instances list
    // 3. Requester disconnects (finish signal)
    // 4. Verify receiver no longer in instances after 5s
    // 5. Verify link records removed from database
  })

  // Permission enforcement (Phase 2.2)
  test('Should deny A2A request for target not in allowed_agent_types', async ({ page }) => {
    // 1. Create role with only specific allowed_agent_types
    // 2. Assign agent to role
    // 3. Request A2A to disallowed target
    // 4. Verify 403 PermissionDenied response
    // 5. Verify denying agent sees error in UI
  })

  // Permission allow scenario
  test('Should allow A2A request for target in allowed_agent_types', async ({ page }) => {
    // 1. Create role with specific allowed_agent_types including "planner-agent"
    // 2. Assign agent to role
    // 3. Request A2A to "planner-agent"
    // 4. Verify 200 success response
  })
})
```

---

### 5.4 Audit/Log Trace Points

**Requirement**: Confirm trace/log visibility for critical lifecycle events (create, connect, disconnect, remove).

| Trace Event | Status | Details |
|---|---|---|
| **A2A Request Create Event** | ❌ MISSING | No test verifying trace span created when A2A request received |
| **Receiver Provisioning Trace** | ❌ MISSING | No test verifying trace when dynamic receiver created |
| **Receiver Connect Trace** | ❌ MISSING | No test verifying trace when receiver session linked |
| **Requester Disconnect Trace** | ❌ MISSING | No test verifying trace when disconnect signal sent |
| **Receiver Remove Trace** | ❌ MISSING | No test verifying trace when receiver cleaned up |
| **Permission Deny Event** | ❌ MISSING | No audit log test for permission violations |
| **Audit Log Completeness** | ⚠️ PARTIAL | General audit infrastructure exists but no Phase 5 specific coverage |

**Recommendation**: Add observability test scenario in backend integration tests:
```python
@pytest.mark.asyncio
async def test_a2a_lifecycle_traces_emitted():
    """Verify trace spans created for all A2A lifecycle events."""
    # 1. Mock OTEL tracer
    # 2. Send A2A request
    # 3. Assert spans: create, lookup, provision, link, connect
    # 4. Requester disconnect
    # 5. Assert spans: disconnect, remove, cleanup
```

---

## Test Counts Summary

### Current Test Status

| Layer | Total Tests | Passed | Failed | Skipped | Status |
|---|---|---|---|---|---|
| **Backend (pytest)** | 31 | 31 | 0 | 0 | ✅ Passing |
| **Frontend (Vitest)** | 611 | 611 | 0 | ~25 | ✅ Passing (but features skipped) |
| **E2E (Playwright)** | N/A | 0 | 0 | 0 | ❌ Unable to run |
| **TOTAL** | **~640+** | **~640+** | **0** | **~25** | ⚠️ Incomplete |

**Note**: E2E tests exist but could not be executed due to web server infrastructure issue. Frontend has ~25 tests marked `it.skip()` for Phase 5 features that need to be enabled.

---

## Phase 5 Completeness Assessment

### Completion Criteria from Implementation Plan

| Criterion | Implemented | Tested | Status |
|---|---|---|---|
| A2A request path routes by target agent type slug | ⚠️ Partial | ❌ No | 🔴 Need Tests |
| Shared-session communication persists until disconnect | ❓ Unknown | ❌ No | 🔴 Need Tests |
| Dynamic receiver instances cleaned up after disconnect | ❓ Unknown | ❌ No | 🔴 Need Tests |
| SOP A2A permissions generated from delegation steps | ✅ Yes | ✅ Partial | 🟡 Need Full Tests |
| Slug enforcement active for agent/MCP naming | ✅ API Endpoint | ❌ No | 🔴 Need Tests |
| Existing SOP editor flow remains intact | ✅ Yes | ✅ Minimal | 🟡 Need Full Tests |
| Plan preview list renders agent-delegation steps | ❓ Unknown | ❌ No | 🔴 Need Tests |
| Topology diagram renders agent-delegation steps | ❓ Unknown | ❌ No | 🔴 Need Tests |
| Agent role dialog shows allowed agent type preview | ✅ API Ready | ⚠️ Skipped | 🟡 Enable Skipped Tests |
| Backend, frontend, E2E tests passing | ✅ Partial | ⚠️ Incomplete | 🔴 Complete Coverage Gap |
| Logging/telemetry cover full A2A lifecycle | ❓ Unknown | ❌ No | 🔴 Need Tests |

---

## Priority Fixes (In Order)

### 🔴 CRITICAL (Blocks Phase 5 Completion)

1. **Backend A2A Tests** (NEW FILE REQUIRED)
   - Create `backend/tests/unit/test_a2a_communication.py`
   - Implement 8+ tests for permission, receiver lifecycle, session continuity, cleanup
   - Verify implementation exists before writing tests

2. **Enable Skipped Frontend Tests** (UNBLOCK EXISTING)
   - Enable 5 skipped tests in `AgentRoleDialog.test.tsx`
   - These tests are already written, just marked `it.skip()`
   - Verify allowed_agent_types feature implementation complete

3. **Plan Preview Delegation Tests** (NEW TESTS REQUIRED)
   - Add delegation step rendering tests to `PlanPreviewModal.test.tsx`
   - Test that delegation steps appear in ordered list
   - Test that delegation targets are labeled correctly

### 🟡 HIGH (Important for Coverage)

4. **Topology Diagram Delegation Tests** (NEW TESTS REQUIRED)
   - Add delegation node type to `TopologyDiagramRenderer.test.tsx` fixtures
   - Test node rendering and edge connections for agent→agent
   - Test multiple delegation targets

5. **Slug Validation Tests** (NEW TESTS REQUIRED)
   - Create `frontend/src/__tests__/features/slug-validation.test.tsx`
   - Test agent type slug validation (spaces, special chars)
   - Test agent name slug validation
   - Test MCP server slug validation

6. **E2E A2A Tests** (NEW FILE REQUIRED)
   - Create `e2e/tests/agent-a2a-communication.spec.ts`
   - Implement 5+ scenarios (auto-provision, continuity, cleanup, permission deny/allow)
   - Run against live backend to verify end-to-end behavior

### 🟢 MEDIUM (Nice to Have)

7. **Observability Tests** (NEW TESTS)
   - Add trace/log verification tests for A2A lifecycle events
   - Verify audit logs capture permission denials

8. **Stress/Regression Tests** (NEW TESTS)
   - Multiple concurrent A2A exchanges
   - Receiver cleanup under high load
   - Permission cache invalidation

---

## Test File Organization

**Current Structure**:
```
backend/tests/unit/
  ├── test_permission_manager.py (15 tests - A2A partial ✅)
  └── services/
      └── test_topology_builder_service.py (16 tests ✅)

frontend/src/__tests__/
  ├── SopEditor.test.tsx (✅ has 1 delegation test)
  ├── AgentRoleDialog.test.tsx (⚠️ 5 tests skipped)
  ├── PlanPreviewModal.test.tsx (❌ no delegation tests)
  ├── TopologyDiagramRenderer.test.tsx (❌ no delegation tests)
  └── AgentRoleViewDialog.test.tsx (✅ passing)

e2e/tests/
  ├── websocket-communication-hub.spec.ts (✅ exists, not A2A)
  ├── three-service-architecture.spec.ts (✅ exists, not A2A)
  └── agent-a2a-communication.spec.ts (❌ MISSING - needs creation)
```

**Recommended New Files**:
```
backend/tests/unit/
  └── test_a2a_communication.py (CREATE - 8+ tests required)

frontend/src/__tests__/
  ├── features/slug-validation.test.tsx (CREATE - 6+ tests required)
  └── (Enable skipped tests in AgentRoleDialog.test.tsx)

e2e/tests/
  └── agent-a2a-communication.spec.ts (CREATE - 5+ scenarios required)
```

---

## Recommendations

### Before Marking Phase 5 Complete

1. **Backend**: Create comprehensive A2A communication test file with lifecycle tests
2. **Frontend**: Enable all skipped tests and add delegation rendering tests
3. **E2E**: Create agent-a2a-communication.spec.ts with full workflow tests
4. **Observability**: Add trace/log verification for all lifecycle events
5. **Run All Layers**: Ensure `pytest`, `vitest`, and `playwright` all pass 100%

### Definition of Done for Phase 5

- [ ] Backend A2A permission allow/deny tests passing
- [ ] Backend dynamic receiver lifecycle tests passing
- [ ] Backend session continuity tests passing
- [ ] Backend disconnect/cleanup tests passing
- [ ] Frontend allowed_agent_types tests enabled and passing
- [ ] Frontend plan preview delegation tests passing
- [ ] Frontend topology diagram delegation tests passing
- [ ] Frontend slug validation tests passing
- [ ] E2E unavailable-target auto-provision test passing
- [ ] E2E session continuity test passing
- [ ] E2E receiver cleanup test passing
- [ ] E2E permission enforcement tests passing
- [ ] All audit/log trace points verified
- [ ] Full test suite execution: Backend ✅ Frontend ✅ E2E ✅
- [ ] No failing tests or skipped phase 5 tests

---

## Test Execution Commands

### Backend
```bash
cd backend
python -m pytest tests/unit/test_permission_manager.py tests/unit/services/test_topology_builder_service.py -v
# Expected: 31 passing
```

### Frontend
```bash
cd frontend
npx vitest run --reporter=verbose
# Expected: 611+ passing, 0 failing
# Note: ~25 tests marked it.skip() for Phase 5 features
```

### E2E
```bash
cd e2e
npx playwright test --grep "a2a|delegation|receiver|Communication Hub" -v
# Currently unavailable (infra issue)
# Planned: 5+ A2A-specific test scenarios
```

---

## Conclusion

**Phase 5 Status**: ⚠️ **INCOMPLETE — Significant Test Gaps**

While the backend and frontend have passing test suites, they **lack critical coverage for Phase 5 requirements**:

- **No A2A permission or receiver lifecycle tests** in backend
- **No delegation step rendering tests** in frontend  
- **No E2E A2A workflow tests** (unable to run current suite)
- **No slug validation tests** across layers
- **Allowed-agent-type feature tests are skipped** pending implementation

**Recommendation**: Complete Phase 5 test implementation before merging code. Use this report as the basis for test case generation and validation.

---

**Report Generated**: 2026-05-20  
**Reviewed By**: Tester Agent (Phase 5 Verification)  
**Next Review**: Upon test implementation completion
