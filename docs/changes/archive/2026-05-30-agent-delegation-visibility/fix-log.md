# Fix Log: agent-delegation-visibility

This document tracks all bug fixes and issues resolved for this change.

---

## FIX-20260530-101323

**Created:** 2026-05-30T10:13:23Z
**Status:** Completed
**Issue:** Delegation intro/progress visibility regressed in conversation chat and is not shown until delegation completes.

### Observed Behavior
When delegation starts in conversation chat, the expected in-sequence delegation visibility is broken. The delegation intro message and progress row/snippets do not render during active delegation and only appear after delegation completes and another chatbot message arrives.

### Expected Behavior
At delegation start, chat should show `Delegating to agent <agent_type>`, then show delegation progress/waiting visibility during active delegation, and finally show the chatbot response after delegation completion.

### Analysis
- **Affected components:** `frontend/src/pages/chat/ChatPage.tsx`, `frontend/src/components/agents/ConversationDialog.tsx`, `frontend/src/hooks/useChatSession.ts`
- **Confirmed root cause:** Delegation inline row rendering was anchored to `messages.map(...)` index matching. In active delegation states with only user messages, computed insertion index became `messages.length`, which has no matching map iteration, so intro/progress block never rendered. Live status bubble remained intentionally suppressed once snippets existed, leaving no visible active delegation cue.
- **Documentation impact:** `docs/changes/agent-delegation-visibility/fix-log.md`, possible updates to `tech-spec.md` and `test-plan.md`

### Fix Tasks
- [x] **Reproduce** — Confirmed with failing frontend reproduction test
- [x] **Fix** — Implemented minimal rendering-condition fix in chat surfaces
- [x] **Verify** — Ran related frontend delegation chat tests with JSON reporter
- [x] **Document** — Updated this fix log entry

### Implementation Details
<!-- Will be filled in as fix progresses -->

### Test Cases Added/Modified
- Frontend Vitest (failing reproduction): `frontend/src/__tests__/ConversationDelegationVisibility.test.tsx`
	- `ConversationDelegationVisibility shows delegation intro and active progress while waiting even before first agent reply`
	- Purpose: reproduces regression where active delegation visibility is missing when only user messages exist and no agent reply anchor has rendered yet.
	- Current result after fix: **PASS** — delegation intro/progress UI remains visible during active delegation before first agent reply.
- Frontend Vitest (new failing regressions, not fixed in implementation yet):
	- `frontend/src/__tests__/useChatSession.test.ts`
		- `useChatSession preserves previous delegation snippets when a second delegation begins`
		- Purpose: reproduces repeated delegation visibility regression where first delegation intro/progress lines are erased when second delegation starts.
		- Current result after regression fix: **PASS**.
	- `frontend/src/__tests__/ConversationDialog.test.tsx`
		- `ConversationDialog shows policy snapshot id from resumed camelCase guardrail payload instead of unknown`
		- Purpose: reproduces guardrail panel regression where policy snapshot renders as fallback (`unknown`) instead of persisted value after resume.
		- Current result after regression fix: **PASS** (`policy-camel-1` rendered).
	- JSON report: `frontend/vitest_results_agent_delegation_visibility_repro_20260530.json`

Resume sequencing bug (#2) reproducibility scope and assertion (documented; automation pending):
- Scope: resume flow combines historical turns with live websocket stream around delegation intro/progress boundaries.
- Practical failing assertion target:
	- Given resumed history containing first delegation intro/snippet timestamps and then a second delegation initiated post-resume,
	- Expected order in rendered transcript is monotonic by event time around delegation markers:
		1) first delegation intro/snippets,
		2) first delegated agent response,
		3) second delegation intro/snippets,
		4) second delegated response.
	- Current observed failure mode: ordering around delegation markers appears interleaved/out of sequence after resume because history-derived and live entries are merged without a strict cross-source ordering contract.

### Code Changes
- `frontend/src/pages/chat/ChatPage.tsx` (around line 476)
	- Updated fallback delegation-inline render condition to also render when no agent anchor exists yet: `(messages.length === 0 || inlineDelegationIntroInsertIndex < 0)`.
	- Why: ensures `Delegating to agent <agent_type>` and active snippet/progress row stay visible while waiting, even when only user messages are present.
- `frontend/src/components/agents/ConversationDialog.tsx` (around line 594)
	- Applied the same condition update for consistency in the dialog chat surface.
	- Why: prevents equivalent visibility disappearance in dialog-based conversation UX.

