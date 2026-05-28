import {
  Box,
  Chip,
  LinearProgress,
  Paper,
  Stack,
  Typography,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty'
import HelpOutlineIcon from '@mui/icons-material/HelpOutline'
import { useTranslation } from 'react-i18next'
import type { LogSummary } from '../../types'

interface Props {
  summary: LogSummary
}

function ResultBadge({ status }: { status: LogSummary['resultStatus'] }) {
  const { t } = useTranslation()
  switch (status) {
    case 'success':
      return (
        <Chip
          icon={<CheckCircleIcon />}
          label={t('agents.sessions.logViewer.summary.statusSuccess')}
          color="success"
          size="small"
        />
      )
    case 'failure':
      return (
        <Chip
          icon={<ErrorIcon />}
          label={t('agents.sessions.logViewer.summary.statusFailure')}
          color="error"
          size="small"
        />
      )
    case 'running':
      return (
        <Chip
          icon={<HourglassEmptyIcon />}
          label={t('agents.sessions.logViewer.summary.statusRunning')}
          color="info"
          size="small"
        />
      )
    default:
      return (
        <Chip
          icon={<HelpOutlineIcon />}
          label={t('agents.sessions.logViewer.summary.statusUnknown')}
          color="default"
          size="small"
        />
      )
  }
}

function SummaryItem({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary" display="block" mb={0.25}>
        {label}
      </Typography>
      {children}
    </Box>
  )
}

function formatTokenCountK(value: number | null): string {
  if (value == null) {
    return ''
  }

  const tokenCountK = value / 1000
  const rounded = Math.round(tokenCountK * 10) / 10
  return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)}k tokens`
}

function formatValuePair(
  current: number | null,
  limit: number | null,
  formatter: (value: number) => string,
): string | null {
  if (current == null) {
    return null
  }

  const currentLabel = formatter(current)
  const limitLabel = limit == null ? null : formatter(limit)
  return limitLabel ? `${currentLabel} / ${limitLabel}` : currentLabel
}

type GuardrailState = 'good' | 'near' | 'over'

function resolveGuardrailState(current: number | null, limit: number | null): GuardrailState {
  if (current == null || limit == null || limit <= 0) {
    return 'good'
  }

  const ratio = current / limit
  if (ratio >= 1) {
    return 'over'
  }
  if (ratio >= 0.8) {
    return 'near'
  }
  return 'good'
}

function progressColor(state: GuardrailState): 'success' | 'warning' | 'error' {
  if (state === 'over') {
    return 'error'
  }
  if (state === 'near') {
    return 'warning'
  }
  return 'success'
}

function stateLabel(t: (key: string) => string, state: GuardrailState): string {
  if (state === 'over') {
    return t('agents.sessions.logViewer.summary.metric.stateOver')
  }
  if (state === 'near') {
    return t('agents.sessions.logViewer.summary.metric.stateNear')
  }
  return t('agents.sessions.logViewer.summary.metric.stateGood')
}

function stateChipColor(state: GuardrailState): 'success' | 'warning' | 'error' {
  if (state === 'over') {
    return 'error'
  }
  if (state === 'near') {
    return 'warning'
  }
  return 'success'
}

export function LogSummaryPanel({ summary }: Props) {
  const { t } = useTranslation()
  const na = t('agents.sessions.logViewer.summary.notAvailable')

  const planLabel =
    summary.planTotal > 0
      ? t('agents.sessions.logViewer.summary.planProgressValue', {
          completed: summary.planCompleted,
          total: summary.planTotal,
        })
      : na

  const guardrailUsage = summary.guardrailUsage
  const guardrailMetrics = [
    {
      label: t('agents.sessions.logViewer.summary.currentSessionTokens'),
      current: guardrailUsage?.tokenUsageCurrentSession ?? null,
      limit: guardrailUsage?.tokenBudget ?? null,
      format: formatTokenCountK,
    },
    {
      label: t('agents.sessions.logViewer.summary.iterations'),
      current: guardrailUsage?.cumulativeIterations ?? null,
      limit: guardrailUsage?.maxIterations ?? null,
      format: (value: number) => `${value}`,
    },
    {
      label: t('agents.sessions.logViewer.summary.delegatedSteps'),
      current: guardrailUsage?.delegatedSteps ?? null,
      limit: guardrailUsage?.maxDelegatedSteps ?? null,
      format: (value: number) => `${value}`,
    },
    {
      label: t('agents.sessions.logViewer.summary.delegationDepth'),
      current: guardrailUsage?.delegationDepth ?? null,
      limit: guardrailUsage?.maxDelegationDepth ?? null,
      format: (value: number) => `${value}`,
    },
  ].filter((metric) => metric.current != null)

  const guardrailStates = guardrailMetrics.map((metric) => resolveGuardrailState(metric.current, metric.limit))
  const hasGuardrailOver = guardrailStates.includes('over')
  const hasGuardrailNear = guardrailStates.includes('near')
  const guardrailRunStateLabel = hasGuardrailOver
    ? t('agents.sessions.logViewer.summary.runStateLimitExceeded')
    : hasGuardrailNear
      ? t('agents.sessions.logViewer.summary.runStateApproachingLimits')
      : t('agents.sessions.logViewer.summary.runStateWithinLimits')

  const guardrailRunStateColor: 'success' | 'warning' | 'error' = hasGuardrailOver
    ? 'error'
    : hasGuardrailNear
      ? 'warning'
      : 'success'

  const guardrailSummaryRows = [
    {
      label: t('agents.sessions.logViewer.summary.policySnapshotLabel'),
      value: guardrailUsage?.policySnapshotId,
    },
  ].filter((row) => row.value)

  // Format duration as "Xs" or "Xm Ys"
  const durationLabel = summary.durationMs !== null
    ? summary.durationMs < 60000
      ? `${(summary.durationMs / 1000).toFixed(1)}s`
      : `${Math.floor(summary.durationMs / 60000)}m ${((summary.durationMs % 60000) / 1000).toFixed(0)}s`
    : na

  return (
    <Paper variant="outlined" sx={{ p: 3, mb: 2 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h6" fontWeight={600}>
          {t('agents.sessions.logViewer.summary.title')}
        </Typography>
        <ResultBadge status={summary.resultStatus} />
      </Box>

      <Box
        display="grid"
        gridTemplateColumns="repeat(auto-fit, minmax(180px, 1fr))"
        gap={2}
      >
        <SummaryItem label={t('agents.sessions.logViewer.summary.identity')}>
          <Typography variant="body2">{summary.identity ?? na}</Typography>
        </SummaryItem>

        <SummaryItem label={t('agents.sessions.logViewer.summary.role')}>
          <Typography variant="body2">{summary.role ?? na}</Typography>
        </SummaryItem>

        <SummaryItem label={t('agents.sessions.logViewer.summary.model')}>
          <Typography variant="body2">{summary.model ?? na}</Typography>
        </SummaryItem>

        <SummaryItem label={t('agents.sessions.logViewer.summary.duration')}>
          <Typography variant="body2">{durationLabel}</Typography>
        </SummaryItem>

        <SummaryItem label={t('agents.sessions.logViewer.summary.planProgress')}>
          <Typography variant="body2">{planLabel}</Typography>
        </SummaryItem>

        {summary.sopsSkills.length > 0 && (
          <SummaryItem label={t('agents.sessions.logViewer.summary.sopsSkills')}>
            <Stack direction="row" flexWrap="wrap" gap={0.5}>
              {summary.sopsSkills.map((s) => (
                <Chip key={s} label={s} size="small" variant="outlined" />
              ))}
            </Stack>
          </SummaryItem>
        )}

      </Box>

      {guardrailMetrics.length > 0 && (
        <Box mt={2.5}>
          <Box
            display="flex"
            alignItems="center"
            justifyContent="space-between"
            gap={1}
            mb={1.25}
            flexWrap="wrap"
          >
            <Typography variant="subtitle2" fontWeight={600}>
              {t('agents.sessions.logViewer.summary.guardrailUsageTitle')}
            </Typography>
            <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
              {guardrailSummaryRows.map((row) => (
                <Chip
                  key={row.label}
                  size="small"
                  variant="outlined"
                  label={`${row.label}: ${row.value}`}
                  sx={{ fontFamily: 'monospace' }}
                />
              ))}
              <Chip size="small" color={guardrailRunStateColor} label={guardrailRunStateLabel} />
            </Stack>
          </Box>

          <Box
            display="grid"
            gap={1.25}
            gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr', md: 'repeat(4, minmax(0, 1fr))' }}
          >
            {guardrailMetrics.map((metric) => {
              const state = resolveGuardrailState(metric.current, metric.limit)
              const currentLabel = metric.current == null ? na : metric.format(metric.current)
              const limitLabel = metric.limit == null ? t('agents.sessions.logViewer.summary.metric.notConfigured') : metric.format(metric.limit)
              const valuePair = metric.current == null ? na : `${currentLabel} / ${limitLabel}`
              const ratio =
                metric.current != null && metric.limit != null && metric.limit > 0
                  ? (metric.current / metric.limit) * 100
                  : 0
              const boundedRatio = Math.min(100, Math.max(0, ratio))
              const percentLabel =
                metric.current != null && metric.limit != null && metric.limit > 0
                  ? t('agents.sessions.logViewer.summary.metric.usedPercent', {
                      value: `${Math.round(ratio)}%`,
                    })
                  : t('agents.sessions.logViewer.summary.metric.notConfigured')

              return (
                <Paper key={metric.label} variant="outlined" sx={{ p: 1.25, borderRadius: 1.5 }}>
                  <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} mb={0.5}>
                    <Typography variant="caption" color="text.secondary" sx={{ letterSpacing: 0.2 }}>
                      {metric.label}
                    </Typography>
                    <Chip size="small" color={stateChipColor(state)} label={stateLabel(t, state)} />
                  </Box>

                  <Typography variant="subtitle2" fontWeight={700} sx={{ fontFamily: 'monospace', mb: 0.75 }}>
                    {valuePair}
                  </Typography>

                  <LinearProgress
                    variant="determinate"
                    value={boundedRatio}
                    color={progressColor(state)}
                    sx={{ height: 6, borderRadius: 999, mb: 0.6 }}
                  />

                  <Box display="flex" justifyContent="space-between" alignItems="center" gap={1}>
                    <Typography variant="caption" color="text.secondary">
                      {percentLabel}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
                      {t('agents.sessions.logViewer.summary.metric.limitPrefix', { value: limitLabel })}
                    </Typography>
                  </Box>
                </Paper>
              )
            })}
          </Box>
        </Box>
      )}
    </Paper>
  )
}
