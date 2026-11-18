import { useCallback, useEffect, useRef, useState } from 'react'
import { API_CONFIG } from '../api/API_CONFIG'
import apiClient from '../api/apiClient'
import { normalizeResumeState } from '../utils/resumeState'
import type { ResumeState } from '../utils/resumeState'
import type {
  InterventionType,
  InterveneRequestMessage,
  LiveTestApprovalSummary,
  LiveTestOperation,
  LiveTestResultMessage,
  LiveTestStatus,
  ScriptRunRecord,
  ScriptRunToolCall,
} from '../types'

export type { ResumeState }
export { hasLiveResume, isActionableWaiting } from '../utils/resumeState'

export type ChatRole = 'user' | 'agent' | 'system'

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  timestamp: string
  /** Persisted turn type — set for history turns so intervene Q&A turns can
   * be rendered as resolved-intervention bubbles instead of plain text. */
  turnType?: 'message' | 'intervene_request' | 'intervene_response'
  /** Links an intervene turn pair (question ↔ response) for grouping. */
  interveneRequestId?: string | null
}

export interface ConversationalGuardrailUsage {
  policySnapshotId: string | null
  tokenUsageCurrentSession: number | null
  tokenBudget: number | null
  cumulativeIterations: number | null
  maxIterations: number | null
  delegatedSteps: number | null
  maxDelegatedSteps: number | null
  delegationDepth: number | null
  maxDelegationDepth: number | null
}

export type ChatStatusKind =
  | 'thinking'
  | 'delegating'
  | 'waiting'
  | 'using_tool'
  | 'waiting_for_human'
  | 'delegation_resumed'
  | 'timeout_or_failed'
  // Persisted ActivityState values (conversation_activity) — surfaced via the
  // `activity_state` hydration push and enriched `status_pong` answers.
  | 'finished'
  | 'failed'
  | 'timed_out'

/** Persisted activity states that end a conversational turn. */
export const TERMINAL_CHAT_STATUS_KINDS: readonly ChatStatusKind[] = [
  'timeout_or_failed',
  'finished',
  'failed',
  'timed_out',
]

export function isTerminalChatStatusKind(kind: ChatStatusKind): boolean {
  return TERMINAL_CHAT_STATUS_KINDS.includes(kind)
}

export interface ChatStatus {
  kind: ChatStatusKind
  agentType: string | null
  toolName: string | null
  receiverSessionId: string | null
  timestamp: string
  /** True when the persisted activity carries a pending human intervention. */
  pendingIntervention?: boolean
  /** Optional human-readable detail (e.g. the reason a turn was interrupted
   * by a service restart) — surfaced instead of the generic terminal label. */
  message?: string
  /** Durable resume state projected by the server (absent for turns that never
   * paused, e.g. plain thinking/finished legs). */
  resumeState?: ResumeState | null
  /** Live resume-record id backing this status. It is the only structural
   * proof that a pause is still answerable — "shown as waiting" must never
   * drift from "actually resumable". */
  activeResumeId?: string | null
  /** Durable terminal reason code (`expired`, `checkpoint_unavailable`, …). */
  terminalReason?: string | null
  /** True when the status came from persisted-activity hydration
   * (`activity_state` / `status_pong`) rather than the live status stream. A
   * hydrated `waiting_for_human` without a live resume id is stale. */
  persisted?: boolean
}

export interface DelegationSnippetLine {
  id: string
  kind: 'delegating' | 'waiting' | 'using_tool' | 'log_title'
  agentType: string | null
  toolName: string | null
  logTitle: string | null
  timestamp: string
}

export interface DelegationCycle {
  id: string
  startedAt: string
  snippets: DelegationSnippetLine[]
  snippetsCollapsed: boolean
  completed: boolean
  executionLogAvailable: boolean
  executionSessionId: string | null
}

export interface DelegationHistoryHydration {
  cycles: DelegationCycle[]
}

export interface ChatError {
  code: string
  message: string
}

// ── Client-side status watchdog ────────────────────────────────────────────
// If no WS traffic of any kind arrives for this long while a turn is in
// flight, the client can no longer trust that the connection is healthy
// (silently-dropped sockets, sleep/wake, dead upstream turn). It then pings
// the server for the authoritative state and surfaces a "checking" hint.
const STATUS_STALE_THRESHOLD_MS = 60_000
// If the status ping itself goes unanswered for this long, the socket is
// presumed dead even though the browser may not have fired onclose yet —
// force-close it so the existing reconnect + recovery path takes over.
const STATUS_STALE_HARD_LIMIT_MS = 90_000
const WATCHDOG_TICK_MS = 5_000

interface ExecutionLogListEntry {
  id: string
  timestamp: string
  message?: string | null
}

function createDelegationCycle(startedAt: string): DelegationCycle {
  return {
    id: crypto.randomUUID(),
    startedAt,
    snippets: [],
    snippetsCollapsed: true,
    completed: false,
    executionLogAvailable: false,
    executionSessionId: null,
  }
}

function normalizeToolDisplayName(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null
  }

  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

function normalizeDelegatedAgentType(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null
  }

  const trimmed = value.trim()
  if (!trimmed) {
    return null
  }

  if (trimmed.startsWith('agent____') && trimmed.length > 'agent____'.length) {
    return trimmed.slice('agent____'.length)
  }

  if (trimmed.startsWith('agent__') && trimmed.length > 'agent__'.length) {
    return trimmed.slice('agent__'.length)
  }

  return trimmed
}

const PERSISTED_ACTIVITY_STATES: readonly ChatStatusKind[] = [
  'thinking',
  'using_tool',
  'delegating',
  'waiting_for_human',
  'finished',
  'failed',
  'timed_out',
]

function isChatStatusKind(value: unknown): value is ChatStatusKind {
  return (
    value === 'thinking' ||
    value === 'delegating' ||
    value === 'waiting' ||
    value === 'using_tool' ||
    value === 'waiting_for_human' ||
    value === 'timeout_or_failed' ||
    value === 'delegation_resumed' ||
    value === 'finished' ||
    value === 'failed' ||
    value === 'timed_out'
  )
}

function normalizeOptionalText(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null
  }
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

/**
 * Extracts the durable-resume projection carried by an `activity_state`
 * hydration push, a `status_pong` answer, or a `chat_status` event. All three
 * use snake_case wire keys.
 */
function resumeProjectionFromPayload(payload: Record<string, unknown>): {
  activeResumeId: string | null
  resumeState: ResumeState | null
  terminalReason: string | null
  message?: string
} {
  const message = normalizeOptionalText(payload['message'])
  return {
    activeResumeId: normalizeOptionalText(payload['active_resume_id']),
    resumeState: normalizeResumeState(payload['resume_state']),
    terminalReason: normalizeOptionalText(payload['terminal_reason_code']),
    ...(message ? { message } : {}),
  }
}

/**
 * Maps a persisted-activity payload (`state` + optional context) to the
 * normalized `ChatStatus` shape. A null/absent state (idle session) yields
 * null. Used by both the `activity_state` connect-hydration push and the
 * reworked `status_pong` answer.
 *
 * The durable-resume projection (live resume id, resume state, terminal reason
 * and the server-rendered message) is preserved so a reconnect renders exactly
 * what the live socket would have shown.
 */
