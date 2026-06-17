# Fix Log: add-conversational-agent-intervention

This document tracks all bug fixes and issues resolved for this change.

---

## FIX-20260617-130000

**Created:** 2026-06-17T13:00:00Z
**Status:** Resolved
**Issue:** Delegation log streaming doesn't resume in chatbot after human intervention response

### Observed Behavior
1. During agent delegation, status events stream correctly BEFORE human intervention
2. When a delegated sub-agent requests human intervention (HITL), the delegation cycle in the chatbot shows indefinite "waiting" with no indication that HITL is in progress
3. After the human responds to the intervention, the sub-agent executes and completes
4. But the chatbot's delegation log streaming and status updates do NOT resume — progress is invisible
5. The delegation cycle remains in "waiting" state and never updates to show resumed activity

### Expected Behavior
1. When human intervention is requested during delegation, a "waiting_for_human" status event should be emitted so the chatbot can show a distinct HITL state
2. The delegation log polling timeout should pause during HITL to prevent premature timeout
3. After human input is provided, a "resumed" status event should be emitted so the delegation cycle and log streaming updates resume in the chatbot
4. The timeout/deadline should resume after the HITL pause ends
5. Delegation progress should remain visible and update in the chatbox throughout the HITL pause/resume cycle

### Analysis
- **Affected components:** `backend/app/services/agents/runtime_executor.py`, `backend/app/agent_runtime/api/conversation.py`, `backend/app/api/ws/chat.py`, `frontend/src/hooks/useChatSession.ts`, `frontend/src/components/agents/ConversationDialog.tsx`
- **Root cause:** Three-part frontend bug chain: (1) `intervene_request` sets `chatStatus=waiting_for_human` — but the log polling predicate only checked `delegating`/`waiting`/`using_tool`, so polling stopped during HITL. (2) When HITL resolved via `intervene_status`, `chatStatus` was cleared to `null`, permanently killing polling. (3) The `delegation_resumed` status event from the NDJSON stream was ignored by `parseChatStatus` (not in its allowed list), so the frontend never received the resume signal. Additionally, `delegation_resumed` was missing from the `ChatStatusKind` type union.
- **Documentation impact:** tech-spec.md, test-plan.md

### Fix Tasks
- [x] **Reproduce** — Create test case that demonstrates the issue ✅
- [x] **Fix** — Implement the fix in code ✅
- [x] **Verify** — Run all tests (backend, frontend, E2E) ✅
- [x] **Document** — Update affected documentation ✅

### Test Cases Added/Modified

**File:** `backend/tests/unit/test_hitl_delegation_status_events.py`  
**Status:** ✅ Passing (both tests now pass)

| # | Test Name | Assertion | Expected | Actual (Current) |
|---|---|---|---|---|
| 1 | `test_delegation_with_hitl_emits_waiting_for_human_and_resumed_events` | `delegation_resumed` in status_events | `delegation_resumed` is emitted after `wait_for_a2a_response()` returns (HITL resolved, sub-agent resumed) | Emitted with `agent_type` |
| 2 | `test_delegation_hitl_status_sequence_order_is_correct` | Sequence contains `delegation_resumed` after `waiting` events | `['using_tool', 'delegating', 'waiting', 'waiting', 'delegation_resumed']` | Exact prefix match

**What this test verifies:**
- The Runtime Executor's `execute_conversation_turn_from_context()` method emits a `delegation_resumed` status event through the NDJSON stream after `wait_for_a2a_response()` returns (i.e., sub-agent completed, HITL resolved).
- The `waiting_for_human` signal is handled by the SEPARATE `intervene_request` WebSocket path (InterventionRouter) — it is NOT expected in the NDJSON status stream.
- The frontend uses `delegation_resumed` to trigger log polling restart and delegation cycle progress updates.

### Code Changes
| File | Lines | Change |
|------|-------|--------|
| `backend/app/services/agents/runtime_executor.py` | 2636-2639 | Removed premature `waiting_for_human` status event emission (it was emitted for ALL delegations, not just HITL ones). The `intervene_request` WS message already handles HITL signaling. |
| `backend/app/services/agents/runtime_executor.py` | 2637-2641 | Keep `delegation_resumed` status event emission after `wait_for_a2a_response()` returns. Includes `agent_type` metadata. |
| `frontend/src/hooks/useChatSession.ts` | 32 | Added `delegation_resumed` to `ChatStatusKind` type union |
| `frontend/src/hooks/useChatSession.ts` | 132 | Added `delegation_resumed` to `parseChatStatus` allowed statuses |
| `frontend/src/hooks/useChatSession.ts` | 340 | Removed `setChatStatus(null)` from `intervene_status` handler (resolved HITL should preserve chatStatus, not kill polling) |
| `frontend/src/hooks/useChatSession.ts` | 495 | Added `waiting_for_human` to log polling predicate (polling continues during HITL pause) |
| `frontend/src/hooks/useChatSession.ts` | 361-382 | Added handler for `delegation_resumed` status: adds resume snippet line to the active delegation cycle, updates `chatStatus` for polling restart |
| `backend/tests/unit/test_hitl_delegation_status_events.py` | 61-250 | Updated test: removed `waiting_for_human` assertions from the NDJSON stream test (HITL signal is now `intervene_request` WS message); updated expected sequence prefix to `['using_tool', 'delegating', 'waiting', 'waiting', 'delegation_resumed']` |
| `frontend/src/hooks/useChatSession.ts` | 340-344 | `intervene_status` handler: on HITL resolved, revert `chatStatus` from `waiting_for_human` → `waiting` (hides the "waiting for your input" indicator immediately after user responds) |
| `frontend/src/hooks/useChatSession.ts` | 805-810 | `sendInterventionResponse`: revert `chatStatus` from `waiting_for_human` → `waiting` on user response submit |
| `frontend/src/hooks/useChatSession.ts` | 833-838 | `cancelIntervention`: revert `chatStatus` from `waiting_for_human` → `waiting` on cancel |

