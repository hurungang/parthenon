import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Box,
  Button,
  Chip,
  Collapse,
  Divider,
  IconButton,
  Paper,
  Stack,
  Tooltip,
  Typography,
  useTheme,
} from '@mui/material'
import AccountTreeIcon from '@mui/icons-material/AccountTree'
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import BuildIcon from '@mui/icons-material/Build'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline'
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import LaunchIcon from '@mui/icons-material/Launch'
import { useTranslation } from 'react-i18next'
import apiClient from '../../api/apiClient'
import { isWorkingStepSpan } from '../../services/LogPresenter'
import type { ExecutionLogEntry, InterveneRequest, WorkingStep, WorkingStepSpan, WorkingStepIconType } from '../../types'

interface Props {
  spans: WorkingStepSpan[]
  onViewSubAgentExecution?: (sessionId: string) => void
  pendingInterventionsByChildSession?: Record<string, InterveneRequest>
}

function StepIcon({ iconType }: { iconType: WorkingStepIconType }) {
  const color: Record<WorkingStepIconType, string> = {
    llm: '#7c4dff',
    tool: '#0288d1',
    success: '#2e7d32',
    error: '#c62828',
    info: '#546e7a',
    delegating: '#7C3AED',
    waiting: '#D97706',
  }
  const sx = { fontSize: 18, color: color[iconType] }
  switch (iconType) {
    case 'llm':
      return <AutoAwesomeIcon sx={sx} />
    case 'tool':
      return <BuildIcon sx={sx} />
    case 'success':
      return <CheckCircleOutlineIcon sx={sx} />
    case 'error':
      return <ErrorOutlineIcon sx={sx} />
    case 'delegating':
      return <AccountTreeIcon sx={sx} />
    case 'waiting':
      return <HourglassEmptyIcon sx={sx} />
    default:
      return <InfoOutlinedIcon sx={sx} />
  }
}

// ── Delegation event colours ────────────────────────────────────────────────

interface DelegationColours {
  iconBg: string
  iconFg: string
  labelColour: string
  cardBg: string
  cardBorder: string
}

const DELEGATION_COLOURS: Record<string, DelegationColours> = {
  delegation_started: {
    iconBg: '#EDE9FE',
    iconFg: '#7C3AED',
    labelColour: '#7C3AED',
    cardBg: '#EDE9FE',
    cardBorder: '#DDD6FE',
  },
  delegation_waiting: {
    iconBg: '#FFFBEB',
    iconFg: '#D97706',
    labelColour: '#D97706',
    cardBg: '#FFFBEB',
    cardBorder: '#FDE68A',
  },
  delegation_resumed: {
    iconBg: '#DCFCE7',
    iconFg: '#166534',
    labelColour: '#166534',
    cardBg: '#DCFCE7',
    cardBorder: '#BBF7D0',
  },
  delegation_merged: {
    iconBg: '#EDE9FE',
    iconFg: '#7C3AED',
    labelColour: '#7C3AED',
    cardBg: '#EDE9FE',
    cardBorder: '#DDD6FE',
  },
  delegation_depth_blocked: {
    iconBg: '#FEE2E2',
    iconFg: '#B91C1C',
    labelColour: '#B91C1C',
    cardBg: '#FEE2E2',
    cardBorder: '#FECACA',
  },
  delegation_timeout: {
    iconBg: '#FEE2E2',
    iconFg: '#B91C1C',
    labelColour: '#B91C1C',
    cardBg: '#FEE2E2',
    cardBorder: '#FECACA',
  },
  delegation_failed: {
    iconBg: '#FEE2E2',
    iconFg: '#B91C1C',
    labelColour: '#B91C1C',
    cardBg: '#FEE2E2',
    cardBorder: '#FECACA',
  },
  human_intervene: {
    iconBg: '#E0F2FE',
    iconFg: '#0369A1',
    labelColour: '#0369A1',
    cardBg: '#E0F2FE',
    cardBorder: '#BAE6FD',
  },
}

