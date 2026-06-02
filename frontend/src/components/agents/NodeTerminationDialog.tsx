import { useState } from 'react'
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  TextField,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import type { RuntimeTopologyNode, TerminationScope } from '../../types'

interface NodeTerminationDialogProps {
  open: boolean
  onClose: () => void
  selectedNode: RuntimeTopologyNode | null
  onConfirm: (scope: TerminationScope, reason: string) => Promise<void>
  isSubmitting: boolean
}

export function NodeTerminationDialog({
  open,
  onClose,
  selectedNode,
  onConfirm,
  isSubmitting,
}: NodeTerminationDialogProps) {
  const { t } = useTranslation()
  const [scope, setScope] = useState<TerminationScope>('cascade_subtree')
  const [reason, setReason] = useState('')
  const [dialogError, setDialogError] = useState<unknown>(null)

  const handleClose = () => {
    onClose()
    setDialogError(null)
    setReason('')
    setScope('cascade_subtree')
  }

  const handleConfirm = async () => {
    try {
      setDialogError(null)
      await onConfirm(scope, reason)
      handleClose()
    } catch (err) {
      setDialogError(err)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      fullWidth
      maxWidth="sm"
    >
      <DialogTitle>{t('agents.sessions.runtimeTerminateDialogTitle')}</DialogTitle>
      <DialogContent>
        {Boolean(dialogError) && <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />}
        <Typography variant="body2" color="text.secondary" mb={2}>
          {t('agents.sessions.runtimeTerminateDialogBody')}
        </Typography>
        <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>
          {selectedNode?.session_id}
        </Typography>

        <FormControl fullWidth sx={{ mt: 2 }}>
          <InputLabel>{t('agents.sessions.runtimeTerminationScope')}</InputLabel>
          <Select
            value={scope}
            label={t('agents.sessions.runtimeTerminationScope')}
            onChange={(e) => setScope(e.target.value as TerminationScope)}
          >
            <MenuItem value="cascade_subtree">{t('agents.sessions.runtimeTerminateCascade')}</MenuItem>
            <MenuItem value="node_only">{t('agents.sessions.runtimeTerminateNodeOnly')}</MenuItem>
          </Select>
        </FormControl>

        <TextField
          label={t('agents.sessions.runtimeTerminationReason')}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          fullWidth
          multiline
          minRows={3}
          sx={{ mt: 2 }}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>{t('app.cancel')}</Button>
        <Button color="error" variant="contained" onClick={() => void handleConfirm()} disabled={isSubmitting}>
          {t('agents.sessions.runtimeConfirmTerminate')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
