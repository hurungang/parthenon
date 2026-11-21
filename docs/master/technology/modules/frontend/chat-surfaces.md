# Module: frontend — Chat Surfaces

> Part of the [frontend hub](tech-spec.md) · [technology documentation](../../README.md).

## Overview

This page covers every conversational surface: the generic conversation dialog and its session controls, the intervention (confirm-before-write) UX, connection-recovery and resumed-turn rendering, the seeded Control Center Assistant entry, and the **optimization-mode** chat surface used to talk to the optimizer.

All of them share one transport hook (`useChatSession`) over the Communication Hub WebSocket and one dialog component (`ConversationDialog`). Mode-specific chrome is layered on top; business conversations render none of it.

---

## Conversation dialog and session controls

| Component | Description |
|-----------|-------------|
| `ConversationDialog` | Dialog-based conversation surface for conversational agents and the assistant: message list, status chip/bubble lifecycle, inline interventions, terminal card, action bar, sessions view, reconnect recovery |
| `ChatInputBar` | Composer; disabled while a turn is in flight, a decision is pending, or the model is unconfigured |
| Action bar | **View All Sessions**, **New Session**, **End Session**, **Exit**; switch/end blocked while a turn is streaming |
| `SessionSwitcherList` | "View All Sessions" experience: show-ended switch (default off), From/To date inputs (last-7-days default), pagination (page size 10), time-desc rows, ended chip; in-place resume for active sessions only |
| `resetForSessionSwitch` / `handleStartNewSession` / `handleSwitchToSession` | Session switch/create/reset helpers (previous session stays active; no implicit end) |
| `mergeUnseenMessages` | Merges a resumed turn list into rendered + live messages (dedupe) so a reply produced during an outage renders after reconnect |
| `DEFAULT_SESSIONS_WINDOW_DAYS` / `SESSIONS_PAGE_SIZE` | Mirror the backend default window and page size |

## Status, delivery and recovery

The status model is persisted-authoritative: `activity_state` on connect and `status_pong` carry the Control Center activity row; live `chat_status` events update it. The bubble stays visible while a non-terminal state is active (including `using_tool` before an approval) and clears on a terminal state.

| Behaviour | Description |
|-----------|-------------|
| Activity bubble | Continuous indicator through thinking → using tool → delegating → waiting for your input; a stale working status alongside a pending/terminal confirmation renders no progressing bubble |
| Server-authoritative finality | An agent message clears the bubble only when it carries `final: true` (legacy fallback: final unless a working status is active) |
| Heartbeat self-heal | `thinking_heartbeat` restores a visible indicator if the bubble was blanked while the turn is still in flight |
| Terminal rendering | `finished` clears silently; failures show the warning alert with the server `message`; guardrail stops map to actionable copy |
| Resume vocabulary | waiting / resumed / resolved / no longer resumable; a live pause stays actionable, a dead one folds into a grey read-only block and re-enables input |
| `ResumeTerminalCard` | Reason-keyed terminal card (expired / resumed elsewhere / checkpoint lost / unexpectedly terminated) with "Ask again" (re-sends the last user request) and dismiss |
| Reconnect | Unexpected close mid-turn auto-reconnects with the SAME session id (max 5 attempts, `intentionalCloseRef` guard) and bumps `recoveryEpoch` so consumers re-fetch `/resume` |

## Interventions

| Component | Description |
|-----------|-------------|
| `InlineInterventionDialog` | Inline approval/choice/text card; renders the preview through `ContentRenderer` (markdown tables become tables) with an Expand toggle to a 90vw × 80vh full-width preview sharing the same Approve/Deny handlers |
| `InterventionPendingIndicator` | "Waiting for your input" indicator |
| `useConversationIntervention` | REST fetch/respond/cancel used to re-surface a pending decision on reconnect |

## Assistant surface

| Component | Description |
|-----------|-------------|
| `openAssistant` | Launcher: resolves the seeded `is_system` agent type, honours the per-agent-type force-new-session flag, otherwise opens the most recent ACTIVE session; the dialog mounts only after resolution |
| `assistantSessionState` | `markAssistantSessionEnded` / `consumeForceNewSessionFlag`: a plain exit keeps resume; an explicit End forces the next open to start fresh |
| `useAssistantModelConfig` | `GET /agents/model-configs/assistant-model` query (enabled flag keeps other surfaces from querying) |
| Assistant model guidance | In-dialog alert with "Configure model" → `/system-config`; input disabled; also triggered by the `assistant_model_not_configured` chat error |
| `ContentRenderer` (assistant) | Replies render in `auto` mode (sanitised HTML/markdown); user messages stay plain text |

## Optimization chat surface

Opened from the agent type's Optimized Plan tab. It is the same conversation dialog in optimization mode: the session is an optimization-channel conversation, the header names the subject agent, and identity parity ("runs as this agent") is a chip tooltip rather than a header block.

