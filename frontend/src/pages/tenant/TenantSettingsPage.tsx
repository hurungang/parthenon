/**
 * TenantSettingsPage — tenant admin settings for THEIR tenant: alias
 * (name, root-only editing), admin contact, onboarding state, and the
 * license & usage panel (Phase 10).  Scoped to tenant::settings; the
 * backend rejects access to any other tenant (fail-closed).  The tenant
 * address (slug) is shown read-only — it is the immutable unique
 * address and no endpoint accepts changes.
 */
import { useState, useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  TextField,
  Typography,
} from '@mui/material'
import LockIcon from '@mui/icons-material/Lock'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { LicenseUsagePanel } from '../../components/tenant/LicenseUsagePanel'
import { useDialogErrorHandler } from '../../hooks/useDialogErrorHandler'
import {
  getTenantSettings,
  updateTenantSettings,
  type TenantSettings,
} from '../../api/tenantApi'

export function TenantSettingsPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()
  const [name, setName] = useState('')
  const [contactName, setContactName] = useState('')
  const [contactEmail, setContactEmail] = useState('')
  const [saved, setSaved] = useState(false)
  const [initialized, setInitialized] = useState(false)

  const settingsQuery = useQuery({
    queryKey: ['tenant', 'settings'],
    queryFn: getTenantSettings,
  })

  const settings: TenantSettings | undefined = settingsQuery.data
  const isRoot = settings?.is_root ?? false

  useEffect(() => {
    if (settings && !initialized) {
      setName(settings.name)
      setContactName(settings.admin_contact_name ?? '')
      setContactEmail(settings.admin_contact_email ?? '')
      setInitialized(true)
    }
  }, [settings, initialized])

  const saveMutation = useMutation({
    mutationFn: () =>
      updateTenantSettings({
        name: name.trim(),
        admin_contact_name: contactName.trim() || null,
        admin_contact_email: contactEmail.trim() || null,
      }),
    onSuccess: () => {
      setSaved(true)
      void queryClient.invalidateQueries({ queryKey: ['tenant', 'settings'] })
    },
    onError: (err) => setDialogError(err),
  })

  if (settingsQuery.isLoading) {
    return (
      <Box p={3} textAlign="center">
        <CircularProgress />
      </Box>
    )
  }

  return (
    <Box p={3} maxWidth={720}>
      <Typography variant="h5" mb={2}>
        {t('tenant.settings.title')}
      </Typography>

      {saved && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSaved(false)}>
          {t('tenant.settings.saved')}
        </Alert>
      )}
      {dialogError != null && (
        <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
      )}

      <Card>
        <CardContent>
          <Box display="flex" alignItems="center" mb={2} gap={1}>
            <Typography variant="h6">{settings?.name}</Typography>
            {isRoot && (
              <Chip size="small" color="primary" label={t('tenant.settings.root')} />
            )}
            {settings?.is_onboarded ? (
              <Chip size="small" color="success" label={t('tenant.settings.onboarded')} />
            ) : (
              <Chip size="small" color="warning" label={t('tenant.settings.pendingOnboarding')} />
            )}
          </Box>
          {/* Alias (name) — root-only editing; others see it disabled with a note */}
          <TextField
            label={t('tenant.settings.name')}
            value={name}
            onChange={(e) => setName(e.target.value)}
            fullWidth
            margin="normal"
            disabled={!isRoot}
            helperText={
              isRoot
                ? t('tenant.settings.nameRootHint')
                : t('tenant.settings.nameRootOnly')
            }
            data-testid="tenant-settings-name"
          />
          {!isRoot && (
            <Box display="flex" alignItems="center" gap={0.5} mt={-1} mb={1}>
              <LockIcon sx={{ fontSize: 14, color: 'text.disabled' }} />
              <Typography variant="caption" color="text.disabled">
                {t('tenant.settings.aliasLockedNote')}
              </Typography>
            </Box>
          )}
          {/* Tenant address — immutable, shown read-only */}
          <TextField
            label={t('tenant.settings.address')}
            value={`/${settings?.slug ?? ''}`}
            fullWidth
            margin="normal"
            disabled
            helperText={t('tenant.settings.addressImmutable')}
            data-testid="tenant-settings-slug"
          />
          <TextField
            label={t('tenant.settings.contactName')}
            value={contactName}
            onChange={(e) => setContactName(e.target.value)}
            fullWidth
            margin="normal"
          />
          <TextField
            label={t('tenant.settings.contactEmail')}
            value={contactEmail}
            onChange={(e) => setContactEmail(e.target.value)}
            fullWidth
            margin="normal"
            type="email"
          />
          <Box mt={2}>
            <Button
              variant="contained"
              disabled={saveMutation.isPending || !name.trim()}
              onClick={() => {
                clearDialogError()
                setSaved(false)
                saveMutation.mutate()
              }}
            >
              {t('app.save')}
            </Button>
          </Box>
        </CardContent>
      </Card>

      <LicenseUsagePanel />
    </Box>
  )
}
