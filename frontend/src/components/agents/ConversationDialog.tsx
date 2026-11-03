import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import { ContentRenderer } from '../ContentRenderer'
import { MaximizableContent } from '../MaximizableContent'
import { AgentExecutionDetailsDialog } from './AgentExecutionDetailsDialog'
import { InlineInterventionDialog } from '../conversations/InlineInterventionDialog'
import { InterventionPendingIndicator } from '../conversations/InterventionPendingIndicator'
import { useConversationIntervention } from '../../hooks/useConversationIntervention'
import {
  useChatSession,
  type ChatMessage,
  type DelegationCycle,
  type ConversationalGuardrailUsage,
} from '../../hooks/useChatSession'
import { useEndConversationSession, useConversationSessionsPage } from '../../hooks/useConversationSessions'
import { markAssistantSessionEnded } from '../../utils/assistantSessionState'
import { buildDelegationHistoryFromTurns, buildHistoryMessagesFromTurns } from '../../utils/delegationHistory'
import type { AgentJob, AgentJobStatus, ConversationSessionDetail, ExecutionLogEntry } from '../../types'

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

function parsePersistedGuardrailUsage(value: unknown): ConversationalGuardrailUsage | null {
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
}: ConversationDialogProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [convSessionId, setConvSessionId] = useState<string | null>(null)
  const [wsSessionId, setWsSessionId] = useState<string | null>(null)
  const [resumedMessages, setResumedMessages] = useState<ChatMessage[]>([])
  const [inputText, setInputText] = useState('')
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
  } =
    useChatSession(wsSessionId, convSessionId)
  const effectiveGuardrailUsage = liveGuardrailUsage ?? resumedGuardrailUsage
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
  } = useConversationIntervention(
    convSessionId,
    sendInterventionResponse,
    cancelIntervention,
  )

  // FIX-20261101-111439 (defect 2): a conversational turn is in flight —
  // session-switching and end actions are blocked while this is true.
  const turnStreaming =
    isResuming ||
    !!pendingQuestion ||
    !!interventionRequest ||
    (chatStatus?.kind === 'thinking' ||
      chatStatus?.kind === 'delegating' ||
      chatStatus?.kind === 'waiting' ||
      chatStatus?.kind === 'using_tool' ||
      chatStatus?.kind === 'waiting_for_human' ||
      chatStatus?.kind === 'delegation_resumed')

  const formatTokenCountK = (value: number | null): string => {
    if (value == null) return t('agents.sessions.logViewer.summary.notAvailable')
    const tokenCountK = value / 1000
    const rounded = Math.round(tokenCountK * 10) / 10
    return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)}k tokens`
  }

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
  const timelineEntries: Array<
    | { kind: 'message'; id: string; timestamp: string; message: ChatMessage }
    | { kind: 'delegation_cycle'; id: string; timestamp: string; cycle: DelegationCycle }
  > = [
    ...messages.map((message) => ({
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
  ].sort((a, b) => toEpochMs(a.timestamp) - toEpochMs(b.timestamp))
  const standaloneDelegationStatusLine =
    chatStatus?.kind === 'waiting'
      ? t('conversations.sessions.statusWaiting')
      : chatStatus?.kind === 'using_tool' && chatStatus.toolName
        ? t('conversations.sessions.statusUsingTool', { toolName: chatStatus.toolName })
        : chatStatus?.kind === 'delegating' && chatStatus.agentType
          ? t('conversations.sessions.statusDelegatingToAgent', { agentType: chatStatus.agentType })
          : null
  const shouldShowStandaloneDelegationStatus =
    effectiveDelegationCycles.length === 0 &&
    Boolean(standaloneDelegationStatusLine) &&
    Boolean(chatStatus) &&
    chatStatus?.kind !== 'thinking' &&
    chatStatus?.kind !== 'timeout_or_failed'

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
      setInputText('')
      setError(null)
      setEndError(null)
      setEndConfirmOpen(false)
      setFullscreen(false)
      setPendingInitialMessage(null)
      setGuardrailHintAnchorEl(null)
      setResumedGuardrailUsage(null)
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
      setInputText('')
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
    setInputText('')
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

  const handleSend = async () => {
    if (!inputText.trim()) return
    const messageToSend = inputText.trim()
    if (isResuming) return

    // If no session exists yet, create it before sending first message
    if (!convSessionId) {
      const startedSessionId = await handleStartSession()
      if (!startedSessionId) {
        return
      }

      setPendingInitialMessage(messageToSend)
      return
    }

    // sendMessage queues when socket is not OPEN yet, then flushes on onopen.
    const wasQueuedOrSent = sendMessage(messageToSend)
    if (wasQueuedOrSent) {
      setInputText('')
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void handleSend()
    }
  }

  const displayTitle = sessionTitle ?? agentTypeName
  const connectionLabel =
    interventionRequest
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
              {displayTitle}
            </Typography>
            {connectionLabel && (
              <Chip
                label={connectionLabel}
                color={interventionRequest ? 'warning' : connected ? 'success' : pendingInitialMessage || isResuming ? 'info' : 'error'}
                size="small"
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

          {isResuming ? (
            <Box display="flex" justifyContent="center" alignItems="center" flex={1}>
              <Typography>{t('app.loading')}</Typography>
            </Box>
          ) : (
            <>
              {/* Messages list */}
              <Box sx={{ m: 2, mb: 1.5, position: 'relative', flex: 1, minHeight: 0 }}>
                <Paper
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
                            ? t('conversations.sessions.statusUsingTool', { toolName: chatStatus.toolName })
                            : chatStatus?.kind === 'delegating' && chatStatus.agentType
                              ? t('conversations.sessions.statusDelegatingToAgent', { agentType: chatStatus.agentType })
                              : null
                      const showLiveStatus = Boolean(
                        isActiveCycle &&
                          statusLine &&
                          chatStatus &&
                          chatStatus.kind !== 'thinking' &&
                          chatStatus.kind !== 'timeout_or_failed',
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

                  {chatStatus && chatStatus.kind === 'timeout_or_failed' && (
                    <Alert
                      severity="warning"
                      sx={{ mt: 1 }}
                      data-testid={testId('chat-status-terminal')}
                    >
                      {t('conversations.sessions.statusTimeoutOrFailed')}
                    </Alert>
                  )}

                  {chatStatus?.kind === 'thinking' && (
                    <Box display="flex" flexDirection="row" alignItems="flex-start" gap={1} mb={2} data-testid={testId('chat-status-indicator')}>
                      <Avatar sx={{ width: 32, height: 32, bgcolor: 'secondary.main' }}>
                        <SmartToyIcon />
                      </Avatar>
                      <Box sx={{ maxWidth: { xs: 'calc(100% - 48px)', sm: '70%' } }}>
                        <Paper sx={{ p: 1.5, width: 'fit-content', maxWidth: '100%', bgcolor: 'background.paper' }}>
                          <Box display="flex" alignItems="center" gap={1}>
                            <CircularProgress size={16} />
                            <Typography variant="body2">
                              {t('conversations.sessions.statusThinking')}
                            </Typography>
                          </Box>
                        </Paper>
                        <Typography color="text.secondary" display="block" sx={{ fontSize: '0.65rem', mt: 0.25, whiteSpace: 'nowrap' }}>
                          {formatDateTime(chatStatus?.timestamp)}
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
                        <Paper sx={{ p: 1.5, width: 'fit-content', maxWidth: '100%', bgcolor: 'background.paper' }}>
                          <Box display="flex" alignItems="center" gap={1}>
                            <CircularProgress size={16} />
                            <Typography variant="body2">
                              {standaloneDelegationStatusLine}
                            </Typography>
                          </Box>
                        </Paper>
                        <Typography color="text.secondary" display="block" sx={{ fontSize: '0.65rem', mt: 0.25, whiteSpace: 'nowrap' }}>
                          {formatDateTime(chatStatus?.timestamp)}
                        </Typography>
                      </Box>
                    </Box>
                  )}

                  {/* Intervention Waiting Indicator */}
                  {chatStatus?.kind === 'waiting_for_human' && !interventionRequest && (
                    <Box mb={2} data-testid={testId('intervention-pending-indicator')}>
                      <InterventionPendingIndicator />
                    </Box>
                  )}

                  {/* Inline Intervention Dialog */}
                  {interventionRequest && (
                    <Box mb={2} data-testid={testId('intervention-dialog')}>
                      <InlineInterventionDialog
                        request={interventionRequest}
                        isSubmitting={interventionIsSubmitting}
                        dialogError={interventionDialogError}
                        onApprove={() =>
                          respondToIntervention(interventionRequest.request_id, {
                            approval_value: true,
                          })
                        }
                        onDeny={() =>
                          respondToIntervention(interventionRequest.request_id, {
                            approval_value: false,
                          })
                        }
                        onSelectChoice={(choice) =>
                          respondToIntervention(interventionRequest.request_id, {
                            selected_choice: choice,
                          })
                        }
                        onSubmitText={(text) =>
                          respondToIntervention(interventionRequest.request_id, {
                            text_value: text,
                          })
                        }
                        onDismiss={() =>
                          cancelInterventionRequest(interventionRequest.request_id)
                        }
                      />
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

              {/* Input box */}
              <Box p={2} pt={0.5}>
                <Box display="flex" gap={1}>
                  <TextField
                    fullWidth
                    multiline
                    maxRows={4}
                    value={inputText}
                    onChange={(e) => setInputText(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={
                      assistantModelUnconfigured
                        ? t('assistant.modelNotConfiguredInputDisabled')
                        : interventionRequest
                          ? t('conversations.sessions.intervention.inputBlocked')
                          : t('conversations.sessions.chatPlaceholder')
                    }
                    disabled={
                      assistantModelUnconfigured ||
                      (convSessionId
                        ? !!interventionRequest || !connected || !!pendingQuestion || !!pendingInitialMessage
                        : false)
                    }
                    size="small"
                  />
                  <Button
                    variant="contained"
                    onClick={() => void handleSend()}
                    disabled={assistantModelUnconfigured || !inputText.trim() || (convSessionId ? !!interventionRequest || !connected || !!pendingQuestion || !!pendingInitialMessage : false)}
                    startIcon={<SendIcon />}
                  >
                    {t('conversations.sessions.send')}
                  </Button>
                </Box>
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