| Component | Description |
|-----------|-------------|
| `ConversationDialog` (`optimizationMode`) | Creates the session via `POST /conversations/optimization`; mode chip, model alert, optimization `chat_error`/`chat_blocked` alerts, inline ask/approval cards, resolved live-test evidence, activity block, detail/ledger invalidation on settle |
| `OptimizationSessionBar` | The only chat chrome above the transcript: compact, default-collapsed "What ran in this session" bar (replay / approved-live counts, replay-only or live-used chip, running chip) expanding to the audit block and identity/scope captions |
| `OptimizerAskCard` | Inline question: choice buttons + free-text answer; composer blocked while the decision is pending |
| `LiveTestApprovalCard` | Script-based approval ("Run this script live"): script name/version, informational tool-call preview, "runs once as this agent; MCP tools are assumed to work", expiry, approve/deny; collapses to a one-line history summary once decided, expandable to the script run record |
| `OptimizerActivityBlock` | Collapsible "working / worked — N steps" from the status stream with per-step tool name/state and terminal outcome |
| `OptimizerAuditBlock` | Replay verifications vs approved live operations, replay-only chip, single-use/attribution note, last live time |
| `OptimizerModelAlert` | Model-unavailable (unset/stale) guidance with an isolated System Config button |

---

## Code Reference Map

### Dialog, transport and recovery

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ConversationDialog` | component | Conversation surface (status, interventions, sessions, resume, optimization mode) | `frontend/src/components/agents/ConversationDialog.tsx` |
| `ChatInputBar` | component | Composer with blocked/disabled states | `frontend/src/components/agents/ConversationDialog.tsx` |
| `SessionSwitcherList` | component block | Paginated sessions view with ended switch and filters | `frontend/src/components/agents/ConversationDialog.tsx` |
| `resetForSessionSwitch` / `handleStartNewSession` / `handleSwitchToSession` / `mergeUnseenMessages` | functions | Session switch/create/reset and message merge | `frontend/src/components/agents/ConversationDialog.tsx` |
| `DEFAULT_SESSIONS_WINDOW_DAYS` / `SESSIONS_PAGE_SIZE` | constants | Sessions window/page defaults | `frontend/src/components/agents/ConversationDialog.tsx` |
| `useChatSession` | hook | WS lifecycle, status/activity parsing, finality, resume vocabulary, intervention and live-test state, reconnect | `frontend/src/hooks/useChatSession.ts` |
| `ChatStatus` / `ChatStatusKind` / `TERMINAL_CHAT_STATUS_KINDS` / `isTerminalChatStatusKind` | types / constant / function | Status model and terminal detection | `frontend/src/hooks/useChatSession.ts` |
| `parseChatStatus` / `parseActivityState` / `activityStateFromPayload` | functions | Live status and hydration parsing (server message + resume fields preserved) | `frontend/src/hooks/useChatSession.ts` |
| `markTurnInFlight` / `isTurnInFlight` | functions | In-flight window | `frontend/src/hooks/useChatSession.ts` |
| `ChatRole` / `ChatMessage` / `DelegationSnippetLine` | types | Chat rendering models | `frontend/src/hooks/useChatSession.ts` |
| `useConversationSessions` / `useConversationSessionsPage` | hooks | Sessions queries (legacy + paginated) | `frontend/src/hooks/useConversationSessions.ts` |
| `useConversationIntervention` | hook | Intervention fetch/respond/cancel | `frontend/src/hooks/useConversationIntervention.ts` |
| `ResumeTerminalCard` | component | Reason-keyed terminal card with "Ask again" | `frontend/src/components/conversations/ResumeTerminalCard.tsx` |

### Interventions

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `InlineInterventionDialog` | component | Inline approval/choice/text card with expandable preview | `frontend/src/components/conversations/InlineInterventionDialog.tsx` |
| `InterventionPendingIndicator` | component | "Waiting for your input" indicator | `frontend/src/components/conversations/InterventionPendingIndicator.tsx` |
| `InterveneRequestMessage` / `InterveneResponseMessage` / `InterveneCancelMessage` / `InterveneStatusMessage` / `ChatBlockedMessage` / `InterventionWsMessage` | types | WebSocket intervention contract | `frontend/src/types/index.ts` |
| `IntervenePage` / `InterveneRequestList` / `InterveneResponseDialog` / `useInterveneRequests` / `interveneApi` | page / components / hook / module | Dashboard intervention list and response dialog (unchanged path) | `frontend/src/pages/agents/IntervenePage.tsx`, `frontend/src/components/agents/InterveneRequestList.tsx`, `InterveneResponseDialog.tsx`, `frontend/src/hooks/useInterveneRequests.ts`, `frontend/src/api/interveneApi.ts` |

### Assistant

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `openAssistant` | handler | Assistant launcher/resolve (latest active session or force-new) | `frontend/src/app/AppShell.tsx` |
| Assistant launcher (FAB) | component usage | Floating entry point with resolving spinner | `frontend/src/app/AppShell.tsx` |
| `assistantSessionState` (`markAssistantSessionEnded`, `consumeForceNewSessionFlag`) | utility module | Force-new-session flag and ended marking | `frontend/src/utils/assistantSessionState.ts` |
| `useAssistantModelConfig` | hook | Assistant model selection query | `frontend/src/hooks/useAssistantModelConfig.ts` |
| `ConversationDialog` (assistant) | component behaviour | Model-unconfigured guidance alert + disabled input | `frontend/src/components/agents/ConversationDialog.tsx` |

### Optimizer

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ConversationDialog` (optimization mode) | component behaviour | Mode chip, model alert, ask/approval cards, activity, ledger invalidation | `frontend/src/components/agents/ConversationDialog.tsx` |
| `OptimizationSessionBar` | component | Collapsed "what ran in this session" bar + audit expansion | `frontend/src/components/optimizer/OptimizationSessionBar.tsx` |
| `LiveTestApprovalCard` | component | Script-based live-test approval and collapsed history summary | `frontend/src/components/optimizer/LiveTestApprovalCard.tsx` |
| `OptimizerAskCard` | component | Inline question card | `frontend/src/components/optimizer/OptimizerAskCard.tsx` |
| `OptimizerActivityBlock` | component | Collapsible activity/step block | `frontend/src/components/optimizer/OptimizerActivityBlock.tsx` |
| `OptimizerAuditBlock` | component | Replay vs live audit detail | `frontend/src/components/optimizer/OptimizerAuditBlock.tsx` |
| `OptimizerModelAlert` / `OptimizerSystemConfigButton` | components | Model-unavailable guidance and shortcut | `frontend/src/components/optimizer/OptimizerModelAlert.tsx` |
| `useOptimizationConversation` | hook | Create/read optimization conversation, availability, ledger, query keys, card-state mapping | `frontend/src/hooks/useOptimizationConversation.ts` |
| `useOptimizerModelConfig` | hook | Optimizer model read/save/clear-to-inherit | `frontend/src/hooks/useOptimizerModelConfig.ts` |
| `useOptimizationGate` | hook | Gate/conversation-availability fields and localized reasons | `frontend/src/hooks/useOptimizationGate.ts` |
| `errorUtils` optimizer helpers | functions | `isOptimizerModelReasonCode`, `isOptimizerChatErrorCode`, `isDecisionPendingBlock`, `isLiveTestRefusalCode`, `extractOptimizerRefusal` | `frontend/src/utils/errorUtils.ts` |
| `OptimizationConversation(Detail)` / `OptimizationAvailability` / `OptimizationAudit` / `OptimizerModelConfig` / `LiveTestRequest` / `ScriptRunRecord` / `LiveTestApprovalSummary` / `LiveTestCardState` | types | Optimizer wire types | `frontend/src/types/index.ts` |

### Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ConversationDialog.actionBar` / `.sessionsView` / `.resumeLiveDelivery` | tests | Action bar, sessions view, reconnect reply delivery | `frontend/src/__tests__/ConversationDialog.actionBar.test.tsx`, `ConversationDialog.sessionsView.test.tsx`, `ConversationDialog.resumeLiveDelivery.test.tsx` |
| `ConversationDialog.usingTool` / `.activityBubble` / `.resumeRecovery` | tests | Tool-phase indicator, bubble lifecycle, four-state recovery + terminal card | `frontend/src/__tests__/ConversationDialog.usingTool.test.tsx`, `ConversationDialog.activityBubble.test.tsx`, `ConversationDialog.resumeRecovery.test.tsx` |
| `useChatSession.interventionGap` / `.finality` / `.activityIndicator` / `.activityState` / `.optimizer` | tests | No blank gap, finality, activity indicator/hydration, optimizer payload parsing | `frontend/src/__tests__/useChatSession.interventionGap.test.ts`, `useChatSession.finality.test.ts`, `useChatSession.activityIndicator.test.ts`, `useChatSession.activityState.test.ts`, `useChatSession.optimizer.test.ts` |
| `OptimizerChatDialog` / `OptimizerPanels` / `LiveTestApprovalCard` / `OptimizerAskCard` | tests | Optimizer mode chrome, panels, approval card, ask card | `frontend/src/__tests__/OptimizerChatDialog.test.tsx`, `OptimizerPanels.test.tsx`, `LiveTestApprovalCard.test.tsx`, `OptimizerAskCard.test.tsx` |
| `useOptimizationConversation` / `useOptimizerModelConfig` / `errorUtils.optimizer` / `optimizerI18n` | tests | Optimizer hooks, error extraction, translation completeness | `frontend/src/__tests__/useOptimizationConversation.test.tsx`, `useOptimizerModelConfig.test.tsx`, `errorUtils.optimizer.test.ts`, `optimizerI18n.test.ts` |
| `ControlCenterAssistantEntry` / `AppShell.assistantSession` / `AssistantModelConfigGuidance` | tests | Launcher, session resume/force-new, model guidance | `frontend/src/__tests__/ControlCenterAssistantEntry.test.tsx`, `AppShell.assistantSession.test.tsx`, `AssistantModelConfigGuidance.test.tsx` |
| `agent-optimizer-conversation.spec.ts` / `agent-optimizer-live-test-approval.spec.ts` / `agent-optimizer-model-config.spec.ts` / `agent-optimizer.real-backend.spec.ts` / `conversation-intervention.spec.ts` | E2E tests | Optimizer conversation, approval, model config, real-backend and HITL round-trips | `e2e/tests/` |
