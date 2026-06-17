import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Chip,
  LinearProgress,
  Paper,
  Radio,
  RadioGroup,
  FormControlLabel,
  FormControl,
  TextField,
  Typography,
} from '@mui/material'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import CancelIcon from '@mui/icons-material/Cancel'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import type { InterventionType, InterveneRequestMessage } from '../../types'

interface InlineInterventionDialogProps {
  request: InterveneRequestMessage
  isSubmitting?: boolean
  dialogError?: unknown
  onApprove: () => void | Promise<void>
  onDeny: () => void | Promise<void>
  onSelectChoice: (choice: string) => void | Promise<void>
  onSubmitText: (text: string) => void | Promise<void>
  onDismiss: () => void | Promise<void>
}

const typeBadgeConfig: Record<
  InterventionType,
  { color: 'warning' | 'info' | 'success'; labelKey: string }
> = {
  approval: { color: 'warning', labelKey: 'conversations.sessions.intervention.typeApproval' },
  choice: { color: 'info', labelKey: 'conversations.sessions.intervention.typeChoice' },
  text: { color: 'success', labelKey: 'conversations.sessions.intervention.typeText' },
}

/**
 * Inline intervention dialog rendered within the chat message flow.
 *
 * Supports three intervention types:
 * - Approval: Appove/Deny buttons
 * - Choice: Radio button group with confirm
 * - Text: Multiline input with submit
 *
 * Follows the prototype design at docs/changes/add-conversational-agent-intervention/prototype/index.html
 * and the Dialog Error Handling Standard with useDialogErrorHandler.
 */
