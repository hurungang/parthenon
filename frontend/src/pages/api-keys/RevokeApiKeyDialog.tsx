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
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import { useRevokeApiKey } from '../../hooks/useApiKeys'
import type { ApiKey } from '../../types/apiKeys'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'

interface RevokeApiKeyDialogProps {
  keyData: ApiKey | null
  open: boolean
  onClose: () => void
  onRevoked: () => void
}

export function RevokeApiKeyDialog({
  keyData,
  open,
  onClose,
  onRevoked,
}: RevokeApiKeyDialogProps) {
  const { t } = useTranslation()
  const [dialogError, setDialogError] = useState<unknown>(null)
  const revokeMutation = useRevokeApiKey()

  useEffect(() => {
    if (open) {
      setDialogError(null)
    }
  }, [open])

  const handleRevoke = async () => {
    if (!keyData) return
    setDialogError(null)
    try {
      await revokeMutation.mutateAsync(keyData.id)
      onRevoked()
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
          <WarningAmberIcon color="warning" />
          {t('apiKeys.revokeTitle')}
        </Box>
      </DialogTitle>
      <DialogContent>
        {dialogError ? (
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
        ) : null}

        <Alert severity="warning" sx={{ mb: 2 }}>
          <Typography variant="body2">
            {t('apiKeys.revokeWarning', { name: keyData?.name ?? '' })}
          </Typography>
        </Alert>

        <DialogContentText>
          {t('apiKeys.revokeDescription')}
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
          onClick={handleRevoke}
          disabled={revokeMutation.isPending}
        >
          {revokeMutation.isPending ? t('apiKeys.revoking') : t('apiKeys.revoke')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
