import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  Typography,
} from '@mui/material'
import { submitAccessRequest } from '../../api/permissionsApi'
import type { RequiredPermission } from '../../utils/permissionError'

interface RequestPermissionModalProps {
  open: boolean
  onClose: () => void
  permissionContext: RequiredPermission | null
}

/**
 * Modal that pre-fills resource/action/id context from a 403 denial and collects
 * a business justification before submitting an access request.
 */
export function RequestPermissionModal({
  open,
  onClose,
  permissionContext,
}: RequestPermissionModalProps) {
  const { t } = useTranslation()
  const [justification, setJustification] = useState('')
  const [justificationError, setJustificationError] = useState('')
  const [loading, setLoading] = useState(false)
  const [submitted, setSubmitted] = useState(false)

  const handleClose = () => {
    setJustification('')
    setJustificationError('')
    setLoading(false)
    setSubmitted(false)
    onClose()
  }

  const handleSubmit = async () => {
    if (!justification.trim()) {
      setJustificationError(t('permissions.errors.requestJustificationRequired'))
      return
    }

    setLoading(true)
    setJustificationError('')

    try {
      const contextSuffix = permissionContext
        ? ` [resource_type=${permissionContext.resource_type}, action=${permissionContext.action}, resource_id=${permissionContext.resource_id ?? '*'}]`
        : ''
      // The access request API expects group_ids; we submit an empty list and embed
      // the permission context in the justification string.
      await submitAccessRequest([], justification.trim() + contextSuffix)
      setSubmitted(true)
      setTimeout(handleClose, 2000)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>{t('permissions.errors.requestModalTitle')}</DialogTitle>
      <DialogContent>
        {submitted ? (
          <Typography color="success.main">
            {t('permissions.errors.requestSubmittedSuccess')}
          </Typography>
        ) : (
          <>
            {permissionContext && (
              <>
                <TextField
                  label={t('permissions.errors.resourceType')}
                  value={permissionContext.resource_type}
                  fullWidth
                  margin="dense"
                  disabled
                  size="small"
                />
                <TextField
                  label={t('permissions.errors.action')}
                  value={permissionContext.action}
                  fullWidth
                  margin="dense"
                  disabled
                  size="small"
                />
                <TextField
                  label={t('permissions.errors.resourceId')}
                  value={permissionContext.resource_id ?? '*'}
                  fullWidth
                  margin="dense"
                  disabled
                  size="small"
                />
              </>
            )}
            <TextField
              label={t('permissions.errors.requestJustificationLabel')}
              placeholder={t('permissions.errors.requestJustificationPlaceholder')}
              value={justification}
              onChange={(e) => setJustification(e.target.value)}
              fullWidth
              multiline
              rows={4}
              margin="normal"
              required
              error={!!justificationError}
              helperText={justificationError}
            />
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={loading}>
          {t('common.cancel')}
        </Button>
        {!submitted && (
          <Button
            onClick={handleSubmit}
            variant="contained"
            disabled={loading}
            startIcon={loading ? <CircularProgress size={16} /> : undefined}
          >
            {t('permissions.accessRequests.submitRequest')}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  )
}
