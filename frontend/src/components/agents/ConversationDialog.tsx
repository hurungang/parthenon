import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  Avatar,
  Box,
  Button,
  CircularProgress,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Fab,
  FormControlLabel,
  IconButton,
  Pagination,
  Paper,
  Popover,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material'
import SendIcon from '@mui/icons-material/Send'
import SmartToyIcon from '@mui/icons-material/SmartToy'
import PersonIcon from '@mui/icons-material/Person'
import CloseIcon from '@mui/icons-material/Close'
import StopCircleIcon from '@mui/icons-material/StopCircle'
import FullscreenIcon from '@mui/icons-material/Fullscreen'
import FullscreenExitIcon from '@mui/icons-material/FullscreenExit'
import VisibilityIcon from '@mui/icons-material/Visibility'
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff'
import ListAltIcon from '@mui/icons-material/ListAlt'
import AddIcon from '@mui/icons-material/Add'
import apiClient from '../../api/apiClient'
import { useSessionExecutionLogStream } from '../../hooks/useSessionExecutionLogStream'
import { useAssistantModelConfig } from '../../hooks/useAssistantModelConfig'
import { useOptimizationGate } from '../../hooks/useOptimizationGate'
import {
  liveTestCardStateFromStatus,
  liveTestRequestsQueryKey,
  liveTestScriptRun,
  optimizationConversationQueryKey,
  resolveLiveTestCardState,
  useCreateOptimizationConversation,
  useLiveTestRequests,
  useOptimizationConversationDetail,
} from '../../hooks/useOptimizationConversation'
import {
  CHAT_BLOCKED_REASON_DECISION_PENDING,
  isDecisionPendingBlock,
  isOptimizerChatErrorCode,
  isOptimizerModelReasonCode,
} from '../../utils/errorUtils'
import { OptimizationSessionBar } from '../optimizer/OptimizationSessionBar'
import { OptimizerAskCard } from '../optimizer/OptimizerAskCard'
import { LiveTestApprovalCard } from '../optimizer/LiveTestApprovalCard'
import {
  OptimizerModelAlert,
  OptimizerSystemConfigButton,
} from '../optimizer/OptimizerModelAlert'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import { ContentRenderer } from '../ContentRenderer'
import { MaximizableContent } from '../MaximizableContent'
import { AgentExecutionDetailsDialog } from './AgentExecutionDetailsDialog'
import { InlineInterventionDialog } from '../conversations/InlineInterventionDialog'
import { InterventionPendingIndicator } from '../conversations/InterventionPendingIndicator'
import { ResumeStateChip } from '../conversations/ResumeStateChip'
import { ResumeTerminalCard } from '../conversations/ResumeTerminalCard'
import {
  ResolvedInterventionBubble,
  type ResolvedInterventionData,
} from '../conversations/ResolvedInterventionBubble'
import {
  useConversationIntervention,
} from '../../hooks/useConversationIntervention'
import {
  useChatSession,
  type ChatMessage,
  type ChatStatus,
  type DelegationCycle,
  type ConversationalGuardrailUsage,
  type ResumeState,
} from '../../hooks/useChatSession'
import { isActionableWaiting } from '../../utils/resumeState'
import { useEndConversationSession, useConversationSessionsPage } from '../../hooks/useConversationSessions'
import { markAssistantSessionEnded } from '../../utils/assistantSessionState'
import { buildDelegationHistoryFromTurns, buildHistoryMessagesFromTurns } from '../../utils/delegationHistory'
import type {
  AgentJob,
  AgentJobStatus,
  ConversationSessionDetail,
  ExecutionLogEntry,
  InterveneRequestMessage,
  LiveTestApprovalSummary,
  LiveTestCardState,
  LiveTestRequest,
  ScriptRunRecord,
} from '../../types'

/**
 * FIX-20261101-120618 Work Item 1: in-chat "View All Sessions" list upgraded
 * to the sessions-tab experience — active/ended toggle (default active-only),
 * date-range inputs (default = configured window, mirrored by
 * DEFAULT_SESSIONS_WINDOW_DAYS), paginated time-desc rows. Resuming calls
 * back into ConversationDialog's switch handler (POST /conversations/{id}/resume)
 * — the previous session is never ended or archived from here (FIX-111439).
 * Ended sessions are viewable but never resumable.
 */

/** Mirrors backend Settings.conversation_sessions_default_window_days (7). */
const DEFAULT_SESSIONS_WINDOW_DAYS = 7
const SESSIONS_PAGE_SIZE = 10

function toDateInput(d: Date): string {
  return d.toISOString().slice(0, 10)
}

function SessionSwitcherList({
  agentTypeId,
  currentSessionId,
  onResume,
}: {
  agentTypeId: string
  currentSessionId: string | null
  onResume: (sessionId: string) => void
}) {
  const { t } = useTranslation()
  const [showEnded, setShowEnded] = useState(false)
  const [page, setPage] = useState(1)
  const [fromInput, setFromInput] = useState(() =>
    toDateInput(new Date(Date.now() - DEFAULT_SESSIONS_WINDOW_DAYS * 24 * 3600 * 1000)),
  )
  const [toInput, setToInput] = useState(() => toDateInput(new Date()))

  const { data, isLoading, error } = useConversationSessionsPage({
    agentTypeId,
    status: showEnded ? 'all' : 'active',
    dateFrom: fromInput ? `${fromInput}T00:00:00.000Z` : undefined,
    dateTo: toInput ? `${toInput}T23:59:59.999Z` : undefined,
    page,
    pageSize: SESSIONS_PAGE_SIZE,
  })

  const sessions = data?.items ?? []
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1

  if (isLoading) {
    return (
      <Box display="flex" justifyContent="center" py={3}>
        <CircularProgress size={24} />
      </Box>
    )
  }
  if (error) {
    return <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />
  }
  return (
    <Box>
      {/* Filters: ended toggle + date range (from/to) */}
      <Box display="flex" alignItems="center" gap={2} flexWrap="wrap" mb={1.5}>
        <FormControlLabel
          control={
            <Switch
              size="small"
              checked={showEnded}
              inputProps={{ 'aria-label': t('conversations.sessions.showEnded') }}
              onChange={() => {
                setShowEnded((v) => !v)
                setPage(1)
              }}
            />
          }
          label={<Typography variant="body2">{t('conversations.sessions.showEnded')}</Typography>}
        />
        <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 1 }}>
          <Typography variant="body2" component="label" htmlFor="sessions-date-from">
            {t('conversations.sessions.dateFrom')}
          </Typography>
          <TextField
            id="sessions-date-from"
            type="date"
            size="small"
            variant="outlined"
            value={fromInput}
            inputProps={{ 'aria-label': t('conversations.sessions.dateFrom') }}
            onChange={(e) => {
              setFromInput(e.target.value)
              setPage(1)
            }}
            sx={{ width: 165 }}
          />
          <Typography variant="body2" component="label" htmlFor="sessions-date-to">
            {t('conversations.sessions.dateTo')}
          </Typography>
          <TextField
            id="sessions-date-to"
            type="date"
            size="small"
            variant="outlined"
            value={toInput}
            inputProps={{ 'aria-label': t('conversations.sessions.dateTo') }}
            onChange={(e) => {
              setToInput(e.target.value)
              setPage(1)
            }}
            sx={{ width: 165 }}
          />
        </Box>
      </Box>

      {sessions.length === 0 ? (
        <Typography color="text.secondary" align="center" py={3}>
          {t('conversations.sessions.empty')}
        </Typography>
      ) : (
        <Stack spacing={0.75}>
          {sessions.map((session) => {
            const isEnded = session.status !== 'active'
            return (
              <Box
                key={session.id}
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 1,
                  border: (theme) => `1px solid ${theme.palette.divider}`,
                  borderRadius: 1.5,
                  px: 1.25,
                  py: 0.85,
                  bgcolor: session.id === currentSessionId ? 'action.selected' : 'background.paper',
                }}
              >
                <Box sx={{ minWidth: 0, flex: 1 }}>
                  <Typography variant="body2" fontWeight={session.id === currentSessionId ? 700 : 400} noWrap>
                    {session.title ?? (
                      <Typography component="em" color="text.secondary">
                        {t('conversations.sessions.untitled')}
                      </Typography>
                    )}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {t(`conversations.sessions.status.${session.status}`)} ·{' '}
                    {new Date(session.updated_at).toLocaleString()}
                  </Typography>
                </Box>
                {isEnded && (
                  <Chip
                    data-testid={`conversation-dialog-session-${session.id}-terminated`}
                    label={t('conversations.sessions.endedTag')}
                    size="small"
                    color="default"
                  />
                )}
                {!isEnded && session.id !== currentSessionId && (
                  <Button
                    size="small"
                    variant="outlined"
                    data-testid={`conversation-dialog-switch-session-${session.id}`}
                    onClick={() => onResume(session.id)}
                  >
                    {t('conversations.sessions.resume')}
                  </Button>
                )}
                {session.id === currentSessionId && (
                  <Chip label={t('conversations.sessions.currentSession')} size="small" color="primary" />
                )}
              </Box>
            )
          })}
        </Stack>
      )}

      {totalPages > 1 && (
        <Box display="flex" justifyContent="center" mt={2}>
          <Pagination
            count={totalPages}
            page={page}
            size="small"
            onChange={(_, p) => setPage(p)}
          />
        </Box>
      )}
    </Box>
  )
}

/**
 * "Configure model" action inside the assistant model-unconfigured guidance
 * Alert. Isolated in its own component so only this button (not the whole
 * dialog) requires a Router context — ConversationDialog is also rendered
 * in non-router test harnesses.
 */
function ConfigureAssistantModelButton({ testId }: { testId: string }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  return (
    <Button
      color="inherit"
      size="small"
      variant="outlined"
      data-testid={testId}
      onClick={() => navigate('/system-config')}
    >
      {t('assistant.modelNotConfiguredCta')}
    </Button>
  )
}