**Why:** The HITL signal is now correctly routed through two complementary paths: (1) The `intervene_request` WebSocket message from the InterventionRouter provides the real-time HITL notification and sets `chatStatus=waiting_for_human`. (2) The `delegation_resumed` NDJSON status event signals that the sub-agent has completed and the delegation cycle can resume. The frontend now properly handles both paths: log polling continues through HITL (predicate includes `waiting_for_human`), `chatStatus` is preserved after HITL resolution, and `delegation_resumed` is recognized to restart the delegation cycle updates.

### Documentation Updates
- `docs/changes/add-conversational-agent-intervention/tech-spec.md`: Code Reference Map updated with `delegation_resumed` status event type entry.
- `docs/changes/add-conversational-agent-intervention/test-plan.md`: Added `test_a2a_hitl_timeout.py` and `test_hitl_delegation_status_events.py` to the backend test file references table.

### Verification Results (2026-06-17T14:38 UTC — Corrected Fix)

| # | Test File | Pass | Fail | Total |
|---|---|---|---|---|
| 1 | `test_hitl_delegation_status_events.py` | 2 | 0 | 2 |
| 2 | `test_a2a_hitl_timeout.py` | 4 | 0 | 4 |
| 3 | `test_conversation_intervention_turns.py` | 25 | 0 | 25 |
| 4 | `test_intervention_api_integration.py` | 13 | 0 | 13 |
| 5 | `test_non_conversational_regression.py` | 7 | 0 | 7 |
| **TOTAL** | | **51** | **0** | **51** |

**Fix-specific tests:** 2/2 | **All related tests:** 51/51

**Frontend tests (Vitest):** 30/31 passing — 1 pre-existing failure: `useChatSession.test.ts` "applies using_tool status from websocket events" expects snippets length 1, but `toDelegationSnippetLine` intentionally returns null for `using_tool` (comment at line 177-181). Unrelated to FIX-20260617-130000.

**Conclusion:** FIX-20260617-130000 is VERIFIED COMPLETE. All reproduction and related tests pass. The corrected fix properly handles the HITL pause/resume cycle through two complementary signal paths.

---

## FIX-20260617-120000

**Created:** 2026-06-17T12:00:00Z
**Status:** Resolved
**Issue:** Delegation streaming stops after human intervention; result not returned to chatbot

### Observed Behavior
1. Delegation status events stream correctly BEFORE human intervention
2. After human responds, sub-agent executes and completes successfully
3. But the delegation result is not returned — chatbot reports error/timeout
4. The CH's `_wait_for_receiver_result` times out because the deadline expired during HITL wait

### Expected Behavior
1. Delegation wait should survive the human intervention pause
2. After human responds, the sub-agent result should be picked up from Redis
3. The chatbot should receive the final agent response

### Analysis
- **Affected components:** `backend/app/communication_hub/api/a2a.py`, `backend/app/agent_runtime/comm_hub_client.py`, `backend/app/services/agents/runtime_executor.py`, `backend/app/api/ws/chat.py`
- **Root cause:** Three interconnected bugs in `_wait_for_receiver_result` causing premature timeout after HITL resume
- **Documentation impact:** None (internal implementation details)

### Fix Tasks
- [x] **Reproduce** — `test_result_received_after_human_intervention_resume` created and confirmed failing
- [x] **Fix** — 3 bugs in `a2a.py` fixed
- [x] **Verify** — 24/24 tests pass
- [x] **Document** — Fix log updated

### Test Cases Added/Modified
**File:** `backend/tests/unit/test_a2a_hitl_timeout.py`
**Test name:** `test_result_received_after_human_intervention_resume`
**Status:** ✅ Passing

### Code Changes
**File:** `backend/app/communication_hub/api/a2a.py`

| Bug | Fix |
|-----|-----|
| #1: Deadline never extended after HITL resume | Track `prev_is_waiting`, reset deadline on `waiting_for_human` → `running` transition to `now + max(timeout_seconds, 30.0)` |
| #2: Premature "expired" on completed/failed/terminated | Defer "expired" return — store terminal status, keep polling Redis, only return "expired" when deadline fires with no result |
| #3: `Request = None` blocks FastAPI injection | Removed `= None` default from `http_request: Request` parameter, reordered so it precedes optional params |

### Documentation Updates
No documentation updates required — these were internal implementation bugs.

### Verification Results
- **Reproduction test:** ✅ Now passing
- **HITL tests:** ✅ 4/4 passing
- **Intervene respond tests:** ✅ 8/8 passing
- **Intervention API tests:** ✅ 13/13 passing
- **Total:** ✅ 25/25 passing

---
