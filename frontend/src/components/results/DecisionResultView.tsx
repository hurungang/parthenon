import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Chip,
  Divider,
  LinearProgress,
  Stack,
  Typography,
} from '@mui/material'
import type {
  DecisionAnswer,
  DecisionExecutionResult,
  DecisionOutcome,
} from '../../api/systemOneApi'

function outcomeColor(outcome: DecisionOutcome): 'success' | 'warning' | 'error' {
  if (outcome === 'act') return 'success'
  if (outcome === 'confirm') return 'warning'
  return 'error'
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

/** Probability distribution bars for one answer. */
function ProbabilityBars({ probabilities }: { probabilities: Record<string, number> }) {
  const { t } = useTranslation()
  const entries = Object.entries(probabilities)
  if (entries.length === 0) return null
  return (
    <Box mt={0.5} sx={{ width: '100%', maxWidth: 480 }}>
      {entries.map(([key, value]) => (
        <Stack key={key} direction="row" spacing={1} alignItems="center" mb={0.5}>
          <Typography variant="caption" sx={{ width: 140, flexShrink: 0 }} noWrap>
            {key}
          </Typography>
          <LinearProgress
            variant="determinate"
            value={Math.max(0, Math.min(100, value * 100))}
            sx={{ flexGrow: 1, height: 8, borderRadius: 4 }}
          />
          <Typography variant="caption" sx={{ width: 48, textAlign: 'right' }}>
            {formatPercent(value)}
          </Typography>
        </Stack>
      ))}
      <Typography variant="caption" color="text.secondary">
        {t('results.decision.probabilities')}
      </Typography>
    </Box>
  )
}

/** One typed per-question answer row. */
function AnswerRow({
  questionKey,
  answer,
}: {
  questionKey: string
  answer: DecisionAnswer
}) {
  const { t } = useTranslation()

  let valueNode: React.ReactNode = null
  if (answer.question_type === 'choice') {
    valueNode = (
      <Chip label={String(answer.choice ?? answer.value ?? '—')} size="small" />
    )
  } else if (answer.question_type === 'score') {
    const score = Number(answer.score ?? answer.value ?? 0)
    valueNode = (
      <Stack spacing={0.5} sx={{ width: '100%', maxWidth: 480 }}>
        <Stack direction="row" spacing={1} alignItems="center">
          <Typography variant="body2" fontWeight={600}>
            {score}
          </Typography>
          {Array.isArray(answer.legend) && answer.legend[score] && (
            <Typography variant="body2" color="text.secondary">
              {answer.legend[score]}
            </Typography>
          )}
        </Stack>
        {Array.isArray(answer.legend) && answer.legend.length > 0 && (
          <Typography variant="caption" color="text.secondary">
            {answer.legend.map((label, i) => `${i}=${label}`).join(' · ')}
          </Typography>
        )}
      </Stack>
    )
  } else {
    const noul = Number(answer.noul ?? answer.value ?? 0)
    valueNode = (
      <Stack spacing={0.5} sx={{ width: '100%', maxWidth: 480 }}>
        <Stack direction="row" spacing={1} alignItems="center">
          <Typography variant="body2" fontWeight={600}>
            {formatPercent(noul)}
          </Typography>
          <LinearProgress
            variant="determinate"
            value={noul * 100}
            sx={{ flexGrow: 1, height: 8, borderRadius: 4 }}
          />
        </Stack>
        <Typography variant="caption" color="text.secondary">
          {t('results.decision.noulProbability')}
        </Typography>
      </Stack>
    )
  }

  return (
    <Box mb={1.5}>
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
        <Typography variant="subtitle2" component="code">
          {questionKey}
        </Typography>
        <Chip
          label={t(`results.decision.questionTypes.${answer.question_type}`)}
          size="small"
          variant="outlined"
        />
        {answer.confidence != null && (
          <Chip
            label={t('results.decision.confidence', {
              value: formatPercent(answer.confidence),
            })}
            size="small"
            color="info"
          />
        )}
      </Stack>
      <Box mt={0.5}>{valueNode}</Box>
      {answer.probabilities != null && (
        <ProbabilityBars probabilities={answer.probabilities} />
      )}
      <Divider sx={{ mt: 1 }} />
    </Box>
  )
}

interface DecisionResultViewProps {
  result: DecisionExecutionResult
}

/**
 * Renders one persisted decision execution: per-question typed answers,
 * probability distributions, confidence, and the gate outcome.
 */
export function DecisionResultView({ result }: DecisionResultViewProps) {
  const { t } = useTranslation()

  if (result.status === 'failed') {
    return (
      <Alert severity="error">
        <Typography variant="subtitle2">{t('results.decision.failed')}</Typography>
        {result.error_message && (
          <Typography variant="body2" sx={{ mt: 0.5, wordBreak: 'break-word' }}>
            {result.error_message}
          </Typography>
        )}
      </Alert>
    )
  }

  const answers = result.answers?.answers ?? {}
  const gateConfidence = result.answers?.gate_confidence

  return (
    <Box>
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" mb={2}>
        <Chip
          label={t(`results.decision.outcomes.${result.outcome}`)}
          color={outcomeColor(result.outcome)}
          size="small"
        />
        {gateConfidence != null && (
          <Chip
            label={t('results.decision.gateConfidence', {
              value: formatPercent(gateConfidence),
            })}
            size="small"
            variant="outlined"
          />
        )}
        {result.provider_model && (
          <Chip label={result.provider_model} size="small" variant="outlined" />
        )}
      </Stack>

      {result.input_state_snapshot != null &&
        Object.keys(result.input_state_snapshot).length > 0 && (
          <Box mb={2}>
            <Typography variant="subtitle2" mb={0.5}>
              {t('results.decision.inputState')}
            </Typography>
            <Box
              component="pre"
              sx={{
                m: 0,
                p: 1,
                bgcolor: 'action.hover',
                borderRadius: 1,
                fontSize: '0.75rem',
                fontFamily: 'monospace',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                maxHeight: 200,
                overflowY: 'auto',
              }}
            >
              {JSON.stringify(result.input_state_snapshot, null, 2)}
            </Box>
          </Box>
        )}

      <Typography variant="subtitle2" mb={1}>
        {t('results.decision.answers')}
      </Typography>
      {Object.entries(answers).map(([key, answer]) => (
        <AnswerRow key={key} questionKey={key} answer={answer} />
      ))}
      {Object.keys(answers).length === 0 && (
        <Typography variant="body2" color="text.secondary">
          {t('app.noData')}
        </Typography>
      )}
    </Box>
  )
}