function delegationEventLabel(eventType: string, t: ReturnType<typeof useTranslation>['t']): string {
  const map: Record<string, string> = {
    delegation_started: t('executions.delegationTimeline.labelDelegating', { defaultValue: 'DELEGATING' }),
    delegation_waiting: t('executions.delegationTimeline.labelWaiting', { defaultValue: 'WAITING' }),
    delegation_resumed: t('executions.delegationTimeline.labelResumed', { defaultValue: 'COMPLETED' }),
    delegation_merged: t('executions.delegationTimeline.labelMerged', { defaultValue: 'DELEGATION' }),
    delegation_depth_blocked: t('executions.delegationTimeline.labelBlocked', { defaultValue: 'DELEGATION BLOCKED' }),
    delegation_timeout: t('executions.delegationTimeline.labelTimeout', { defaultValue: 'DELEGATION TIMEOUT' }),
    delegation_failed: t('executions.delegationTimeline.labelFailed', { defaultValue: 'DELEGATION FAILED' }),
  }
  return map[eventType] ?? eventType.toUpperCase()
}

function StepRow({ step, onViewSubAgentExecution, pendingInterventionsByChildSession }: {
  step: WorkingStep
  onViewSubAgentExecution?: (sessionId: string) => void
  pendingInterventionsByChildSession?: Record<string, InterveneRequest>
}) {
  const { t } = useTranslation()
  const theme = useTheme()
  const [detailOpen, setDetailOpen] = useState(false)

  // Detect if this is a delegation event
  const delegationEventType = step.detail?.eventType?.toLowerCase() ?? ''
  const isDelegation = delegationEventType.startsWith('delegation_')

  // Parse delegation data from detail content
  const delegationData = useMemo(() => {
    if (!isDelegation || !step.detail) return null
    try {
      return JSON.parse(step.detail.content)
    } catch {
      return null
    }
  }, [isDelegation, step.detail])

  // For merged entries, resolve the effective/terminal event type
  const effectiveDelegationType =
    delegationEventType === 'delegation_merged'
      ? (delegationData?.['delegation_final_event_type'] as string) ?? delegationEventType
      : delegationEventType

  const effectiveColourKey =
    effectiveDelegationType && DELEGATION_COLOURS[effectiveDelegationType]
      ? effectiveDelegationType
      : delegationEventType

  const subAgentName = delegationData
    ? (delegationData['sub_agent'] as string | undefined)
      ?? (delegationData['delegation_target'] as string | undefined)
      ?? (delegationData['agent_type'] as string | undefined)
      ?? null
    : null

  const subAgentStateRaw = delegationData
    ? (delegationData['state'] as string | undefined) ?? null
    : null

  // Infer sub-agent state from effective event type when data doesn't have explicit state field
  const subAgentState: 'running' | 'completed' | 'failed' | null =
    subAgentStateRaw === 'running' ? 'running'
    : (subAgentStateRaw === 'completed' || subAgentStateRaw === 'done') ? 'completed'
    : (subAgentStateRaw === 'failed' || subAgentStateRaw === 'error') ? 'failed'
    : (effectiveDelegationType === 'delegation_started' || effectiveDelegationType === 'delegation_waiting') ? 'running'
    : effectiveDelegationType === 'human_intervene' ? 'running'
    : effectiveDelegationType === 'delegation_resumed' ? 'completed'
    : effectiveDelegationType === 'delegation_merged' ? 'completed'
    : effectiveDelegationType === 'delegation_failed' ? 'failed'
    : null

  const isDelegationActive = effectiveDelegationType === 'delegation_started' || effectiveDelegationType === 'delegation_waiting' || effectiveDelegationType === 'human_intervene'

  // Intermediate events for merged delegation
  const mergedEvents = delegationEventType === 'delegation_merged'
    ? (delegationData?.['delegation_events'] as Array<{ event_type: string; message: string; timestamp: string }> | undefined) ?? []
    : []

  // Sub-agent execution log entries (fetched for merged delegation)
  const [subAgentEntries, setSubAgentEntries] = useState<ExecutionLogEntry[]>([])
  const [subAgentEntriesLoading, setSubAgentEntriesLoading] = useState(false)
  const actualReceiverSessionId = delegationEventType === 'delegation_merged'
    ? (delegationData?.['receiver_session_id'] as string | undefined) ?? null
    : null

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchSubAgentEntries = useCallback((sessionId: string, initial: boolean) => {
    if (initial) setSubAgentEntriesLoading(true)
    apiClient.get<ExecutionLogEntry[]>(`/agents/sessions/${sessionId}/logs`)
      .then(({ data }) => {
        setSubAgentEntries(data)
        if (initial) setSubAgentEntriesLoading(false)
      })
      .catch(() => {
        setSubAgentEntries([])
        if (initial) setSubAgentEntriesLoading(false)
      })
  }, [])

  useEffect(() => {
    if (!actualReceiverSessionId || !detailOpen) {
      setSubAgentEntries([])
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
      return
    }

    fetchSubAgentEntries(actualReceiverSessionId, true)

    if (isDelegationActive) {
      pollRef.current = setInterval(
        () => fetchSubAgentEntries(actualReceiverSessionId, false),
        4000,
      )
    }

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [actualReceiverSessionId, detailOpen, isDelegationActive, fetchSubAgentEntries])

  const formattedTime = new Date(step.timestamp).toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  } as Intl.DateTimeFormatOptions)

  // Rich inline delegation UI
  if (isDelegation) {
    const colours = DELEGATION_COLOURS[effectiveColourKey] ?? DELEGATION_COLOURS.delegation_started
    const isMerged = delegationEventType === 'delegation_merged'

    return (
      <Box>
        <Box
          sx={{
            display: 'flex',
            gap: 1.5,
            py: 1.25,
            px: 1,
            position: 'relative',
            transition: 'background 0.2s ease',
            '&:hover': { bgcolor: 'action.hover' },
            bgcolor: isDelegationActive ? 'action.hover' : 'transparent',
          }}
        >
          {/* Timestamp */}
          <Typography
            variant="caption"
            sx={{
              minWidth: 72,
              flexShrink: 0,
              fontFamily: 'monospace',
              color: 'text.secondary',
              fontSize: 11,
              pt: 0.5,
            }}
          >
            {formattedTime}
          </Typography>

          {/* Icon */}
          <Box
            sx={{
              width: 28,
              height: 28,
              borderRadius: '50%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              bgcolor: colours.iconBg,
              color: colours.iconFg,
              flexShrink: 0,
              mt: 0.25,
              animation: isDelegationActive ? 'dtPulse 1.5s infinite' : undefined,
              '@keyframes dtPulse': {
                '0%, 80%, 100%': { opacity: 0.3 },
                '40%': { opacity: 1 },
              },
            }}
          >
            <StepIcon iconType={step.iconType} />
          </Box>

          {/* Body */}
          <Box sx={{ flex: 1, minWidth: 0 }}>
            {/* Event type label */}
            <Typography
              variant="caption"
              sx={{
                fontSize: 10.5,
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: 0.5,
                color: colours.labelColour,
                display: 'block',
                mb: 0.25,
              }}
            >
              {delegationEventLabel(delegationEventType, t)}
            </Typography>

            {/* For merged entries, show final message instead of first */}
            <Typography variant="body2" sx={{ fontSize: 13, color: 'text.primary', lineHeight: 1.45, wordBreak: 'break-word' }}>
              {isMerged
                ? (delegationData?.['delegation_final_message'] as string) ?? step.message
                : step.message}
            </Typography>

            {/* Check if this sub-agent has a pending human intervention */}
            {(() => {
              const childSessionId = delegationEventType === 'delegation_merged'
                ? (delegationData?.['receiver_session_id'] as string | undefined)
                : null
              const pendingIntervention = childSessionId && pendingInterventionsByChildSession?.[childSessionId]
              return pendingIntervention && subAgentState === 'running'
                ? (
                  <Box
                    sx={{
                      mt: 1,
                      borderRadius: 1,
                      overflow: 'hidden',
                      border: 2,
                      borderColor: '#FF9800',
                      bgcolor: '#FFF8E1',
                    }}
                  >
                    {/* Sub-agent card merged with intervention notice */}
                    <Box
                      sx={{
                        p: 1.25,
                        display: 'flex',
                        alignItems: 'center',
                        gap: 1.25,
                      }}
                    >
                      <Box
                        sx={{
                          width: 32,
                          height: 32,
                          borderRadius: '50%',
                          bgcolor: '#D97706',
                          color: '#fff',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: 15,
                          flexShrink: 0,
                        }}
                      >
                        <AccountTreeIcon sx={{ fontSize: 16 }} />
                      </Box>
                      <Box sx={{ flex: 1, minWidth: 0 }}>
                        <Typography variant="body2" sx={{ fontWeight: 600, color: '#92400E', fontSize: 13 }}>
                          {subAgentName}
                        </Typography>
                        <Typography variant="caption" sx={{ fontSize: 11, color: '#D97706', fontWeight: 600 }}>
                          {t('executions.delegationTimeline.requiresIntervention', { defaultValue: 'Requires human input' })}
                        </Typography>
                      </Box>
                      <Chip
                        label={t('executions.delegationTimeline.stateWaiting', { defaultValue: 'Waiting' })}
                        size="small"
                        sx={{ fontSize: 11, fontWeight: 600, height: 22, bgcolor: '#FEF3C7', color: '#92400E' }}
                      />
                    </Box>
                    {/* Intervention reason */}
                    <Box sx={{ px: 1.25, pb: 1.25 }}>
                      <Typography variant="caption" sx={{ fontSize: 12, color: '#78350F', lineHeight: 1.5, display: 'block' }}>
                        {pendingIntervention.reason}
                      </Typography>
                    </Box>
                  </Box>
                )
                : subAgentName && (
                  <Box
                    sx={{
                      mt: 1,
                      p: 1.25,
                      borderRadius: 1,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 1.25,
                      bgcolor: colours.cardBg,
                      border: 1,
                      borderColor: colours.cardBorder,
                    }}
                  >
                    <Box
                      sx={{
                        width: 32,
                        height: 32,
                        borderRadius: '50%',
                        bgcolor: colours.iconFg,
                        color: '#fff',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: 15,
                        flexShrink: 0,
                      }}
                    >
                      <AccountTreeIcon sx={{ fontSize: 16 }} />
                    </Box>
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Typography variant="body2" sx={{ fontWeight: 600, color: colours.labelColour, fontSize: 13 }}>
                        {subAgentName}
                      </Typography>
                      <Typography variant="caption" sx={{ fontSize: 11, color: colours.iconFg }}>
                        {subAgentState === 'running'
                          ? t('executions.delegationTimeline.subAgentExecuting', { defaultValue: 'Sub-agent executing...' })
                          : subAgentState === 'completed'
                            ? t('executions.delegationTimeline.subAgentCompleted', { defaultValue: 'Sub-agent completed' })
                            : subAgentState === 'failed'
                              ? t('executions.delegationTimeline.subAgentFailed', { defaultValue: 'Sub-agent failed' })
                              : ''}
                      </Typography>
                    </Box>
                    {subAgentState && (
                      <Chip
                        label={
                          subAgentState === 'running'
                            ? t('executions.delegationTimeline.stateRunning', { defaultValue: 'Running' })
                            : subAgentState === 'completed'
                              ? t('executions.delegationTimeline.stateCompleted', { defaultValue: 'Completed' })
                              : t('executions.delegationTimeline.stateFailed', { defaultValue: 'Failed' })
                        }
                        size="small"
                        sx={{
                          fontSize: 11,
                          fontWeight: 600,
                          height: 22,
                          bgcolor: subAgentState === 'running'
                            ? '#EDE9FE'
                            : subAgentState === 'completed'
                              ? '#DCFCE7'
                              : '#FEE2E2',
                          color: subAgentState === 'running'
                            ? '#6D28D9'
                            : subAgentState === 'completed'
                              ? '#15803D'
                              : '#B91C1C',
                        }}
                      />
                    )}
                  </Box>
                )
            })()}

            {/* For merged entries, show expand icon to view delegation timeline */}
            {isMerged && mergedEvents.length > 0 && (
              <Box sx={{ mt: 1 }}>
                <Tooltip title={detailOpen ? 'Collapse delegation timeline' : 'View delegation timeline'}>
                  <IconButton
                    size="small"
                    onClick={() => setDetailOpen((v) => !v)}
                    aria-expanded={detailOpen}
                    aria-label={detailOpen ? 'Collapse delegation timeline' : 'View delegation timeline'}
                    sx={{ fontSize: 12, color: 'text.secondary' }}
                  >
                    <Typography variant="caption" sx={{ mr: 0.5, fontSize: 11 }}>
                      {detailOpen ? 'Hide timeline' : 'Show timeline'}
                    </Typography>
                    <ExpandMoreIcon
                      fontSize="small"
                      sx={{
                        transform: detailOpen ? 'rotate(180deg)' : 'rotate(0deg)',
                        transition: 'transform 0.2s',
                      }}
                    />
                  </IconButton>
                </Tooltip>
              </Box>
            )}

            {/* Animated loading bar for delegating/waiting */}
            {isDelegationActive && (
              <Box
                sx={{
                  height: 2,
                  bgcolor: theme.palette.divider,
                  borderRadius: 2,
                  mt: 1,
                  overflow: 'hidden',
                }}
              >
                <Box
                  sx={{
                    height: '100%',
                    width: 0,
                    borderRadius: 2,
                    bgcolor: effectiveDelegationType === 'delegation_started' ? '#7C3AED' : '#D97706',
                    animation: 'dtLoadBar 2s ease-in-out infinite',
                    '@keyframes dtLoadBar': {
                      '0%': { width: 0, marginLeft: 0 },
                      '50%': { width: '65%', marginLeft: '17%' },
                      '100%': { width: 0, marginLeft: '100%' },
                    },
                  }}
                />
              </Box>
            )}
          </Box>
        </Box>

        {/* Delegation timeline (expanded) for merged entries */}
        {isMerged && (
          <Collapse in={detailOpen}>
            <Box sx={{ ml: 9.5, mb: 1, p: 1.5, bgcolor: 'grey.50', borderRadius: 1, border: 1, borderColor: 'divider' }}>
              <Typography variant="caption" sx={{ fontWeight: 600, display: 'block', mb: 0.75, color: 'text.secondary' }}>
                Delegation timeline
              </Typography>
              {mergedEvents.map((evt, idx) => {
                const evtColours = DELEGATION_COLOURS[evt.event_type]
                const evtTime = new Date(evt.timestamp).toLocaleTimeString('en-US', {
                  hour: '2-digit',
                  minute: '2-digit',
                  second: '2-digit',
                } as Intl.DateTimeFormatOptions)
                return (
                  <Box key={idx} sx={{ display: 'flex', gap: 1, py: 0.25, alignItems: 'center' }}>
                    <Typography variant="caption" sx={{ fontFamily: 'monospace', fontSize: 10, color: 'text.disabled', minWidth: 60 }}>
                      {evtTime}
                    </Typography>
                    <Box
                      sx={{
                        width: 8,
                        height: 8,
                        borderRadius: '50%',
                        bgcolor: evtColours?.iconFg ?? '#ccc',
                        flexShrink: 0,
                      }}
                    />
                    <Typography variant="caption" sx={{ fontSize: 11, color: evtColours?.labelColour ?? 'text.secondary' }}>
                      {evt.message}
                    </Typography>
                  </Box>
                )
              })}

              {/* Sub-agent high-level execution entries */}
              {subAgentEntriesLoading && (
                <Typography variant="caption" sx={{ display: 'block', mt: 1, color: 'text.secondary', fontStyle: 'italic' }}>
                  Loading sub-agent execution log...
                </Typography>
              )}
              {!subAgentEntriesLoading && subAgentEntries.length > 0 && (
                <Box sx={{ mt: 1.5 }}>
                  <Typography variant="caption" sx={{ fontWeight: 600, display: 'block', mb: 0.5, color: 'text.secondary' }}>
                    Sub-agent execution
                  </Typography>
                  {subAgentEntries
                    .filter(e => ['tool_call', 'llm_request', 'llm_response', 'observe'].includes(e.event_type))
                    .slice(-10)
                    .map((entry) => {
                      const entryTime = new Date(entry.timestamp).toLocaleTimeString('en-US', {
                        hour: '2-digit', minute: '2-digit', second: '2-digit',
                      } as Intl.DateTimeFormatOptions)
                      const toolName = entry.data?.['tool_name'] as string | undefined
                      const tool = entry.data?.['tool'] as string | undefined
                      const toolLabel = toolName ?? tool ?? ''
                      return (
                        <Box key={entry.id} sx={{ display: 'flex', gap: 1, py: 0.25, alignItems: 'center' }}>
                          <Typography variant="caption" sx={{ fontFamily: 'monospace', fontSize: 10, color: 'text.disabled', minWidth: 60 }}>
                            {entryTime}
                          </Typography>
                          <Box sx={{
                            width: 8, height: 8, borderRadius: '50%',
                            bgcolor: entry.event_type === 'tool_call' ? '#0288d1' : entry.event_type === 'llm_request' ? '#7c4dff' : '#757575',
                            flexShrink: 0,
                          }} />
                          <Typography variant="caption" sx={{ fontSize: 11, color: 'text.secondary' }}>
                            {entry.event_type === 'tool_call'
                              ? `Using tool${toolLabel ? `: ${toolLabel}` : ''}`
                              : entry.event_type === 'llm_request' ? 'Thinking...'
                              : entry.event_type === 'llm_response' ? 'Got response'
                              : entry.message}
                          </Typography>
                        </Box>
                      )
                    })}
                </Box>
              )}

              {/* View Full Execution Log button */}
              {actualReceiverSessionId && !subAgentEntriesLoading && (
                <Box sx={{ mt: 1.5 }}>
                  <Button
                    size="small"
                    variant="outlined"
                    onClick={() => onViewSubAgentExecution?.(actualReceiverSessionId)}
                    endIcon={<LaunchIcon sx={{ fontSize: 14 }} />}
                    sx={{ fontSize: 12, textTransform: 'none' }}
                  >
                    View Full Execution Log
                  </Button>
                </Box>
              )}
            </Box>
          </Collapse>
        )}
      </Box>
    )
  }

  // Standard non-delegation step row
  const isError = step.iconType === 'error'
  return (
    <Box
      sx={
        isError
          ? { bgcolor: '#FFF5F5', borderLeft: '3px solid #C62828', borderRadius: '0 4px 4px 0', mb: 0.25 }
          : undefined
      }
    >
      <Box display="flex" alignItems="center" gap={1} py={0.75} px={isError ? 1 : 0}>
        <StepIcon iconType={step.iconType} />
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ minWidth: 80, fontFamily: 'monospace' }}
        >
          {formattedTime}
        </Typography>
        <Typography variant="body2" sx={{ flex: 1 }}>
          {step.message}
        </Typography>
        {step.detail && (
          <Tooltip title={detailOpen ? 'Collapse detail' : 'Expand detail'}>
            <IconButton
              size="small"
              onClick={() => setDetailOpen((v) => !v)}
              aria-expanded={detailOpen}
              aria-label={detailOpen ? 'Collapse detail' : 'Expand detail'}
            >
              <ExpandMoreIcon
                fontSize="small"
                sx={{
                  transform: detailOpen ? 'rotate(180deg)' : 'rotate(0deg)',
                  transition: 'transform 0.2s',
                }}
              />
            </IconButton>
          </Tooltip>
        )}
      </Box>
      {step.detail && (
        <Collapse in={detailOpen}>
          <Box ml={4} mb={1}>
            <Chip
              label={step.detail.label}
              size="small"
              variant="outlined"
              sx={{ mb: 0.5, fontSize: '0.7rem' }}
            />
            <Box
              component="pre"
              sx={{
                bgcolor: 'grey.50',
                border: 1,
                borderColor: 'divider',
                borderRadius: 1,
                p: 1.5,
                fontSize: 12,
                fontFamily: 'monospace',
                overflow: 'auto',
                maxHeight: 240,
                m: 0,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {step.detail.content}
            </Box>
          </Box>
        </Collapse>
      )}
    </Box>
  )
}

