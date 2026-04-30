import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
} from '@mui/material'
import { useCloneRole } from '../../hooks/usePermissions'
import PermissionDeniedAlert from './PermissionDeniedAlert'
import type { Role } from '../../types/permissions'

interface CloneRoleDialogProps {
  open: boolean
  sourceRole: Role | null
  onClose: () => void
}

export default function CloneRoleDialog({
  open,
  sourceRole,
  onClose,
}: CloneRoleDialogProps) {
  const { t } = useTranslation()
  const cloneRole = useCloneRole()

  const [dialogError, setDialogError] = useState<unknown>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  // Pre-fill from source when dialog opens
  useEffect(() => {
    if (open && sourceRole) {
      setName(t('permissions.roles.cloneNamePrefix', { name: sourceRole.name }))
      setDescription(sourceRole.description ?? '')
      setDialogError(null)
    }
  }, [open, sourceRole, t])

  const handleSubmit = async () => {
    if (!sourceRole) return
    try {
      setDialogError(null)
      await cloneRole.mutateAsync({
        sourceId: sourceRole.id,
        data: { name, description: description || undefined },
      })
      onClose()
    } catch (err) {
      setDialogError(err)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={() => {
        onClose()
        setDialogError(null)
      }}
      maxWidth="sm"
      fullWidth
    >
      <DialogTitle>{t('permissions.roles.cloneRole')}</DialogTitle>
      <DialogContent>
        {dialogError != null && (
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
        )}
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            label={t('app.name')}
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            autoFocus
          />
          <TextField
            label={t('app.description')}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            multiline
            rows={2}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button
          onClick={() => {
            onClose()
            setDialogError(null)
          }}
        >
          {t('app.cancel')}
        </Button>
        <Button
          onClick={handleSubmit}
          variant="contained"
          disabled={!name.trim() || cloneRole.isPending}
        >
          {t('permissions.roles.cloneRole')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
