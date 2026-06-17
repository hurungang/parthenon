import { Box, CircularProgress, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'

interface InterventionPendingIndicatorProps {
  /** Show a smaller variant for inline chat flow */
  inline?: boolean
}

/**
 * Visual indicator in the chat flow when an intervention is awaiting user input.
 * Replaces the indefinite "thinking" or "waiting" dots with "Waiting for your input"
 * styled text with amber/warning color treatment.
 */
export function InterventionPendingIndicator({
  inline = false,
}: InterventionPendingIndicatorProps) {
  const { t } = useTranslation()

  return (
    <Box
      display="flex"
      alignItems="center"
      gap={1.5}
      sx={{
        py: inline ? 1 : 1.5,
        px: inline ? 0 : 2,
        bgcolor: 'warning.light',
        borderRadius: 2,
        border: 1,
        borderColor: 'warning.main',
        opacity: 0.92,
      }}
    >
      <CircularProgress size={inline ? 16 : 20} color="warning" />
      <Typography
        variant={inline ? 'body2' : 'body1'}
        fontWeight={600}
        color="warning.dark"
      >
        {t('conversations.sessions.intervention.waitingForInput')}
      </Typography>
    </Box>
  )
}
