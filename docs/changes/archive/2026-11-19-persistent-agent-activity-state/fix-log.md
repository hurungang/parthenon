# Fix Log: persistent-agent-activity-state

This document tracks all bug fixes and issues resolved for this change.

---

## FIX-20261111-082435

**Created:** 2026-11-11T08:24:35Z
**Status:** Resolved
**Issue:** Processing bubble shows "thinking" then goes blank during the management-tool phase, before the intervention dialog — even though the client's status is correct.

### Observed Behavior
Browser console proved the client state was correct the whole time (`chatStatus = using_tool` + tool name, `turnInFlight=true`), yet the dialog rendered **no** indicator between "thinking" and the intervention dialog.

### Expected Behavior
The "Using tool <name>…" indicator should render continuously while a tool is executing.

### Analysis
- **Affected component:** `frontend/src/components/agents/ConversationDialog.tsx` (status-indicator visibility flags).
- **Root cause (proven via the server `WS->client` log + browser `[chatStatus]` trace):** `using_tool` creates an EMPTY delegation cycle that `filterEmptyDelegationCycles` drops. The visibility flags were computed from `effectiveDelegationCycles.length` and the raw `activeDelegationCycleId`:
  - `shouldShowStandaloneDelegationStatus = effectiveDelegationCycles.length === 0 && …` → **false** whenever the session already had ANY delegation cycles (e.g. resumed delegation history).
  - `cycleLiveStatusVisible = effectiveDelegationCycles.length > 0 && effectiveActiveDelegationCycleId != null && …` → **true** even though the active id pointed at the filtered (non-rendered) `using_tool` cycle.
  - Result: `showThinking` was suppressed (because `cycleLiveStatusVisible` was true) AND the in-cycle status never rendered (the active cycle wasn't rendered) → **blank**.
  - A session with no delegation history masked the bug (standalone path rendered), which is why it was intermittent.

### Fix
- Added `activeCycleRendered` = the active cycle id is actually present in `effectiveDelegationCycles`.
- `shouldShowStandaloneDelegationStatus` now gates on `!activeCycleRendered` (not `length === 0`).
- `cycleLiveStatusVisible` now gates on `activeCycleRendered` (not `length > 0`).
- Net effect: whenever the active cycle isn't rendered, the standalone status line renders; when it is rendered, the in-cycle line renders — one of them is always visible.

### Test Cases Added/Modified
- `frontend/src/__tests__/ConversationDialog.usingTool.test.tsx` — new regression: resumed delegation history exists **and** the active cycle is a filtered empty `using_tool` cycle → still renders "Using tool …" (failed before the fix).

### Verification Results
- `tsc` clean; targeted suites (usingTool, delegation visibility, activity indicator/bubble, dialog, finality, gap) **35/35**; full suite re-run.

---

## FIX-20261111-014618

**Created:** 2026-11-11T01:46:18Z
**Status:** Issue 1 fixed (bubble no longer vanishes during the tool phase); Issue 2 clarity fixed; true restart-resume still requires a persistent checkpointer (open follow-up)
**Issue:** Resume issues: (1) reopening a session while the assistant is thinking shows the processing bubble briefly, then it disappears until the intervention dialog; (2) after restarting the service and acting on a pending human intervention, the user gets "Delegated step timed out or failed."

### Observed Behavior
- **Issue 1:** While `thinking`, exit the session and reopen it → the processing bubble appears briefly ("flips") then disappears until the intervention dialog pops up.
- **Issue 2:** Restart a backend service while an intervention is pending, resume the session, then approve/deny → "Delegated step timed out or failed. Please try again."

### Expected Behavior
- Issue 1: reopening mid-turn restores and keeps the persisted activity indicator.
- Issue 2: after a restart, acting on a pending intervention resumes the turn (or, at minimum, fails with a clear, actionable message instead of a misleading "Delegated step timed out or failed").

### Analysis
- **Issue 2 (confirmed root cause):** the conversational turn is held entirely in Agent Runtime process memory — the LangGraph checkpointer is `MemorySaver()` (`runtime_executor.py`) and the pause/resume mechanism is the in-process `app/agent_runtime/conversation_resume.py` registry. A service restart destroys both. When the operator responds, CH forwards to AR `/internal/resume`, AR reports `not_awaiting`, and `app/communication_hub/api/internal/agent_resume.py` surfaces a terminal `timeout_or_failed` (log-proven: "Orphaned resume: delivered terminal timeout_or_failed status … (status=not_awaiting)").
- **Issue 1 / thinking-bubble gap (confirmed root cause — this is a REGRESSION fix):** an in-flight agent message arriving while the current status is `using_tool` (the confirm-before-write tool-calling phase) was misclassified as the turn's FINAL reply by `isIntermediateMidTurn` (it only recognized `delegating`/`waiting`/`delegation_resumed`). That called `markTurnInFlight(false)` and cleared `chatStatus` to `null` → the bubble vanished. Including `using_tool`/`waiting_for_human` keeps the indicator visible through the tool phase. Confirmed by user testing: the bubble persists with the fix and disappears without it.
- **Issue 2 (required architecture):** true resume-after-restart needs a **persistent LangGraph checkpointer** (keyed by `thread_id = conv_session_id`) plus re-hydration of the pending intervention, so `Command(resume=...)` can continue the paused graph on a restarted AR. No persistent saver is currently installed (`langgraph.checkpoint.postgres`/`redis` absent); because AR must not connect to the database, a Redis-backed or CC-mediated store is the viable option. This is the remaining core of the "resumable agent" goal and warrants its own scoped change.

### Fix Tasks
- [x] **Reproduce** — failing hook test (agent message during `using_tool` → bubble blanked / turnInFlight false).
- [x] **Fix (Issue 1)** — include `using_tool` and `waiting_for_human` in `isIntermediateMidTurn`.
- [x] **Fix (final-reply clearing)** — CH emits an authoritative terminal `finished` status on successful completion, so the bubble clears from a real signal rather than guessing from the agent message; `finished` clears silently (no per-reply banner).
- [x] **Fix (Issue 2 clarity)** — surface the specific terminal `message` in the UI instead of the generic label.
- [ ] **Fix (Issue 2 resume)** — persistent checkpointer + pending-turn rehydration (follow-up change).

### Code Changes
**Modified by:** conductor (es-developer role)
**Timestamp:** 2026-11-11T01:46:18Z

- `frontend/src/hooks/useChatSession.ts`
  - Server-authoritative finality: an agent message only clears the bubble when it carries `final: true` (legacy fallback: final unless a working status is active). Non-final in-flight messages keep a visible indicator.
  - `isIntermediateMidTurn` no longer requires an active delegation cycle — the confirm-before-write preamble can arrive before any tool creates a cycle.
  - `thinking_heartbeat` restores a visible thinking indicator if the bubble was ever blanked while the turn is still in flight (self-healing safety net).
  - `ChatStatus.message` captured from the status payload.
- `frontend/src/components/agents/ConversationDialog.tsx` — terminal alert prefers `chatStatus.message`; `finished` clears silently (no per-reply banner); failures still show the warning alert.
- `backend/app/api/ws/chat.py`
  - `run_conversation_turn` emits a terminal `chat_status finished` after a successful reply (skipped when the turn ended in `timeout_or_failed`/guardrail).
  - The three agent-message sends (`deliver_reply`, generic error, persisted error) now carry `final: True` so the client clears the bubble from an explicit signal, not a guess.
  - Added a temporary `WS->client` INFO log (type/status/role/tool/final/len) to diagnose exactly what the client receives (to be removed after verification).
  - Activity hydration is defensive against sockets without `.app`.

### Test Cases Added/Modified
- `frontend/src/__tests__/useChatSession.interventionGap.test.ts` (new) — full sequence (thinking → using_tool → silence → intervene_request) never blanks.
- `frontend/src/__tests__/ConversationDialog.usingTool.test.tsx` (new) — `using_tool` renders "Using tool …" with/without an (empty) delegation cycle.
- `frontend/src/__tests__/useChatSession.finality.test.ts` (new) — non-final message keeps the bubble; `final: true` clears; heartbeat restores.
- `frontend/src/__tests__/useChatSession.activityIndicator.test.ts` — (b2) updated: in-flight agent message is intermediate; terminal `finished` clears.
- `frontend/src/__tests__/ConversationDialog.activityBubble.test.tsx` — `finished` clears silently.

### Verification Results
**Verified by:** conductor
**Timestamp:** 2026-11-11T01:46:18Z

- **Frontend:** `tsc --noEmit` clean; targeted suites 48/48 passing; full suite re-run.
- **Backend:** `app.api.ws.chat` imports clean.

---

## FIX-20261110-225332

**Created:** 2026-11-10T22:53:32Z
**Status:** Resolved
**Issue:** Thinking bubble disappears (~30s) before the human-intervention dialog popup; persisted activity state was never written.

### Observed Behavior
In a conversational (Control Center Assistant) turn that triggers a confirm-before-write human intervention, the chat window showed "thinking", then the bubble went blank for ~30s, and only then did the intervention popup appear. There was no "waiting for your input" status during the transition.

### Expected Behavior
The chat should show a continuous indicator: thinking → calling tools → waiting for your input → intervention popup, with no blank gap — driven by the persisted activity state, not solely by Agent Runtime's response stream.

### Analysis
- **Affected components:** `backend/app/api/deps.py` — Communication Hub internal allowlist; `backend/app/api/v1/internal/system_tools.py` — `human_intervene_tool`.
- **Root cause (two defects, both log-confirmed):**
  1. The `PUT`/`GET` `/internal/data/conversations/{conv_session_id}/activity` routes were never added to `_CH_ALLOWLIST`, so **every** CH activity upsert/hydrate was rejected with 403 `internal.allowlist.denied` / `endpoint_not_allowlisted`. The persisted activity state was never written (log: repeated `Activity upsert failed ... returned 403: endpoint_not_allowlisted`).
  2. The conversational `human_intervene` path never persisted a `waiting_for_human` state (the tool avoids LangGraph `interrupt()` for conversational turns), so CC created the `InterveneRequest` without recording the activity state.

### Fix Tasks
- [x] **Reproduce** — added regression tests (allowlist membership; human_intervene → persisted `waiting_for_human`).
- [x] **Fix** — registered activity routes in `_CH_ALLOWLIST`; persist `waiting_for_human` in `human_intervene_tool`.
- [x] **Verify** — 98 activity/system-tools backend tests pass.
- [x] **Document** — fix log + test-plan references updated.

### Test Cases Added/Modified
- `backend/tests/unit/test_internal_allowlist_activity.py`
- `backend/tests/unit/test_human_intervene_persists_activity.py`

### Code Changes
**Modified by:** conductor (es-developer role)
**Timestamp:** 2026-11-10T22:53:32Z

- `backend/app/api/deps.py` — added `("PUT", .../activity)` and `("GET", .../activity)` to `_CH_ALLOWLIST`.
- `backend/app/api/v1/internal/system_tools.py` — `human_intervene_tool` upserts `ConversationActivity` → `waiting_for_human` (with `pending_intervene_request_id`) for conversation-scoped interventions.

### Verification Results
**Verified by:** conductor
**Timestamp:** 2026-11-10T22:53:32Z

- **Backend (activity/system-tools):** ✓ 98 passed

---