/** Renders a single span section (collapsible, with nested spans or leaf steps). */
function SpanSection({
  span,
  depth = 0,
  onViewSubAgentExecution,
  pendingInterventionsByChildSession,
}: {
  span: WorkingStepSpan
  depth?: number
  onViewSubAgentExecution?: (sessionId: string) => void
  pendingInterventionsByChildSession?: Record<string, InterveneRequest>
}) {
  const [collapsed, setCollapsed] = useState(span.collapsed)

  const indentPx = depth * 16

  return (
    <Box>
      {/* Span header — toggle button */}
      <Box
        display="flex"
        alignItems="center"
        gap={0.75}
        py={0.75}
        pl={`${indentPx}px`}
        onClick={() => setCollapsed((v) => !v)}
        sx={{ cursor: 'pointer', userSelect: 'none' }}
        role="button"
        aria-expanded={!collapsed}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setCollapsed((v) => !v)
          }
        }}
      >
        <ExpandMoreIcon
          sx={{
            fontSize: 18,
            transform: collapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
            transition: 'transform 0.2s',
            color: 'text.secondary',
          }}
        />
        <StepIcon iconType={span.iconType} />
        <Typography variant="subtitle2" fontWeight={600}>
          {span.title}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          ({span.children.length})
        </Typography>
      </Box>

      {/* Span children */}
      <Collapse in={!collapsed}>
        <Box
          sx={{
            ml: `${indentPx + 16}px`,
            borderLeft: 1,
            borderColor: 'divider',
            pl: 1,
            mb: 0.5,
          }}
        >
          <Stack divider={<Divider />}>
            {span.children.map((child) =>
              isWorkingStepSpan(child) ? (
                <SpanSection key={child.id} span={child} depth={depth + 1} onViewSubAgentExecution={onViewSubAgentExecution} pendingInterventionsByChildSession={pendingInterventionsByChildSession} />
              ) : (
                <StepRow key={child.id} step={child} onViewSubAgentExecution={onViewSubAgentExecution} pendingInterventionsByChildSession={pendingInterventionsByChildSession} />
              )
            )}
          </Stack>
        </Box>
      </Collapse>
    </Box>
  )
}