function activityStateFromPayload(payload: Record<string, unknown>): ChatStatus | null {
  const state = payload['state']
  if (!isChatStatusKind(state) || !PERSISTED_ACTIVITY_STATES.includes(state)) {
    return null
  }

  const timestamp = typeof payload['timestamp'] === 'string'
    ? payload['timestamp']
    : new Date().toISOString()
  const projection = resumeProjectionFromPayload(payload)

  return {
    kind: state,
    agentType: normalizeDelegatedAgentType(payload['agent_type']),
    toolName: normalizeToolDisplayName(payload['tool_name']),
    receiverSessionId: null,
    timestamp,
    pendingIntervention: payload['pending_intervention'] === true,
    activeResumeId: projection.activeResumeId,
    resumeState: projection.resumeState,
    terminalReason: projection.terminalReason,
    ...(projection.message ? { message: projection.message } : {}),
    // Hydration provenance — lets the dialog tell a stale persisted wait from
    // a live pause whose request object has not arrived yet.
    persisted: true,
  }
}

/** Parses the `activity_state` hydration message pushed on WebSocket connect. */
export function parseActivityState(value: unknown): ChatStatus | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }
  const payload = value as Record<string, unknown>
  if (payload['type'] !== 'activity_state') {
    return null
  }
  return activityStateFromPayload(payload)
}

function parseChatStatus(value: unknown): ChatStatus | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }

  const payload = value as Record<string, unknown>
  const type = payload['type']
  if (type !== 'chat_status') {
    return null
  }

  const status = payload['status']
  if (
    !isChatStatusKind(status)
  ) {
    return null
  }

  const timestamp = typeof payload['timestamp'] === 'string'
    ? payload['timestamp']
    : new Date().toISOString()
  const projection = resumeProjectionFromPayload(payload)
  const receiverSessionId = normalizeOptionalText(payload['receiver_session_id'])

  return {
    kind: status,
    agentType: normalizeDelegatedAgentType(payload['agent_type']),
    toolName: normalizeToolDisplayName(payload['tool_name']),
    receiverSessionId,
    timestamp,
    // Live wire statuses carry the same optional resume projection — keep them
    // so a resumed/terminal turn renders identically on both paths.
    activeResumeId: projection.activeResumeId,
    resumeState: projection.resumeState,
    terminalReason: projection.terminalReason,
    // Provenance: a live status is not persisted-activity hydration.
    persisted: false,
    ...(projection.message ? { message: projection.message } : {}),
  }
}

function toDelegationSnippetLine(status: ChatStatus): DelegationSnippetLine | null {
  if (status.kind === 'delegating' && status.agentType) {
    return {
      id: crypto.randomUUID(),
      kind: 'delegating',
      agentType: status.agentType,
      toolName: null,
      logTitle: null,
      timestamp: status.timestamp,
    }
  }

  if (status.kind === 'waiting' && status.agentType) {
    return {
      id: crypto.randomUUID(),
      kind: 'waiting',
      agentType: status.agentType,
      toolName: null,
      logTitle: null,
      timestamp: status.timestamp,
    }
  }

  // Note: 'using_tool' snippets are intentionally NOT added to the delegation
  // cycle panel — they represent regular MCP/system tool execution, not agent
  // delegation.  The standalone status line (statusUsingTool) handles them
  // separately in ConversationDialog.

  return null
}

function toNullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function pickRecordValue(payload: Record<string, unknown>, snakeKey: string, camelKey: string): unknown {
  if (snakeKey in payload) {
    return payload[snakeKey]
  }
  return payload[camelKey]
}

function parseGuardrailUsage(value: unknown): ConversationalGuardrailUsage | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }

  const payload = value as Record<string, unknown>
  return {
    policySnapshotId: (() => {
      const raw = pickRecordValue(payload, 'policy_snapshot_id', 'policySnapshotId')
      return typeof raw === 'string' ? raw : null
    })(),
    tokenUsageCurrentSession: toNullableNumber(
      pickRecordValue(payload, 'token_usage_current_session', 'tokenUsageCurrentSession'),
    ),
    tokenBudget: toNullableNumber(pickRecordValue(payload, 'token_budget', 'tokenBudget')),
    cumulativeIterations: toNullableNumber(
      pickRecordValue(payload, 'cumulative_iterations', 'cumulativeIterations'),
    ),
    maxIterations: toNullableNumber(pickRecordValue(payload, 'max_iterations', 'maxIterations')),
    delegatedSteps: toNullableNumber(pickRecordValue(payload, 'delegated_steps', 'delegatedSteps')),
    maxDelegatedSteps: toNullableNumber(
      pickRecordValue(payload, 'max_delegated_steps', 'maxDelegatedSteps'),
    ),
    delegationDepth: toNullableNumber(pickRecordValue(payload, 'delegation_depth', 'delegationDepth')),
    maxDelegationDepth: toNullableNumber(
      pickRecordValue(payload, 'max_delegation_depth', 'maxDelegationDepth'),
    ),
  }
}

/**
 * One step of the visible turn activity ("what it looked at"). Derived from the
 * live status stream so the optimizer chat can expand tool calls without a new
 * endpoint; a step is `running` until the next tool call or the turn's end.
 */
export interface ChatActivityStep {
  id: string
  toolName: string | null
  state: 'running' | 'done'
  timestamp: string
}

/** A `chat_blocked` chunk — the input is refused while a decision is pending. */
export interface ChatBlockedState {
  reason: string
  message: string
  liveTestRequestId: string | null
  expiresAt: string | null
}

/** Latest authoritative answer to a decision (`intervene_status` chunk). */
export interface InterventionStatusState {
  requestId: string
  status: 'pending' | 'responded' | 'cancelled' | 'expired' | 'error'
  timestamp: string
}

const LIVE_TEST_STATUSES: readonly LiveTestStatus[] = [
  'pending',
  'approved',
  'executed',
  'failed',
  'denied',
  'expired',
  'cancelled',
]

function normalizeLiveTestStatus(value: unknown): LiveTestStatus {
  return typeof value === 'string' && (LIVE_TEST_STATUSES as readonly string[]).includes(value)
    ? (value as LiveTestStatus)
    : 'pending'
}

function normalizeLiveTestOperations(value: unknown): LiveTestOperation[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((entry): entry is Record<string, unknown> => !!entry && typeof entry === 'object')
    .map((entry) => ({
      tool_name: typeof entry['tool_name'] === 'string' ? entry['tool_name'] : '',
      arguments:
        entry['arguments'] && typeof entry['arguments'] === 'object' && !Array.isArray(entry['arguments'])
          ? (entry['arguments'] as Record<string, unknown>)
          : {},
      purpose: typeof entry['purpose'] === 'string' ? entry['purpose'] : null,
    }))
}

function normalizeLiveTestOutcomes(value: unknown): ScriptRunRecord[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((entry): entry is Record<string, unknown> => !!entry && typeof entry === 'object')
    .map((entry) => {
      const toolCalls = Array.isArray(entry['tool_calls'])
        ? entry['tool_calls'].filter(
            (call): call is Record<string, unknown> => !!call && typeof call === 'object',
          )
        : []
      return {
        kind: typeof entry['kind'] === 'string' ? entry['kind'] : 'script_run',
        script_version_id:
          typeof entry['script_version_id'] === 'string' ? entry['script_version_id'] : null,
        script_name: typeof entry['script_name'] === 'string' ? entry['script_name'] : null,
        script_version_label:
          typeof entry['script_version_label'] === 'string'
            ? entry['script_version_label']
            : null,
        status: typeof entry['status'] === 'string' ? entry['status'] : 'error',
        result_summary:
          typeof entry['result_summary'] === 'string' ? entry['result_summary'] : null,
        error: typeof entry['error'] === 'string' ? entry['error'] : null,
        duration_ms: typeof entry['duration_ms'] === 'number' ? entry['duration_ms'] : null,
        tool_calls: toolCalls.map(
          (call): ScriptRunToolCall => ({
            tool_name: typeof call['tool_name'] === 'string' ? call['tool_name'] : '',
            status: typeof call['status'] === 'string' ? call['status'] : 'error',
            duration_ms:
              typeof call['duration_ms'] === 'number' ? call['duration_ms'] : null,
            result_summary:
              typeof call['result_summary'] === 'string' ? call['result_summary'] : null,
            error: typeof call['error'] === 'string' ? call['error'] : null,
          }),
        ),
        telemetry:
          entry['telemetry'] && typeof entry['telemetry'] === 'object'
            ? (entry['telemetry'] as Record<string, unknown>)
            : {},
      }
    })
}

