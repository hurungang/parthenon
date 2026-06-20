import { useCallback, useState } from 'react'
import { Box, Button, Typography, Radio, RadioGroup, FormControlLabel, TextField } from '@mui/material'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import { useTranslation } from 'react-i18next'
import type { InterveneRequest } from '../../types'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import { useDialogErrorHandler } from '../../hooks/useDialogErrorHandler'

// ── Props ─────────────────────────────────────────────────────────────────────

interface TaskInterventionDialogProps {
  request: InterveneRequest
  onSubmit: (requestId: string, value: {
    approval_value?: boolean
    selected_choice?: string
    text_value?: string
  }) => Promise<void>
  onDismiss: () => void
  expired?: boolean
}

// ── Type badge config ─────────────────────────────────────────────────────────

function typeBadgeStyles(type: string): { bg: string; color: string; label: string } {
  switch (type) {
    case 'approval':
      return { bg: '#FEF3C7', color: '#92400E', label: 'APPROVAL' }
    case 'choice':
      return { bg: '#DBEAFE', color: '#1D4ED8', label: 'CHOICE' }
    case 'text':
      return { bg: '#DCFCE7', color: '#15803D', label: 'TEXT INPUT' }
    default:
      return { bg: '#F5F5F5', color: '#757575', label: type.toUpperCase() }
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export function TaskInterventionDialog({
  request,
  onSubmit,
  onDismiss,
  expired = false,
}: TaskInterventionDialogProps) {
  const { t } = useTranslation()
  const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()
  const [submitting, setSubmitting] = useState(false)
  const [resolved, setResolved] = useState(false)
  const [approvalValue, setApprovalValue] = useState<boolean | null>(null)
  const [selectedChoice, setSelectedChoice] = useState('')
  const [textValue, setTextValue] = useState('')
  const badge = typeBadgeStyles(request.intervention_type)

  // For choice type: track selected option index
  const [selectedChoiceIdx, setSelectedChoiceIdx] = useState<number | null>(null)

  const handleSubmit = useCallback(async () => {
    try {
      clearDialogError()
      setSubmitting(true)

      const value: {
        approval_value?: boolean
        selected_choice?: string
        text_value?: string
      } = {}

      if (request.intervention_type === 'approval') {
        if (approvalValue === null) return
        value.approval_value = approvalValue
      } else if (request.intervention_type === 'choice') {
        if (!selectedChoice) return
        value.selected_choice = selectedChoice
      } else if (request.intervention_type === 'text') {
        if (!textValue.trim()) return
        value.text_value = textValue.trim()
      }

      await onSubmit(request.id, value)
      setResolved(true)
    } catch (err) {
      setDialogError(err)
    } finally {
      setSubmitting(false)
    }
  }, [request, approvalValue, selectedChoice, textValue, onSubmit, clearDialogError, setDialogError])

  const handleChoiceSelect = (choice: string, idx: number) => {
    setSelectedChoice(choice)
    setSelectedChoiceIdx(idx)
  }

  // Determine if submit should be enabled
  const canSubmit =
    !submitting &&
    !resolved &&
    !expired &&
    (request.intervention_type === 'approval' ? approvalValue !== null
      : request.intervention_type === 'choice' ? selectedChoice !== ''
        : request.intervention_type === 'text' ? textValue.trim().length > 0
          : false)

  // ── Resolved state ──
  if (resolved) {
    return (
      <Box
        sx={{
          border: 2,
          borderColor: '#D1D5DB',
          borderRadius: 2,
          opacity: 0.7,
          pointerEvents: 'none',
          bgcolor: 'background.paper',
          mb: 1,
          mt: 0.5,
        }}
      >
        <Box sx={{ bgcolor: '#F5F5F5', p: 2, display: 'flex', alignItems: 'flex-start', gap: 1.5 }}>
          <WarningAmberIcon sx={{ color: '#D97706', fontSize: 22, flexShrink: 0 }} />
          <Box>
            <Typography variant="subtitle2" sx={{ color: '#92400E', fontWeight: 600 }}>
              {t('intervene.responseDialogTitle', { defaultValue: 'Human Intervention Required' })}
            </Typography>
            <Typography variant="caption" sx={{ color: '#A16207' }}>
              {t('executions.taskIntervention.requestedBy', { defaultValue: 'Requested by' })} <strong>{request.agent_name ?? request.agent_session_id.slice(0, 8)}</strong>
            </Typography>
          </Box>
        </Box>
        <Box sx={{ p: 2 }}>
          <Box sx={{ p: 1.5, bgcolor: '#E8F5E9', borderRadius: 1, fontSize: 12, color: '#1B5E20', fontWeight: 500 }}>
            ✓ {t('executions.taskIntervention.responseSubmitted', { defaultValue: 'Response submitted' })}
          </Box>
        </Box>
      </Box>
    )
  }

  return (
    <Box
      sx={{
        border: 2,
        borderColor: expired ? '#FCA5A5' : '#FF9800',
        borderRadius: 2,
        overflow: 'hidden',
        boxShadow: expired ? undefined : 3,
        bgcolor: 'background.paper',
        mb: 1,
        mt: 0.5,
        opacity: expired ? 0.6 : 1,
        pointerEvents: expired ? 'none' : undefined,
        animation: 'ivSlide 0.35s ease',
        '@keyframes ivSlide': {
          from: { opacity: 0, transform: 'translateY(-6px)' },
          to: { opacity: 1, transform: 'translateY(0)' },
        },
      }}
    >
      {/* Error banner */}
      {!!dialogError && (
        <Box sx={{ px: 2, pt: 1 }}>
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
        </Box>
      )}

      {/* Header */}
      <Box
        sx={{
          bgcolor: expired ? '#FEF2F2' : '#FFF8E1',
          p: 2,
          display: 'flex',
          alignItems: 'flex-start',
          gap: 1.5,
          borderBottom: 1,
          borderColor: expired ? '#FECACA' : '#FFE0B2',
        }}
      >
        <WarningAmberIcon sx={{ color: expired ? '#F44336' : '#FF9800', fontSize: 22, flexShrink: 0 }} />
        <Box sx={{ flex: 1 }}>
          <Typography variant="subtitle2" sx={{ color: '#92400E', fontWeight: 600, mb: 0.25 }}>
            {t('executions.taskIntervention.title', { defaultValue: 'Intervention Required' })}
          </Typography>
          <Typography variant="caption" sx={{ color: '#A16207', display: 'block', lineHeight: 1.4 }}>
            {t('executions.taskIntervention.requestedByMeta', {
              defaultValue: 'Requested by {{agent}} during delegation',
              agent: request.agent_name ?? request.agent_session_id.slice(0, 8),
            })}
          </Typography>
          <Box
            sx={{
              display: 'inline-block',
              px: 1.25,
              py: 0.4,
              borderRadius: 1.5,
              fontSize: 10.5,
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: 0.5,
              mt: 0.75,
              bgcolor: badge.bg,
              color: badge.color,
              border: 1,
              borderColor: badge.bg,
            }}
          >
            {badge.label}
          </Box>
        </Box>
      </Box>

      {/* Body */}
      <Box sx={{ p: 2 }}>
        {/* Reason */}
        <Typography variant="body2" sx={{ fontSize: 13.5, color: 'text.primary', mb: 2, lineHeight: 1.5 }}>
          {request.reason}
        </Typography>

        {/* Context metadata if available */}
        {request.choices && request.intervention_type !== 'choice' && (
          <Typography variant="caption" sx={{ display: 'block', mb: 2, color: 'text.secondary', fontSize: 11 }}>
            {t('executions.taskIntervention.choicesAvailable', {
              defaultValue: 'Options available: {{count}}',
              count: request.choices.length,
            })}
          </Typography>
        )}

        {/* Expired overlay */}
        {expired && (
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              p: 1.25,
              bgcolor: '#FEF2F2',
              border: 1,
              borderColor: '#FECACA',
              borderRadius: 1,
              mb: 1,
              fontSize: 12,
              color: '#B91C1C',
              fontWeight: 500,
            }}
          >
            ⏱ {t('executions.taskIntervention.expiredMessage', { defaultValue: 'This intervention request has expired (sub-agent timed out). No further action possible.' })}
          </Box>
        )}

        {/* Approval mode */}
        {!expired && request.intervention_type === 'approval' && (
          <Box sx={{ display: 'flex', gap: 1.5 }}>
            <Button
              variant={approvalValue === true ? 'contained' : 'outlined'}
              onClick={() => setApprovalValue(true)}
              sx={{
                flex: 1,
                py: 1.25,
                fontWeight: 600,
                fontSize: 14,
                bgcolor: approvalValue === true ? '#4CAF50' : undefined,
                color: approvalValue === true ? '#fff' : '#F44336',
                borderColor: '#F44336',
                '&:hover': {
                  bgcolor: approvalValue === true ? '#388E3C' : '#FFEBEE',
                },
              }}
            >
              ✓ {t('executions.taskIntervention.approve', { defaultValue: 'Approve' })}
            </Button>
            <Button
              variant={approvalValue === false ? 'contained' : 'outlined'}
              onClick={() => setApprovalValue(false)}
              sx={{
                flex: 1,
                py: 1.25,
                fontWeight: 600,
                fontSize: 14,
                bgcolor: approvalValue === false ? '#F44336' : undefined,
                color: approvalValue === false ? '#fff' : '#F44336',
                borderColor: '#F44336',
                '&:hover': {
                  bgcolor: approvalValue === false ? '#D32F2F' : '#FFEBEE',
                },
              }}
            >
              ✗ {t('executions.taskIntervention.deny', { defaultValue: 'Deny' })}
            </Button>
          </Box>
        )}

        {/* Choice mode */}
        {!expired && request.intervention_type === 'choice' && request.choices && (
          <RadioGroup value={selectedChoice} onChange={(e) => setSelectedChoice(e.target.value)}>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {request.choices.map((choice, idx) => (
                <FormControlLabel
                  key={idx}
                  value={choice}
                  control={
                    <Radio
                      checked={selectedChoiceIdx === idx}
                      onChange={() => handleChoiceSelect(choice, idx)}
                      sx={{
                        '&.Mui-checked': { color: '#2563EB' },
                      }}
                    />
                  }
                  label={choice}
                  sx={{
                    m: 0,
                    p: 1.25,
                    border: 1.5,
                    borderColor: selectedChoiceIdx === idx ? '#2563EB' : 'divider',
                    borderRadius: 1,
                    transition: 'all 0.2s ease',
                    bgcolor: selectedChoiceIdx === idx ? '#DBEAFE' : 'transparent',
                    '&:hover': {
                      borderColor: '#2563EB',
                      bgcolor: '#EFF6FF',
                    },
                  }}
                  slotProps={{ typography: { sx: { fontSize: 13.5, fontWeight: selectedChoiceIdx === idx ? 600 : 400 } } }}
                />
              ))}
            </Box>
          </RadioGroup>
        )}

        {/* Text mode */}
        {!expired && request.intervention_type === 'text' && (
          <TextField
            value={textValue}
            onChange={(e) => setTextValue(e.target.value)}
            fullWidth
            multiline
            minRows={3}
            maxRows={6}
            placeholder={t('executions.taskIntervention.textPlaceholder', { defaultValue: 'Enter your response here...' })}
            sx={{
              '& .MuiOutlinedInput-root': {
                fontSize: 13.5,
                fontFamily: 'inherit',
              },
            }}
            slotProps={{
              htmlInput: { maxLength: 2000 },
            }}
            helperText={`${textValue.length}/2000`}
          />
        )}
      </Box>

      {/* Footer */}
      {!expired && (
        <Box
          sx={{
            px: 2,
            pb: 1.5,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <Button
            onClick={onDismiss}
            disabled={submitting}
            sx={{
              color: 'text.secondary',
              fontSize: 12,
              textTransform: 'none',
              '&:hover': { bgcolor: '#F5F5F5', color: '#F44336' },
            }}
          >
            {t('executions.taskIntervention.dismiss', { defaultValue: 'Dismiss (banner stays)' })}
          </Button>
          {(request.intervention_type === 'choice' || request.intervention_type === 'text' || request.intervention_type === 'approval') && (
            <Button
              variant="contained"
              onClick={handleSubmit}
              disabled={!canSubmit}
              sx={{
                py: 0.75,
                px: 2.5,
                fontWeight: 600,
                fontSize: 13,
              }}
            >
              {submitting
                ? t('app.saving', { defaultValue: 'Submitting...' })
                : t('intervene.submitResponse', { defaultValue: 'Submit Response' })}
            </Button>
          )}
        </Box>
      )}
    </Box>
  )
}
