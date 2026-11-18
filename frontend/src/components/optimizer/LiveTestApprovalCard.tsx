import { useEffect, useMemo, useState } from 'react'
import {
  Box,
  Button,
  Chip,
  Collapse,
  Divider,
  Paper,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import CancelIcon from '@mui/icons-material/Cancel'
import LockIcon from '@mui/icons-material/Lock'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import type {
  LiveTestApprovalSummary,
  LiveTestCardState,
  ScriptRunRecord,
} from '../../types'
import { liveTestCardStateFromStatus } from '../../hooks/useOptimizationConversation'

export interface LiveTestApprovalCardProps {
  liveTest: LiveTestApprovalSummary
  /** The subject agent type's name — the script runs as this agent. */
  agentTypeName: string
  /** UI state; defaults to the ledger status carried by the proposal. */
  state?: LiveTestCardState
  /** The script run record once the approved script ran (or failed). */
  scriptRun?: ScriptRunRecord | null
  /** Failure explanation when the run failed. */
  errorText?: string | null
  /** Decision attribution (who answered, when) once decided. */
  decidedBy?: string | null
  decidedAt?: string | null
  isSubmitting?: boolean
  onApprove: () => void | Promise<void>
  onDeny: () => void | Promise<void>
  testIdPrefix?: string
}

function remainingMinutes(expiresAt: string | null | undefined): number | null {
  if (!expiresAt) return null
  const ms = Date.parse(expiresAt)
  if (Number.isNaN(ms)) return null
  return Math.max(0, Math.ceil((ms - Date.now()) / 60_000))
}

function formatDuration(durationMs: number | null | undefined): string | null {
  if (durationMs == null || !Number.isFinite(durationMs)) return null
  if (durationMs < 1000) return `${Math.round(durationMs)} ms`
  return `${(durationMs / 1000).toFixed(1)} s`
}

/**
 * In-chat live-test approval card (optimization mode).
 *
 * The SCRIPT is the unit of approval — not the individual MCP tools: MCP tools
 * are assumed to work, and approving runs the whole script once, end to end, in
 * the real sandbox as the agent. The tool-call preview is informational.
 *
 * Pending is the only expanded state. Once the request leaves `pending`
 * (approved / running / executed / failed / denied / expired / cancelled) the
 * card collapses into a one-line chat-history summary — status chip + script
 * name + short result/denial — with a chevron that expands the full detail
 * (script output, telemetry, per-`tools.call` outcomes, attribution).
 */
export function LiveTestApprovalCard({
  liveTest,
  agentTypeName,
  state,
  scriptRun,
  errorText,
  decidedBy,
  decidedAt,
  isSubmitting = false,
  onApprove,
  onDeny,
  testIdPrefix = 'live-test-approval',
}: LiveTestApprovalCardProps) {
  const { t } = useTranslation()
  const cardState: LiveTestCardState =
    state ?? liveTestCardStateFromStatus(liveTest.status)
  const isPending = cardState === 'pending'
  const [open, setOpen] = useState(false)
  // A decision collapses the card: the expanded approval must never linger at
  // the end of the transcript after the operator answered.
  useEffect(() => {
    if (!isPending) setOpen(false)
  }, [isPending, cardState])

  const minutesLeft = useMemo(() => remainingMinutes(liveTest.expires_at), [liveTest.expires_at])

  const scriptName =
    liveTest.script_name ?? scriptRun?.script_name ?? null
  const scriptVersionLabel =
    liveTest.script_version_label ?? scriptRun?.script_version_label ?? null
  const scriptTitle = scriptName ?? t('agents.optimizer.approval.thisScript')
  const versionLine = scriptVersionLabel
    ? t('agents.optimizer.approval.scriptVersion', {
        name: scriptTitle,
        version: scriptVersionLabel,
      })
    : scriptTitle

  const previewNames = useMemo(
    () =>
      Array.from(
        new Set(
          liveTest.operations
            .map((operation) => operation.tool_name)
            .filter((name) => name.trim().length > 0),
        ),
      ),
    [liveTest.operations],
  )
  const previewLine =
    previewNames.length > 0
      ? t('agents.optimizer.approval.itWillCall', { tools: previewNames.join(', ') })
      : t('agents.optimizer.approval.noPreview')

  const duration = formatDuration(scriptRun?.duration_ms)
  const toolCallCount = scriptRun?.tool_calls?.length ?? 0

  const stateChip = (() => {
    switch (cardState) {
      case 'pending':
        return <Chip size="small" color="warning" label={t('agents.optimizer.approval.chipPending')} />
      case 'running':
        return <Chip size="small" color="info" label={t('agents.optimizer.approval.chipRunning')} />
      case 'executed':
        return <Chip size="small" color="success" label={t('agents.optimizer.approval.chipExecuted')} />
      case 'failed':
        return <Chip size="small" color="error" label={t('agents.optimizer.approval.chipFailed')} />
      case 'expired':
        return (
          <Chip
            size="small"
            variant="outlined"
            label={t('agents.optimizer.approval.chipExpired')}
            data-testid={`${testIdPrefix}-expired-chip`}
          />
        )
      case 'cancelled':
        return (
          <Chip
            size="small"
            variant="outlined"
            label={t('agents.optimizer.approval.chipCancelled')}
            data-testid={`${testIdPrefix}-cancelled-chip`}
          />
        )
      default:
        return <Chip size="small" label={t('agents.optimizer.approval.chipDenied')} />
    }
  })()

  const shortSummary = (() => {
    switch (cardState) {
      case 'executed':
        return scriptRun?.result_summary ?? t('agents.optimizer.approval.summaryExecuted')
      case 'failed':
        return errorText ?? scriptRun?.error ?? t('agents.optimizer.approval.summaryFailed')
      case 'running':
        return t('agents.optimizer.approval.summaryRunning', { name: agentTypeName })
      case 'denied':
        return t('agents.optimizer.approval.summaryDenied')
      case 'expired':
        return t('agents.optimizer.approval.summaryExpired')
      case 'cancelled':
        return t('agents.optimizer.approval.summaryCancelled')
      default:
        return ''
    }
  })()

  const borderColor =
    cardState === 'executed'
      ? 'success.main'
      : cardState === 'failed'
        ? 'error.main'
        : cardState === 'pending'
          ? 'warning.main'
          : cardState === 'running'
            ? 'info.main'
            : 'divider'

  const stateNote = (() => {
    switch (cardState) {
      case 'expired':
        return t('agents.optimizer.approval.noteExpired')
      case 'denied':
        return t('agents.optimizer.approval.denied')
      case 'cancelled':
        return t('agents.optimizer.approval.noteCancelled')
      case 'executed':
        return t('agents.optimizer.approval.usedOnce')
      case 'failed':
        return t('agents.optimizer.approval.failedReplayOnly')
      default:
        return t('agents.optimizer.approval.runningOneScript', { name: agentTypeName })
    }
  })()

  // ── Pending: the only expanded card ────────────────────────────────────────
  if (isPending) {
    return (
      <Paper
        variant="outlined"
        data-testid={testIdPrefix}
        data-state={cardState}
        data-expanded="true"
        sx={{ borderWidth: 2, borderColor, borderRadius: 3, maxWidth: 680, overflow: 'hidden', boxShadow: 3 }}
      >
        <Box sx={{ px: 2, py: 1.5, bgcolor: '#FFF7ED', display: 'flex', gap: 1, alignItems: 'flex-start' }}>
          <LockIcon sx={{ color: 'text.secondary', mt: 0.25 }} />
          <Box flex={1}>
            <Typography variant="subtitle2" fontWeight={700}>
              {t('agents.optimizer.approval.runScriptTitle')}
            </Typography>
            <Typography
              variant="caption"
              color="text.secondary"
              display="block"
              data-testid={`${testIdPrefix}-script`}
            >
              {versionLine}
            </Typography>
          </Box>
          {stateChip}
        </Box>

        <Box sx={{ p: 2 }}>
          <Typography
            variant="body2"
            color="text.secondary"
            data-testid={`${testIdPrefix}-subtitle`}
          >
            {t('agents.optimizer.approval.scriptSubtitle', { name: agentTypeName })}
          </Typography>

          <Box
            data-testid={`${testIdPrefix}-preview`}
            sx={{ mt: 1.5, p: 1.25, borderRadius: 1, border: 1, borderColor: 'divider', bgcolor: 'action.hover' }}
          >
            <Typography variant="caption" sx={{ fontFamily: 'monospace', wordBreak: 'break-word' }}>
              {previewLine}
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block" mt={0.5}>
              {t('agents.optimizer.approval.previewNote')}
            </Typography>
          </Box>

          <Box data-testid={`${testIdPrefix}-note`} sx={{ mt: 1.5 }}>
            <Typography variant="caption" color="text.secondary">
              {t('agents.optimizer.approval.runsOnceNote', { name: agentTypeName })}
            </Typography>
          </Box>

          <Box display="flex" gap={1} mt={1.5} flexWrap="wrap" alignItems="center">
            <Button
              size="small"
              variant="contained"
              color="success"
              startIcon={<CheckCircleIcon />}
              disabled={isSubmitting}
              onClick={() => void onApprove()}
              data-testid={`${testIdPrefix}-approve`}
            >
              {t('agents.optimizer.approval.approve')}
            </Button>
            <Button
              size="small"
              variant="outlined"
              color="error"
              startIcon={<CancelIcon />}
              disabled={isSubmitting}
              onClick={() => void onDeny()}
              data-testid={`${testIdPrefix}-deny`}
            >
              {t('agents.optimizer.approval.deny')}
            </Button>
            <Typography variant="caption" color="text.secondary">
              {t('agents.optimizer.approval.denyHint')}
            </Typography>
          </Box>

          <Typography variant="caption" color="text.secondary" display="block" mt={1}>
            {minutesLeft != null
              ? t('agents.optimizer.approval.expiryWindowMinutes', { minutes: minutesLeft })
              : t('agents.optimizer.approval.expiryWindow')}
          </Typography>
        </Box>
      </Paper>
    )
  }

  // ── Decided / running: a one-line history summary, expandable ──────────────
  return (
    <Paper
      variant="outlined"
      data-testid={testIdPrefix}
      data-state={cardState}
      data-expanded={open ? 'true' : 'false'}
      sx={{
        borderWidth: 1,
        borderStyle: cardState === 'expired' || cardState === 'cancelled' ? 'dashed' : 'solid',
        borderColor,
        borderRadius: 2,
        maxWidth: 680,
        overflow: 'hidden',
      }}
    >
      <Button
        fullWidth
        disableRipple
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        data-testid={`${testIdPrefix}-toggle`}
        sx={{
          justifyContent: 'flex-start',
          textTransform: 'none',
          color: 'text.primary',
          px: 1.5,
          py: 1,
          gap: 1,
          minHeight: 0,
          textAlign: 'left',
        }}
      >
        {stateChip}
        <Typography
          variant="caption"
          fontWeight={700}
          noWrap
          sx={{ maxWidth: { xs: 140, sm: 220 } }}
          data-testid={`${testIdPrefix}-script`}
        >
          {scriptTitle}
        </Typography>
        <Typography
          variant="caption"
          color="text.secondary"
          noWrap
          sx={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}
          data-testid={`${testIdPrefix}-summary`}
        >
          {shortSummary}
        </Typography>
        {open ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
      </Button>

      <Collapse in={open}>
        <Box sx={{ borderTop: 1, borderColor: 'divider', px: 2, py: 1.5 }} data-testid={`${testIdPrefix}-details`}>
          <Typography variant="caption" color="text.secondary" display="block">
            {versionLine}
          </Typography>

          {scriptRun?.result_summary && (
            <Box mt={1} data-testid={`${testIdPrefix}-result`}>
              <Typography variant="caption" fontWeight={700} display="block">
                {t('agents.optimizer.approval.scriptOutput')}
              </Typography>
              <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                {scriptRun.result_summary}
              </Typography>
            </Box>
          )}

          {(duration || toolCallCount > 0) && (
            <Box display="flex" gap={0.75} flexWrap="wrap" mt={1} data-testid={`${testIdPrefix}-telemetry`}>
              {duration && (
                <Chip
                  size="small"
                  variant="outlined"
                  label={t('agents.optimizer.approval.duration', { duration })}
                />
              )}
              <Chip
                size="small"
                variant="outlined"
                label={t('agents.optimizer.approval.toolCalls', { count: toolCallCount })}
              />
            </Box>
          )}

          {scriptRun && (scriptRun.tool_calls?.length ?? 0) > 0 && (
            <Box mt={1} data-testid={`${testIdPrefix}-tool-calls`}>
              <Typography variant="caption" fontWeight={700} display="block" mb={0.5}>
                {t('agents.optimizer.approval.toolCallsTitle')}
              </Typography>
              {(scriptRun.tool_calls ?? []).map((call, index) => (
                <Box
                  key={`${call.tool_name}-${index}`}
                  display="flex"
                  alignItems="flex-start"
                  gap={1}
                  py={0.25}
                  data-testid={`${testIdPrefix}-tool-call-${index}`}
                >
                  {call.status === 'success' ? (
                    <CheckCircleIcon fontSize="inherit" color="success" sx={{ mt: '2px' }} />
                  ) : (
                    <CancelIcon fontSize="inherit" color="error" sx={{ mt: '2px' }} />
                  )}
                  <Box flex={1} minWidth={0}>
                    <Typography variant="caption" sx={{ fontFamily: 'monospace', fontWeight: 700, wordBreak: 'break-word' }}>
                      {call.tool_name}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" display="block">
                      {call.error ?? call.result_summary ?? call.status}
                      {formatDuration(call.duration_ms) ? ` · ${formatDuration(call.duration_ms)}` : ''}
                    </Typography>
                  </Box>
                </Box>
              ))}
            </Box>
          )}

          {errorText && (
            <Typography
              variant="caption"
              color="error.main"
              display="block"
              mt={1}
              data-testid={`${testIdPrefix}-error`}
            >
              {errorText}
            </Typography>
          )}

          {previewNames.length > 0 && (
            <Typography
              variant="caption"
              color="text.secondary"
              display="block"
              mt={1}
              data-testid={`${testIdPrefix}-preview`}
            >
              {previewLine}
            </Typography>
          )}

          <Divider sx={{ my: 1 }} />

          <Typography variant="caption" color="text.secondary" display="block">
            {stateNote}
          </Typography>

          {(decidedBy || decidedAt) && (
            <Typography variant="caption" color="text.secondary" display="block" mt={0.5}>
              {decidedBy
                ? t('agents.optimizer.approval.decidedBy', { name: decidedBy })
                : t('agents.optimizer.approval.decided')}
              {decidedAt ? ` · ${new Date(decidedAt).toLocaleString()}` : ''}
            </Typography>
          )}
        </Box>
      </Collapse>
    </Paper>
  )
}