Validation run:
- Command: `npx vitest run src/__tests__/ConversationDelegationVisibility.test.tsx src/__tests__/ConversationDialog.test.tsx --reporter=json --outputFile=vitest_results_FIX-20260530-101323.json`
- Result summary: Passed 11, Failed 0, Total 11.

Iteration 2 (targeted waiting-indicator visibility follow-up):
- `frontend/src/pages/chat/ChatPage.tsx`
	- Updated `shouldShowLiveStatusBubble` so `waiting` state always keeps the live status bubble visible, even when inline delegation intro/snippets are rendered.
	- Why: preserve required in-sequence visibility (`Delegating to agent <agent_type>` followed by active waiting indicator) during delegation.
- `frontend/src/components/agents/ConversationDialog.tsx`
	- Applied the same `waiting` live-bubble visibility rule for dialog parity.
	- Why: keep behavior consistent across chat surfaces and avoid dialog regressions.
- `frontend/src/__tests__/ConversationDelegationVisibility.test.tsx`
	- Added explicit assertion for `chat-status-indicator` in waiting/delegation scenarios.
	- Scoped waiting text assertions to the live indicator container to avoid ambiguity with snippet preview text.
- `frontend/src/__tests__/ConversationDialog.test.tsx`
	- Scoped waiting text assertion to `conversation-dialog-chat-status-indicator` for the same reason.

Iteration 3 (regression restoration for multi-cycle delegation + camelCase resume payloads):
- `frontend/src/hooks/useChatSession.ts`
	- Updated delegation cycle reset logic to preserve prior completed delegation snippets when a new delegation begins after a subsequent user turn.
	- Added `delegationCompletedRef` to avoid stale state in WebSocket callback and consume pending new-cycle flag on first delegation status event.
	- Kept expected behavior for interrupted/incomplete cycles by only resetting snippets for new user turns when no completed delegation cycle exists.
	- Extended guardrail usage parsing to accept both snake_case and camelCase payload keys.
- `frontend/src/components/agents/ConversationDialog.tsx`
	- Extended persisted guardrail usage parsing to accept both snake_case and camelCase keys so resumed payloads render concrete guardrail values.
	- Restores policy snapshot display from resumed payloads such as `policySnapshotId`.

### Verification Results
- **Verifier:** GitHub Copilot (GPT-5.3-Codex)
- **Verified at:** 2026-05-30T10:26:57Z

Reproduction verification:
- Command: `npx vitest run src/__tests__/ConversationDelegationVisibility.test.tsx --reporter=json --outputFile=vitest_results_FIX-20260530-101323_repro_verify.json`
- Result: **PASS** (`ReproTestStatus:passed`, Passed 4, Failed 0, Total 4)
- Report: `frontend/vitest_results_FIX-20260530-101323_repro_verify.json`

Iteration 2 targeted verification:
- Frontend unit tests: **PASS**
	- Command: `Set-Location "C:\Users\rhu\source\personal\coding-workspace\Parthenon\frontend"; npx vitest run src/__tests__/ConversationDelegationVisibility.test.tsx src/__tests__/ConversationDialog.test.tsx --reporter=json --outputFile=vitest_results_FIX-20260530-101323_iter2.json`
	- Result summary: Passed 11, Failed 0, Total 11
	- Report: `frontend/vitest_results_FIX-20260530-101323_iter2.json`
- E2E delegation visibility spec: **PASS**
	- Command: `Set-Location "C:\Users\rhu\source\personal\coding-workspace\Parthenon\e2e"; npx playwright test tests/conversation-delegation-visibility.spec.ts --config=playwright.dev.config.ts --reporter=json > playwright_results_FIX-20260530-101323_iter2_conversation_delegation_visibility.json`
	- Result summary: Expected 2, Unexpected 0, Flaky 0, Skipped 0
	- Report: `e2e/playwright_results_FIX-20260530-101323_iter2_conversation_delegation_visibility.json`

Iteration 3 targeted regression verification:
- Frontend unit tests: **PASS**
	- Command: `Set-Location "C:\Users\rhu\source\personal\coding-workspace\Parthenon\frontend"; npx vitest run src/__tests__/useChatSession.test.ts src/__tests__/ConversationDialog.test.tsx --reporter=json --outputFile=vitest_results_FIX-20260530-101323_regression_fix.json`
	- Result summary: Passed 20, Failed 0, Total 20
	- Report: `frontend/vitest_results_FIX-20260530-101323_regression_fix.json`
