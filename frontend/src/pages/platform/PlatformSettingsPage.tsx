/**
 * PlatformSettingsPage — platform configuration including the tenancy
 * switch.  Enabling multi-tenancy is a major, one-way-feeling operation:
 * the page shows an explicit adoption warning and requires typing a
 * confirmation phrase before the toggle is sent.  Errors surface per the
 * dialog error handling standard.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  FormControlLabel,
  Paper,
  Switch,
  TextField,
  Typography,
} from '@mui/material'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { useDialogErrorHandler } from '../../hooks/useDialogErrorHandler'
import {
  getPlatformSettings,
  updatePlatformSetting,
} from '../../api/platformAdminApi'

const CONFIRM_PHRASE = 'ENABLE'

export function PlatformSettingsPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [adoptionResult, setAdoptionResult] = useState<string | null>(null)

  const settingsQuery = useQuery({
    queryKey: ['platform', 'settings'],
    queryFn: getPlatformSettings,
  })

  const toggleMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      updatePlatformSetting('multi_tenancy_enabled', enabled),
    onSuccess: (data) => {
      setConfirmOpen(false)
      setConfirmText('')
      const adoption = data.adoption
      if (data.multi_tenancy_enabled) {
        setAdoptionResult(
          t('platform.settings.adoptionDone', {
            tables: adoption?.backfilled_tables ?? 0,
            admins: adoption?.memberships_granted ?? 0,
          }),
        )
      } else {
        setAdoptionResult(t('platform.settings.disableDone'))
      }
      void queryClient.invalidateQueries({ queryKey: ['platform'] })
    },
    onError: (err) => {
      setDialogError(err)
    },
  })

  const enabled = settingsQuery.data?.multi_tenancy_enabled ?? false
  const busy = toggleMutation.isPending || settingsQuery.isLoading

  return (
    <Box p={3}>
      <Typography variant="h5" mb={2}>
        {t('platform.settings.title')}
      </Typography>

      {adoptionResult && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setAdoptionResult(null)}>
          {adoptionResult}
        </Alert>
      )}
      {dialogError != null && !confirmOpen && (
        <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
      )}

      <Card>
        <CardContent>
          <Box display="flex" alignItems="center" justifyContent="space-between">
            <Box>
              <Typography variant="h6">{t('platform.settings.tenancySwitch')}</Typography>
              <Typography variant="body2" color="text.secondary" maxWidth={560}>
                {t('platform.settings.tenancyHelp')}
              </Typography>
            </Box>
            {busy ? (
              <CircularProgress size={26} />
            ) : (
              <FormControlLabel
                control={
                  <Switch
                    checked={enabled}
                    data-testid="tenancy-switch"
                    onChange={() => {
                      clearDialogError()
                      if (!enabled) {
                        setConfirmOpen(true)
                      } else {
                        toggleMutation.mutate(false)
                      }
                    }}
                  />
                }
                label={
                  enabled
                    ? t('platform.settings.tenancyOn')
                    : t('platform.settings.tenancyOff')
                }
              />
            )}
          </Box>

          {enabled && (
            <Alert severity="info" sx={{ mt: 2 }}>
              {t('platform.settings.tenancyOnNote')}
            </Alert>
          )}
        </CardContent>
      </Card>

      {/* Enable confirmation dialog — irreversible adoption warning */}
      <Dialog
        open={confirmOpen}
        onClose={() => {
          setConfirmOpen(false)
          setConfirmText('')
        }}
      >
        <DialogTitle>{t('platform.settings.confirmTitle')}</DialogTitle>
        <DialogContent>
          {dialogError != null && (
            <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
          )}
          <DialogContentText mb={2}>{t('platform.settings.confirmWarning')}</DialogContentText>
          <Paper variant="outlined" sx={{ p: 2, mb: 2, bgcolor: 'warning.light' }}>
            <Typography variant="body2">
              {t('platform.settings.confirmDetails')}
            </Typography>
          </Paper>
          <DialogContentText mb={1}>
            {t('platform.settings.confirmPrompt', { phrase: CONFIRM_PHRASE })}
          </DialogContentText>
          <TextField
            size="small"
            fullWidth
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            data-testid="tenancy-confirm-input"
          />
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              setConfirmOpen(false)
              setConfirmText('')
              clearDialogError()
            }}
          >
            {t('app.cancel')}
          </Button>
          <Button
            variant="contained"
            color="warning"
            disabled={confirmText !== CONFIRM_PHRASE || toggleMutation.isPending}
            onClick={() => toggleMutation.mutate(true)}
          >
            {t('platform.settings.confirmEnable')}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
