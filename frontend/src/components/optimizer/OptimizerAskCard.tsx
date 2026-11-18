import { useState } from 'react'
import {
  Box,
  Button,
  Chip,
  LinearProgress,
  Paper,
  TextField,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import HelpOutlineIcon from '@mui/icons-material/HelpOutline'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import CancelIcon from '@mui/icons-material/Cancel'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import { ContentRenderer } from '../ContentRenderer'
import type { InterventionType } from '../../types'

export interface OptimizerAskCardProps {
  /** The optimizer's question / ask (markdown allowed). */
  reason: string
  interventionType: InterventionType
  choices?: string[] | null
  /** Set once answered — the card renders read-only with the given answer. */
  resolvedAnswer?: string | null
  isSubmitting?: boolean
  dialogError?: unknown
  onSelectChoice: (choice: string) => void | Promise<void>
  onSubmitText: (text: string) => void | Promise<void>
  onCancel: () => void | Promise<void>
  /** Plain approval (not a live test) — approve / deny the ask. */
  onApprove?: () => void | Promise<void>
  onDeny?: () => void | Promise<void>
  testIdPrefix?: string
}

/**
 * In-chat ask card for an optimization conversation.
 *
 * Reuses the SAME decision chain as every other intervention (WS
 * `intervene_response` → durable resume): the answer is recorded once and the
 * optimizer never proceeds on an assumption. Options come from the request; a
 * free-text answer is always accepted (the backend takes `text_value` for any
 * intervention type). Resolved cards stay in the record as confirmation.
 */
export function OptimizerAskCard({
  reason,
  interventionType,
  choices,
  resolvedAnswer,
  isSubmitting = false,
  dialogError = null,
  onSelectChoice,
  onSubmitText,
  onCancel,
  onApprove,
  onDeny,
  testIdPrefix = 'optimizer-ask',
}: OptimizerAskCardProps) {
  const { t } = useTranslation()
  const [textValue, setTextValue] = useState('')

  const handleSubmitText = async () => {
    const trimmed = textValue.trim()
    if (!trimmed) return
    await onSubmitText(trimmed)
    setTextValue('')
  }

  return (
    <Paper
      variant="outlined"
      data-testid={testIdPrefix}
      sx={{
        borderWidth: 2,
        borderColor: 'warning.main',
        borderRadius: 3,
        maxWidth: 620,
        overflow: 'hidden',
      }}
    >
      <Box sx={{ px: 2, py: 1.5, bgcolor: 'warning.light', display: 'flex', gap: 1 }}>
        <HelpOutlineIcon sx={{ color: 'warning.dark', mt: 0.25 }} />
        <Box flex={1}>
          <Typography variant="subtitle2" fontWeight={700} color="warning.dark">
            {t('agents.optimizer.askTitle')}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {t('agents.optimizer.askSubtitle')}
          </Typography>
        </Box>
        <Chip
          size="small"
          color="warning"
          label={t('agents.optimizer.askChip')}
          data-testid={`${testIdPrefix}-chip`}
        />
      </Box>

      <Box sx={{ p: 2 }}>
        {dialogError != null && (
          <Box mb={2}>
            <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
          </Box>
        )}
        {isSubmitting && <LinearProgress sx={{ mb: 2 }} />}

        <ContentRenderer content={reason} />

        {resolvedAnswer ? (
          <Box
            display="flex"
            alignItems="center"
            gap={1}
            mt={1.5}
            data-testid={`${testIdPrefix}-resolved`}
          >
            <CheckCircleIcon fontSize="small" color="success" />
            <Typography variant="body2" fontWeight={600} color="success.dark">
              {t('agents.optimizer.askResolved', { answer: resolvedAnswer })}
            </Typography>
          </Box>
        ) : (
          <>
            {interventionType === 'approval' && onApprove && onDeny && (
              <Box display="flex" gap={1} mt={1.5}>
                <Button
                  variant="contained"
                  color="success"
                  startIcon={<CheckCircleIcon />}
                  disabled={isSubmitting}
                  onClick={() => void onApprove()}
                  data-testid={`${testIdPrefix}-approve`}
                >
                  {t('conversations.sessions.intervention.approve')}
                </Button>
                <Button
                  variant="outlined"
                  color="error"
                  startIcon={<CancelIcon />}
                  disabled={isSubmitting}
                  onClick={() => void onDeny()}
                  data-testid={`${testIdPrefix}-deny`}
                >
                  {t('conversations.sessions.intervention.deny')}
                </Button>
              </Box>
            )}
            {interventionType === 'choice' && choices && choices.length > 0 && (
              <Box display="flex" flexDirection="column" gap={1} mt={1.5}>
                {choices.map((choice) => (
                  <Button
                    key={choice}
                    variant="outlined"
                    color="inherit"
                    disabled={isSubmitting}
                    onClick={() => void onSelectChoice(choice)}
                    data-testid={`${testIdPrefix}-choice-${choice}`}
                    sx={{
                      justifyContent: 'flex-start',
                      textTransform: 'none',
                      borderColor: 'divider',
                      '&:hover': { borderColor: 'secondary.main', bgcolor: '#FAF5FF' },
                    }}
                  >
                    {choice}
                  </Button>
                ))}
              </Box>
            )}

            <Box mt={1.5} pt={interventionType === 'choice' ? 1.5 : 0} borderTop={interventionType === 'choice' ? 1 : 0} borderColor="divider">
              <Typography variant="caption" color="text.secondary" display="block" mb={0.5}>
                {t('agents.optimizer.askFreeTextLabel')}
              </Typography>
              <TextField
                fullWidth
                multiline
                minRows={2}
                maxRows={5}
                size="small"
                value={textValue}
                placeholder={t('agents.optimizer.askFreeTextPlaceholder')}
                onChange={(event) => setTextValue(event.target.value)}
                disabled={isSubmitting}
                inputProps={{ 'data-testid': `${testIdPrefix}-text` }}
              />
              <Box display="flex" gap={1} mt={1}>
                <Button
                  size="small"
                  variant="contained"
                  onClick={() => void handleSubmitText()}
                  disabled={!textValue.trim() || isSubmitting}
                  data-testid={`${testIdPrefix}-submit`}
                >
                  {t('agents.optimizer.askSubmit')}
                </Button>
                <Button
                  size="small"
                  variant="text"
                  color="inherit"
                  onClick={() => void onCancel()}
                  disabled={isSubmitting}
                  sx={{ color: 'text.secondary' }}
                  data-testid={`${testIdPrefix}-cancel`}
                >
                  {t('agents.optimizer.askCancel')}
                </Button>
              </Box>
              <Typography variant="caption" color="text.secondary" display="block" mt={1}>
                {t('agents.optimizer.askFreeTextHint')}
              </Typography>
            </Box>
          </>
        )}
      </Box>
    </Paper>
  )
}