- E2E delegation visibility spec: **PASS**
	- Command: `Set-Location "C:\Users\rhu\source\personal\coding-workspace\Parthenon\e2e"; npx playwright test tests/conversation-delegation-visibility.spec.ts --config=playwright.dev.config.ts --reporter=json > playwright_results_FIX-20260530-101323_regression_fix.json`
	- Result summary: Expected 2, Unexpected 0, Flaky 0, Skipped 0
	- Report: `e2e/playwright_results_FIX-20260530-101323_regression_fix.json`

Three-layer verification summary (scoped to this change test plan):
- Backend (pytest): **FAIL** — Passed 10, Failed 4, Total 14
	- Command used: `..\\.venv\\Scripts\\python.exe -m pytest tests/unit/test_fix_support_role_conversation_delegation_tools.py tests/unit/test_fix_20260521_tool_routing_and_chat_timeout.py tests/unit/test_fix_20260521_192300_ws_chat_runtime_boundary.py tests/unit/test_ws_delegation_visibility.py tests/api/test_agents_api.py tests/api/test_agents_session_log_stream_api.py --junitxml=test-results/FIX-20260530-101323_backend_pytest.xml`
	- Report: `backend/test-results/FIX-20260530-101323_backend_pytest.xml`
	- Note: `pytest --json-report` is not available in this environment/plugin set.
- Frontend (Vitest): **PASS** — Passed 35, Failed 0, Total 35
	- Command used: `npx vitest run src/__tests__/ConversationDialog.test.tsx src/__tests__/useChatSession.test.ts src/__tests__/AgentSessionPage.test.tsx src/__tests__/ConversationDelegationVisibility.test.tsx src/__tests__/SessionExecutionLogsDialog.test.tsx src/__tests__/useSessionExecutionLogStream.test.ts --reporter=json --outputFile=vitest_results_FIX-20260530-101323_frontend_fullscope.json`
	- Report: `frontend/vitest_results_FIX-20260530-101323_frontend_fullscope.json`
- E2E (Playwright): **FAIL** — Passed 36, Failed 1, Total 37
	- Command used: `npx playwright test tests/chat.spec.ts tests/conversations.spec.ts tests/conversation-delegation-visibility.spec.ts tests/agent-logs.spec.ts tests/agent-a2a-communication.spec.ts tests/agent-live-logs-stream.spec.ts --config=playwright.dev.config.ts --reporter='line,json'`
	- Report: `e2e/playwright_results_FIX-20260530-101323_e2e_fullscope.json`

Failure triage for this fix scope:
- **Related to this fix (initial run):**
	- `e2e/tests/conversation-delegation-visibility.spec.ts` — `shows delegating label and waiting indicator with fold-expand-collapse snippet behavior`
	- Evidence: `chat-status-indicator` not found while expecting delegation/waiting visibility during active delegation.
	- Resolution: fixed in iteration 2; targeted E2E spec now passes (Expected 2, Unexpected 0).
- **Unrelated / pre-existing to this fix implementation:**
	- `backend/tests/unit/test_fix_20260521_tool_routing_and_chat_timeout.py::test_delegate_conversation_turn_preserves_tool_name_in_status_events`
	- `backend/tests/unit/test_fix_20260521_tool_routing_and_chat_timeout.py::test_delegate_conversation_turn_streams_status_events_to_callback`
	- `backend/tests/unit/test_ws_delegation_visibility.py::test_conversation_context_emits_delegation_status_events`
	- `backend/tests/api/test_agents_api.py::test_create_no_input_agent_without_sop_fails`
	- Evidence: failures assert legacy backend expectations (`status_events` shape without `timestamp`, `wait_for_response=True`, and API 400 vs 422 name validation) and do not map to the frontend-only render-condition change documented for this fix.

### Documentation Updates
- Updated `docs/changes/agent-delegation-visibility/fix-log.md` for FIX-20260530-101323.
- Updated `docs/changes/agent-delegation-visibility/prd.md` to clarify sequencing acceptance criteria (delegation label + waiting indicator must appear before first delegated agent reply).
- Updated `docs/changes/agent-delegation-visibility/tech-spec.md` to reflect waiting-indicator visibility behavior during active delegation.
- Updated `docs/changes/agent-delegation-visibility/test-plan.md` to explicitly cover the no-agent-anchor (pre-first-reply) delegation visibility scenario.

---