export function InlineInterventionDialog({
  request,
  isSubmitting = false,
  dialogError = null,
  onApprove,
  onDeny,
  onSelectChoice,
  onSubmitText,
  onDismiss,
}: InlineInterventionDialogProps) {
  const { t } = useTranslation()
  const interventionType = request.intervention_type as InterventionType
  const badge = typeBadgeConfig[interventionType] ?? {
    color: 'warning' as const,
    labelKey: 'conversations.sessions.intervention.typeApproval',
  }

  // Choice state
  const [selectedChoice, setSelectedChoice] = useState<string>('')
  // Text state
  const [textValue, setTextValue] = useState('')

  const handleConfirmChoice = async () => {
    if (selectedChoice) {
      await onSelectChoice(selectedChoice)
      setSelectedChoice('')
    }
  }

  const handleSubmitText = async () => {
    if (textValue.trim()) {
      await onSubmitText(textValue.trim())
      setTextValue('')
    }
  }

  return (
    <Paper
      variant="outlined"
      sx={{
        border: 2,
        borderColor: 'warning.main',
        borderRadius: 3,
        overflow: 'hidden',
        boxShadow: 4,
        bgcolor: 'background.paper',
        maxWidth: 520,
        width: '100%',
        animation: 'slideIn 0.3s ease',
        '@keyframes slideIn': {
          from: { opacity: 0, transform: 'translateY(-8px)' },
          to: { opacity: 1, transform: 'translateY(0)' },
        },
      }}
    >
      {/* Header */}
      <Box
        sx={{
          bgcolor: 'warning.light',
          py: 1.5,
          px: 2,
          display: 'flex',
          alignItems: 'flex-start',
          gap: 1.5,
          borderBottom: 1,
          borderColor: '#FFE0B2',
        }}
      >
        <WarningAmberIcon sx={{ color: 'warning.dark', mt: 0.25 }} />
        <Box flex={1}>
          <Typography variant="subtitle1" fontWeight={600} color="warning.dark">
            {t('conversations.sessions.intervention.requiresYourInput', {
              agentType: request.agent_type ?? 'Agent',
            })}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block">
            {t('conversations.sessions.intervention.delegatedBy', {
              parentAgent: request.agent_type ?? 'Parent Agent',
              depth: request.delegation_depth,
            })}
          </Typography>
          <Chip
            label={t(badge.labelKey)}
            color={badge.color}
            size="small"
            sx={{ mt: 0.5, fontWeight: 700, fontSize: '0.7rem' }}
          />
        </Box>
      </Box>

      {/* Body */}
      <Box sx={{ p: 2 }}>
        {/* Error banner */}
        {dialogError != null && (
          <Box mb={2}>
            <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
          </Box>
        )}

        {/* Loading indicator */}
        {isSubmitting && <LinearProgress sx={{ mb: 2 }} />}

        {/* Question text */}
        <Typography variant="body2" sx={{ mb: 2, lineHeight: 1.6 }}>
          {request.reason}
        </Typography>

        {/* Approval type */}
        {interventionType === 'approval' && (
          <Box display="flex" gap={1.5}>
            <Button
              variant="contained"
              color="success"
              startIcon={<CheckCircleIcon />}
              onClick={() => void onApprove()}
              disabled={isSubmitting}
              fullWidth
              sx={{ fontWeight: 600 }}
            >
              {t('conversations.sessions.intervention.approve')}
            </Button>
            <Button
              variant="outlined"
              color="error"
              startIcon={<CancelIcon />}
              onClick={() => void onDeny()}
              disabled={isSubmitting}
              fullWidth
              sx={{ fontWeight: 600 }}
            >
              {t('conversations.sessions.intervention.deny')}
            </Button>
          </Box>
        )}

        {/* Choice type */}
        {interventionType === 'choice' && request.choices && (
          <Box>
            <FormControl component="fieldset" fullWidth disabled={isSubmitting}>
              <RadioGroup
                value={selectedChoice}
                onChange={(e) => setSelectedChoice(e.target.value)}
              >
                {request.choices.map((choice) => (
                  <FormControlLabel
                    key={choice}
                    value={choice}
                    control={<Radio />}
                    label={choice}
                    sx={{
                      py: 0.5,
                      px: 1,
                      border: 1,
                      borderColor: selectedChoice === choice ? 'primary.main' : 'divider',
                      borderRadius: 1,
                      bgcolor: selectedChoice === choice ? 'primary.light' : 'transparent',
                      mb: 0.5,
                      '&:hover': {
                        bgcolor: 'action.hover',
                      },
                    }}
                  />
                ))}
              </RadioGroup>
            </FormControl>
            <Box display="flex" justifyContent="flex-end" mt={1.5}>
              <Button
                variant="contained"
                onClick={() => void handleConfirmChoice()}
                disabled={!selectedChoice || isSubmitting}
                size="small"
              >
                {t('conversations.sessions.intervention.confirmSelection')}
              </Button>
            </Box>
          </Box>
        )}

        {/* Text type */}
        {interventionType === 'text' && (
          <Box>
            <TextField
              fullWidth
              multiline
              minRows={3}
              maxRows={6}
              placeholder={t('conversations.sessions.intervention.placeholderText')}
              value={textValue}
              onChange={(e) => setTextValue(e.target.value)}
              disabled={isSubmitting}
              size="small"
            />
            <Box display="flex" justifyContent="flex-end" mt={1.5}>
              <Button
                variant="contained"
                onClick={() => void handleSubmitText()}
                disabled={!textValue.trim() || isSubmitting}
                size="small"
              >
                {t('conversations.sessions.intervention.submitResponse')}
              </Button>
            </Box>
          </Box>
        )}
      </Box>

      {/* Dismiss row */}
      <Box
        display="flex"
        justifyContent="flex-end"
        px={2}
        pb={1.5}
        pt={0}
      >
        <Button
          size="small"
          variant="text"
          color="inherit"
          onClick={() => void onDismiss()}
          disabled={isSubmitting}
          sx={{ color: 'text.secondary', fontSize: '0.75rem' }}
        >
          {t('conversations.sessions.intervention.dismissCancel')}
        </Button>
      </Box>
    </Paper>
  )
}
