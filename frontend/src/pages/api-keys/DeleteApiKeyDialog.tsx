import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  Button,
  Alert,
  Box,
  Typography,
} from '@mui/material'
import DeleteForeverIcon from '@mui/icons-material/DeleteForever'
import { useDeleteApiKey } from '../../hooks/useApiKeys'
import type { ApiKey } from '../../types/apiKeys'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'

interface DeleteApiKeyDialogProps {
  keyData: ApiKey | null
  open: boolean
  onClose: () => void
  onDeleted: () => void
}

export function DeleteApiKeyDialog({
  keyData,
  open,
  onClose,
  onDeleted,
}: DeleteApiKeyDialogProps) {
  const { t } = useTranslation()
  const [dialogError, setDialogError] = useState<unknown>(null)
  const deleteMutation = useDeleteApiKey()

  useEffect(() => {
    if (open) {
      setDialogError(null)
    }
  }, [open])

  const handleDelete = async () => {
    if (!keyData) return
    setDialogError(null)
    try {
      await deleteMutation.mutateAsync(keyData.id)
      onDeleted()
    } catch (err) {
      setDialogError(err)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={() => { onClose(); setDialogError(null) }}
      maxWidth="sm"
      fullWidth
    >
      <DialogTitle>
        <Box display="flex" alignItems="center" gap={1}>
          <DeleteForeverIcon color="error" />
          {t('apiKeys.deleteTitle')}
        </Box>
      </DialogTitle>
      <DialogContent>
        {dialogError ? (
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
        ) : null}

        <Alert severity="error" sx={{ mb: 2 }}>
          <Typography variant="body2">
            {t('apiKeys.deleteWarning', { name: keyData?.name ?? '' })}
          </Typography>
        </Alert>

        <DialogContentText>
          {t('apiKeys.deleteDescription')}
        </DialogContentText>

        {keyData && (
          <Box mt={2}>
            <Typography variant="body2">
              <strong>{t('app.name')}:</strong> {keyData.name}
            </Typography>
            <Typography variant="body2">
              <strong>{t('apiKeys.agentIdentity')}:</strong> {keyData.agent_identity_name}
            </Typography>
            <Typography variant="body2">
              <strong>{t('apiKeys.agentRole')}:</strong> {keyData.agent_role_name}
            </Typography>
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={() => { onClose(); setDialogError(null) }}>
          {t('app.cancel')}
        </Button>
        <Button
          variant="contained"
          color="error"
          onClick={handleDelete}
          disabled={deleteMutation.isPending}
        >
          {deleteMutation.isPending ? t('apiKeys.deleting') : t('apiKeys.delete')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
