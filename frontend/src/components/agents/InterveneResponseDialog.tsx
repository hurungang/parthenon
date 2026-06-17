import { useState } from 'react'
import {
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  FormLabel,
  IconButton,
  LinearProgress,
  Radio,
  RadioGroup,
  TextField,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import { useTranslation } from 'react-i18next'
import type { InterveneRequest } from '../../types'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import { useDialogErrorHandler } from '../../hooks/useDialogErrorHandler'

interface InterveneResponseDialogProps {
  open: boolean
  request: InterveneRequest | null
  onClose: () => void
  onSubmit: (requestId: string, value: {
    approval_value?: boolean
    selected_choice?: string
    text_value?: string
  }) => Promise<void>
  onTerminate?: (sessionId: string, requestId: string) => Promise<void>
}

export function InterveneResponseDialog({
  open,
  request,
  onClose,
  onSubmit,
  onTerminate,
}: InterveneResponseDialogProps) {
  const { t } = useTranslation()
  const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()
  const [submitting, setSubmitting] = useState(false)
  const [terminating, setTerminating] = useState(false)
  const [approvalValue, setApprovalValue] = useState<boolean | null>(null)
  const [selectedChoice, setSelectedChoice] = useState('')
  const [textValue, setTextValue] = useState('')

  const handleClose = () => {
    clearDialogError()
    setSubmitting(false)
    setApprovalValue(null)
    setSelectedChoice('')
    setTextValue('')
    onClose()
  }

  const handleSubmit = async () => {
    if (!request) return
    try {
      clearDialogError()
      setSubmitting(true)
      const value: {
        approval_value?: boolean
        selected_choice?: string
        text_value?: string
      } = {}
      if (request.intervention_type === 'approval') {
        value.approval_value = approvalValue ?? false
      } else if (request.intervention_type === 'choice') {
        value.selected_choice = selectedChoice
      } else if (request.intervention_type === 'text') {
        value.text_value = textValue
      }
      await onSubmit(request.id, value)
      handleClose()
    } catch (err) {
      setDialogError(err)
    } finally {
      setSubmitting(false)
    }
  }

  const interventionTypeLabel = (type: string) => {
    switch (type) {
      case 'approval':
        return t('intervene.typeApproval', 'Approval')
      case 'choice':
        return t('intervene.typeChoice', 'Choice')
      case 'text':
        return t('intervene.typeText', 'Text Input')
      default:
        return type
    }
  }

  if (!request) return null

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Box display="flex" alignItems="center" gap={1}>
          <Typography variant="h6" component="span">
            {t('intervene.responseDialogTitle', 'Human Intervention Required')}
          </Typography>
          <Chip
            label={interventionTypeLabel(request.intervention_type)}
            size="small"
            color="warning"
          />
        </Box>
        <IconButton edge="end" onClick={handleClose} size="small">
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent>
        {!!dialogError && (
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
        )}
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {request.reason}
        </Typography>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
          {t('intervene.sessionLabel', 'Session')}: {request.agent_session_id.slice(0, 8)}…
        </Typography>

        {request.intervention_type === 'approval' && (
          <Box display="flex" gap={2} justifyContent="center" sx={{ mt: 2 }}>
            <Button
              variant={approvalValue === true ? 'contained' : 'outlined'}
              color="success"
              onClick={() => setApprovalValue(true)}
              sx={{ minWidth: 120 }}
            >
              {t('app.yes')}
            </Button>
            <Button
              variant={approvalValue === false ? 'contained' : 'outlined'}
              color="error"
              onClick={() => setApprovalValue(false)}
              sx={{ minWidth: 120 }}
            >
              {t('app.no')}
            </Button>
          </Box>
        )}

        {request.intervention_type === 'choice' && request.choices && (
          <FormControl component="fieldset" sx={{ mt: 1, width: '100%' }}>
            <FormLabel component="legend">{t('intervene.selectOption', 'Select an option')}</FormLabel>
            <RadioGroup
              value={selectedChoice}
              onChange={(e) => setSelectedChoice(e.target.value)}
            >
              {request.choices.map((choice, idx) => (
                <FormControlLabel
                  key={idx}
                  value={choice}
                  control={<Radio />}
                  label={choice}
                />
              ))}
            </RadioGroup>
          </FormControl>
        )}

        {request.intervention_type === 'text' && (
          <TextField
            label={t('intervene.textResponse', 'Your response')}
            value={textValue}
            onChange={(e) => setTextValue(e.target.value)}
            fullWidth
            multiline
            minRows={3}
            maxRows={8}
            sx={{ mt: 1 }}
            slotProps={{
              htmlInput: { maxLength: 2000 },
            }}
            helperText={`${textValue.length}/2000`}
          />
        )}

        {submitting && <LinearProgress sx={{ mt: 2 }} />}
      </DialogContent>
      <DialogActions>
        {onTerminate && (
          <Button
            color="error"
            disabled={submitting || terminating}
            onClick={async () => {
              try {
                setTerminating(true)
                await onTerminate(request.agent_session_id, request.id)
                handleClose()
              } catch (err) {
                setDialogError(err)
              } finally {
                setTerminating(false)
              }
            }}
          >
            {terminating ? t('app.saving') : t('intervene.terminate', 'Terminate Session')}
          </Button>
        )}
        <Box flex={1} />
        <Button onClick={handleClose} disabled={submitting || terminating}>
          {t('app.cancel')}
        </Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={
            submitting || terminating ||
            (request.intervention_type === 'choice' && !selectedChoice)
          }
        >
          {submitting ? t('app.saving') : t('intervene.submitResponse', 'Submit')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