/**
 * Parses the optional `live_test` block carried by an `intervene_request` (live
 * dispatch AND reconnect re-surface). Plain ask/decide requests have none.
 */
export function parseLiveTestApproval(value: unknown): LiveTestApprovalSummary | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const payload = value as Record<string, unknown>
  const requestId = payload['live_test_request_id']
  if (typeof requestId !== 'string' || !requestId) return null
  const executed = normalizeLiveTestOutcomes(payload['executed_operations'])
  return {
    live_test_request_id: requestId,
    status: normalizeLiveTestStatus(payload['status']),
    expires_at: typeof payload['expires_at'] === 'string' ? payload['expires_at'] : null,
    script_version_id:
      typeof payload['script_version_id'] === 'string' ? payload['script_version_id'] : null,
    script_name: typeof payload['script_name'] === 'string' ? payload['script_name'] : null,
    script_version_label:
      typeof payload['script_version_label'] === 'string'
        ? payload['script_version_label']
        : null,
    operations: normalizeLiveTestOperations(payload['operations']),
    executed_operations: executed.length > 0 ? executed : null,
    target_agent_type_id:
      typeof payload['target_agent_type_id'] === 'string'
        ? payload['target_agent_type_id']
        : null,
  }
}

/**
 * Parses the `live_test_result` chunk emitted after an approved live test runs
 * (before the resumed reply) so the card can be replaced with the script run
 * record.
 */
export function parseLiveTestResult(value: unknown): LiveTestResultMessage | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const payload = value as Record<string, unknown>
  if (payload['type'] !== 'live_test_result') return null
  const requestId = payload['live_test_request_id']
  if (typeof requestId !== 'string' || !requestId) return null
  const status = payload['live_test_status'] === 'failed' ? 'failed' : 'executed'
  const records = normalizeLiveTestOutcomes(payload['executed_operations'])
  const scriptRun = normalizeLiveTestOutcomes(
    payload['script_run'] != null ? [payload['script_run']] : [],
  )[0] ?? records[0] ?? null
  return {
    type: 'live_test_result',
    live_test_request_id: requestId,
    live_test_status: status,
    script_version_id:
      typeof payload['script_version_id'] === 'string' ? payload['script_version_id'] : null,
    script_run: scriptRun,
    executed_operations: records.length > 0 ? records : scriptRun ? [scriptRun] : [],
    live_test_error:
      typeof payload['live_test_error'] === 'string' ? payload['live_test_error'] : null,
  }
}

/**
 * Manages WebSocket connection lifecycle, inbound message queue,
 * pending question state, and reconnection for a chat session.
 */