interface ConversationDialogProps {
  open: boolean
  sessionId: string | null
  agentTypeId: string
  agentTypeName: string
  onClose: () => void
  initialFullscreen?: boolean
  testIdPrefix?: string
  /** Assistant-only: proactively check the tenant's assistant model selection
   * and show setup guidance (with a Configure-model action) when unconfigured. */
  assistantModelConfigCheck?: boolean
  /**
   * Optimization mode: this conversation is an optimization conversation on the
   * SUBJECT agent type (`channel === 'optimization'`). It runs as that agent —
   * same identity, role and tool grants — and reuses the multi-turn activity /
   * pause / resume experience with optimization chrome, the ask card, the
   * live-test approval card and the replay-vs-live audit block.
   */
  optimizationMode?: boolean
  /** Optimization turn started/stopped — lets the host poll the plan. */
  onOptimizationTurnStateChange?: (inFlight: boolean) => void
  /** Optimization turn settled — lets the host refresh the optimized plan. */
  onOptimizationTurnSettled?: () => void
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

/**
 * PERF: the chat input owns its text state locally so every keystroke
 * re-renders ONLY this bar — not the whole ConversationDialog with its
 * full message timeline (which made typing visibly laggy on long chats).
 * The parent receives the final text via `onSend`; the input is cleared
 * only when the parent reports the message was actually sent/queued.
 */
const ChatInputBar = memo(function ChatInputBar({
  disabled,
  placeholder,
  onSend,
  sendLabel,
  clearToken = 0,
}: {
  disabled: boolean
  placeholder: string
  sendLabel: string
  onSend: (text: string) => Promise<boolean>
  /** Increment to programmatically clear the input (session switch, close,
   * or flush of the pending first message). */
  clearToken?: number
}) {
  const [text, setText] = useState('')
  const lastClearTokenRef = useRef(clearToken)
  useEffect(() => {
    if (clearToken !== lastClearTokenRef.current) {
      lastClearTokenRef.current = clearToken
      setText('')
    }
  }, [clearToken])
  const canSend = !disabled && text.trim().length > 0

  const handleSend = async () => {
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    const sent = await onSend(trimmed)
    if (sent) {
      setText('')
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void handleSend()
    }
  }

  return (
    <Box display="flex" gap={1}>
      <TextField
        fullWidth
        multiline
        maxRows={4}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={disabled}
        size="small"
      />
      <Button
        variant="contained"
        onClick={() => void handleSend()}
        disabled={!canSend}
        startIcon={<SendIcon />}
      >
        {sendLabel}
      </Button>
    </Box>
  )
})

/**
 * FIX-20261031-071721 (defect 1): merge persisted history turns into the
 * rendered message list without duplicating what is already visible (e.g. the
 * optimistic user message, or a reply that did arrive before a reconnect).
 * Occurrences are counted per (role, content) pair; only the difference is
 * appended, preserving history order.
 */
function mergeUnseenMessages(
  rendered: ChatMessage[],
  live: ChatMessage[],
  incoming: ChatMessage[],
): ChatMessage[] {
  const counts = new Map<string, number>()
  for (const msg of [...rendered, ...live]) {
    const key = `${msg.role}|${msg.content}`
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  const unseen: ChatMessage[] = []
  for (const msg of incoming) {
    const key = `${msg.role}|${msg.content}`
    const count = counts.get(key) ?? 0
    if (count > 0) {
      counts.set(key, count - 1)
    } else {
      unseen.push(msg)
    }
  }
  return unseen.length > 0 ? [...rendered, ...unseen] : rendered
}

/** Persisted terminal activity kinds — local mirror of the hook's
 * TERMINAL_CHAT_STATUS_KINDS (kept inline so test-only hook mocks that
 * export just `useChatSession` keep working). */
const TERMINAL_CHAT_STATUS_KINDS: readonly ChatStatus['kind'][] = [
  'timeout_or_failed',
  'finished',
  'failed',
  'timed_out',
]

function isTerminalChatStatus(status: ChatStatus | null): boolean {
  return status != null && TERMINAL_CHAT_STATUS_KINDS.includes(status.kind)
}

function parsePersistedGuardrailUsage(value: unknown): ConversationalGuardrailUsage | null {  if (!value || typeof value !== 'object' || Array.isArray(value)) {
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

const DELEGATION_LOG_EVENT_TYPES = new Set([
  'agent_initialized', 'tool_call', 'tool_response',
  'llm_request', 'llm_response', 'observe', 'session_completed',
])

function DelegationMiniLog({
  receiverSessionId,
  isActive,
}: {
  receiverSessionId: string | null
  isActive: boolean
}) {
  const [entries, setEntries] = useState<ExecutionLogEntry[]>([])
  const [sessionStatus, setSessionStatus] = useState<AgentJobStatus | null>(null)
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Fetch real session status when receiver session ID is known — overrides local isActive
  // to correctly reflect terminated/completed state even if status events were missed
  useEffect(() => {
    if (!receiverSessionId) { setSessionStatus(null); return }
    apiClient.get<AgentJob>(`/agents/sessions/${receiverSessionId}`)
      .then(({ data }) => setSessionStatus(data.status))
      .catch(() => {})
  }, [receiverSessionId])

  const effectiveIsActive = isActive && (
    sessionStatus === null || sessionStatus === 'running' || sessionStatus === 'queued' || sessionStatus === 'waiting_for_human'
  )

  const fetchEntries = useCallback((sessionId: string) => {
    apiClient.get<ExecutionLogEntry[]>(`/agents/sessions/${sessionId}/logs`)
      .then(({ data }) => setEntries(data))
      .catch(() => setEntries([]))
  }, [])

  useEffect(() => {
    if (!receiverSessionId) { setEntries([]); return }
    fetchEntries(receiverSessionId)
    retryRef.current = setTimeout(() => fetchEntries(receiverSessionId), 12000)
    return () => {
      if (retryRef.current) clearTimeout(retryRef.current)
    }
  }, [receiverSessionId, fetchEntries])

  const { entries: streamedEntries } = useSessionExecutionLogStream({
    sessionId: receiverSessionId,
    enabled: effectiveIsActive && !!receiverSessionId,
    onComplete: (status) => setSessionStatus(status),
  })

  const allEntries = useMemo(() => {
    if (streamedEntries.length === 0) return entries
    const merged = new Map<string, ExecutionLogEntry>()
    for (const e of entries) merged.set(e.id, e)
    for (const e of streamedEntries) merged.set(e.id, e)
    return Array.from(merged.values()).sort(
      (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
    )
  }, [entries, streamedEntries])

  const filtered = allEntries
    .filter(e => DELEGATION_LOG_EVENT_TYPES.has(e.event_type))
    .slice(-5)

  if (!receiverSessionId) return null
  if (filtered.length === 0) {
    return effectiveIsActive ? (
      <Typography variant="caption" color="text.disabled" sx={{ fontSize: 11 }}>Connecting...</Typography>
    ) : null
  }

  return (
    <Box sx={{ mt: 0.5 }}>
      {filtered.map((entry) => {
        const entryTime = new Date(entry.timestamp).toLocaleTimeString('en-US', {
          hour: '2-digit', minute: '2-digit', second: '2-digit',
        } as Intl.DateTimeFormatOptions)
        return (
          <Box key={entry.id} sx={{ display: 'flex', gap: 1, py: 0.2, alignItems: 'center' }}>
            <Typography variant="caption" sx={{ fontFamily: 'monospace', fontSize: 10, color: 'text.disabled', minWidth: 60 }}>
              {entryTime}
            </Typography>
            <Box sx={{
              width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
              bgcolor:
                entry.event_type === 'tool_call' || entry.event_type === 'tool_response' ? '#0288d1'
                : entry.event_type === 'llm_request' || entry.event_type === 'llm_response' ? '#7c4dff'
                : '#757575',
            }} />
            <Typography variant="caption" sx={{ fontSize: 11, color: 'text.secondary' }}>
              {entry.message}
            </Typography>
          </Box>
        )
      })}
    </Box>
  )
}

/**
 * A DECIDED live test, rendered as an inline chat-history entry (collapsed,
 * expandable to the script-run record). It keeps the historical position of the
 * approval request: `timestamp` is the decision time (falling back to the time
 * the proposal was first shown), so a late `live_test_result` update changes the
 * card IN PLACE instead of moving it to the end of the transcript.
 */
interface ResolvedLiveTestCardEntry {
  id: string
  proposal: LiveTestApprovalSummary
  state: LiveTestCardState
  scriptRun: ScriptRunRecord | null
  errorText: string | null
  decidedAt: string | null
  timestamp: string
  /** Stable index for the card's test-id prefix (`live-test-resolved-N`). */
  testIdIndex: number
}

/**
 * Full-screen capable conversation dialog for real-time chat with agents.
 * Handles session resume, WebSocket connection, and session end.
 */
export function ConversationDialog({
  open,
  sessionId,
  agentTypeId,
  agentTypeName,
  onClose,
  initialFullscreen = false,
  testIdPrefix = 'conversation-dialog',
  assistantModelConfigCheck = false,
  optimizationMode = false,
  onOptimizationTurnStateChange,
  onOptimizationTurnSettled,
}: ConversationDialogProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [convSessionId, setConvSessionId] = useState<string | null>(null)
  const [wsSessionId, setWsSessionId] = useState<string | null>(null)
  const [resumedMessages, setResumedMessages] = useState<ChatMessage[]>([])
  // Interventions resolved during THIS live session — rendered as
  // confirmation bubbles with a view-only reopen of the original request.
  const [liveResolvedInterventions, setLiveResolvedInterventions] = useState<
    ResolvedInterventionData[]
  >([])
  // Snapshot of the in-flight response so the confirmation bubble can be
  // emitted when the intervention request is cleared (intervene_status
  // "responded"). Cancel/dismiss clears the ref so no bubble is emitted.
  const respondedSnapshotRef = useRef<{
    request: InterveneRequestMessage
    answer: string
  } | null>(null)
  // Incremented to clear the ChatInputBar's local text (session close /
  // switch / pending-first-message flush).
  const [inputClearToken, setInputClearToken] = useState(0)
  const [isResuming, setIsResuming] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [endError, setEndError] = useState<unknown>(null)
  const [endConfirmOpen, setEndConfirmOpen] = useState(false)
  const [fullscreen, setFullscreen] = useState(initialFullscreen)
  const [pendingInitialMessage, setPendingInitialMessage] = useState<string | null>(null)
  const [executionDetailsOpen, setExecutionDetailsOpen] = useState(false)
  const [executionDetailsSessionId, setExecutionDetailsSessionId] = useState<string | null>(null)
  const [guardrailHintAnchorEl, setGuardrailHintAnchorEl] = useState<HTMLElement | null>(null)
  const [resumedGuardrailUsage, setResumedGuardrailUsage] =
    useState<ConversationalGuardrailUsage | null>(null)
  // FIX-20261101-111439 (defect 2): action-bar "View All Sessions" switcher.
  const [sessionsDialogOpen, setSessionsDialogOpen] = useState(false)
  // resumable-agent-turn-persistence 6.3: the "no longer resumable" terminal
  // card is dismissible, and a duplicate approval aimed at an already-terminal
  // turn must never be re-sent — it surfaces a "nothing to replay" notice.
  const [dismissedTerminalKey, setDismissedTerminalKey] = useState<string | null>(null)
  const [nothingToReplay, setNothingToReplay] = useState(false)

  // ── Optimization mode (same conversation experience, optimization chrome) ──
  // The exact live-test proposals seen in this dialog, so a resolved card can
  // still render the operation list after the pause has cleared.
  const seenLiveTestsRef = useRef<Record<string, LiveTestApprovalSummary>>({})
  // First time this dialog rendered each proposal. A decided card becomes an
  // inline chat-history entry at its ORIGINAL position — this timestamp keeps
  // it there even before the ledger row (decision/execution times) arrives, so
  // the card never jumps to the bottom of the transcript.
  const liveTestObservedAtRef = useRef<Record<string, string>>({})
  // Request id whose approval was submitted — shows "running once" until the
  // `live_test_result` chunk (or the ledger) reports the outcome.
  const [liveTestApprovedRequestId, setLiveTestApprovedRequestId] = useState<string | null>(null)
  // Turn-in-flight transitions drive the host's plan polling / refresh.
  const optimizationTurnWasInFlightRef = useRef(false)

  const endSession = useEndConversationSession(agentTypeId)
  const testId = (suffix: string) => `${testIdPrefix}-${suffix}`

  const formatDateTime = (value: string | null | undefined): string => {
    if (!value) {
      return new Date().toLocaleString()
    }
    return new Date(value).toLocaleString()
  }

  const toEpochMs = (value: string | null | undefined): number => {
    if (!value) {
      return Number.MAX_SAFE_INTEGER
    }
    const ms = Date.parse(value)
    return Number.isNaN(ms) ? Number.MAX_SAFE_INTEGER : ms
  }

  const resolveCycleAgentType = (cycle: DelegationCycle, isActiveCycle: boolean): string | null => {
    const snippetWithAgent =
      cycle.snippets.find(
        (snippet) =>
          (snippet.kind === 'delegating' || snippet.kind === 'waiting') &&
          Boolean(snippet.agentType),
      ) ?? null
    if (snippetWithAgent?.agentType) {
      return snippetWithAgent.agentType
    }

    if (
      isActiveCycle &&
      (chatStatus?.kind === 'delegating' || chatStatus?.kind === 'waiting') &&
      chatStatus.agentType
    ) {
      return chatStatus.agentType
    }

    return null
  }

  const buildCyclesFromLegacySnippets = (): DelegationCycle[] => {
    if (delegationSnippets.length === 0) {
      return []
    }

    const cycles: DelegationCycle[] = []
    let current: DelegationCycle | null = null

    for (const snippet of delegationSnippets) {
      if (!current || snippet.kind === 'delegating') {
        current = {
          id: `legacy-cycle-${cycles.length + 1}`,
          startedAt: snippet.timestamp,
          snippets: [],
          snippetsCollapsed: true,
          completed: false,
          executionLogAvailable: false,
          executionSessionId: null,
        }
        cycles.push(current)
      }
      current.snippets.push(snippet)
    }

    if (cycles.length === 1) {
      cycles[0] = {
        ...cycles[0],
        snippetsCollapsed: delegationSnippetsCollapsed,
        completed: delegationCompleted,
        executionLogAvailable: delegationExecutionLogAvailable,
        executionSessionId: delegationExecutionSessionId,
      }
      return cycles
    }

    for (let index = 0; index < cycles.length; index += 1) {
      const isLast = index === cycles.length - 1
      cycles[index] = {
        ...cycles[index],
        snippetsCollapsed: isLast ? delegationSnippetsCollapsed : true,
        completed: !isLast,
      }
    }

    if (delegationExecutionSessionId && cycles.length > 0) {
      cycles[0] = {
        ...cycles[0],
        executionLogAvailable: delegationExecutionLogAvailable,
        executionSessionId: delegationExecutionSessionId,
      }
    }

    return cycles
  }

  const {
    messages: wsMessages,
    connected,
    pendingQuestion,
    sessionTitle,
    guardrailUsage: liveGuardrailUsage,
    chatStatus,
    delegationCycles,
    activeDelegationCycleId,
    delegationSnippets,
    delegationSnippetsCollapsed,
    delegationCompleted,
    delegationExecutionLogAvailable,
    delegationExecutionSessionId,
    hydrateDelegationFromHistory,
    sendMessage,
    chatError,
    interventionRequest,
    interventionQueueLength: _interventionQueueLength,
    sendInterventionResponse,
    cancelIntervention,
    clearMessages,
    recoveryEpoch,
    turnInFlight,
    statusStale,
    pendingIntervention,
    interventionStatus,
    liveTestResults = {},
    chatBlocked,
  } =
    useChatSession(wsSessionId, convSessionId)
  const effectiveGuardrailUsage = liveGuardrailUsage ?? resumedGuardrailUsage

  // ── Optimization-mode data ────────────────────────────────────────────────
  // Creation goes through the dedicated optimization endpoint (subject only);
  // the conversation itself carries the mode, so no client-supplied channel.
  const createOptimizationConversation = useCreateOptimizationConversation(agentTypeId)
  const { data: optimizationDetail } = useOptimizationConversationDetail(
    optimizationMode ? convSessionId : null,
    optimizationMode && open,
  )
  const { data: liveTestRequests } = useLiveTestRequests(
    optimizationMode ? convSessionId : null,
    optimizationMode && open,
  )
  // Pre-session model state comes from the gate (cached from the Optimized Plan
  // tab); once the conversation exists the read's availability is authoritative.
  const { data: optimizationGate } = useOptimizationGate(
    optimizationMode ? agentTypeId : null,
    optimizationMode && open,
  )
  const optimizationSubjectName = optimizationDetail?.subject.name ?? agentTypeName
  const optimizationIsConversational =
    optimizationDetail?.subject.is_conversational ??
    optimizationGate?.is_conversational ??
    false
  const optimizationAvailability = optimizationDetail?.availability ?? null
  const optimizationAudit = optimizationDetail?.audit ?? null
  const optimizerModelReasonCode =
    optimizationAvailability?.optimizer_model.reason_code ??
    (isOptimizerModelReasonCode(chatError?.code) ? (chatError?.code ?? null) : null) ??
    optimizationGate?.optimizer_model_reason_code ??
    null
  const optimizerModelBlocked =
    optimizationMode && isOptimizerModelReasonCode(optimizerModelReasonCode)
  const optimizerModelId =
    optimizationAvailability?.optimizer_model.effective_model_id ??
    optimizationGate?.optimizer_model_id ??
    null
  const planPresent = optimizationAvailability?.plan_present ?? true

  // Latest live WS messages for the mid-turn recovery merge (effect-safe read).
  const wsMessagesRef = useRef<ChatMessage[]>(wsMessages)
  wsMessagesRef.current = wsMessages

  // Assistant-specific proactive model-config check: when the tenant has not
  // selected a model for the Control Center Assistant (or the backend reports
  // `assistant_model_not_configured` mid-session), show setup guidance and
  // disable chatting instead of letting turns fail. Regular agent types are
  // unaffected (the check is off by default).
  const { data: assistantModelConfig } = useAssistantModelConfig(
    open && assistantModelConfigCheck,
  )
  // Unconfigured when the loaded tenant config has no selection, or when the
  // backend surfaces the structured error mid-session (generic mapping).
  const ASSISTANT_MODEL_NOT_CONFIGURED_CODE = 'assistant_model_not_configured'
  const assistantModelUnconfigured =
    (assistantModelConfigCheck &&
      assistantModelConfig != null &&
      assistantModelConfig.selected_model_id == null) ||
    chatError?.code === ASSISTANT_MODEL_NOT_CONFIGURED_CODE

  const {
    dialogError: interventionDialogError,
    isSubmitting: interventionIsSubmitting,
    respondToIntervention,
    cancelIntervention: cancelInterventionRequest,
    currentIntervention: fetchedPendingIntervention,
    pendingInterventions: fetchedPendingList,
  } = useConversationIntervention(
    convSessionId,
    sendInterventionResponse,
    cancelIntervention,
  )

  // Refresh recovery: a pending intervention fetched via REST when the WS
  // has not re-surfaced it (page refreshed mid-request). Mapped into the
  // same message shape the WS path uses so ONE render path serves both.
  const activeIntervention: InterveneRequestMessage | null = useMemo(() => {
    if (interventionRequest) return interventionRequest
    if (fetchedPendingIntervention) {
      // Same shape as the WS path — including the optimization `live_test`
      // block (exact operation list + expiry), so a reconnected approval card
      // renders identically instead of only showing the server-rendered text.
      return {
        type: 'intervene_request',
        request_id: fetchedPendingIntervention.id,
        intervention_type: fetchedPendingIntervention.intervention_type,
        reason: fetchedPendingIntervention.reason,
        choices: fetchedPendingIntervention.choices,
        agent_type: fetchedPendingIntervention.agent_name ?? undefined,
        delegation_depth: fetchedPendingIntervention.delegation_depth ?? 0,
        conversation_session_id: fetchedPendingIntervention.conversation_session_id ?? '',
        live_test: fetchedPendingIntervention.live_test ?? null,
      }
    }
    return null
  }, [interventionRequest, fetchedPendingIntervention])

  // Remember every live-test proposal this dialog rendered: after the pause
  // clears (approved / denied / expired) the resolved card still needs the
  // operation list to show what was requested and what ran.
  useEffect(() => {
    const proposal = activeIntervention?.live_test
    if (proposal) {
      seenLiveTestsRef.current[proposal.live_test_request_id] = proposal
      if (!liveTestObservedAtRef.current[proposal.live_test_request_id]) {
        liveTestObservedAtRef.current[proposal.live_test_request_id] =
          new Date().toISOString()
      }
    }
  }, [activeIntervention])

  // A new confirmation request starts a fresh interaction — clear the stale
  // "nothing to replay" notice from a previous terminal turn.
  useEffect(() => {
    setNothingToReplay(false)
  }, [activeIntervention?.request_id])

  // REAL turn activity only: create/resume requests are NOT turns. The
  // optimization host derives "a turn settled → refresh the plan" from this, so
  // counting the conversation-create request here made the first message of a
  // fresh optimization chat look like a finished turn and destroyed the session.
  const turnActive =
    !!pendingQuestion ||
    !!interventionRequest ||
    !!fetchedPendingIntervention ||
    (chatStatus?.kind === 'thinking' ||
      chatStatus?.kind === 'delegating' ||
      chatStatus?.kind === 'waiting' ||
      chatStatus?.kind === 'using_tool' ||
      chatStatus?.kind === 'waiting_for_human' ||
      chatStatus?.kind === 'delegation_resumed' ||
      turnInFlight)

  // FIX-20261101-111439 (defect 2): a conversational turn is in flight —
  // session-switching and end actions are blocked while this is true. A
  // create/resume request also blocks them (nothing to switch to yet).
  const turnStreaming = isResuming || turnActive

  // ── Optimization mode: plan refresh + live-test card projections ───────────
  // Turn completion (reply, pause, denial, live-test result) refreshes the
  // optimized plan on the host tab; while a turn is in flight the host polls.
  // Only REAL turn activity counts — the conversation-create request must never
  // report "settled", otherwise the host's plan refetch remounts this dialog and
  // the just-created session is lost.
  useEffect(() => {
    if (!optimizationMode) return
    onOptimizationTurnStateChange?.(turnActive)
    if (optimizationTurnWasInFlightRef.current && !turnActive) {
      onOptimizationTurnSettled?.()
      // The audit projection ("what ran") is part of the conversation read —
      // refresh it when a turn settles so replay/live counts never lag.
      if (convSessionId) {
        void queryClient.invalidateQueries({
          queryKey: optimizationConversationQueryKey(convSessionId),
        })
      }
    }
    optimizationTurnWasInFlightRef.current = turnActive
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [optimizationMode, turnActive])

  // A live-test result changes plan evidence too — refresh the plan even if the
  // turn status was already idle when the chunk arrived.
  const liveTestResultCount = Object.keys(liveTestResults).length
  useEffect(() => {
    if (!optimizationMode || liveTestResultCount === 0) return
    onOptimizationTurnSettled?.()
    if (convSessionId) {
      void queryClient.invalidateQueries({
        queryKey: optimizationConversationQueryKey(convSessionId),
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [optimizationMode, liveTestResultCount])

  // The approved request stops being "running" as soon as its outcome is KNOWN
  // — the `live_test_result` chunk or a terminal ledger row (executed / failed /
  // denied / expired / cancelled). Without this the mode bar kept claiming
  // "Live test running…" for the rest of the dialog's life.
  useEffect(() => {
    if (!liveTestApprovedRequestId) return
    const result = liveTestResults[liveTestApprovedRequestId]
    const ledgerRow = (liveTestRequests ?? []).find(
      (row) => row.id === liveTestApprovedRequestId,
    )
    const ledgerTerminal =
      ledgerRow != null &&
      (ledgerRow.status === 'executed' ||
        ledgerRow.status === 'failed' ||
        ledgerRow.status === 'denied' ||
        ledgerRow.status === 'expired' ||
        ledgerRow.status === 'cancelled')
    if (result || ledgerTerminal) {
      setLiveTestApprovedRequestId(null)
    }
  }, [liveTestApprovedRequestId, liveTestResults, liveTestRequests])

  // FIX: invariant — from the moment the user sends a message until the
  // turn's final agent reply (or a terminal status), an activity indicator
  // MUST always render. `showThinking` is computed below (after the
  // delegation status visibility flags are known) so it can fall back to the
  // thinking bubble whenever NO other indicator will actually render.

  const formatTokenCountK = (value: number | null): string => {
    if (value == null) return t('agents.sessions.logViewer.summary.notAvailable')
    const tokenCountK = value / 1000
    const rounded = Math.round(tokenCountK * 10) / 10
    return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)}k tokens`
  }

  // Emit the resolved-intervention confirmation bubble once the intervention
  // request is cleared after a respond action (the WS `intervene_status:
  // responded` / REST fallback both clear the active request). A pending
  // snapshot ref distinguishes a real response from a cancel/dismiss.
  useEffect(() => {
    if (activeIntervention) {
      return
    }
    const snapshot = respondedSnapshotRef.current
    if (!snapshot) {
      return
    }
    respondedSnapshotRef.current = null
    setLiveResolvedInterventions((prev) => [
      ...prev,
      {
        id: `resolved-${snapshot.request.request_id}-${Date.now()}`,
        interventionType: snapshot.request.intervention_type,
        reason: snapshot.request.reason,
        choices: snapshot.request.choices ?? null,
        agentType: snapshot.request.agent_type ?? null,
        answer: snapshot.answer,
        resolvedAt: new Date().toISOString(),
      },
    ])
  }, [activeIntervention])

  // Persisted history: pair intervene_request/intervene_response turns (by
  // intervene_request_id) into resolved-intervention bubbles so a resumed
  // session shows the Q&A record instead of bare system text. Response turns
  // without a matching question turn (legacy data) render as plain messages.
  const historyResolvedInterventions = useMemo<ResolvedInterventionData[]>(() => {
    const pairs = new Map<
      string,
      { question: ChatMessage | null; answer: ChatMessage | null }
    >()
    const seenQuestionIds = new Set<string>()
    for (const msg of resumedMessages) {
      if (msg.turnType === 'intervene_request') {
        const key = msg.interveneRequestId ?? msg.id
        const existing = pairs.get(key) ?? { question: null, answer: null }
        existing.question = msg
        pairs.set(key, existing)
        seenQuestionIds.add(msg.id)
      } else if (msg.turnType === 'intervene_response') {
        const key = msg.interveneRequestId ?? ''
        const existing = pairs.get(key)
        if (existing) {
          existing.answer = msg
          seenQuestionIds.add(msg.id)
        }
      }
    }
    const resolved: ResolvedInterventionData[] = []
    for (const [key, pair] of pairs) {
      // A question turn WITHOUT a persisted response turn is a still-pending
      // (or failed) request — it must NOT render as "resolved". The pending
      // card is re-surfaced separately via the REST pending fetch.
      if (!pair.question || !pair.answer) continue
      seenQuestionIds.add(pair.answer?.id ?? '')
      resolved.push({
        id: `history-resolved-${key}`,
        interventionType: 'approval',
        reason: pair.question.content,
        choices: null,
        agentType: null,
        answer: pair.answer.content,
        resolvedAt: pair.answer.timestamp,
      })
    }
    // Light dedupe: drop history-derived bubbles already shown live (the
    // mid-turn recovery merge can pull persisted turns into resumedMessages
    // while the live bubble is still on screen).
    return resolved.filter(
      (entry) =>
        !liveResolvedInterventions.some(
          (live) => live.reason === entry.reason && live.answer === entry.answer,
        ),
    )
  }, [resumedMessages, liveResolvedInterventions])

  // Message ids rendered as resolved bubbles — excluded from plain message
  // entries in the timeline. Question turns without an answer stay visible
  // as plain history UNLESS the request is still pending (then the pending
  // card represents it).
  const resolvedInterventionMessageIds = useMemo(() => {
    const ids = new Set<string>()
    const pendingIds = new Set(
      (fetchedPendingList ?? []).map((r) => r.id),
    )
    for (const msg of resumedMessages) {
      if (msg.turnType === 'intervene_request') {
        const paired = resumedMessages.some(
          (m) =>
            m.turnType === 'intervene_response' &&
            m.interveneRequestId &&
            m.interveneRequestId === msg.interveneRequestId,
        )
        if (paired || (msg.interveneRequestId && pendingIds.has(msg.interveneRequestId))) {
          ids.add(msg.id)
        }
      } else if (
        msg.turnType === 'intervene_response' &&
        msg.interveneRequestId &&
        resumedMessages.some(
          (m) =>
            m.turnType === 'intervene_request' && m.interveneRequestId === msg.interveneRequestId,
        )
      ) {
        ids.add(msg.id)
      }
    }
    return ids
  }, [resumedMessages, fetchedPendingList])

  const formatPair = (current: number | null, limit: number | null, formatter?: (value: number) => string): string => {
    if (current == null) return t('agents.sessions.logViewer.summary.notAvailable')
    const format = formatter ?? ((value: number) => `${value}`)
    const currentLabel = format(current)
    const limitLabel = limit == null ? null : format(limit)
    return limitLabel ? `${currentLabel} / ${limitLabel}` : currentLabel
  }

  const guardrailRows = effectiveGuardrailUsage
    ? [
        {
          label: t('agents.sessions.logViewer.summary.policySnapshot'),
          value: effectiveGuardrailUsage.policySnapshotId ?? t('agents.sessions.logViewer.summary.notAvailable'),
        },
        {
          label: t('agents.sessions.logViewer.summary.currentSessionTokens'),
          value: formatPair(effectiveGuardrailUsage.tokenUsageCurrentSession, effectiveGuardrailUsage.tokenBudget, formatTokenCountK),
        },
        {
          label: t('agents.sessions.logViewer.summary.iterations'),
          value: formatPair(effectiveGuardrailUsage.cumulativeIterations, effectiveGuardrailUsage.maxIterations),
        },
        {
          label: t('agents.sessions.logViewer.summary.delegatedSteps'),
          value: formatPair(effectiveGuardrailUsage.delegatedSteps, effectiveGuardrailUsage.maxDelegatedSteps),
        },
        {
          label: t('agents.sessions.logViewer.summary.delegationDepth'),
          value: formatPair(effectiveGuardrailUsage.delegationDepth, effectiveGuardrailUsage.maxDelegationDepth),
        },
      ]
    : []

  const guardrailHintOpen = Boolean(guardrailHintAnchorEl)

  // Combine resumed history with live WebSocket messages
  const messages = [...resumedMessages, ...wsMessages]
  const filterEmptyDelegationCycles = (cycles: DelegationCycle[]) =>
    cycles.filter((cycle) => {
      if (!cycle.snippets || cycle.snippets.length === 0) return false
      if (cycle.snippets.length === 1 && !cycle.snippets[0].agentType) return false
      return true
    })

  const legacyCycles = buildCyclesFromLegacySnippets()
  const effectiveDelegationCycles =
    Array.isArray(delegationCycles) && delegationCycles.length > 0
      ? filterEmptyDelegationCycles(delegationCycles)
      : filterEmptyDelegationCycles(legacyCycles)
  const effectiveActiveDelegationCycleId =
    activeDelegationCycleId ??
    (effectiveDelegationCycles.length > 0 ? effectiveDelegationCycles[effectiveDelegationCycles.length - 1].id : null)
  // Is the *active* cycle actually among the rendered (non-empty) cycles? A
  // `using_tool` status creates an EMPTY delegation cycle that
  // `filterEmptyDelegationCycles` drops, so the active-cycle id can point at a
  // cycle that is not rendered. In that case the standalone status line must
  // still render — otherwise the processing bubble goes blank whenever the
  // session already has any (e.g. resumed) delegation history.
  const activeCycleRendered =
    effectiveActiveDelegationCycleId != null &&
    effectiveDelegationCycles.some((cycle) => cycle.id === effectiveActiveDelegationCycleId)
  // ── Live-pause gate (FIX-20261113) ─────────────────────────────────────────
  // A confirmation is only actionable while the pause is actually LIVE. A
  // stale working status (`using_tool` / `thinking`) with a pending/terminal
  // confirmation must never render as a progressing bubble next to a live-looking
  // dialog: the operator would approve a turn that can no longer continue.
  const interventionIsLive =
    interventionRequest != null ||
    chatStatus?.kind === 'waiting_for_human' ||
    pendingIntervention
  // Suppress every working indicator when a confirmation exists (or the turn is
  // terminal) but no live pause backs it — there is nothing progressing.
  const workingStatusSuppressed =
    !interventionIsLive &&
    (activeIntervention != null ||
      (chatStatus != null && isTerminalChatStatus(chatStatus)))

  // Transitional "requesting human intervention" phase: the agent has called
  // the human-intervene management tool but the intervene_request bubble has
  // not arrived yet — show a distinct status instead of a generic tool line.
  const isHumanInterveneToolCall =
    chatStatus?.kind === 'using_tool' &&
    Boolean(chatStatus.toolName && /intervene|human/i.test(chatStatus.toolName))
  const standaloneDelegationStatusLine =
    chatStatus?.kind === 'waiting'
      ? t('conversations.sessions.statusWaiting')
      : chatStatus?.kind === 'using_tool' && chatStatus.toolName
        ? isHumanInterveneToolCall
          ? t('conversations.sessions.statusRequestingHuman')
          : t('conversations.sessions.statusUsingTool', { toolName: chatStatus.toolName })
        : chatStatus?.kind === 'delegating' && chatStatus.agentType
          ? t('conversations.sessions.statusDelegatingToAgent', { agentType: chatStatus.agentType })
          : chatStatus?.kind === 'delegation_resumed'
            ? t('conversations.sessions.statusThinking')
            : null
  const shouldShowStandaloneDelegationStatus =
    !workingStatusSuppressed &&
    !activeCycleRendered &&
    Boolean(standaloneDelegationStatusLine) &&
    Boolean(chatStatus) &&
    chatStatus?.kind !== 'thinking' &&
    chatStatus?.kind !== 'timeout_or_failed'

  // Persisted terminal states (finished / failed / timed_out, or the legacy
  // timeout_or_failed wire status) end the turn — they clear the activity
  // bubble / in-flight spinner and render a clear terminal message instead.
  const terminalStatus = chatStatus && isTerminalChatStatus(chatStatus) ? chatStatus : null
  const terminalStatusKind = terminalStatus?.kind ?? null
  const terminalStatusLabel =
    (chatStatus?.message
      ? chatStatus.message
      : terminalStatusKind === 'timeout_or_failed'
        ? t('conversations.sessions.statusTimeoutOrFailed')
        : terminalStatusKind === 'finished'
          ? t('conversations.sessions.statusFinished')
          : terminalStatusKind === 'failed'
            ? t('conversations.sessions.statusFailed')
            : terminalStatusKind === 'timed_out'
              ? t('conversations.sessions.statusTimedOut')
              : null)

  // ── Durable resume vocabulary (resumable-agent-turn-persistence, Phase 6) ──
  // A pause is only rendered as "waiting for your input" when a live resume
  // record backs it; a stale hydrated `waiting_for_human` without one is not a
  // waiting turn. A resumed turn (thinking / using a tool after a pause) is
  // rendered distinctly from a fresh turn.
  const waitingForInput = isActionableWaiting(chatStatus)
  const isUnresumableTurn =
    terminalStatus != null &&
    (terminalStatus.resumeState === 'unresumable' || terminalStatus.terminalReason != null)
  const isResolvedResumeTurn = terminalStatus?.resumeState === 'resolved'
  const resumedTurnActive =
    chatStatus != null &&
    !isTerminalChatStatus(chatStatus) &&
    (chatStatus.resumeState === 'resuming' || Boolean(chatStatus.activeResumeId))
  const resumeChipState: ResumeState | null = waitingForInput || pendingIntervention
    ? 'waiting_for_human'
    : isUnresumableTurn
      ? 'unresumable'
      : resumedTurnActive
        ? 'resuming'
        : isResolvedResumeTurn
          ? 'resolved'
          : null
  // Identity of the terminal card; a NEW terminal status re-opens a dismissed
  // card, while dismissing keeps it hidden for the same turn.
  const terminalCardKey = terminalStatus
    ? `${terminalStatus.kind}|${terminalStatus.terminalReason ?? ''}|${terminalStatus.activeResumeId ?? ''}|${terminalStatus.timestamp}`
    : null
  const showTerminalCard =
    isUnresumableTurn && terminalCardKey != null && terminalCardKey !== dismissedTerminalKey
  const dismissTerminalCard = () => {
    setDismissedTerminalKey(terminalCardKey)
    setNothingToReplay(false)
  }
  // "Ask again" retires the terminal card and REPEATS the last user request:
  // re-sending it starts a fresh turn (nothing was written on the dead turn, so
  // repeating is safe). Falls back to just clearing the input when there is no
  // prior user message to replay.
  const handleAskAgain = () => {
    dismissTerminalCard()
    setInputClearToken((n) => n + 1)
    const lastUserMessage = [...messages]
      .reverse()
      .find((message) => message.role === 'user' && message.content.trim().length > 0)
    if (lastUserMessage) {
      sendMessage(lastUserMessage.content)
    }
  }

  // A confirmation aimed at an already-terminal turn can no longer be replayed:
  // surface "nothing to replay" and never dispatch the response (the write is
  // over — applied once or not at all).
  const interventionTargetTerminal = terminalStatus != null
  // When the turn is terminal OR the pause is no longer live, a lingering
  // confirmation must be folded into a grey read-only state — it can no longer
  // be acted on and must not block the input (the operator retries via "Ask
  // again" or a new message instead).
  const interventionActionable =
    activeIntervention != null && !interventionTargetTerminal && interventionIsLive

  // ── Optimization mode: approval-card view models ──────────────────────────
  // The actionable card is the pending proposal; decided ones render as read-only
  // evidence (operation list + per-operation outcomes) so the chat shows what was
  // requested and what actually ran, including after a reconnect.
  const pendingLiveTest = interventionActionable ? (activeIntervention?.live_test ?? null) : null
  const pendingLiveTestResult = pendingLiveTest
    ? (liveTestResults[pendingLiveTest.live_test_request_id] ?? null)
    : null
  const pendingLiveTestState = pendingLiveTest
    ? resolveLiveTestCardState(pendingLiveTest, {
        result: pendingLiveTestResult,
        localState:
          liveTestApprovedRequestId === pendingLiveTest.live_test_request_id &&
          !pendingLiveTestResult
            ? 'running'
            : liveTestCardStateFromStatus(pendingLiveTest.status),
      })
    : null

  const resolvedLiveTestCards = useMemo<ResolvedLiveTestCardEntry[]>(() => {
    if (!optimizationMode) {
      return []
    }
    const ledgerById = new Map<string, LiveTestRequest>()
    for (const row of liveTestRequests ?? []) ledgerById.set(row.id, row)
    const ids = new Set<string>()
    for (const id of Object.keys(liveTestResults)) ids.add(id)
    for (const id of Object.keys(seenLiveTestsRef.current)) {
      if (liveTestResults[id]) ids.add(id)
    }
    // Every request this dialog actually showed (denied / expired / executed
    // with no result chunk) keeps its evidence card.
    for (const row of liveTestRequests ?? []) {
      if (seenLiveTestsRef.current[row.id]) ids.add(row.id)
    }
    // Reconnect / review: the newest decided row renders once even without a
    // locally received result chunk.
    const latestDecided = (liveTestRequests ?? []).find((row) => row.status !== 'pending')
    if (latestDecided) ids.add(latestDecided.id)
    if (pendingLiveTest) ids.delete(pendingLiveTest.live_test_request_id)

    // The card's place in the transcript: where the approval was FIRST SHOWN
    // (the operator's request position), so it stays in history and never
    // re-sorts when the decision/result lands. Only a reloaded history (no
    // local observation) falls back to the decision/creation time.
    const sortTimestamp = (id: string, row: LiveTestRequest | undefined): string => {
      const observedAt = liveTestObservedAtRef.current[id]
      if (observedAt) return observedAt
      const decidedAt = row?.decision?.responded_at
      if (decidedAt) return decidedAt
      if (row?.created_at) return row.created_at
      // Transient only: never cache this as the observed time, otherwise the
      // card stays pinned at "now" and cannot re-sort when the ledger lands.
      return new Date().toISOString()
    }

    let index = 0
    return [...ids].map((id) => {
      const row = ledgerById.get(id)
      const result = liveTestResults[id] ?? null
      const proposal: LiveTestApprovalSummary = {
        live_test_request_id: id,
        status: row?.status ?? seenLiveTestsRef.current[id]?.status ?? 'expired',
        expires_at: row?.expires_at ?? seenLiveTestsRef.current[id]?.expires_at ?? null,
        script_version_id:
          row?.script_version_id ?? seenLiveTestsRef.current[id]?.script_version_id ?? null,
        script_name: row?.script_name ?? seenLiveTestsRef.current[id]?.script_name ?? null,
        script_version_label:
          row?.script_version_label ??
          seenLiveTestsRef.current[id]?.script_version_label ??
          null,
        operations: row?.requested_operations ?? seenLiveTestsRef.current[id]?.operations ?? [],
        executed_operations:
          row?.executed_operations ?? seenLiveTestsRef.current[id]?.executed_operations ?? null,
        target_agent_type_id: row?.target_agent_type_id ?? null,
      }
      const decidedDenied = row?.decision?.approval_value === false
      const state = decidedDenied
        ? ('denied' as const)
        : resolveLiveTestCardState(proposal, {
            result,
            localState:
              liveTestApprovedRequestId === id && !result ? ('running' as const) : null,
          })
      const card: ResolvedLiveTestCardEntry = {
        id,
        proposal,
        state,
        scriptRun: liveTestScriptRun(proposal, result),
        errorText: result?.live_test_error ?? null,
        decidedAt: row?.decision?.responded_at ?? null,
        timestamp: sortTimestamp(id, row),
        testIdIndex: index,
      }
      index += 1
      return card
    })
  }, [
    optimizationMode,
    liveTestRequests,
    liveTestResults,
    pendingLiveTest,
    liveTestApprovedRequestId,
  ])

  // Chronological transcript: persisted + live messages, delegation cycles,
  // resolved interventions AND decided live tests, all sorted by their own
  // timestamp. A decided live test is therefore ordinary chat history in the
  // position where the approval happened — never a trailing card.
  const timelineEntries: Array<
    | { kind: 'message'; id: string; timestamp: string; message: ChatMessage }
    | { kind: 'delegation_cycle'; id: string; timestamp: string; cycle: DelegationCycle }
    | { kind: 'intervention_resolved'; id: string; timestamp: string; data: ResolvedInterventionData }
    | { kind: 'live_test_resolved'; id: string; timestamp: string; card: ResolvedLiveTestCardEntry }
  > = [
    ...messages
      // Intervene Q&A turns render as resolved-intervention bubbles instead
      // of plain system text.
      .filter((message) => !resolvedInterventionMessageIds.has(message.id))
      .map((message) => ({
        kind: 'message' as const,
        id: `message-${message.id}`,
        timestamp: message.timestamp,
        message,
      })),
    ...effectiveDelegationCycles.map((cycle) => ({
      kind: 'delegation_cycle' as const,
      id: `delegation-cycle-${cycle.id}`,
      timestamp: cycle.startedAt,
      cycle,
    })),
    ...[...historyResolvedInterventions, ...liveResolvedInterventions].map((data) => ({
      kind: 'intervention_resolved' as const,
      id: `intervention-resolved-${data.id}`,
      timestamp: data.resolvedAt,
      data,
    })),
    ...resolvedLiveTestCards.map((card) => ({
      kind: 'live_test_resolved' as const,
      id: `live-test-resolved-${card.id}`,
      timestamp: card.timestamp,
      card,
    })),
  ].sort((a, b) => toEpochMs(a.timestamp) - toEpochMs(b.timestamp))

  // Decision / result evidence: re-read the ledger so the resolved card shows
  // the stored domain status (and denial attribution) without a reload.
  useEffect(() => {
    if (!optimizationMode || !convSessionId) return
    if (!interventionStatus && liveTestResultCount === 0) return
    void queryClient.invalidateQueries({ queryKey: liveTestRequestsQueryKey(convSessionId) })
  }, [optimizationMode, convSessionId, interventionStatus, liveTestResultCount, queryClient])

  const guardTerminalIntervention = (): boolean => {
    if (!interventionTargetTerminal) {
      return false
    }
    setNothingToReplay(true)
    return true
  }

  // FIX-20261109-BUG: invariant enforcement — while a turn is in flight the
  // window must never be blank. Compute whether each non-thinking indicator
  // would actually render: the standalone delegation status line (only when
  // no delegation cycles exist) or the in-cycle live status line (requires a
  // hydrated cycle whose id matches the active cycle and a non-null status
  // line, e.g. `using_tool` without a toolName renders nothing). If neither
  // renders, `showThinking` falls back to the thinking bubble.
  const standaloneStatusVisible = shouldShowStandaloneDelegationStatus
  const cycleLiveStatusVisible =
    !workingStatusSuppressed &&
    activeCycleRendered &&
    Boolean(standaloneDelegationStatusLine) &&
    chatStatus != null &&
    !isTerminalChatStatus(chatStatus)
  const showThinking =
    !workingStatusSuppressed &&
    ((chatStatus?.kind === 'thinking' || chatStatus?.kind === 'delegation_resumed') ||
      (turnInFlight &&
        chatStatus?.kind !== 'waiting_for_human' &&
        (chatStatus == null || !isTerminalChatStatus(chatStatus)) &&
        !standaloneStatusVisible &&
        !cycleLiveStatusVisible))

  // Resume session when dialog opens with a sessionId
  // For new chats, session is created only when user sends first message
  // FIX-20261031-071721: guard with a ref so concurrent effect invocations
  // (e.g. React StrictMode's double-mount in dev) never fire two resume POSTs
  // for the same session — the second response could race and re-render stale
  // history over freshly arrived live messages.
  const resumeRequestedForRef = useRef<string | null>(null)
  useEffect(() => {
    if (open && sessionId && !convSessionId && resumeRequestedForRef.current !== sessionId) {
      resumeRequestedForRef.current = sessionId
      void handleResumeSession(sessionId)
    }
  }, [open, sessionId])

  // FIX-20261031-071721 (defect 1): mid-turn WS loss recovery. When the chat
  // socket reconnects while a turn was in flight, the reply generated during
  // the outage was never transmitted — refetch the persisted history and
  // merge any turns not already rendered so the response appears live
  // instead of only after exit/reopen.
  const lastRecoveryEpochRef = useRef(0)
  useEffect(() => {
    if (!convSessionId || !recoveryEpoch || recoveryEpoch === lastRecoveryEpochRef.current) {
      return
    }
    lastRecoveryEpochRef.current = recoveryEpoch
    void (async () => {
      try {
        const { data } = await apiClient.post<ConversationSessionDetail>(
          `/conversations/${convSessionId}/resume`,
        )
        const history: ChatMessage[] = buildHistoryMessagesFromTurns(
          data.turns,
          (agentType) => t('conversations.sessions.statusDelegatingToAgent', { agentType }),
        )
        setResumedMessages((prev) =>
          mergeUnseenMessages(prev, wsMessagesRef.current, history),
        )
      } catch {
        // Best-effort recovery only.
      }
    })()
  }, [convSessionId, recoveryEpoch, t])

  // Refresh the sessions list when title arrives
  useEffect(() => {
    if (sessionTitle && agentTypeId) {
      void queryClient.invalidateQueries({ queryKey: ['conversations', agentTypeId] })
    }
  }, [sessionTitle, agentTypeId, queryClient])

  // Reset state and clean up empty sessions when dialog closes
  useEffect(() => {
    if (!open) {
      // Clean up empty session (no user messages sent)
      if (convSessionId && messages.filter(m => m.role === 'user').length === 0 && !sessionId) {
        // Delete empty session only if it was newly created (not resumed)
        // Use archive endpoint since there's no delete endpoint
        void apiClient.post(`/conversations/${convSessionId}/archive`).catch(() => {
          // Ignore errors - session might already be deleted
        })
      }
      
      setConvSessionId(null)
      setWsSessionId(null)
      setResumedMessages([])
      setInputClearToken((n) => n + 1)
      setError(null)
      setEndError(null)
      setEndConfirmOpen(false)
      setFullscreen(false)
      setPendingInitialMessage(null)
      setGuardrailHintAnchorEl(null)
      setResumedGuardrailUsage(null)
      setDismissedTerminalKey(null)
      setNothingToReplay(false)
      setLiveTestApprovedRequestId(null)
      seenLiveTestsRef.current = {}
      liveTestObservedAtRef.current = {}
      resumeRequestedForRef.current = null
      lastRecoveryEpochRef.current = 0
    }
  }, [open, convSessionId, messages, sessionId])

  useEffect(() => {
    if (!pendingInitialMessage || !convSessionId || !connected || isResuming) {
      return
    }

    const wasQueuedOrSent = sendMessage(pendingInitialMessage)
    if (wasQueuedOrSent) {
      setInputClearToken((n) => n + 1)
      setPendingInitialMessage(null)
    }
  }, [connected, convSessionId, isResuming, pendingInitialMessage, sendMessage])

  const handleResumeSession = async (sessionId: string) => {
    setIsResuming(true)
    setError(null)
    try {
      const { data } = await apiClient.post<ConversationSessionDetail>(
        `/conversations/${sessionId}/resume`,
      )
      setConvSessionId(data.id)
      setResumedGuardrailUsage(parsePersistedGuardrailUsage(data.guardrail_usage))
      // Convert history turns to ChatMessages for display
      const history: ChatMessage[] = buildHistoryMessagesFromTurns(
        data.turns,
        (agentType) => t('conversations.sessions.statusDelegatingToAgent', { agentType }),
      )
      setResumedMessages(history)
      hydrateDelegationFromHistory(buildDelegationHistoryFromTurns(data.turns))
      // Use conv session id as ws handle
      setWsSessionId(data.id)
    } catch (err) {
      setError(err)
    } finally {
      setIsResuming(false)
    }
  }
  const handleStartSession = async (): Promise<string | null> => {
    setIsResuming(true)
    setError(null)
    try {
      if (optimizationMode) {
        // Optimization conversations are created through the dedicated
        // endpoint: `{agent_type_id}` only — the subject IS the session's agent
        // type, and the channel is never client-supplied.
        const created = await createOptimizationConversation.mutateAsync()
        setConvSessionId(created.conversation.id)
        setWsSessionId(created.conversation.id)
        setResumedGuardrailUsage(null)
        return created.conversation.id
      }
      const { data } = await apiClient.post('/conversations', {
        agent_type_id: agentTypeId,
      })
      setConvSessionId(data.id)
      setWsSessionId(data.id)
      setResumedGuardrailUsage(null)
      return data.id
    } catch (err) {
      setError(err)
      return null
    } finally {
      setIsResuming(false)
    }
  }
  const handleEndSession = async () => {
    if (!convSessionId) return
    setEndError(null)
    try {
      await endSession.mutateAsync(convSessionId)
      // FIX-20261031-091657 (Defect B): after an explicit END, the next open
      // for this agent type must start a NEW session, not resume an old one.
      markAssistantSessionEnded(agentTypeId)
      setEndConfirmOpen(false)
      onClose() // Close dialog after ending session
    } catch (err) {
      setEndError(err)
    }
  }

  // FIX-20261101-111439 (defect 2): reset the in-chat state without ending or
  // archiving the current session. Used by "New Session" (fresh session) and
  // "View All Sessions" (switch to another session). The torn-down WebSocket
  // is closed as intentional by useChatSession's effect cleanup (no
  // reconnect), and the previous session stays `active` on the server.
  const resetForSessionSwitch = () => {
    setResumedMessages([])
    setResumedGuardrailUsage(null)
    setPendingInitialMessage(null)
    setInputClearToken((n) => n + 1)
    setDismissedTerminalKey(null)
    setNothingToReplay(false)
    setError(null)
    clearMessages()
    hydrateDelegationFromHistory({ cycles: [] })
  }

  // "New Session": start a FRESH session immediately. The current session is
  // intentionally left active (it remains visible in View All Sessions); the
  // end/archive API is never called and no force-new flag is set.
  const handleStartNewSession = async () => {
    if (turnStreaming) return
    resetForSessionSwitch()
    await handleStartSession()
  }

  // "View All Sessions": switch to an existing session and resume it.
  const handleSwitchToSession = (targetSessionId: string) => {
    if (turnStreaming) return
    setSessionsDialogOpen(false)
    resetForSessionSwitch()
    void handleResumeSession(targetSessionId)
  }

  const handleSend = async (rawText: string): Promise<boolean> => {
    const messageToSend = rawText.trim()
    if (!messageToSend) return false
    if (isResuming) return false

    // If no session exists yet, create it before sending first message
    if (!convSessionId) {
      const startedSessionId = await handleStartSession()
      if (!startedSessionId) {
        return false
      }

      setPendingInitialMessage(messageToSend)
      // The text stays in the input as the pending first message
      return false
    }

    // sendMessage queues when socket is not OPEN yet, then flushes on onopen.
    return sendMessage(messageToSend)
  }

  // Stable onSend identity for ChatInputBar — the memoized input bar must
  // not re-render (or lose its local text) when the parent re-renders.
  const handleSendRef = useRef(handleSend)
  handleSendRef.current = handleSend
  const handleSendStable = useCallback((text: string) => handleSendRef.current(text), [])

  // Auto-scroll the message timeline to the newest content. Only scrolls
  // when the operator is already near the bottom (never yanks the view back
  // while they are reading scrollback). Double-rAF ensures layout from the
  // newly rendered entries (markdown tables, tall bubbles) has settled, so
  // the latest message is fully visible instead of half-cut.
  const timelineScrollRef = useRef<HTMLDivElement | null>(null)
  // On first content load of a session (history hydration, reopen, session
  // switch) always jump to the newest message regardless of scroll position —
  // the "only when near bottom" rule applies to ongoing updates afterwards.
  // NOTE: the effect depends on the values themselves (a new array identity
  // each render) — a ref-based dependency would never re-run, since ref
  // identity is stable across renders.
  const lastForcedScrollKeyRef = useRef<string | null>(null)
  const autoScrollDeps = [
    messages,
    effectiveDelegationCycles,
    chatStatus,
    liveResolvedInterventions,
    activeIntervention,
  ]
  useEffect(() => {
    const el = timelineScrollRef.current
    if (!el) return
    const sessionKey = `${wsSessionId ?? ''}:${convSessionId ?? ''}`
    const needsInitialScroll =
      messages.length > 0 && lastForcedScrollKeyRef.current !== sessionKey
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    // Stick-to-bottom: always follow when within ~160px of the end.
    if (!needsInitialScroll && distanceFromBottom > 160) return
    if (needsInitialScroll) {
      lastForcedScrollKeyRef.current = sessionKey
    }
    // Double rAF ensures layout from the newly rendered entries (markdown
    // tables, tall bubbles) has settled, so the latest message is fully
    // visible instead of half-cut.
    const raf = requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        el.scrollTop = el.scrollHeight
      })
    })
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, autoScrollDeps)

  const displayTitle = sessionTitle ?? agentTypeName
  // Show "waiting for your input" via the connection chip ONLY when no
  // dedicated resume chip already conveys it (avoids the duplicated label).
  const connectionLabel =
    activeIntervention && !resumeChipState
      ? t('conversations.sessions.intervention.waitingForInput')
      : convSessionId && !connected
        ? pendingInitialMessage || isResuming
          ? t('conversations.sessions.connecting')
          : t('conversations.sessions.disconnected')
        : connected
          ? t('conversations.sessions.connected')
          : null

  const handleToggleGuardrailHint = (event: React.MouseEvent<HTMLElement>) => {
    setGuardrailHintAnchorEl((current) => (current ? null : event.currentTarget))
  }

  const handleCloseGuardrailHint = () => {
    setGuardrailHintAnchorEl(null)
  }

  return (
    <>
      <Dialog
        open={open}
        onClose={onClose}
        maxWidth={fullscreen ? false : 'lg'}
        fullWidth
        fullScreen={fullscreen}
        PaperProps={{
          sx: {
            height: fullscreen ? '100%' : '80vh',
          },
        }}
      >
        <DialogTitle>
          <Box display="flex" alignItems="center" gap={1}>
            <SmartToyIcon color="primary" />
            <Typography variant="h6" component="span" fontWeight={600}>
              {optimizationMode ? optimizationSubjectName : displayTitle}
            </Typography>
            {optimizationMode && (
              <span
                title={t('agents.optimizer.identityParity')}
                data-testid={testId('optimization-identity')}
                style={{ display: 'inline-flex' }}
              >
                <Chip
                  label={t('agents.optimizer.modeOnAgent', { name: optimizationSubjectName })}
                  color="secondary"
                  size="small"
                  data-testid={testId('optimization-mode-chip')}
                />
              </span>
            )}
            {connectionLabel && (
              <Chip
                label={connectionLabel}
                color={activeIntervention ? 'warning' : connected ? 'success' : pendingInitialMessage || isResuming ? 'info' : 'error'}
                size="small"
              />
            )}
            {resumeChipState && (
              <ResumeStateChip
                state={resumeChipState}
                testId={testId('resume-state-chip')}
              />
            )}
            <Box sx={{ ml: 'auto' }} display="flex" gap={1}>
              <IconButton size="small" onClick={() => setFullscreen(!fullscreen)}>
                {fullscreen ? <FullscreenExitIcon /> : <FullscreenIcon />}
              </IconButton>
              <IconButton size="small" onClick={onClose}>
                <CloseIcon />
              </IconButton>
            </Box>
          </Box>
        </DialogTitle>

        <DialogContent dividers sx={{ display: 'flex', flexDirection: 'column', p: 0 }}>
          {Boolean(error) && (
            <Box p={2}>
              <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />
            </Box>
          )}

          {assistantModelUnconfigured && (
            <Box p={2} pb={0}>
              <Alert
                severity="warning"
                data-testid={testId('assistant-model-not-configured')}
                action={
                  <ConfigureAssistantModelButton testId={testId('configure-assistant-model')} />
                }
              >
                <Typography variant="body2" fontWeight={600}>
                  {t('assistant.modelNotConfiguredTitle')}
                </Typography>
                <Typography variant="body2">
                  {t('assistant.modelNotConfiguredBody')}
                </Typography>
              </Alert>
            </Box>
          )}

          {/* ── Optimization mode chrome ─────────────────────────────────── */}
          {optimizationMode && (
            <>
              {optimizerModelBlocked && (
                <Box p={2} pb={0}>
                  <OptimizerModelAlert
                    reasonCode={optimizerModelReasonCode}
                    modelId={optimizerModelId}
                    testId={testId('optimizer-model-alert')}
                    action={
                      <OptimizerSystemConfigButton
                        testId={testId('optimizer-open-system-config')}
                      />
                    }
                  />
                </Box>
              )}
              {!optimizerModelBlocked && isOptimizerChatErrorCode(chatError?.code) && (
                <Box p={2} pb={0}>
                  <Alert severity="warning" data-testid={testId('optimizer-chat-error')}>
                    {t(`agents.optimizer.chatErrors.${chatError?.code}`, {
                      defaultValue: chatError?.message ?? '',
                    })}
                  </Alert>
                </Box>
              )}
              {!optimizerModelBlocked &&
                optimizationAvailability &&
                !optimizationAvailability.available && (
                  <Box p={2} pb={0}>
                    <Alert severity="warning" data-testid={testId('optimization-unavailable')}>
                      {optimizationAvailability.reason_code === 'no_successful_execution'
                        ? t('agents.optimizer.conversationReasonNoExecution')
                        : (optimizationAvailability.reason ??
                          t('agents.optimizer.modelAlertTitle'))}
                    </Alert>
                  </Box>
                )}
              {isDecisionPendingBlock(chatBlocked?.reason) && (
                <Box p={2} pb={0}>
                  <Alert severity="info" data-testid={testId('optimization-decision-blocked')}>
                    {chatBlocked?.reason === CHAT_BLOCKED_REASON_DECISION_PENDING
                      ? t('agents.optimizer.blockedDecision')
                      : chatBlocked?.message || t('agents.optimizer.blockedDecision')}
                  </Alert>
                </Box>
              )}
              <OptimizationSessionBar
                audit={optimizationAudit}
                subjectName={optimizationSubjectName}
                isConversational={optimizationIsConversational}
                agentTypeName={optimizationSubjectName}
                liveTestRunning={
                  pendingLiveTestState === 'running' || liveTestApprovedRequestId != null
                }
                testId={testId('optimization-session-bar')}
              />
            </>
          )}

          {isResuming ? (
            <Box display="flex" justifyContent="center" alignItems="center" flex={1}>
              <Typography>{t('app.loading')}</Typography>
            </Box>
          ) : (
            <>
              {/* Messages list */}
              <Box sx={{ m: 2, mb: 1.5, position: 'relative', flex: 1, minHeight: 0 }}>
                <Paper
                  ref={timelineScrollRef}
                  variant="outlined"
                  sx={{ height: '100%', overflow: 'auto', p: 2, bgcolor: 'grey.50' }}
                >
                  {timelineEntries.length === 0 ? (
                    <Typography color="text.secondary" align="center">
                      {t('conversations.sessions.chatEmpty')}
                    </Typography>
                  ) : (
                    timelineEntries.map((entry) => {
                      if (entry.kind === 'message') {
                        const msg = entry.message
                        return (
                          <Box
                            key={entry.id}
                            display="flex"
                            flexDirection={msg.role === 'user' ? 'row-reverse' : 'row'}
                            alignItems="flex-start"
                            gap={1}
                            mb={2}
                          >
                            <Avatar
                              sx={{
                                width: 32,
                                height: 32,
                                bgcolor: msg.role === 'user' ? 'primary.main' : 'secondary.main',
                              }}
                            >
                              {msg.role === 'user' ? <PersonIcon /> : <SmartToyIcon />}
                            </Avatar>
                            <Box sx={{ maxWidth: { xs: 'calc(100% - 48px)', sm: '70%' } }}>
                                <Paper
                                  sx={{
                                    p: 1.5,
                                    width: 'fit-content',
                                    maxWidth: '100%',
                                    bgcolor: msg.role === 'user' ? 'primary.light' : 'background.paper',
                                  }}
                                >
                                  {msg.role !== 'user' ? (
                                    <MaximizableContent title="Agent Response">
                                      <ContentRenderer mode="auto" content={msg.content} />
                                    </MaximizableContent>
                                  ) : (
                                    <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                                      {msg.content}
                                    </Typography>
                                  )}
                                </Paper>
                              <Typography color="text.secondary" display="block" sx={{ fontSize: '0.65rem', mt: 0.25, whiteSpace: 'nowrap' }}>
                                {formatDateTime(msg.timestamp)}
                              </Typography>
                            </Box>
                          </Box>
                        )
                      }

                      if (entry.kind === 'intervention_resolved') {
                        return <ResolvedInterventionBubble key={entry.id} data={entry.data} />
                      }

                      if (entry.kind === 'live_test_resolved') {
                        // Decided live test = chat history at its original
                        // position. Collapsed (no spinner — the normal chat
                        // status indicator is the only processing UI) and
                        // expandable to the script-run record.
                        return (
                          <Box key={entry.id} mb={2}>
                            <LiveTestApprovalCard
                              liveTest={entry.card.proposal}
                              agentTypeName={optimizationSubjectName}
                              state={entry.card.state}
                              scriptRun={entry.card.scriptRun}
                              errorText={entry.card.errorText}
                              decidedAt={entry.card.decidedAt}
                              onApprove={() => undefined}
                              onDeny={() => undefined}
                              testIdPrefix={testId(
                                `live-test-resolved-${entry.card.testIdIndex}`,
                              )}
                            />
                          </Box>
                        )
                      }

                      const cycle = entry.cycle
                      const isActiveCycle = cycle.id === effectiveActiveDelegationCycleId
                      const introAgentType = resolveCycleAgentType(cycle, isActiveCycle)
                      const introText = introAgentType
                        ? t('conversations.sessions.statusDelegatingToAgent', { agentType: introAgentType })
                        : t('conversations.sessions.snippetPanelTitle')
                      const statusLine =
                        chatStatus?.kind === 'waiting'
                          ? t('conversations.sessions.statusWaiting')
                          : chatStatus?.kind === 'using_tool' && chatStatus.toolName
                            ? /intervene|human/i.test(chatStatus.toolName)
                              ? t('conversations.sessions.statusRequestingHuman')
                              : t('conversations.sessions.statusUsingTool', { toolName: chatStatus.toolName })
                            : chatStatus?.kind === 'delegating' && chatStatus.agentType
                              ? t('conversations.sessions.statusDelegatingToAgent', { agentType: chatStatus.agentType })
                              : chatStatus?.kind === 'delegation_resumed'
                                ? t('conversations.sessions.statusThinking')
                                : null
                      const showLiveStatus = Boolean(
                        !workingStatusSuppressed &&
                          isActiveCycle &&
                          statusLine &&
                          chatStatus &&
                          chatStatus.kind !== 'thinking' &&
                          !isTerminalChatStatus(chatStatus),
                      )
                      return (
                        <Box
                          key={entry.id}
                          display="flex"
                          flexDirection="row"
                          alignItems="flex-start"
                          gap={1}
                          mb={2}
                          data-testid={testId('delegation-inline-row')}
                        >
                          <Avatar sx={{ width: 32, height: 32, bgcolor: 'secondary.main' }}>
                            <SmartToyIcon />
                          </Avatar>
                          <Box sx={{ maxWidth: { xs: 'calc(100% - 48px)', sm: '70%' } }}>
                            <Paper sx={{ p: 1.5, width: 'fit-content', maxWidth: '100%', bgcolor: 'background.paper' }}>
                              <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', mb: 1 }}>
                                {introText}
                              </Typography>

                              {showLiveStatus && (
                                  <Box display="flex" alignItems="center" gap={1} mb={1} data-testid={testId('chat-status-indicator')}>
                                  <CircularProgress size={16} />
                                  <Typography variant="body2">{statusLine}</Typography>
                                  {resumedTurnActive && (
                                    <ResumeStateChip
                                      state="resuming"
                                      testId={testId('resume-badge')}
                                    />
                                  )}
                                </Box>
                              )}

                              <Box data-testid={isActiveCycle ? testId('delegation-snippets') : testId('delegation-snippets-history')}>
                                <DelegationMiniLog
                                  receiverSessionId={cycle.executionSessionId}
                                  isActive={isActiveCycle && !cycle.completed}
                                />
                                {cycle.executionSessionId && cycle.completed && (
                                  <Box mt={1}>
                                    <Button
                                      size="small"
                                      onClick={() => {
                                        setExecutionDetailsSessionId(cycle.executionSessionId)
                                        setExecutionDetailsOpen(true)
                                      }}
                                    >
                                      {t('conversations.sessions.snippetPanelViewExecutionLogs')}
                                    </Button>
                                  </Box>
                                )}
                              </Box>
                            </Paper>
                            <Typography color="text.secondary" display="block" sx={{ fontSize: '0.65rem', mt: 0.25, whiteSpace: 'nowrap' }}>
                              {formatDateTime(cycle.startedAt)}
                            </Typography>
                          </Box>
                        </Box>
                      )
                    })
                  )}

                  {/* Optimization mode: nothing to optimize yet is information,
                      not a block — the conversation starts from the
                      operator's description. */}
                  {optimizationMode && optimizationDetail && !planPresent && (
                    <Alert severity="info" sx={{ mb: 2 }} data-testid={testId('optimization-empty-state')}>
                      <Typography variant="body2" fontWeight={700}>
                        {t('agents.optimizedPlan.talkToOptimizerEmptyTitle')}
                      </Typography>
                      <Typography variant="body2">
                        {t('agents.optimizedPlan.talkToOptimizerPrompt')}
                      </Typography>
                    </Alert>
                  )}

                  {activeIntervention && !interventionActionable && !(optimizationMode && activeIntervention.live_test) && (
                    <Box
                      data-testid={testId('intervention-closed')}
                      sx={{
                        mb: 1.5,
                        p: 1.25,
                        borderRadius: 1,
                        border: 1,
                        borderColor: 'divider',
                        bgcolor: 'action.hover',
                        opacity: 0.7,
                      }}
                    >
                      <Typography variant="body2" color="text.secondary">
                        {t('conversations.sessions.intervention.closedReadOnly')}
                      </Typography>
                    </Box>
                  )}

                  {showTerminalCard && (
                    <ResumeTerminalCard
                      reason={terminalStatus?.terminalReason ?? null}
                      referenceId={terminalStatus?.activeResumeId ?? null}
                      testId={testId}
                      onAskAgain={handleAskAgain}
                      onDismiss={dismissTerminalCard}
                    />
                  )}

                  {!isUnresumableTurn && terminalStatusKind && terminalStatusKind !== 'finished' && (
                    <Alert
                      severity="warning"
                      sx={{ mt: 1 }}
                      data-testid={testId('chat-status-terminal')}
                    >
                      {terminalStatusLabel}
                    </Alert>
                  )}

                  {showThinking && (
                    <Box display="flex" flexDirection="row" alignItems="flex-start" gap={1} mb={2} data-testid={testId('chat-status-indicator')}>
                      <Avatar sx={{ width: 32, height: 32, bgcolor: 'secondary.main' }}>
                        <SmartToyIcon />
                      </Avatar>
                      <Box sx={{ maxWidth: { xs: 'calc(100% - 48px)', sm: '70%' } }}>
                        <Paper
                          sx={{
                            p: 1.5,
                            width: 'fit-content',
                            maxWidth: '100%',
                            bgcolor: resumedTurnActive ? '#F5F3FF' : 'background.paper',
                            ...(resumedTurnActive
                              ? { border: '1px solid #DDD6FE' }
                              : {}),
                          }}
                        >
                          <Box display="flex" alignItems="center" gap={1}>
                            <CircularProgress size={16} />
                            <Typography variant="body2">
                              {t('conversations.sessions.statusThinking')}
                            </Typography>
                            {resumedTurnActive && (
                              <ResumeStateChip
                                state="resuming"
                                testId={testId('resume-badge')}
                              />
                            )}
                          </Box>
                        </Paper>
                        <Typography color="text.secondary" display="block" sx={{ fontSize: '0.65rem', mt: 0.25, whiteSpace: 'nowrap' }}>
                          {formatDateTime(chatStatus?.timestamp)}
                          {statusStale && turnInFlight
                            ? ` · ${t('conversations.sessions.statusChecking')}`
                            : ''}
                        </Typography>
                      </Box>
                    </Box>
                  )}

                  {shouldShowStandaloneDelegationStatus && (
                    <Box display="flex" flexDirection="row" alignItems="flex-start" gap={1} mb={2} data-testid={testId('chat-status-indicator')}>
                      <Avatar sx={{ width: 32, height: 32, bgcolor: 'secondary.main' }}>
                        <SmartToyIcon />
                      </Avatar>
                      <Box sx={{ maxWidth: { xs: 'calc(100% - 48px)', sm: '70%' } }}>
                        <Paper
                          sx={{
                            p: 1.5,
                            width: 'fit-content',
                            maxWidth: '100%',
                            bgcolor: resumedTurnActive ? '#F5F3FF' : 'background.paper',
                            ...(resumedTurnActive
                              ? { border: '1px solid #DDD6FE' }
                              : {}),
                          }}
                        >
                          <Box display="flex" alignItems="center" gap={1}>
                            <CircularProgress size={16} />
                            <Typography variant="body2">
                              {standaloneDelegationStatusLine}
                            </Typography>
                            {resumedTurnActive && (
                              <ResumeStateChip
                                state="resuming"
                                testId={testId('resume-badge')}
                              />
                            )}
                          </Box>
                        </Paper>
                        <Typography color="text.secondary" display="block" sx={{ fontSize: '0.65rem', mt: 0.25, whiteSpace: 'nowrap' }}>
                          {formatDateTime(chatStatus?.timestamp)}
                          {statusStale && turnInFlight
                            ? ` · ${t('conversations.sessions.statusChecking')}`
                            : ''}
                        </Typography>
                      </Box>
                    </Box>
                  )}

                  {/* Intervention Waiting Indicator — rendered CONTINUOUSLY
                      while an actionable pause is live (waiting_for_human
                      backed by a durable resume record, or a hydrated
                      pending-intervention flag), so there is no blank gap
                      between the agent pausing and the intervene_request
                      dialog. A stale `waiting_for_human` without a live
                      resume id is NOT a waiting turn and renders nothing. */}
                  {(waitingForInput || pendingIntervention) && !activeIntervention && !interventionTargetTerminal && (
                    <Box mb={2} data-testid={testId('intervention-pending-indicator')}>
                      <InterventionPendingIndicator />
                    </Box>
                  )}

                  {/* Duplicate approval against an already-terminal turn: the
                      response is never re-sent, the operator sees why. */}
                  {nothingToReplay && (
                    <Alert
                      severity="info"
                      sx={{ mb: 2 }}
                      data-testid={testId('nothing-to-replay')}
                    >
                      {t('conversations.sessions.terminalCard.nothingToReplay')}
                    </Alert>
                  )}

                  {/* Inline Intervention Dialog — live WS request, or the
                      REST-fetched pending request after a page refresh */}
                  {interventionActionable && (
                    <Box mb={2} data-testid={testId('intervention-dialog')}>
                      {pendingLiveTest && pendingLiveTestState ? (
                        <LiveTestApprovalCard
                          liveTest={pendingLiveTest}
                          agentTypeName={optimizationSubjectName}
                          state={pendingLiveTestState}
                          scriptRun={liveTestScriptRun(pendingLiveTest, pendingLiveTestResult)}
                          errorText={pendingLiveTestResult?.live_test_error ?? null}
                          isSubmitting={interventionIsSubmitting}
                          onApprove={() => {
                            if (guardTerminalIntervention()) return
                            // No generic resolved bubble: THIS card becomes the
                            // record of what ran (approved once, not remembered).
                            respondedSnapshotRef.current = null
                            setLiveTestApprovedRequestId(
                              pendingLiveTest.live_test_request_id,
                            )
                            void respondToIntervention(activeIntervention.request_id, {
                              approval_value: true,
                            })
                          }}
                          onDeny={() => {
                            if (guardTerminalIntervention()) return
                            respondedSnapshotRef.current = null
                            void respondToIntervention(activeIntervention.request_id, {
                              approval_value: false,
                            })
                          }}
                          testIdPrefix={testId('live-test-approval')}
                        />
                      ) : optimizationMode ? (
                        <OptimizerAskCard
                          reason={activeIntervention.reason}
                          interventionType={activeIntervention.intervention_type}
                          choices={activeIntervention.choices}
                          isSubmitting={interventionIsSubmitting}
                          dialogError={interventionDialogError}
                          onSelectChoice={(choice) => {
                            if (guardTerminalIntervention()) return
                            respondedSnapshotRef.current = {
                              request: activeIntervention,
                              answer: choice,
                            }
                            void respondToIntervention(activeIntervention.request_id, {
                              selected_choice: choice,
                            })
                          }}
                          onSubmitText={(text) => {
                            if (guardTerminalIntervention()) return
                            respondedSnapshotRef.current = {
                              request: activeIntervention,
                              answer: text,
                            }
                            void respondToIntervention(activeIntervention.request_id, {
                              text_value: text,
                            })
                          }}
                          onCancel={() => {
                            if (guardTerminalIntervention()) return
                            respondedSnapshotRef.current = null
                            void cancelInterventionRequest(activeIntervention.request_id)
                          }}
                          onApprove={() => {
                            if (guardTerminalIntervention()) return
                            respondedSnapshotRef.current = {
                              request: activeIntervention,
                              answer: t('conversations.sessions.intervention.approve'),
                            }
                            void respondToIntervention(activeIntervention.request_id, {
                              approval_value: true,
                            })
                          }}
                          onDeny={() => {
                            if (guardTerminalIntervention()) return
                            respondedSnapshotRef.current = {
                              request: activeIntervention,
                              answer: t('conversations.sessions.intervention.deny'),
                            }
                            void respondToIntervention(activeIntervention.request_id, {
                              approval_value: false,
                            })
                          }}
                          testIdPrefix={testId('optimizer-ask')}
                        />
                      ) : (
                        <InlineInterventionDialog
                          request={activeIntervention}
                          isSubmitting={interventionIsSubmitting}
                          dialogError={interventionDialogError}
                          onApprove={() => {
                            if (guardTerminalIntervention()) return
                            respondedSnapshotRef.current = {
                              request: activeIntervention,
                              answer: t('conversations.sessions.intervention.approve'),
                            }
                            void respondToIntervention(activeIntervention.request_id, {
                              approval_value: true,
                            })
                          }}
                          onDeny={() => {
                            if (guardTerminalIntervention()) return
                            respondedSnapshotRef.current = {
                              request: activeIntervention,
                              answer: t('conversations.sessions.intervention.deny'),
                            }
                            void respondToIntervention(activeIntervention.request_id, {
                              approval_value: false,
                            })
                          }}
                          onSelectChoice={(choice) => {
                            if (guardTerminalIntervention()) return
                            respondedSnapshotRef.current = {
                              request: activeIntervention,
                              answer: choice,
                            }
                            void respondToIntervention(activeIntervention.request_id, {
                              selected_choice: choice,
                            })
                          }}
                          onSubmitText={(text) => {
                            if (guardTerminalIntervention()) return
                            respondedSnapshotRef.current = {
                              request: activeIntervention,
                              answer: text,
                            }
                            void respondToIntervention(activeIntervention.request_id, {
                              text_value: text,
                            })
                          }}
                          onDismiss={() => {
                            // Cancel/dismiss — never emit a resolved bubble.
                            if (guardTerminalIntervention()) return
                            respondedSnapshotRef.current = null
                            void cancelInterventionRequest(activeIntervention.request_id)
                          }}
                        />
                      )}
                    </Box>
                  )}
                </Paper>

                {guardrailRows.length > 0 && (
                  <Fab
                    size="small"
                    color="default"
                    aria-label={t('conversations.sessions.guardrailFloatingAriaLabel')}
                    aria-expanded={guardrailHintOpen}
                    onClick={handleToggleGuardrailHint}
                    sx={{
                      position: 'absolute',
                      right: { xs: 10, md: 12 },
                      bottom: { xs: 10, md: 12 },
                      zIndex: 2,
                      boxShadow: 3,
                      minHeight: 34,
                      height: 34,
                      width: 'auto',
                      px: 1.2,
                      borderRadius: 999,
                      gap: 0.8,
                    }}
                  >
                    {guardrailHintOpen ? <VisibilityOffIcon fontSize="small" /> : <VisibilityIcon fontSize="small" />}
                    <Typography variant="caption" fontWeight={700} sx={{ whiteSpace: 'nowrap' }}>
                      {guardrailHintOpen
                        ? t('conversations.sessions.guardrailHintClose')
                        : t('conversations.sessions.guardrailHintOpen')}
                    </Typography>
                  </Fab>
                )}
              </Box>

              {/* Input box — PERF: self-contained bar, keystrokes re-render
                  only the bar, never the message timeline. */}
              <Box p={2} pt={0.5}>
                <ChatInputBar
                  disabled={
                    assistantModelUnconfigured ||
                    (optimizationMode && optimizerModelBlocked) ||
                    (convSessionId
                      ? interventionActionable ||
                        !connected ||
                        !!pendingQuestion ||
                        !!pendingInitialMessage ||
                        (optimizationMode &&
                          (pendingIntervention || isDecisionPendingBlock(chatBlocked?.reason)))
                      : false)
                  }
                  placeholder={
                    assistantModelUnconfigured
                      ? t('assistant.modelNotConfiguredInputDisabled')
                      : optimizationMode && optimizerModelBlocked
                        ? t('agents.optimizer.inputBlockedModel')
                        : interventionActionable ||
                            (optimizationMode &&
                              (pendingIntervention || isDecisionPendingBlock(chatBlocked?.reason)))
                          ? t('agents.optimizer.inputBlockedDecision')
                          : optimizationMode
                            ? turnStreaming
                              ? t('agents.optimizer.inputBlockedBusy')
                              : t('agents.optimizer.inputPlaceholder')
                            : t('conversations.sessions.chatPlaceholder')
                  }
                  sendLabel={t('conversations.sessions.send')}
                  onSend={handleSendStable}
                  clearToken={inputClearToken}
                />
              </Box>

              {guardrailRows.length > 0 && (
                <Popover
                  open={guardrailHintOpen}
                  anchorEl={guardrailHintAnchorEl}
                  onClose={handleCloseGuardrailHint}
                  anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
                  transformOrigin={{ vertical: 'bottom', horizontal: 'right' }}
                  slotProps={{
                    paper: {
                      sx: {
                        mt: -1,
                        width: { xs: 'calc(100vw - 32px)', sm: 360 },
                        maxHeight: { xs: '50vh', sm: 320 },
                        p: 1.25,
                        borderRadius: 2,
                        overflowY: 'auto',
                      },
                    },
                  }}
                >
                  <Stack direction="row" alignItems="center" justifyContent="space-between" mb={0.75}>
                    <Typography variant="subtitle2" fontWeight={700}>
                      {t('conversations.sessions.guardrailPanelTitle')}
                    </Typography>
                    <Button size="small" onClick={handleCloseGuardrailHint}>
                      {t('conversations.sessions.guardrailCollapse')}
                    </Button>
                  </Stack>
                  <Typography variant="caption" color="text.secondary" display="block" mb={1}>
                    {t('conversations.sessions.guardrailPanelSubtitle')}
                  </Typography>

                  <Stack spacing={0.75}>
                    {guardrailRows.map((row) => (
                      <Box
                        key={row.label}
                        sx={{
                          border: (theme) => `1px solid ${theme.palette.divider}`,
                          borderRadius: 1.5,
                          px: 1,
                          py: 0.85,
                          bgcolor: 'background.paper',
                        }}
                      >
                        <Typography variant="caption" color="text.secondary" display="block" mb={0.25}>
                          {row.label}
                        </Typography>
                        <Typography variant="body2" sx={{ fontFamily: 'monospace', wordBreak: 'break-word' }}>
                          {row.value}
                        </Typography>
                      </Box>
                    ))}
                  </Stack>
                </Popover>
              )}
            </>
          )}
        </DialogContent>

        <DialogActions sx={{ gap: 1 }}>
          <Button
            size="small"
            startIcon={<ListAltIcon />}
            data-testid={testId('view-all-sessions')}
            onClick={() => setSessionsDialogOpen(true)}
          >
            {t('conversations.sessions.viewAllSessions')}
          </Button>
          <Button
            size="small"
            startIcon={<AddIcon />}
            data-testid={testId('new-session')}
            onClick={() => void handleStartNewSession()}
            disabled={turnStreaming || isResuming}
          >
            {t('conversations.sessions.newSession')}
          </Button>
          <Box sx={{ flex: 1 }} />
          {convSessionId && (
            <Button
              size="small"
              variant="outlined"
              color="error"
              startIcon={<StopCircleIcon />}
              onClick={() => setEndConfirmOpen(true)}
              disabled={endSession.isPending || turnStreaming}
            >
              {t('conversations.sessions.end')}
            </Button>
          )}
          <Button size="small" onClick={onClose}>
            {t('conversations.sessions.exit')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* FIX-20261101-111439 (defect 2): View All Sessions switcher — lists the
          agent type's sessions and resumes the chosen one in this dialog. */}
      {sessionsDialogOpen && (
        <Dialog
          open
          onClose={() => setSessionsDialogOpen(false)}
          maxWidth="sm"
          fullWidth
          data-testid={testId('sessions-switcher')}
        >
          <DialogTitle>{t('conversations.sessions.viewAllSessionsTitle')}</DialogTitle>
          <DialogContent dividers>
            <SessionSwitcherList
              agentTypeId={agentTypeId}
              currentSessionId={convSessionId}
              onResume={handleSwitchToSession}
            />
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setSessionsDialogOpen(false)}>{t('app.cancel')}</Button>
          </DialogActions>
        </Dialog>
      )}

      {/* End Session confirmation dialog */}
      <Dialog
        open={endConfirmOpen}
        onClose={() => { setEndConfirmOpen(false); setEndError(null) }}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>{t('conversations.sessions.endConfirmTitle')}</DialogTitle>
        <DialogContent dividers>
          {endError != null && (
            <PermissionDeniedAlert error={endError} fallbackMessage={t('app.error')} />
          )}
          <Typography>{t('conversations.sessions.endConfirmBody')}</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setEndConfirmOpen(false); setEndError(null) }}>
            {t('app.cancel')}
          </Button>
          <Button
            variant="contained"
            color="error"
            onClick={() => void handleEndSession()}
            disabled={endSession.isPending}
          >
            {t('conversations.sessions.end')}
          </Button>
        </DialogActions>
      </Dialog>

      {executionDetailsSessionId && executionDetailsOpen && (
        <AgentExecutionDetailsDialog
          open={true}
          sessionId={executionDetailsSessionId}
          onClose={() => {
            setExecutionDetailsOpen(false)
            setExecutionDetailsSessionId(null)
          }}
        />
      )}
    </>
  )
}
