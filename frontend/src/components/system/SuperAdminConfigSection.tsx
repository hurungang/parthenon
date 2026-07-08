import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  FormControlLabel,
  Switch,
  TextField,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { useDialogErrorHandler } from '../../hooks/useDialogErrorHandler'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import { toggleSuperAdmin, updateSuperAdminPassword, type SuperAdminStatusResponse } from '../../api/systemConfigApi'
import { useQueryClient } from '@tanstack/react-query'

interface SuperAdminConfigSectionProps {
  status: SuperAdminStatusResponse | null
  hasActiveOidcProvider: boolean
}

export function SuperAdminConfigSection({
  status,
  hasActiveOidcProvider,
}: SuperAdminConfigSectionProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()

  const [disableDialogOpen, setDisableDialogOpen] = useState(false)
  const [guardRailDialogOpen, setGuardRailDialogOpen] = useState(false)
  const [passwordDialogOpen, setPasswordDialogOpen] = useState(false)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [updating, setUpdating] = useState(false)
  const [toggling, setToggling] = useState(false)

  const isEnabled = status?.is_enabled ?? false

  const handleToggle = async (enabled: boolean) => {
    if (!enabled && !hasActiveOidcProvider) {
      setGuardRailDialogOpen(true)
      return
    }
    if (!enabled) {
      setDisableDialogOpen(true)
      return
    }
    // Enable directly
    await performToggle(true)
  }

  const performToggle = async (enabled: boolean) => {
    try {
      clearDialogError()
      setToggling(true)
      await toggleSuperAdmin(enabled)
      void queryClient.invalidateQueries({ queryKey: ['system', 'super-admin-status'] })
    } catch (err) {
      setDialogError(err)
    } finally {
      setToggling(false)
      setDisableDialogOpen(false)
    }
  }

  const handlePasswordUpdate = async () => {
    setPasswordError(null)
    if (newPassword !== confirmPassword) {
      setPasswordError(t('systemConfig.superAdmin.passwordMismatch'))
      return
    }
    if (newPassword.length < 8) {
      setPasswordError('Password must be at least 8 characters')
      return
    }
    try {
      clearDialogError()
      setUpdating(true)
      await updateSuperAdminPassword(currentPassword, newPassword)
      setPasswordDialogOpen(false)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (err) {
      setDialogError(err)
    } finally {
      setUpdating(false)
    }
  }

  return (
    <Box>
      {dialogError && (
        <Box mb={2}>
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
        </Box>
      )}

      <Typography variant="h6" mb={2}>
        {t('systemConfig.superAdmin.title')}
      </Typography>

      {/* Status display */}
      {status && (
        <Box mb={2} p={1} bgcolor="grey.50" borderRadius={1}>
          <Typography variant="body2">
            {t('auth.username')}: <strong>{status.username ?? t('app.noData')}</strong>
          </Typography>
          <Typography variant="body2">
            {t('systemConfig.superAdmin.lastLogin')}:{' '}
            <strong>
              {status.last_login_at
                ? new Date(status.last_login_at).toLocaleString()
                : t('systemConfig.superAdmin.never')}
            </strong>
          </Typography>
        </Box>
      )}

      {/* Enable/Disable toggle */}
      <Box mb={2}>
        <FormControlLabel
          control={
            <Switch
              checked={isEnabled}
              onChange={(e) => { void handleToggle(e.target.checked); }}
              disabled={toggling}
            />
          }
          label={
            isEnabled
              ? t('systemConfig.superAdmin.enabled')
              : t('systemConfig.superAdmin.disabled')
          }
        />
      </Box>

      {isEnabled ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          {t('systemConfig.superAdmin.enableDescription')}
        </Alert>
      ) : (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {t('systemConfig.superAdmin.disableDescription')}
        </Alert>
      )}

      {/* Password change */}
      <Button
        variant="outlined"
        onClick={() => setPasswordDialogOpen(true)}
        disabled={!isEnabled}
      >
        {t('systemConfig.superAdmin.passwordChange')}
      </Button>

      {/* Disable confirmation modal */}
      <Dialog open={disableDialogOpen} onClose={() => setDisableDialogOpen(false)}>
        <DialogTitle>{t('systemConfig.superAdmin.disableWarningTitle')}</DialogTitle>
        <DialogContent>
          <DialogContentText>
            {t('systemConfig.superAdmin.disableWarningBody')}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDisableDialogOpen(false)}>{t('app.cancel')}</Button>
          <Button
            onClick={() => { void performToggle(false); }}
            color="error"
            variant="contained"
            disabled={toggling}
          >
            {toggling ? t('app.saving') : t('app.confirm')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Guard rail modal */}
      <Dialog open={guardRailDialogOpen} onClose={() => setGuardRailDialogOpen(false)}>
        <DialogTitle>{t('systemConfig.superAdmin.guardRailTitle')}</DialogTitle>
        <DialogContent>
          <DialogContentText>
            {t('systemConfig.superAdmin.disableGuardRail')}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setGuardRailDialogOpen(false)}>{t('app.close')}</Button>
        </DialogActions>
      </Dialog>

      {/* Password change dialog */}
      <Dialog open={passwordDialogOpen} onClose={() => { setPasswordDialogOpen(false); setPasswordError(null); }}>
        <DialogTitle>{t('systemConfig.superAdmin.passwordChange')}</DialogTitle>
        <DialogContent>
          {passwordError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {passwordError}
            </Alert>
          )}
          <Box display="grid" gap={2} mt={1}>
            <TextField
              label={t('systemConfig.superAdmin.currentPassword')}
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              fullWidth
            />
            <TextField
              label={t('systemConfig.superAdmin.newPassword')}
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              fullWidth
            />
            <TextField
              label={t('systemConfig.superAdmin.confirmPassword')}
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              fullWidth
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setPasswordDialogOpen(false); setPasswordError(null); }}>
            {t('app.cancel')}
          </Button>
          <Button
            onClick={() => { void handlePasswordUpdate(); }}
            variant="contained"
            disabled={updating || !currentPassword || !newPassword || !confirmPassword}
          >
            {updating ? t('app.saving') : t('app.save')}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
