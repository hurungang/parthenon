import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  IconButton,
  Paper,
  Stack,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import LogoutIcon from '@mui/icons-material/Logout'
import { useTranslation } from 'react-i18next'
import apiClient from '../../api/apiClient'
import type { AgentJob, RuntimeTopologyNode } from '../../types'
import { useAgentType } from '../../hooks/useAgentTypes'
import { useConversationSessions, useEndConversationSession } from '../../hooks/useConversationSessions'
import { AgentExecutionDetailsDialog } from './AgentExecutionDetailsDialog'
import { nodeKind, statusChipColor, statusLabelKey } from './runtimeNodeMeta'

interface AgentDetailBubbleProps {
  node: RuntimeTopologyNode
  position: { left: number; top: number }
  onDismiss: () => void
  onTerminate: (node: RuntimeTopologyNode) => void
  /** Invoked after a state-changing action (e.g. ending a session). */
  onChanged?: () => Promise<void> | void
}

// ── Guardrail usage (snake_case shape stored by the runtime executor) ────────

/**
 * Guardrail usage payload as persisted by the Agent Runtime executor:
 * ``AgentJob.output_data.guardrail_usage`` (agent-kind nodes) and
 * ``ConversationSession.guardrail_usage`` (conversation-kind nodes).
 * All keys are snake_case; the ``max_*`` limits are only present on the
 * conversation builder — agent jobs fall back to the agent-type limits.
 */
interface GuardrailUsageRaw {
  token_usage_current_session?: unknown
  token_budget?: unknown
  cumulative_iterations?: unknown
  max_iterations?: unknown
  delegated_steps?: unknown
  max_delegated_steps?: unknown
  delegation_depth?: unknown
  max_delegation_depth?: unknown
}

/** Parsed, typed guardrail usage (current values + limits when known). */
interface GuardrailUsage {
  tokenUsageCurrentSession: number | null
  tokenBudget: number | null
  cumulativeIterations: number | null
  maxIterations: number | null
  delegatedSteps: number | null
  maxDelegatedSteps: number | null
  delegationDepth: number | null
  maxDelegationDepth: number | null
}

/** Defensively parse a guardrail usage dict; null when absent/empty. */
function parseGuardrailUsage(raw: unknown): GuardrailUsage | null {
  if (raw == null || typeof raw !== 'object') return null
  const src = raw as GuardrailUsageRaw
  const num = (v: unknown): number | null =>
    typeof v === 'number' && Number.isFinite(v) ? v : null
  const usage: GuardrailUsage = {
    tokenUsageCurrentSession: num(src.token_usage_current_session),
    tokenBudget: num(src.token_budget),
    cumulativeIterations: num(src.cumulative_iterations),
    maxIterations: num(src.max_iterations),
    delegatedSteps: num(src.delegated_steps),
    maxDelegatedSteps: num(src.max_delegated_steps),
    delegationDepth: num(src.delegation_depth),
    maxDelegationDepth: num(src.max_delegation_depth),
  }
  const hasCurrent =
    usage.tokenUsageCurrentSession != null ||
    usage.cumulativeIterations != null ||
    usage.delegatedSteps != null ||
    usage.delegationDepth != null
  return hasCurrent ? usage : null
}

type GuardrailState = 'good' | 'near' | 'reached' | 'over'

/** Same near/over semantics as the execution-log summary panel. */
function resolveGuardrailState(
  current: number | null,
  limit: number | null,
): GuardrailState | null {
  if (current == null || limit == null || limit <= 0) return null
  const ratio = current / limit
  if (ratio > 1) return 'over'
  if (ratio === 1) return 'reached'
  if (ratio >= 0.8) return 'near'
  return 'good'
}

function usageValueColor(state: GuardrailState | null): string {
  if (state === 'over') return 'error.main'
  if (state === 'reached' || state === 'near') return 'warning.main'
  return 'text.primary'
}

interface GuardrailRow {
  key: string
  label: string
  current: number | null
  limit: number | null
}

function formatCount(value: number): string {
  return value.toLocaleString('en-US')
}

/**
 * Inline detail bubble shown beside the selected agent tile.
 *
 * Reuses the existing agent detail data (agent type, session, status,
 * depth) plus a guardrail summary of USAGE vs LIMITS (same four metrics
 * as the execution-log summary panel), an "Execution log" link for
 * agent-kind nodes (opens ``AgentExecutionDetailsDialog``), a terminate
 * action (via the page-owned ``NodeTerminationDialog``), and — for
 * sleeping conversation sessions — the existing "End Session" flow.
 */
