import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
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
  IconButton,
  Paper,
  Popover,
  Stack,
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
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import { AgentExecutionDetailsDialog } from './AgentExecutionDetailsDialog'
import { InlineInterventionDialog } from '../conversations/InlineInterventionDialog'
import { InterventionPendingIndicator } from '../conversations/InterventionPendingIndicator'
import { useConversationIntervention } from '../../hooks/useConversationIntervention'
import {
  useChatSession,
  type ChatMessage,
  type DelegationCycle,
  type ConversationalGuardrailUsage,
  type DelegationSnippetLine,
} from '../../hooks/useChatSession'
import { useEndConversationSession } from '../../hooks/useConversationSessions'
import { buildDelegationHistoryFromTurns, buildHistoryMessagesFromTurns } from '../../utils/delegationHistory'
import type { ConversationSessionDetail } from '../../types'

interface ConversationDialogProps {
  open: boolean
  sessionId: string | null
  agentTypeId: string
  agentTypeName: string
  onClose: () => void
  initialFullscreen?: boolean
  testIdPrefix?: string
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

  const endSession = useEndConversationSession(agentTypeId)
  const testId = (suffix: string) => `${testIdPrefix}-${suffix}`

  const formatSnippetLine = (snippet: DelegationSnippetLine): string => {
    if (snippet.kind === 'delegating' && snippet.agentType) {
      return t('conversations.sessions.statusDelegatingToAgent', { agentType: snippet.agentType })
    }
    if (snippet.kind === 'waiting') {
      return t('conversations.sessions.statusWaiting')
    }
    if (snippet.kind === 'using_tool' && snippet.toolName) {
      return t('conversations.sessions.statusUsingTool', { toolName: snippet.toolName })
    }
    if (snippet.kind === 'log_title' && snippet.logTitle) {
      return snippet.logTitle
    }
    return t('conversations.sessions.snippetPanelEmpty')
  }

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
    toggleDelegationSnippetsCollapsed,
    hydrateDelegationFromHistory,
    sendMessage,
    interventionRequest,
    interventionQueueLength: _interventionQueueLength,
    sendInterventionResponse,
    cancelIntervention,
  } =
    useChatSession(wsSessionId, convSessionId)
  const effectiveGuardrailUsage = liveGuardrailUsage ?? resumedGuardrailUsage

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
  useEffect(() => {
    if (open && sessionId && !convSessionId) {
      void handleResumeSession(sessionId)
    }
  }, [open, sessionId])

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
      setEndConfirmOpen(false)
      onClose() // Close dialog after ending session
    } catch (err) {
      setEndError(err)
    }
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
                                <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                                  {msg.content}
                                </Typography>
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
                      const displaySnippets = cycle.snippets
                      const displaySnippet = displaySnippets[displaySnippets.length - 1]
                      const previewSnippet =
                        displaySnippets.length > 1 || displaySnippet?.kind === 'log_title'
                          ? displaySnippet
                          : null

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
                                <Box display="flex" alignItems="center" justifyContent="space-between" gap={1}>
                                  <Typography variant="subtitle2" fontWeight={600}>
                                    {t('conversations.sessions.snippetPanelTitle')}
                                  </Typography>
                                  {isActiveCycle && displaySnippets.length > 0 ? (
                                    <Button
                                      size="small"
                                      onClick={toggleDelegationSnippetsCollapsed}
                                      endIcon={cycle.snippetsCollapsed ? <ExpandMoreIcon /> : <ExpandLessIcon />}
                                    >
                                      {cycle.snippetsCollapsed
                                        ? t('conversations.sessions.snippetPanelExpand')
                                        : t('conversations.sessions.snippetPanelCollapse')}
                                    </Button>
                                  ) : null}
                                </Box>

                                {cycle.snippetsCollapsed ? (
                                  <Typography
                                    variant="body2"
                                    color="text.secondary"
                                    data-testid={isActiveCycle ? testId('snippet-preview') : testId('snippet-preview-history')}
                                  >
                                    {previewSnippet ? formatSnippetLine(previewSnippet) : t('conversations.sessions.snippetPanelEmpty')}
                                  </Typography>
                                ) : (
                                  <Box
                                    display="flex"
                                    flexDirection="column"
                                    gap={0.5}
                                    data-testid={isActiveCycle ? testId('snippet-expanded') : testId('snippet-expanded-history')}
                                  >
                                    {displaySnippets.map((snippet) => (
                                      <Typography key={snippet.id} variant="caption" color="text.secondary">
                                        {formatSnippetLine(snippet)}
                                      </Typography>
                                    ))}
                                  </Box>
                                )}

                                {cycle.completed && cycle.executionLogAvailable && cycle.executionSessionId && (
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
                      interventionRequest
                        ? t('conversations.sessions.intervention.inputBlocked')
                        : t('conversations.sessions.chatPlaceholder')
                    }
                    disabled={
                      convSessionId
                        ? !!interventionRequest || !connected || !!pendingQuestion || !!pendingInitialMessage
                        : false
                    }
                    size="small"
                  />
                  <Button
                    variant="contained"
                    onClick={() => void handleSend()}
                    disabled={!inputText.trim() || (convSessionId ? !!interventionRequest || !connected || !!pendingQuestion || !!pendingInitialMessage : false)}
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

        <DialogActions>
          <Button onClick={onClose}>{t('conversations.sessions.exit')}</Button>
          {convSessionId && (
            <Button
              variant="outlined"
              color="error"
              startIcon={<StopCircleIcon />}
              onClick={() => setEndConfirmOpen(true)}
              disabled={endSession.isPending}
            >
              {t('conversations.sessions.end')}
            </Button>
          )}
        </DialogActions>
      </Dialog>

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
