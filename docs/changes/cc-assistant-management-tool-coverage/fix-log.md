# Fix Log: cc-assistant-management-tool-coverage

This document tracks all bug fixes and issues resolved for this change.

---

## FIX-20261108-121000

**Created:** 2026-11-08T12:20:00Z
**Status:** Resolved
**Issue:** A2A delegation times out after 120s and the sub-agent execution log is unreachable; fixes from earlier today were not live.

### Observed Behavior
- Assistant delegation to a sub-agent (e.g. `airline-booking-agent`) hangs; AR polls `GET /internal/a2a/wait/<id>` every 90s with no reply, then the parent conversation turn dies with "Conversation turn timed out after 120s".
- The sub-agent execution log cannot be fetched (sub-session never progressed under the stale services).
- Earlier same-day fixes (activity watchdog, thinking indicator, revocation transport) appeared ineffective.

### Expected Behavior
Delegation stays alive (with a visible chat indicator) for as long as the sub-agent legitimately works; services restart cleanly with current code.

### Analysis
- **Affected components:** `backend/app/services/agents/langchain_tool_wrapper.py` (A2A poll loop), `scripts/restart-backend.sh` (stale-process cleanup), service lifecycle.
- **Root cause hypothesis:** (1) The A2A poll loop emits no status events, so the conversation watchdog sees no activity and cancels a healthy parent turn at the 120s bound. (2) Restart script `pkill -f "uvicorn …"` kills uvicorn parents but NOT their orphaned `multiprocessing.spawn` worker forks, which keep ports 8000/8001/8002 bound — new instances fail with `[Errno 48] address already in use` (confirmed in both AR and CH logs) and the stale pre-fix processes kept serving.
- **Documentation impact:** none beyond this log (operational + code fix).

### Fix Tasks
- [x] **Reproduce** — Log evidence: 90s-spaced A2A wait calls (12:06:14 → 12:07:45) followed by the 120s watchdog kill (12:08:08); `[Errno 48]` bind failures; orphaned `spawn_main` processes confirmed via `ps`.
- [x] **Fix** — (a) `langchain_tool_wrapper.py` A2A poll loop now re-emits `{"status": "waiting", agent_type, receiver_session_id}` on every still-running poll — resets the conversational watchdog's activity marker (turn extends while the sub-agent works) and keeps a visible chat indicator; (b) `scripts/restart-backend.sh` now kills any listener on ports 8000/8001/8002 directly, so orphaned workers can never hold the ports.
- [x] **Verify** — `pytest backend/tests/agent_runtime -k "deleg or hitl or timeout"`: 14 passed. Full restart: all three services fresh PIDs (12:15:08/12:15:21/12:15:25), health 200 on 8000/8001/8002, zero bind errors.
- [x] **Document** — This entry; parity/docs unaffected.

### Code Changes
- `backend/app/services/agents/langchain_tool_wrapper.py` — A2A poll loop emits waiting status per poll (activity + UI indicator).
- `scripts/restart-backend.sh` — port-listener kill for 8000/8001/8002 added.

### Verification Results
- Backend targeted suites: 14 passed.
- Live stack: fresh processes, all health probes 200, no bind errors in restart output.

---