export function useChatSession(sessionId: string | null, convSessionId?: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [connected, setConnected] = useState(false)
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null)
  const [sessionTitle, setSessionTitle] = useState<string | null>(null)
  const [guardrailUsage, setGuardrailUsage] = useState<ConversationalGuardrailUsage | null>(null)
  const [chatStatus, setChatStatus] = useState<ChatStatus | null>(null)
  const [chatError, setChatError] = useState<ChatError | null>(null)
  const [delegationCycles, setDelegationCycles] = useState<DelegationCycle[]>([])
  const [activeDelegationCycleId, setActiveDelegationCycleId] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const outboundQueueRef = useRef<string[]>([])
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // FIX-20261031-071721 (defect 1): live-delivery loss on unexpected WS close.
  // When the socket drops mid-turn (the reply is generated after the close, so
  // it is never transmitted and only shows up after exit/reopen), the hook now
  // (a) reconnects automatically with the SAME session id and (b) bumps
  // `recoveryEpoch` once reconnected while a turn was in flight, so the
  // dialog can refetch the persisted history and render the missed reply.
  const intentionalCloseRef = useRef(false)
  const reconnectAttemptsRef = useRef(0)
  const turnInFlightAtDisconnectRef = useRef(false)
  // FIX: invariant — from the moment the user sends a message until the
  // turn's final agent reply (or a terminal timeout_or_failed status), the
  // UI must always render an activity indicator regardless of which
  // chatStatus transitions occur. `turnInFlight` tracks that window
  // explicitly so the dialog can fall back to a thinking-equivalent when a
  // status change would otherwise render nothing.
  const [turnInFlight, setTurnInFlight] = useState(false)
  const turnInFlightRef = useRef(false)
  const [recoveryEpoch, setRecoveryEpoch] = useState(0)
  const chatStatusRef = useRef<ChatStatus | null>(null)
  const delegationCyclesRef = useRef<DelegationCycle[]>([])
  const activeDelegationCycleIdRef = useRef<string | null>(null)
  const seenExecutionLogIdsByCycleRef = useRef<Map<string, Set<string>>>(new Map())
  const pendingNewDelegationCycleRef = useRef(false)

  // Intervention state
  const [interventionRequest, setInterventionRequest] = useState<InterveneRequestMessage | null>(null)
  const [interventionQueueLength, _setInterventionQueueLength] = useState(0)
  const interventionActiveRef = useRef(false)
  // True once a message was sent (or queued) after the current socket
  // connected. The connect-time `activity_state` hydration snapshot predates
  // any such message, so it must not clobber the optimistic in-flight state
  // (the live status stream / status_pong reconcile it afterwards).
  const localSendSinceConnectRef = useRef(false)
  // Hydrated pending-intervention flag: true when the persisted activity (or a
  // live waiting_for_human status) reports an unresolved intervention but no
  // request object has (yet) arrived — drives the pending-intervention
  // indicator without fabricating a request payload.
  const [pendingIntervention, setPendingIntervention] = useState(false)

  // ── Optimization-mode projections (additive; unused by business chats) ────
  // Per-request `live_test_result` chunks — the approval card swaps the pending
  // operation list for what actually ran.
  const [liveTestResults, setLiveTestResults] = useState<Record<string, LiveTestResultMessage>>({})
  // Latest decision answer for a request (`intervene_status`), so an approval
  // card that is no longer actionable can distinguish denied / expired.
  const [interventionStatus, setInterventionStatus] = useState<InterventionStatusState | null>(null)
  // A `chat_blocked` chunk — input is refused while a decision is pending.
  const [chatBlocked, setChatBlocked] = useState<ChatBlockedState | null>(null)
  // Visible turn activity: tool calls seen on the live status stream.
  const [activitySteps, setActivitySteps] = useState<ChatActivityStep[]>([])

  // Status watchdog state: last inbound WS traffic timestamp (ANY message —
  // chat messages, status events, heartbeats) and whether the current status
  // has gone stale past the threshold.
  const lastActivityAtRef = useRef<number>(Date.now())
  const [statusStale, setStatusStale] = useState(false)

  useEffect(() => {
    chatStatusRef.current = chatStatus
  }, [chatStatus])

  useEffect(() => {
    turnInFlightRef.current = turnInFlight
  }, [turnInFlight])

  const markTurnInFlight = useCallback((inFlight: boolean) => {
    turnInFlightRef.current = inFlight
    setTurnInFlight(inFlight)
  }, [])

  useEffect(() => {
    delegationCyclesRef.current = delegationCycles
  }, [delegationCycles])

  useEffect(() => {
    activeDelegationCycleIdRef.current = activeDelegationCycleId
  }, [activeDelegationCycleId])

  const flushOutboundQueue = useCallback(() => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return
    if (outboundQueueRef.current.length === 0) return

    const queued = [...outboundQueueRef.current]
    outboundQueueRef.current = []
    for (const content of queued) {
      wsRef.current.send(JSON.stringify({ message: content }))
    }
  }, [])

  /** True when a conversational turn is still being processed (reply not yet received). */
  const isTurnInFlight = useCallback((): boolean => {
    const kind = chatStatusRef.current?.kind
    return (
      kind === 'thinking' ||
      kind === 'delegating' ||
      kind === 'waiting' ||
      kind === 'using_tool' ||
      kind === 'waiting_for_human' ||
      kind === 'delegation_resumed'
    )
  }, [])

  const connect = useCallback(() => {
    if (!sessionId) return
    intentionalCloseRef.current = false

    const token = localStorage.getItem('access_token')
    let wsUrl = `${API_CONFIG.WS_BASE_URL}/sessions/${sessionId}?token=${token ?? ''}`
    if (convSessionId) {
      wsUrl += `&conv_session_id=${convSessionId}`
    }
    const ws = new WebSocket(wsUrl)
    // FIX-20261110 (new-session routing): capture this socket instance so
    // handlers can detect when it has been superseded. When the dialog
    // switches sessions (e.g. "New Session"), the effect cleanup closes the
    // old socket — but that socket's `onclose` fires ASYNCHRONOUSLY, after
    // the new `connect()` has already reset `intentionalCloseRef`. Without
    // a staleness check, the old socket's close handler treats the switch
    // as an unexpected drop and reconnects to the OLD session, overwriting
    // `wsRef.current` — so subsequent user messages were routed to (and
    // persisted in) the previous conversation session instead of the new one.
    const socket = ws
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      reconnectAttemptsRef.current = 0
      lastActivityAtRef.current = Date.now()
      setStatusStale(false)
      localSendSinceConnectRef.current = false
      flushOutboundQueue()
      // A queued message flushed right at connect starts a new turn whose
      // persisted state does not exist yet — the hydration snapshot must
      // not clobber it.
      if (outboundQueueRef.current.length > 0) {
        localSendSinceConnectRef.current = true
      }
      // If a turn was in flight while the socket was down, its reply may have
      // been missed — signal the dialog to refresh persisted history.
      if (turnInFlightAtDisconnectRef.current) {
        turnInFlightAtDisconnectRef.current = false
        // The turn is still running server-side — restore a visible activity
        // indicator (a stale/pre-close kind may no longer render) until the
        // recovered reply or the next status event arrives.
        setChatStatus({
          kind: 'thinking',
          agentType: chatStatusRef.current?.agentType ?? null,
          toolName: null,
          receiverSessionId: null,
          timestamp: new Date().toISOString(),
        })
        // The turn is still running server-side — keep the in-flight window
        // open so the fallback indicator stays visible until the reply lands.
        markTurnInFlight(true)
        setRecoveryEpoch((epoch) => epoch + 1)
      }
    }

    ws.onmessage = (event: MessageEvent<string>) => {
      // Stale socket: a superseded connection (session switch) must never
      // inject messages into the current session's timeline.
      if (wsRef.current !== socket) {
        return
      }
      // Any inbound traffic is proof the connection is alive — reset the
      // watchdog clock and clear the stale hint.
      lastActivityAtRef.current = Date.now()
      setStatusStale(false)
      try {
        const data = JSON.parse(event.data) as {
          type?: string
          title?: string
          sender_role?: ChatRole
          content?: string
          timestamp?: string
          guardrail_usage?: unknown
          status?: string
          agent_type?: string
          request_id?: string
          intervention_type?: string
          reason?: string
          choices?: string[]
          delegation_depth?: number
          conversation_session_id?: string
          code?: string
          message?: string
          turn_in_flight?: boolean
          intervention_pending?: boolean
          is_terminal?: boolean
          state?: string
          tool_name?: string
          final?: boolean
          live_test?: unknown
          live_test_request_id?: string
          live_test_status?: string
          live_test_error?: string
          executed_operations?: unknown
          intervene_request_id?: string
          expires_at?: string
        }

        // ── Handle intervention messages ───────────────────────────────────
        if (data.type === 'intervene_request') {
          const interveneMsg: InterveneRequestMessage = {
            type: 'intervene_request',
            request_id: data.request_id ?? '',
            intervention_type: (data.intervention_type as InterventionType) ?? 'approval',
            reason: data.reason ?? '',
            choices: data.choices,
            agent_type: data.agent_type,
            delegation_depth: data.delegation_depth ?? 0,
            conversation_session_id: data.conversation_session_id ?? '',
            // Optimization live-test approvals carry the exact operation list +
            // expiry so the card renders identically after a reconnect.
            live_test: parseLiveTestApproval(data.live_test),
          }
          setInterventionRequest(interveneMsg)
          interventionActiveRef.current = true
          setPendingIntervention(true)
          setChatBlocked(null)
          setInterventionStatus(null)
          setActivitySteps((prev) => prev.map((step) => ({ ...step, state: 'done' as const })))
          setChatStatus({
            kind: 'waiting_for_human',
            agentType: data.agent_type ?? null,
            toolName: null,
            receiverSessionId: null,
            timestamp: new Date().toISOString(),
          })
          return
        }

        if (data.type === 'live_test_result') {
          const result = parseLiveTestResult(data)
          if (result) {
            setLiveTestResults((prev) => ({
              ...prev,
              [result.live_test_request_id]: result,
            }))
          }
          return
        }

        if (data.type === 'intervene_status') {
          const statusVal = data.status
          if (statusVal === 'responded' || statusVal === 'cancelled' || statusVal === 'expired') {
            setInterventionStatus({
              requestId: data.request_id ?? '',
              status: statusVal,
              timestamp: new Date().toISOString(),
            })
            setInterventionRequest(null)
            interventionActiveRef.current = false
            setPendingIntervention(false)
            setChatStatus((prev) => {
              // FIX-20261110: a terminal status must never be overwritten by
              // the post-response demotion (e.g. a durably unresumable turn
              // delivered one right after the response was persisted) — the
              // turn is over and nothing will replace it, which left the
              // thinking bubble stuck forever.
              if (prev && isTerminalChatStatusKind(prev.kind)) {
                return prev
              }
              const agentType = prev?.agentType ?? null
              if (statusVal === 'responded') {
                // The turn is processing again — show the ordinary thinking
                // indicator. A normal in-process approval is NOT a "resumed"
                // turn (no chip); the resumed vocabulary comes only from server
                // hydration after a real reconnect/restart.
                return {
                  kind: 'thinking',
                  agentType,
                  toolName: null,
                  receiverSessionId: null,
                  timestamp: new Date().toISOString(),
                }
              }
              return { kind: 'waiting', agentType, toolName: null, receiverSessionId: null, timestamp: new Date().toISOString() }
            })
            if (statusVal === 'responded') {
              // The turn resumed server-side — open the in-flight window so
              // the status watchdog covers the post-response silence (if the
              // resumed turn hangs or the socket dies, polling kicks in). If
              // a terminal status was just delivered, the next status_pong
              // closes the window again — self-correcting either way.
              markTurnInFlight(true)
            }
          }
          return
        }

        if (data.type === 'chat_error') {
          const code = typeof data.code === 'string' ? data.code : ''
          if (code) {
            setChatError({
              code,
              message: typeof data.message === 'string' ? data.message : '',
            })
          }
          return
        }

        if (data.type === 'chat_blocked') {
          // The message was refused because a decision is pending (an
          // intervention, including an optimization live-test approval).
          // Surface the reason so the dialog can block input and point at the
          // pending card instead of silently dropping what was typed.
          setChatBlocked({
            reason: typeof data.reason === 'string' ? data.reason : 'decision_pending',
            message: typeof data.message === 'string' ? data.message : '',
            liveTestRequestId:
              typeof data.live_test_request_id === 'string' ? data.live_test_request_id : null,
            expiresAt: typeof data.expires_at === 'string' ? data.expires_at : null,
          })
          return
        }

        // ── Connect-time hydration (persisted activity state) ───────────────
        // CH pushes the persisted ConversationActivity on every (re)connect.
        // Reconcile chatStatus / in-flight window / pending-intervention flag
        // from it — a non-terminal state re-opens the in-flight window
        // immediately (no blank gap on a mid-turn reconnect), a terminal
        // state closes it, and `waiting_for_human` re-arms the intervention
        // flag so the pending indicator re-surfaces after a reload.
        if (data.type === 'activity_state') {
          // A message already sent/queued for this connection started a NEW
          // turn — the hydration snapshot predates it and would wrongly
          // clear the optimistic in-flight indicator. The live status
          // stream / status_pong reconcile the real state instead.
          if (localSendSinceConnectRef.current) {
            return
          }
          const hydrated = parseActivityState(data)
          if (hydrated) {
            setChatStatus(hydrated)
            if (isTerminalChatStatusKind(hydrated.kind)) {
              markTurnInFlight(false)
              interventionActiveRef.current = false
              setPendingIntervention(false)
            } else {
              markTurnInFlight(true)
              if (hydrated.kind === 'waiting_for_human' && hydrated.pendingIntervention) {
                interventionActiveRef.current = true
                setPendingIntervention(true)
              }
            }
          } else {
            // Explicit null state — the session is idle: clear any lingering
            // client-side status instead of keeping a stale bubble. Never
            // clear an optimistically-open in-flight window though: a
            // queued message flushed right at reconnect can race the
            // hydration push (the server persisted state is still null) —
            // the watchdog/status stream reconciles it afterwards.
            if (!turnInFlightRef.current) {
              setChatStatus(null)
              markTurnInFlight(false)
              interventionActiveRef.current = false
              setPendingIntervention(false)
            }
          }
          return
        }

        // ── Watchdog reconciliation (reply to our status_ping) ─────────────
        // The server reports the authoritative turn state — now derived from
        // the persisted ConversationActivity. If it disagrees with what the
        // client believes (e.g. the turn already finished but the final reply
        // / intervention event was lost to a dead socket), bump
        // `recoveryEpoch` so the dialog refetches persisted history and the
        // missed reply or pending intervention becomes visible.
        if (data.type === 'status_pong') {
          const serverTurnInFlight = data.turn_in_flight === true
          const serverInterventionPending = data.intervention_pending === true
          const pongActivity = activityStateFromPayload(data as Record<string, unknown>)
          if (pongActivity) {
            // Persisted state available — reconcile directly from it.
            setChatStatus(pongActivity)
            if (isTerminalChatStatusKind(pongActivity.kind)) {
              if (turnInFlightRef.current) {
                // We never received the final reply / terminal event —
                // trigger the persisted-history recovery path.
                setRecoveryEpoch((epoch) => epoch + 1)
              }
              markTurnInFlight(false)
              interventionActiveRef.current = false
              setPendingIntervention(false)
            } else if (pongActivity.kind === 'waiting_for_human' && pongActivity.pendingIntervention) {
              if (!interventionActiveRef.current) {
                // The pending intervention request object never arrived —
                // the recovery refetch restores it.
                setRecoveryEpoch((epoch) => epoch + 1)
              }
              interventionActiveRef.current = true
              setPendingIntervention(true)
              markTurnInFlight(true)
            } else {
              markTurnInFlight(true)
            }
            return
          }
          if (
            turnInFlightRef.current &&
            !serverTurnInFlight &&
            !serverInterventionPending
          ) {
            // Server says the turn is over but we never got the final reply —
            // trigger the persisted-history recovery path.
            markTurnInFlight(false)
            setChatStatus(null)
            setRecoveryEpoch((epoch) => epoch + 1)
          } else if (serverInterventionPending && !interventionActiveRef.current) {
            // A pending intervention exists server-side but never arrived —
            // recovery refetch restores it.
            setRecoveryEpoch((epoch) => epoch + 1)
          }
          return
        }

        // FIX-20261031-091657: app-level keepalive from the CH while a turn is
        // in flight — refreshes the status timestamp so the indicator stays
        // visibly alive during long turns. If the bubble was blanked while the
        // turn is still in flight (e.g. an intermediate message cleared it),
        // the heartbeat restores a visible thinking indicator.
        if (data.type === 'chat_status' && data.status === 'thinking_heartbeat') {
          setChatStatus((prev) =>
            prev
              ? { ...prev, timestamp: new Date().toISOString() }
              : turnInFlightRef.current
                ? {
                    kind: 'thinking',
                    agentType: null,
                    toolName: null,
                    receiverSessionId: null,
                    timestamp: new Date().toISOString(),
                  }
                : prev,
          )
          return
        }

        const parsedStatus = parseChatStatus(data)
        if (parsedStatus) {
          const isDelegationKind =
            parsedStatus.kind === 'delegating' ||
            parsedStatus.kind === 'waiting' ||
            parsedStatus.kind === 'using_tool'

          setChatStatus(parsedStatus)

          // Visible turn activity: every tool call becomes a step; starting a
          // new one closes the previous (a turn ends by closing the last).
          if (parsedStatus.kind === 'using_tool' && parsedStatus.toolName) {
            const step: ChatActivityStep = {
              id: crypto.randomUUID(),
              toolName: parsedStatus.toolName,
              state: 'running',
              timestamp: parsedStatus.timestamp,
            }
            setActivitySteps((prev) => [
              ...prev.map((existing) => ({ ...existing, state: 'done' as const })),
              step,
            ])
          }

          if (isTerminalChatStatusKind(parsedStatus.kind)) {
            // Terminal status — the turn is over; close the in-flight window
            // and disarm the pending-intervention flag.
            markTurnInFlight(false)
            interventionActiveRef.current = false
            setPendingIntervention(false)
            setActivitySteps((prev) => prev.map((step) => ({ ...step, state: 'done' as const })))
          }

          if (parsedStatus.kind === 'waiting_for_human') {
            // Server-pushed pause — surface the pending-intervention
            // indicator continuously (no blank gap between the agent pausing
            // and the intervene_request arriving). When the payload carries
            // the persisted pending flag, arm the intervention state so
            // message sends stay blocked until it resolves.
            if (parsedStatus.pendingIntervention) {
              interventionActiveRef.current = true
              setPendingIntervention(true)
            }
            return
          }

          if (parsedStatus.kind === 'delegation_resumed') {
            // FIX: `delegation_resumed` has no dedicated rendering in
            // ConversationDialog (thinking bubble / standalone line / in-cycle
            // line all exclude it), and `thinking_heartbeat` preserves the
            // previous kind forever — so the window went blank while the parent
            // agent kept working after a delegation resumed. Store it as a
            // `thinking`-equivalent so an indicator is always visible.
            setChatStatus({
              kind: 'thinking',
              agentType: parsedStatus.agentType,
              toolName: null,
              receiverSessionId: parsedStatus.receiverSessionId,
              timestamp: parsedStatus.timestamp,
            })
            const targetCycleId = activeDelegationCycleIdRef.current
            if (targetCycleId) {
              const resumeLine: DelegationSnippetLine = {
                id: crypto.randomUUID(),
                kind: 'waiting',
                agentType: parsedStatus.agentType,
                toolName: null,
                logTitle: null,
                timestamp: parsedStatus.timestamp,
              }
              setDelegationCycles((prev) =>
                prev.map((cycle) =>
                  cycle.id === targetCycleId
                    ? {
                        ...cycle,
                        snippets: [...cycle.snippets, resumeLine],
                      }
                    : cycle,
                ),
              )
            }
            return
          }

          if (!isDelegationKind) {
            return
          }

          let nextActiveCycleId = activeDelegationCycleIdRef.current
          const shouldStartNewCycle = pendingNewDelegationCycleRef.current || !nextActiveCycleId
          if (shouldStartNewCycle) {
            const startedAt = parsedStatus.timestamp ?? new Date().toISOString()
            const cycle = createDelegationCycle(startedAt)
            nextActiveCycleId = cycle.id
            activeDelegationCycleIdRef.current = cycle.id
            delegationCyclesRef.current = [...delegationCyclesRef.current, cycle]
            setDelegationCycles((prev) => [...prev, cycle])
            setActiveDelegationCycleId(cycle.id)
            seenExecutionLogIdsByCycleRef.current.set(cycle.id, new Set())
            pendingNewDelegationCycleRef.current = false
          }

          const targetCycleId = nextActiveCycleId
          if (!targetCycleId) {
            return
          }

          if (!seenExecutionLogIdsByCycleRef.current.has(targetCycleId)) {
            seenExecutionLogIdsByCycleRef.current.set(targetCycleId, new Set())
          }

          const snippetLine = toDelegationSnippetLine(parsedStatus)
          setDelegationCycles((prev) =>
            prev.map((cycle) => {
              if (cycle.id !== targetCycleId) {
                return cycle
              }

              let nextSnippets = cycle.snippets
              if (snippetLine) {
                const last = cycle.snippets[cycle.snippets.length - 1]
                if (
                  !last ||
                  last.kind !== snippetLine.kind ||
                  last.agentType !== snippetLine.agentType ||
                  last.toolName !== snippetLine.toolName
                ) {
                  nextSnippets = [...cycle.snippets, snippetLine]
                }
              }

              return {
                ...cycle,
                snippets: nextSnippets,
                executionSessionId: parsedStatus.receiverSessionId ?? cycle.executionSessionId,
                executionLogAvailable: cycle.executionLogAvailable || Boolean(parsedStatus.receiverSessionId),
              }
            }),
          )

          return
        }

        // Handle title_update server event without adding it to messages
        if (data.type === 'title_update' && data.title) {
          setSessionTitle(data.title)
          return
        }

        if (data.type === 'guardrail_update') {
          const parsed = parseGuardrailUsage(data.guardrail_usage)
          if (parsed) {
            setGuardrailUsage(parsed)
          }
          return
        }

        // Guard: server events with no textual content (e.g. an empty
        // chat_message emitted when a turn suspends on an intervention)
        // must never render as an empty bubble.
        const rawContent = typeof data.content === 'string' ? data.content : ''
        if (!rawContent.trim()) {
          return
        }

        const msg: ChatMessage = {
          id: crypto.randomUUID(),
          role: data.sender_role ?? 'agent',
          content: rawContent,
          timestamp: data.timestamp ?? new Date().toISOString(),
        }
        setMessages((prev) => [...prev, msg])

        if (data.sender_role === 'agent') {
          pendingNewDelegationCycleRef.current = false
          const statusKind = chatStatusRef.current?.kind
          const hadDelegationInFlight =
            statusKind === 'delegating' ||
            statusKind === 'waiting' ||
            statusKind === 'using_tool' ||
            statusKind === 'delegation_resumed' ||
            statusKind === 'waiting_for_human'

          const targetCycleId = activeDelegationCycleIdRef.current
          if (hadDelegationInFlight && targetCycleId) {
            setDelegationCycles((prev) =>
              prev.map((cycle) =>
                cycle.id === targetCycleId
                  ? {
                      ...cycle,
                      completed: true,
                      executionLogAvailable: cycle.executionLogAvailable || Boolean(cycle.executionSessionId),
                    }
                  : cycle,
              ),
            )
          }
        }

        if (data.sender_role === 'agent') {
          const isAskUserTurn = (data.content ?? '').startsWith('?')
          const wasTurnInFlight = turnInFlightRef.current
          const statusKindNow = chatStatusRef.current?.kind
          // A message is the turn's FINAL reply when the server marks it with
          // `final: true`. Legacy fallback (no flag): final when the turn is
          // not in flight, or when no working status is active. In-flight
          // messages during a working status are INTERMEDIATE and must not
          // blank the bubble — that is exactly the confirm-before-write gap
          // where the indicator vanished while the agent kept calling tools.
          const isWorkingKind =
            statusKindNow === 'delegating' ||
            statusKindNow === 'waiting' ||
            statusKindNow === 'using_tool' ||
            statusKindNow === 'waiting_for_human' ||
            statusKindNow === 'delegation_resumed'
          const isFinal =
            typeof data.final === 'boolean'
              ? data.final
              : !wasTurnInFlight || !isWorkingKind
          const isIntermediateMidTurn = wasTurnInFlight && !isFinal

          if (wasTurnInFlight && isFinal) {
            // The turn's final reply arrived — close the in-flight window.
            markTurnInFlight(false)
            setActivitySteps((prev) => prev.map((step) => ({ ...step, state: 'done' as const })))
          }
          setChatStatus((prev) => {
            if (prev && isTerminalChatStatusKind(prev.kind)) return prev
            if (isAskUserTurn || isIntermediateMidTurn) {
              // Mid-turn message: the turn keeps running — keep a visible
              // indicator instead of blanking the window.
              return {
                kind: 'thinking',
                agentType: prev?.agentType ?? null,
                toolName: null,
                receiverSessionId: null,
                timestamp: new Date().toISOString(),
              }
            }
            // Final reply (explicit flag, or legacy non-working / not-in-flight
            // message): clear the indicator.
            return null
          })
        }
        if (data.sender_role === 'agent' && (data.content ?? '').startsWith('?')) {
          setPendingQuestion(data.content ?? null)
        }
      } catch {
        // ignore parse errors
      }
    }

    ws.onclose = () => {
      // Stale socket guard (FIX-20261110): if this socket was superseded by a
      // session switch or a newer reconnect, its closure is expected cleanup —
      // never update connection state and NEVER schedule a reconnect from a
      // stale closure (that would resurrect the old session's socket).
      if (wsRef.current !== socket) {
        return
      }
      setConnected(false)
      // Unexpected close while a turn is still processing: remember it so the
      // reconnect can recover the missed reply, and reconnect automatically.
      // (Auto-reconnect is intentional here — without it a mid-turn disconnect
      // permanently loses the live response; intentional unmount closes are
      // marked via intentionalCloseRef and never reconnect.)
      if (isTurnInFlight()) {
        turnInFlightAtDisconnectRef.current = true
      }
      if (intentionalCloseRef.current || reconnectAttemptsRef.current >= 5) {
        return
      }
      reconnectAttemptsRef.current += 1
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = setTimeout(() => connect(), 1500)
    }

    ws.onerror = () => ws.close()
  }, [sessionId, convSessionId, flushOutboundQueue, markTurnInFlight])

  const activeDelegationCycle =
    delegationCycles.find((cycle) => cycle.id === activeDelegationCycleId) ?? null

  useEffect(() => {
    if (!sessionId) {
      return
    }

    const shouldPollLogs =
      chatStatus?.kind === 'delegating' ||
      chatStatus?.kind === 'waiting' ||
      chatStatus?.kind === 'waiting_for_human' ||
      chatStatus?.kind === 'using_tool'

    if (!activeDelegationCycleId) {
      return
    }

    if (!activeDelegationCycle?.executionSessionId) {
      return
    }

    if (!shouldPollLogs) {
      return
    }

    // Skip polling in tests to prevent hangs from persistent intervals
    if ((typeof window !== 'undefined' && (window as any).__VITEST__)) {
      return
    }

    let cancelled = false

    const fetchExecutionLogTitles = async () => {
      try {
        const { data } = await apiClient.get<ExecutionLogListEntry[]>(
          `/agents/sessions/${activeDelegationCycle.executionSessionId}/logs`,
        )

        if (cancelled || !Array.isArray(data)) {
          return
        }

        const seenIds = seenExecutionLogIdsByCycleRef.current.get(activeDelegationCycleId) ?? new Set<string>()
        seenExecutionLogIdsByCycleRef.current.set(activeDelegationCycleId, seenIds)

        const newLines: DelegationSnippetLine[] = []
        for (const entry of data) {
          if (!entry?.id || seenIds.has(entry.id)) {
            continue
          }
          seenIds.add(entry.id)

          const title = typeof entry.message === 'string' ? entry.message.trim() : ''
          if (!title) {
            continue
          }

          newLines.push({
            id: `log-${entry.id}`,
            kind: 'log_title',
            agentType: null,
            toolName: null,
            logTitle: title,
            timestamp: entry.timestamp || new Date().toISOString(),
          })
        }

        if (newLines.length > 0) {
          setDelegationCycles((prev) =>
            prev.map((cycle) =>
              cycle.id === activeDelegationCycleId
                ? {
                    ...cycle,
                    executionLogAvailable: true,
                    snippets: [...cycle.snippets, ...newLines],
                  }
                : cycle,
            ),
          )
        }
      } catch {
        // Best-effort streaming enhancement only.
      }
    }

    void fetchExecutionLogTitles()
    const timer = setInterval(() => {
      void fetchExecutionLogTitles()
    }, 1500)

    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [sessionId, chatStatus?.kind, activeDelegationCycleId, activeDelegationCycle?.executionSessionId])

  useEffect(() => {
    connect()
    return () => {
      // Mark the close as intentional so onclose never schedules a reconnect
      // for a torn-down dialog.
      intentionalCloseRef.current = true
      // Dialog closed or session switched — the in-flight window belongs to
      // the previous turn and must not leak into the next session.
      markTurnInFlight(false)
      wsRef.current?.close()
      outboundQueueRef.current = []
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
    }
  }, [connect])

  // ── Status watchdog ────────────────────────────────────────────────────────
  // While a turn is in flight, silence on the WS is ambiguous: the agent may
  // just be thinking, or the connection may be silently dead. After the stale
  // threshold, ping the server for authoritative state (and surface a
  // "checking status" hint in the UI); if even the ping goes unanswered,
  // force-close the socket so the reconnect + recovery path takes over.
  useEffect(() => {
    if (typeof window !== 'undefined' && (window as unknown as { __VITEST__?: boolean }).__VITEST__) {
      return
    }
    const timer = setInterval(() => {
      if (!turnInFlightRef.current || interventionActiveRef.current) {
        setStatusStale(false)
        return
      }
      const idleMs = Date.now() - lastActivityAtRef.current
      if (idleMs < STATUS_STALE_THRESHOLD_MS) {
        return
      }
      setStatusStale(true)
      const ws = wsRef.current
      if (idleMs >= STATUS_STALE_HARD_LIMIT_MS) {
        // Even the status_ping got no reply — the socket is presumed dead.
        // Force-close so onclose schedules the reconnect; the in-flight
        // flag makes that reconnect run the history recovery.
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.close()
        }
        return
      }
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'status_ping' }))
      }
    }, WATCHDOG_TICK_MS)
    return () => clearInterval(timer)
  }, [])

  const sendMessage = useCallback((content: string) => {
    if (!content.trim()) return false

    // Block messages when intervention is active
    if (interventionActiveRef.current) {
      return false
    }

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ message: content }))
    } else {
      outboundQueueRef.current.push(content)
    }

    const msg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
      timestamp: new Date().toISOString(),
    }
    pendingNewDelegationCycleRef.current = true
    localSendSinceConnectRef.current = true
    setMessages((prev) => [...prev, msg])
    // The turn is in flight from the moment the user message is sent until
    // its final agent reply (or a terminal status) — keeps an indicator
    // visible regardless of intermediate status transitions.
    markTurnInFlight(true)
    // The watchdog clock starts from the send, not from the last unrelated
    // traffic — otherwise a long-idle session would go stale immediately.
    lastActivityAtRef.current = Date.now()
    setStatusStale(false)
    setChatStatus({
      kind: 'thinking',
      agentType: null,
      toolName: null,
      receiverSessionId: null,
      timestamp: new Date().toISOString(),
    })
    setPendingQuestion(null)
    setChatError(null)
    // A fresh message starts a fresh activity group and clears the "decision
    // pending" refusal notice from a previous attempt.
    setActivitySteps([])
    setChatBlocked(null)
    return true
  }, [])

  const clearMessages = useCallback(() => {
    delegationCyclesRef.current = []
    activeDelegationCycleIdRef.current = null
    setMessages([])
    setDelegationCycles([])
    setActiveDelegationCycleId(null)
    seenExecutionLogIdsByCycleRef.current = new Map()
    pendingNewDelegationCycleRef.current = false
    // Session switch / new optimization session: the previous session's
    // activity, decisions and live-test evidence never leak into the next one.
    setActivitySteps([])
    setLiveTestResults({})
    setInterventionStatus(null)
    setChatBlocked(null)
  }, [])

  const toggleDelegationSnippetsCollapsed = useCallback(() => {
    const targetCycleId = activeDelegationCycleIdRef.current
    if (!targetCycleId) {
      const cycle = createDelegationCycle(new Date().toISOString())
      cycle.snippetsCollapsed = false
      activeDelegationCycleIdRef.current = cycle.id
      delegationCyclesRef.current = [...delegationCyclesRef.current, cycle]
      setDelegationCycles((prev) => [...prev, cycle])
      setActiveDelegationCycleId(cycle.id)
      return
    }

    setDelegationCycles((prev) =>
      prev.map((cycle) =>
        cycle.id === targetCycleId
          ? { ...cycle, snippetsCollapsed: !cycle.snippetsCollapsed }
          : cycle,
      ),
    )
  }, [])

  const setDelegationSnippetsCollapsed = useCallback((collapsed: boolean) => {
    const targetCycleId = activeDelegationCycleIdRef.current
    if (!targetCycleId) {
      const cycle = createDelegationCycle(new Date().toISOString())
      cycle.snippetsCollapsed = collapsed
      activeDelegationCycleIdRef.current = cycle.id
      delegationCyclesRef.current = [...delegationCyclesRef.current, cycle]
      setDelegationCycles((prev) => [...prev, cycle])
      setActiveDelegationCycleId(cycle.id)
      return
    }

    setDelegationCycles((prev) =>
      prev.map((cycle) =>
        cycle.id === targetCycleId
          ? { ...cycle, snippetsCollapsed: collapsed }
          : cycle,
      ),
    )
  }, [])

  const hydrateDelegationFromHistory = useCallback((history: DelegationHistoryHydration) => {
    const nextCycles = Array.isArray(history.cycles)
      ? history.cycles.map((cycle) => ({
          ...cycle,
          snippets: Array.isArray(cycle.snippets) ? cycle.snippets : [],
          snippetsCollapsed: typeof cycle.snippetsCollapsed === 'boolean' ? cycle.snippetsCollapsed : true,
          completed: typeof cycle.completed === 'boolean' ? cycle.completed : true,
          executionLogAvailable: Boolean(cycle.executionLogAvailable),
          executionSessionId:
            typeof cycle.executionSessionId === 'string' && cycle.executionSessionId.trim().length > 0
              ? cycle.executionSessionId.trim()
              : null,
        }))
      : []

    seenExecutionLogIdsByCycleRef.current = new Map()
    for (const cycle of nextCycles) {
      seenExecutionLogIdsByCycleRef.current.set(cycle.id, new Set())
    }

    setDelegationCycles(nextCycles)
    setActiveDelegationCycleId(nextCycles.length > 0 ? nextCycles[nextCycles.length - 1].id : null)
    delegationCyclesRef.current = nextCycles
    activeDelegationCycleIdRef.current = nextCycles.length > 0 ? nextCycles[nextCycles.length - 1].id : null
    pendingNewDelegationCycleRef.current = false

    for (const cycle of nextCycles) {
      if (!cycle.executionSessionId) {
        continue
      }

      void apiClient
        .get<ExecutionLogListEntry[]>(`/agents/sessions/${cycle.executionSessionId}/logs`)
        .then(({ data }) => {
          if (!Array.isArray(data)) {
            return
          }

          const seenIds = seenExecutionLogIdsByCycleRef.current.get(cycle.id) ?? new Set<string>()
          seenExecutionLogIdsByCycleRef.current.set(cycle.id, seenIds)

          const logLines: DelegationSnippetLine[] = []
          for (const entry of data) {
            if (!entry?.id || seenIds.has(entry.id)) {
              continue
            }
            seenIds.add(entry.id)

            const title = typeof entry.message === 'string' ? entry.message.trim() : ''
            if (!title) {
              continue
            }

            logLines.push({
              id: `log-${entry.id}`,
              kind: 'log_title',
              agentType: null,
              toolName: null,
              logTitle: title,
              timestamp: entry.timestamp || new Date().toISOString(),
            })
          }

          if (logLines.length > 0) {
            setDelegationCycles((prev) =>
              prev.map((existingCycle) =>
                existingCycle.id === cycle.id
                  ? {
                      ...existingCycle,
                      completed: true,
                      executionLogAvailable: true,
                      snippets: [...existingCycle.snippets, ...logLines],
                    }
                  : existingCycle,
              ),
            )
          }
        })
        .catch(() => {
          // Best-effort hydration enhancement only.
        })
    }
  }, [])

  const delegationSnippets = activeDelegationCycle?.snippets ?? []
  const delegationSnippetsCollapsed = activeDelegationCycle?.snippetsCollapsed ?? true
  const delegationCompleted = activeDelegationCycle?.completed ?? false
  const delegationExecutionLogAvailable = activeDelegationCycle?.executionLogAvailable ?? false
  const delegationExecutionSessionId = activeDelegationCycle?.executionSessionId ?? null

  // ── Intervention actions ─────────────────────────────────────────────────

  const sendInterventionResponse = useCallback(
    (requestId: string, value: {
      approval_value?: boolean
      selected_choice?: string
      text_value?: string
    }) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        // Best-effort: refresh the server-side cached JWT right before an
        // intervention response so management tool calls keep a valid token
        // even if the scheduled silent-renew push was missed.
        const currentToken = localStorage.getItem('access_token')
        if (currentToken) {
          wsRef.current.send(JSON.stringify({ type: 'token_refresh', token: currentToken }))
        }
        wsRef.current.send(
          JSON.stringify({
            type: 'intervene_response',
            request_id: requestId,
            ...value,
          }),
        )
        setInterventionRequest(null)
        interventionActiveRef.current = false
        // The pause is resolved locally: clear the pending-intervention flag so
        // the amber "waiting for your input" indicator disappears immediately.
        setPendingIntervention(false)
        setChatBlocked(null)
        setChatStatus((prev) => {
          // Never clobber a just-delivered terminal status (e.g. a durably
          // unresumable turn racing the response submit).
          if (prev && isTerminalChatStatusKind(prev.kind)) {
            return prev
          }
          // A normal, in-process approval is NOT a "resumed" turn — just show
          // the ordinary processing bubble (no "resumed" chip). The resumed
          // chip is only produced by server hydration after a real reconnect.
          return {
            kind: 'thinking',
            agentType: prev?.agentType ?? null,
            toolName: null,
            receiverSessionId: null,
            timestamp: new Date().toISOString(),
          }
        })
        // The turn is resuming server-side — from now until its final reply
        // (or a terminal status) the in-flight window must stay open so an
        // indicator is always visible and the watchdog polls on silence.
        markTurnInFlight(true)
        return true
      }
      return false
    },
    [],
  )

  const cancelIntervention = useCallback((requestId: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: 'intervene_cancel',
          request_id: requestId,
        }),
      )
      setInterventionRequest(null)
      interventionActiveRef.current = false
      setChatStatus((prev) => ({
        kind: 'waiting',
        agentType: prev?.agentType ?? null,
        toolName: null,
        receiverSessionId: null,
        timestamp: new Date().toISOString(),
      }))
      return true
    }
    return false
  }, [])

  // ── Live token refresh ─────────────────────────────────────────────────────
  // The backend caches the user JWT once at WS connect; OIDC tokens expire
  // while a conversation stays open (e.g. suspended awaiting a human
  // intervention), breaking CC management tool identity resolution. The
  // backend accepts {type:'token_refresh', token} to update the cache.

  const sendTokenRefresh = useCallback((token: string): boolean => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return false
    wsRef.current.send(JSON.stringify({ type: 'token_refresh', token }))
    return true
  }, [])

  // (a) Whenever the auth layer silently renews the access token, push the
  // fresh JWT through this live socket so the server-side cache stays valid.
  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ token?: string }>).detail
      const token = typeof detail?.token === 'string' ? detail.token : ''
      if (token) sendTokenRefresh(token)
    }
    window.addEventListener('parthenon:access_token_refreshed', handler)
    return () => window.removeEventListener('parthenon:access_token_refreshed', handler)
  }, [sendTokenRefresh])

  return {
    messages,
    connected,
    pendingQuestion,
    sessionTitle,
    guardrailUsage,
    chatStatus,
    delegationCycles,
    activeDelegationCycleId,
    delegationSnippets,
    delegationSnippetsCollapsed,
    delegationCompleted,
    delegationExecutionLogAvailable,
    delegationExecutionSessionId,
    /** Bumped after a reconnect that happened while a turn was in flight —
     * consumers should refresh persisted history to recover missed replies. */
    recoveryEpoch,
    /** True from user-message send until the turn's final agent reply or a
     * terminal status — drives the fallback activity indicator. */
    turnInFlight,
    /** True when the watchdog detected no WS traffic past the stale
     * threshold while a turn is in flight — UI should show a "checking
     * status" hint and the hook is actively pinging/reconnecting. */
    statusStale,
    setDelegationSnippetsCollapsed,
    toggleDelegationSnippetsCollapsed,
    hydrateDelegationFromHistory,
    sendMessage,
    clearMessages,
    chatError,
    // Intervention
    interventionRequest,
    /** True when the persisted/live activity reports a pending intervention
     * but no request object has arrived (hydration) — drives the
     * pending-intervention indicator. */
    pendingIntervention,
    /** Latest `intervene_status` answer, so a resolved optimization card can
     * distinguish denied / cancelled / expired without a second request. */
    interventionStatus,
    /** Per-request `live_test_result` chunks (executed operations, failures). */
    liveTestResults,
    /** Input was refused because a decision is pending (message + reason). */
    chatBlocked,
    /** Visible turn activity derived from the live status stream. */
    activitySteps,
    interventionQueueLength,
    sendInterventionResponse,
    cancelIntervention,
    sendTokenRefresh,
  }
}
