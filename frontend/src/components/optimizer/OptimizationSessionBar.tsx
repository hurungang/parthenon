import { useState } from 'react'
import { Box, Button, Chip, Collapse, Paper, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import HistoryIcon from '@mui/icons-material/History'
import type { OptimizationAudit } from '../../types'
import { OptimizerAuditBlock } from './OptimizerAuditBlock'

export interface OptimizationSessionBarProps {
  /** Replay-vs-live projection for the session (null before it is read). */
  audit: OptimizationAudit | null
  /** The subject agent type's name (the agent being optimized). */
  subjectName: string
  /** Conversational subjects have no plan on record — the scope note says so. */
  isConversational?: boolean
  /** Attribution for live work: the agent plus the operator. */
  agentTypeName?: string | null
  operatorName?: string | null
  /** True between an approval and its result — the chip shows "running". */
  liveTestRunning?: boolean
  testId?: string
}

/**
 * Compact, default-collapsed "What ran in this session" bar.
 *
 * This is the ONLY chrome the optimization chat carries above the transcript:
 * it keeps the essential safety signal visible at a glance (replay-only vs
 * live-used, with the replay / approved-live counts) and hides the audit
 * detail — identity parity, scope, last live time — behind one chevron. The
 * full mode/scope header block is deliberately gone: the chat reads as a
 * conversation, not a configuration surface.
 */
export function OptimizationSessionBar({
  audit,
  subjectName,
  isConversational = false,
  agentTypeName,
  operatorName,
  liveTestRunning = false,
  testId = 'optimization-session-bar',
}: OptimizationSessionBarProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)

  const replayCount = audit?.replay_verifications ?? 0
  const liveCount = audit?.live_operations ?? 0
  const replayOnly = audit?.replay_only ?? liveCount === 0

  return (
    <Paper
      variant="outlined"
      square
      data-testid={testId}
      data-expanded={open ? 'true' : 'false'}
      sx={{ px: 1.5, py: 0.5, bgcolor: '#F8FAFC', borderColor: '#E2E8F0' }}
    >
      <Button
        fullWidth
        disableRipple
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        data-testid={`${testId}-toggle`}
        sx={{
          justifyContent: 'flex-start',
          textTransform: 'none',
          color: 'text.primary',
          px: 0.5,
          py: 0.75,
          gap: 1,
          minHeight: 0,
        }}
      >
        <HistoryIcon fontSize="small" sx={{ color: 'text.secondary' }} />
        <Typography variant="caption" fontWeight={700} noWrap>
          {t('agents.optimizer.sessionBar.title')}
        </Typography>
        <Box
          display="flex"
          gap={0.75}
          alignItems="center"
          flexWrap="wrap"
          data-testid={`${testId}-summary`}
        >
          <Chip
            size="small"
            color="primary"
            variant="outlined"
            label={t('agents.optimizer.audit.replay', { count: replayCount })}
            data-testid={`${testId}-replay-chip`}
          />
          {liveCount > 0 ? (
            <Chip
              size="small"
              color="warning"
              label={t('agents.optimizer.audit.liveUsed', { count: liveCount })}
              title={t('agents.optimizer.liveUsedTitle')}
              data-testid={`${testId}-live-chip`}
            />
          ) : (
            <Chip
              size="small"
              variant="outlined"
              label={t('agents.optimizer.audit.noLive')}
              data-testid={`${testId}-live-chip`}
            />
          )}
          {liveTestRunning ? (
            <Chip
              size="small"
              color="info"
              label={t('agents.optimizer.liveRunning')}
              data-testid={`${testId}-running-chip`}
            />
          ) : (
            replayOnly && (
              <Chip
                size="small"
                color="success"
                label={t('agents.optimizer.replayOnly')}
                title={t('agents.optimizer.replayOnlyTitle')}
                data-testid={`${testId}-replay-only-chip`}
              />
            )
          )}
        </Box>
        <Box sx={{ flexGrow: 1 }} />
        <Typography
          variant="caption"
          color="text.secondary"
          noWrap
          sx={{ display: { xs: 'none', sm: 'block' } }}
        >
          {open
            ? t('agents.optimizer.sessionBar.collapse')
            : t('agents.optimizer.sessionBar.expand')}
        </Typography>
        {open ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
      </Button>

      <Collapse in={open}>
        <Box sx={{ pt: 0.5, pb: 1 }} data-testid={`${testId}-details`}>
          <OptimizerAuditBlock
            audit={audit ?? {
              replay_verifications: 0,
              live_operations: 0,
              last_live_at: null,
              replay_only: true,
            }}
            agentTypeName={agentTypeName ?? subjectName}
            operatorName={operatorName}
            showTitle={false}
            testId={`${testId}-audit`}
          />
          <Typography
            variant="caption"
            color="text.secondary"
            display="block"
            mt={0.75}
            data-testid={`${testId}-identity`}
          >
            {t('agents.optimizer.identityParity')}
          </Typography>
          <Typography
            variant="caption"
            color="text.secondary"
            display="block"
            data-testid={`${testId}-scope`}
          >
            {isConversational
              ? t('agents.optimizer.scopeConversational', { name: subjectName })
              : t('agents.optimizer.scopePlan', { name: subjectName })}
          </Typography>
        </Box>
      </Collapse>
    </Paper>
  )
}
