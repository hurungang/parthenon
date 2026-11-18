import { Box, Chip, Paper, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { OptimizationAudit } from '../../types'

export interface OptimizerAuditBlockProps {
  audit: OptimizationAudit
  /** Who the live work is attributed to (the agent) plus the operator. */
  agentTypeName?: string | null
  operatorName?: string | null
  /** The compact bar already labels the block — hide the duplicate heading. */
  showTitle?: boolean
  testId?: string
}

/**
 * Replay-vs-live audit block ("what ran in this session").
 *
 * Makes the safety distinction unambiguous: replay verifications are the
 * default verification path, while `liveOperations` counts only tool calls that
 * came from an operator-approved, single-use live test. A reviewer can tell
 * whether a real integration was contacted without opening the ledger.
 */
export function OptimizerAuditBlock({
  audit,
  agentTypeName,
  operatorName,
  showTitle = true,
  testId = 'optimizer-audit',
}: OptimizerAuditBlockProps) {
  const { t } = useTranslation()

  return (
    <Paper
      variant="outlined"
      data-testid={testId}
      sx={{ maxWidth: 580, borderRadius: 2, px: 1.5, py: 1.25 }}
    >
      {showTitle && (
        <Typography
          variant="caption"
          fontWeight={700}
          color="text.secondary"
          display="block"
          mb={0.75}
          sx={{ textTransform: 'uppercase', letterSpacing: 0.5 }}
        >
          {t('agents.optimizer.audit.title')}
        </Typography>
      )}
      <Box display="flex" gap={0.75} flexWrap="wrap" alignItems="center">
        <Chip
          size="small"
          color="primary"
          variant="outlined"
          label={t('agents.optimizer.audit.replay', { count: audit.replay_verifications })}
          data-testid={`${testId}-replay`}
        />
        {audit.live_operations > 0 ? (
          <Chip
            size="small"
            color="warning"
            label={t('agents.optimizer.audit.liveUsed', { count: audit.live_operations })}
            data-testid={`${testId}-live`}
          />
        ) : (
          <Chip
            size="small"
            variant="outlined"
            label={t('agents.optimizer.audit.noLive')}
            data-testid={`${testId}-live`}
          />
        )}
        {audit.replay_only && (
          <Chip
            size="small"
            color="success"
            label={t('agents.optimizer.audit.replayOnlyChip')}
            data-testid={`${testId}-replay-only`}
          />
        )}
      </Box>
      <Typography variant="caption" color="text.secondary" display="block" mt={0.75}>
        {audit.live_operations > 0
          ? t('agents.optimizer.audit.noteLive', {
              name: agentTypeName ?? t('agents.optimizer.audit.thisAgent'),
              operator: operatorName ?? t('agents.optimizer.audit.theOperator'),
            })
          : t('agents.optimizer.audit.noteReplayOnly')}
      </Typography>
      {audit.last_live_at && (
        <Typography variant="caption" color="text.secondary" display="block" mt={0.5}>
          {t('agents.optimizer.audit.lastLiveAt', {
            when: new Date(audit.last_live_at).toLocaleString(),
          })}
        </Typography>
      )}
    </Paper>
  )
}
