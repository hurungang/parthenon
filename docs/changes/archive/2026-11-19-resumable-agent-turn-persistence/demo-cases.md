# Demo Cases: resumable-agent-turn-persistence
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/resumable-agent-turn-persistence/demo-cases.md -->

## Grep Patterns
- Resumable Paused Turn Recovery (Mocked) > pending → approve → resumed and continuing → resolved (input re-enabled)
- Resumable Paused Turn Recovery (Mocked) > pending → deny → resolved without a terminal card
- Resumable Paused Turn Recovery (Mocked) > no-longer-resumable turn renders one reason-specific terminal card
- Resumable Paused Turn Recovery (Mocked) > a stale approval on a terminal turn is never sent
- Resumable Paused Turn Recovery (Mocked) > reload hydration restores the waiting state and the terminal message

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Approve after a pause (resume works) | The chat presents "Waiting for your input" backed by a live resume id; the operator approves once, the turn flips to "Resumed · continuing", keeps working through a real tool call, and ends as "Resolved" with the message input re-enabled and no misleading "delegated step timed out or failed" text. | `e2e/tests/conversation-resume-recovery.spec.ts` | pending → approve → resumed and continuing → resolved (input re-enabled) |
| 2 | Deny after a pause | The operator rejects the confirmation; the rejection is sent once, the turn reports "Resumed · continuing", resolves cleanly, and no terminal card is shown — a clean denial is not an error state. | `e2e/tests/conversation-resume-recovery.spec.ts` | pending → deny → resolved without a terminal card |
| 3 | Clear terminal outcome vocabulary | A no-longer-resumable turn renders exactly one reason-specific terminal card (expired) with what happened, what was not written, a next step, an "ask again" action and a dismiss action; the legacy generic timeout alert is gone and typing is possible again. | `e2e/tests/conversation-resume-recovery.spec.ts` | no-longer-resumable turn renders one reason-specific terminal card |
| 4 | Exactly-once guard on a stale approval | A confirmation that expires while the dialog is open is replaced by the "pause point could not be restored" card; a late approve click sends no response frame and shows "nothing to replay", proving a stale answer can never re-apply the confirmed write. | `e2e/tests/conversation-resume-recovery.spec.ts` | a stale approval on a terminal turn is never sent |
| 5 | Reconnect / reload hydration | After a full reload the chat rehydrates the persisted waiting state ("Waiting for your input") from activity state, and a terminal hydration preserves the reason so the same terminal card and "No longer resumable" state appear — reconnect matches the live push. | `e2e/tests/conversation-resume-recovery.spec.ts` | reload hydration restores the waiting state and the terminal message |