export function WorkingStepsPanel({ spans, onViewSubAgentExecution, pendingInterventionsByChildSession }: Props) {
  const { t } = useTranslation()
  const [sectionCollapsed, setSectionCollapsed] = useState(false)

  const totalSteps = spans.reduce(function countChildren(sum, s): number {
    return sum + s.children.reduce(
      (acc, child) =>
        isWorkingStepSpan(child)
          ? countChildren(acc, child)
          : acc + 1,
      0
    )
  }, 0)

  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      <Box
        display="flex"
        alignItems="center"
        gap={1}
        mb={2}
        onClick={() => setSectionCollapsed((v) => !v)}
        sx={{ cursor: 'pointer', userSelect: 'none' }}
        role="button"
        aria-expanded={!sectionCollapsed}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setSectionCollapsed((v) => !v)
          }
        }}
      >
        <Typography variant="h6" fontWeight={600}>
          {t('agents.sessions.logViewer.workingSteps.title')}
        </Typography>
        {spans.length > 0 && (
          <Typography variant="body2" color="text.secondary">
            ({sectionCollapsed 
              ? t('agents.sessions.logViewer.workingSteps.showSteps', { count: totalSteps })
              : t('agents.sessions.logViewer.workingSteps.hideSteps')})
          </Typography>
        )}
      </Box>

      {spans.length === 0 && (
        <Typography variant="body2" color="text.secondary">
          {t('agents.sessions.logViewer.workingSteps.empty')}
        </Typography>
      )}

      {spans.length > 0 && (
        <Collapse in={!sectionCollapsed}>
          <Stack divider={<Divider />}>
            {spans.map((span) => (
              <SpanSection key={span.id} span={span} onViewSubAgentExecution={onViewSubAgentExecution} pendingInterventionsByChildSession={pendingInterventionsByChildSession} />
            ))}
          </Stack>
        </Collapse>
      )}
    </Paper>
  )
}