export function AgentDetailBubble({
  node,
  position,
  onDismiss,
  onTerminate,
  onChanged,
}: AgentDetailBubbleProps) {
  const { t } = useTranslation()
  const kind = nodeKind(node)
  const isAgentKind = kind === 'agent'
  const isConversationKind = kind === 'conversation'
  const { data: agentType } = useAgentType(node.agent_type_id)
  const endConversation = useEndConversationSession(node.agent_type_id)
  const [endError, setEndError] = useState<string | null>(null)
  const [executionLogOpen, setExecutionLogOpen] = useState(false)

  const isSleepConversation = kind === 'conversation' && node.status === 'sleep'
  const latestCall = node.tool_calls?.[0]

  // Agent-kind: lazily fetch the backing job for its recorded guardrail
  // usage (``output_data.guardrail_usage``).  Failures degrade to "no
  // usage" — the box falls back to "—" placeholders.
  const { data: agentJob } = useQuery<AgentJob | null>({
    queryKey: ['agents', 'sessions', node.session_id, 'guardrail-usage'],
    queryFn: async () => {
      try {
        const { data } = await apiClient.get<AgentJob>(`/agents/sessions/${node.session_id}`)
        return data
      } catch {
        return null
      }
    },
    enabled: isAgentKind && !!node.session_id,
    staleTime: 30_000,
  })

  // Conversation-kind: usage lives on the conversation session itself
  // (``ConversationSession.guardrail_usage``, returned by the list/detail
  // conversation endpoints).
  const { data: conversations } = useConversationSessions(
    isConversationKind ? node.agent_type_id : '',
  )

  const guardrailUsage = useMemo<GuardrailUsage | null>(() => {
    if (isAgentKind) {
      const outputData: unknown = agentJob?.output_data
      const raw =
        outputData != null && typeof outputData === 'object'
          ? (outputData as Record<string, unknown>)['guardrail_usage']
          : null
      return parseGuardrailUsage(raw)
    }
    if (isConversationKind) {
      const conv = conversations?.find((c) => c.id === node.session_id)
      return parseGuardrailUsage(conv?.guardrail_usage)
    }
    return null
  }, [isAgentKind, isConversationKind, agentJob, conversations, node.session_id])

  // Current values come from the usage dict; limits from the usage dict's
  // own max_* when present, otherwise from the agent-type configuration.
  const guardrailRows: GuardrailRow[] = [
    {
      key: 'tokens',
      label: t('agents.sessions.logViewer.summary.currentSessionTokens'),
      current: guardrailUsage?.tokenUsageCurrentSession ?? null,
      limit: guardrailUsage?.tokenBudget ?? agentType?.guardrail_token_budget ?? null,
    },
    {
      key: 'iterations',
      label: t('agents.sessions.logViewer.summary.iterations'),
      current: guardrailUsage?.cumulativeIterations ?? null,
      limit: guardrailUsage?.maxIterations ?? agentType?.guardrail_max_iterations ?? null,
    },
    {
      key: 'delegated-steps',
      label: t('agents.sessions.logViewer.summary.delegatedSteps'),
      current: guardrailUsage?.delegatedSteps ?? null,
      limit: guardrailUsage?.maxDelegatedSteps ?? agentType?.guardrail_max_delegated_steps ?? null,
    },
    {
      key: 'delegation-depth',
      label: t('agents.sessions.logViewer.summary.delegationDepth'),
      current: guardrailUsage?.delegationDepth ?? null,
      limit: guardrailUsage?.maxDelegationDepth ?? agentType?.guardrail_max_delegation_depth ?? null,
    },
  ]

  const handleEndSession = async () => {
    setEndError(null)
    try {
      await endConversation.mutateAsync(node.session_id)
      await onChanged?.()
      onDismiss()
    } catch (err) {
      setEndError(err instanceof Error ? err.message : t('app.error'))
    }
  }

  return (
    <Paper
      elevation={4}
      role="dialog"
      aria-label={t('agents.sessions.runtimeSelectedNode')}
      data-testid="agent-detail-bubble"
      sx={{
        position: 'absolute',
        left: position.left,
        top: position.top,
        width: 288,
        zIndex: 30,
        p: 1.75,
        borderRadius: 2,
      }}
    >
      <Box display="flex" alignItems="flex-start" justifyContent="space-between" gap={1} mb={1}>
        <Typography variant="subtitle1" fontWeight={700} sx={{ wordBreak: 'break-word' }}>
          {node.agent_type_name ?? t('agents.sessions.runtimeUnknownAgent')}
        </Typography>
        <IconButton
          size="small"
          onClick={onDismiss}
          aria-label={t('agents.sessions.runtimeMonitorDismiss')}
          data-testid="agent-detail-bubble-close"
        >
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>

      <Stack direction="row" spacing={0.5} mb={1}>
        <Chip size="small" label={t(statusLabelKey(node.status, kind), node.status)} color={statusChipColor(node.status, kind)} />
      </Stack>

      <Box component="dl" sx={{ m: 0, mb: 1, display: 'grid', gridTemplateColumns: '82px 1fr', gap: 0.5 }}>
        <Typography component="dt" variant="caption" color="text.secondary">
          {t('agents.sessions.runtimeSession')}
        </Typography>
        <Typography component="dd" variant="caption" sx={{ m: 0, fontFamily: 'monospace', wordBreak: 'break-all' }}>
          {node.session_id}
        </Typography>
        {node.parent_session_id && (
          <>
            <Typography component="dt" variant="caption" color="text.secondary">
              {t('agents.sessions.runtimeParent')}
            </Typography>
            <Typography component="dd" variant="caption" sx={{ m: 0, fontFamily: 'monospace', wordBreak: 'break-all' }}>
              {node.parent_session_id}
            </Typography>
          </>
        )}
        <Typography component="dt" variant="caption" color="text.secondary">
          {t('agents.sessions.runtimeDepth')}
        </Typography>
        <Typography component="dd" variant="caption" sx={{ m: 0 }}>
          {node.depth_from_root}
        </Typography>
        {(node.trigger_source_label || node.trigger_source !== 'unknown') && (
          <>
            <Typography component="dt" variant="caption" color="text.secondary">
              {t('agents.sessions.runtimeTriggeredByLabel')}
            </Typography>
            <Typography
              component="dd"
              variant="caption"
              sx={{ m: 0 }}
              data-testid="agent-detail-trigger-source"
            >
              {node.trigger_source_label ?? t('agents.sessions.runtimeTriggerSourceUnknown')}
            </Typography>
          </>
        )}
        {latestCall && (
          <>
            <Typography component="dt" variant="caption" color="text.secondary">
              {t('agents.sessions.runtimeLatestToolCall')}
            </Typography>
            <Typography
              component="dd"
              variant="caption"
              sx={{ m: 0, wordBreak: 'break-all' }}
              data-testid="agent-detail-latest-tool-call"
            >
              {latestCall.tool_name}
            </Typography>
          </>
        )}
      </Box>

      <Box
        sx={{
          border: '1px solid',
          borderColor: 'divider',
          borderRadius: 1,
          bgcolor: 'action.hover',
          px: 1.25,
          py: 1,
          mb: 1.5,
        }}
      >
        <Typography variant="caption" fontWeight={700} color="text.secondary" display="block" mb={0.5}>
          {t('agents.sessions.runtimeMonitorGuardrailSummary')}
        </Typography>
        {guardrailRows.map((row) => {
          const state = resolveGuardrailState(row.current, row.limit)
          // Usage missing → "—" placeholder; limits unknown → "—" as well.
          const currentText = row.current != null ? formatCount(row.current) : '—'
          const limitText = row.limit != null ? formatCount(row.limit) : '—'
          return (
            <Box key={row.key} display="flex" justifyContent="space-between" py={0.25}>
              <Typography variant="caption" color="text.secondary">
                {row.label}
              </Typography>
              <Typography
                variant="caption"
                fontWeight={600}
                color={usageValueColor(state)}
                data-testid={`guardrail-usage-${row.key}`}
                data-state={state ?? 'none'}
              >
                {`${currentText} / ${limitText}`}
              </Typography>
            </Box>
          )
        })}
      </Box>

      {isAgentKind && (
        <Button
          size="small"
          data-testid="agent-detail-execution-log"
          onClick={() => setExecutionLogOpen(true)}
          sx={{ mb: 0.5, px: 0.5, justifyContent: 'flex-start' }}
        >
          {t('agents.sessions.runtimeMonitorExecutionLog')}
        </Button>
      )}

      <Divider sx={{ my: 1 }} />

      {endError != null && (
        <Alert severity="error" onClose={() => setEndError(null)} sx={{ mb: 1 }}>
          {endError}
        </Alert>
      )}

      {isSleepConversation ? (
        <Button
          variant="contained"
          color="warning"
          fullWidth
          startIcon={<LogoutIcon />}
          disabled={endConversation.isPending}
          data-testid="end-conversation-button"
          onClick={() => void handleEndSession()}
        >
          {endConversation.isPending ? (
            <CircularProgress size={18} color="inherit" />
          ) : (
            t('agents.sessions.runtimeEndSession')
          )}
        </Button>
      ) : (
        <Button
          variant="contained"
          color="error"
          fullWidth
          data-testid="terminate-node-button"
          onClick={() => onTerminate(node)}
        >
          {t('agents.sessions.runtimeMonitorTerminate')}
        </Button>
      )}

      {executionLogOpen && (
        <AgentExecutionDetailsDialog
          open
          onClose={() => setExecutionLogOpen(false)}
          sessionId={node.session_id}
        />
      )}
    </Paper>
  )
}
