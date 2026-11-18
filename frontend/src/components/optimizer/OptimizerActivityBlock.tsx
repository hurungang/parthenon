import { useState } from 'react'
import { Box, Button, Chip, Collapse, Paper, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import CircularProgress from '@mui/material/CircularProgress'
import type { ChatActivityStep } from '../../hooks/useChatSession'

export interface OptimizerActivityBlockProps {
  steps: ChatActivityStep[]
  /**
   * Terminal outcome summary (e.g. the plan result or the bounded stop). A
   * finished turn must read as an outcome, never as an indefinite spinner.
   */
  outcome?: string | null
  testId?: string
}

/**
 * Expandable "what it looked at" block for an optimization turn.
 *
 * Fed by the existing status stream (`using_tool` events) — no new endpoint and
 * no direct tool log access. Collapsed it reads "Working / Worked — N steps";
 * expanded it lists every tool the turn touched with its state.
 */
export function OptimizerActivityBlock({
  steps,
  outcome,
  testId = 'optimizer-activity',
}: OptimizerActivityBlockProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)

  if (steps.length === 0) return null

  const running = steps.some((step) => step.state === 'running')
  const names = steps.map((step) => step.toolName ?? '—').join(' · ')

  return (
    <Paper
      variant="outlined"
      data-testid={testId}
      data-running={running ? 'true' : 'false'}
      sx={{ maxWidth: '88%', borderRadius: 2, overflow: 'hidden' }}
    >
      <Button
        fullWidth
        disableRipple
        onClick={() => setOpen((value) => !value)}
        data-testid={`${testId}-toggle`}
        sx={{
          justifyContent: 'flex-start',
          textTransform: 'none',
          color: 'text.primary',
          px: 1.5,
          py: 1,
          gap: 1,
        }}
      >
        {running ? (
          <CircularProgress size={10} data-testid={`${testId}-running`} />
        ) : (
          <CheckCircleIcon fontSize="inherit" color="success" />
        )}
        <Typography variant="caption" fontWeight={700} noWrap>
          {running
            ? t('agents.optimizer.activity.working', { count: steps.length })
            : t('agents.optimizer.activity.worked', { count: steps.length })}
        </Typography>
        <Typography
          variant="caption"
          color="text.secondary"
          noWrap
          sx={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}
        >
          {names}
        </Typography>
        {open ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
      </Button>
      <Collapse in={open}>
        <Box sx={{ borderTop: 1, borderColor: 'divider', px: 1.5, py: 1 }}>
          {steps.map((step) => (
            <Box
              key={step.id}
              display="flex"
              alignItems="flex-start"
              gap={1}
              py={0.5}
              data-testid={`${testId}-step`}
            >
              {step.state === 'running' ? (
                <CircularProgress size={10} sx={{ mt: '4px' }} />
              ) : (
                <CheckCircleIcon fontSize="inherit" color="success" sx={{ mt: '2px' }} />
              )}
              <Box flex={1} minWidth={0}>
                <Typography
                  variant="caption"
                  sx={{ fontFamily: 'monospace', fontWeight: 700, wordBreak: 'break-word' }}
                >
                  {step.toolName ?? '—'}
                </Typography>
                <Typography variant="caption" color="text.secondary" display="block">
                  {step.state === 'running'
                    ? t('agents.optimizer.activity.stepRunning')
                    : t('agents.optimizer.activity.stepDone')}{' '}
                  · {new Date(step.timestamp).toLocaleTimeString()}
                </Typography>
              </Box>
            </Box>
          ))}
          <Typography variant="caption" color="text.secondary" display="block" mt={1}>
            {t('agents.optimizer.activity.note')}
          </Typography>
          {outcome && (
            <Chip
              size="small"
              sx={{ mt: 1 }}
              label={outcome}
              data-testid={`${testId}-outcome`}
              color={running ? 'info' : 'default'}
            />
          )}
        </Box>
      </Collapse>
    </Paper>
  )
}
