import { Box, Button, Paper, Stack, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'

interface ResumeTerminalCardProps {
  /** Durable terminal reason code from the server (`expired`, `checkpoint_unavailable`, …). */
  reason: string | null
  /** Paused-turn / confirmation identifier shown in the card subtitle. */
  referenceId: string | null
  /** Builds the dialog-scoped `data-testid` value. */
  testId: (suffix: string) => string
  onAskAgain: () => void
  onDismiss: () => void
}

/**
 * Terminal card for a turn that can no longer be resumed
 * (resumable-agent-turn-persistence, 6.3).
 *
 * Rendered in the message stream instead of the old generic
 * "delegated step timed out or failed" warning. It states what happened, that
 * nothing was written, and the next step — with "Ask again" / "Dismiss"
 * actions. The chat input stays enabled while this card is visible (and after
 * dismissal) because the turn is over.
 */
export function ResumeTerminalCard({
  reason,
  referenceId,
  testId,
  onAskAgain,
  onDismiss,
}: ResumeTerminalCardProps) {
  const { t } = useTranslation()
  const bodyKey =
    reason === 'expired'
      ? 'conversations.sessions.terminalCard.bodyExpired'
      : reason === 'unexpectedly_terminated'
        ? 'conversations.sessions.terminalCard.bodyUnexpectedlyTerminated'
        : 'conversations.sessions.terminalCard.bodyLostPausePoint'

  return (
    <Paper
      variant="outlined"
      data-testid={testId('terminal-card')}
      data-terminal-reason={reason ?? 'unknown'}
      sx={{
        mt: 1,
        p: 1.5,
        borderColor: 'error.light',
        bgcolor: (theme) => theme.palette.mode === 'dark'
          ? 'rgba(244, 67, 54, 0.12)'
          : 'rgba(211, 47, 47, 0.06)',
      }}
    >
      <Box display="flex" alignItems="flex-start" gap={1}>
        <Box
          aria-hidden
          sx={{
            width: 24,
            height: 24,
            borderRadius: '50%',
            bgcolor: 'error.main',
            color: 'error.contrastText',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontWeight: 700,
            fontSize: 14,
            flexShrink: 0,
          }}
        >
          !
        </Box>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="subtitle2" fontWeight={700}>
            {t('conversations.sessions.terminalCard.title')}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block">
            {referenceId
              ? `${referenceId} · ${t('conversations.sessions.terminalCard.subtitle')}`
              : t('conversations.sessions.terminalCard.subtitle')}
          </Typography>
        </Box>
      </Box>

      <Typography
        variant="body2"
        sx={{ mt: 1 }}
        data-testid={testId('terminal-card-body')}
      >
        {t(bodyKey)}
      </Typography>

      <Box
        sx={{
          mt: 1,
          p: 1,
          borderRadius: 1,
          bgcolor: 'background.paper',
          border: (theme) => `1px dashed ${theme.palette.divider}`,
        }}
      >
        <Typography variant="body2" data-testid={testId('terminal-card-next-step')}>
          <Box component="span" fontWeight={700} sx={{ mr: 0.75 }}>
            {t('conversations.sessions.terminalCard.nextStepLabel')}
          </Box>
          {t('conversations.sessions.terminalCard.nextStep')}
        </Typography>
      </Box>

      <Stack direction="row" spacing={1} sx={{ mt: 1.25 }}>
        <Button
          size="small"
          variant="contained"
          data-testid={testId('terminal-card-ask-again')}
          onClick={onAskAgain}
        >
          {t('conversations.sessions.terminalCard.askAgain')}
        </Button>
        <Button
          size="small"
          variant="outlined"
          data-testid={testId('terminal-card-dismiss')}
          onClick={onDismiss}
        >
          {t('conversations.sessions.terminalCard.dismiss')}
        </Button>
      </Stack>
    </Paper>
  )
}
