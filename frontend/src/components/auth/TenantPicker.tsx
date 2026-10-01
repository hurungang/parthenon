/**
 * TenantPicker — organization chooser for multi-organization users.
 *
 * Shown after OIDC authentication when the signed-in user holds more than
 * one active tenant membership: one session is bound to exactly one
 * tenant, so selecting a different organization re-runs the sign-in flow
 * against that organization's identity provider (fresh token with the
 * matching tenant claim).  Rendered only when multi-tenancy is on.
 */
import { useState } from 'react'
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  List,
  ListItemButton,
  ListItemText,
  Typography,
} from '@mui/material'
import BusinessIcon from '@mui/icons-material/Business'
import { useTranslation } from 'react-i18next'
import type { TenantMembership } from '../../types'

/** Static i18n keys per tenant role (avoids dynamic key construction). */
const ROLE_KEY: Record<TenantMembership['tenant_role'], string> = {
  platform_admin: 'auth.tenantPicker.role.platform_admin',
  tenant_admin: 'auth.tenantPicker.role.tenant_admin',
  member: 'auth.tenantPicker.role.member',
}

interface TenantPickerProps {
  open: boolean
  memberships: TenantMembership[]
  currentTenantSlug: string | null
  onSelect: (membership: TenantMembership) => void
  /** Selecting the current tenant continues into the workspace */
  onContinue: () => void
  loading?: boolean
  error?: string | null
}

export function TenantPicker({
  open,
  memberships,
  currentTenantSlug,
  onSelect,
  onContinue,
  loading = false,
  error = null,
}: TenantPickerProps) {
  const { t } = useTranslation()
  const [switching, setSwitching] = useState<string | null>(null)

  const currentMembership = memberships.find(
    (m) => m.tenant_slug === currentTenantSlug,
  )

  const handleSelect = (membership: TenantMembership) => {
    if (membership.tenant_slug === currentTenantSlug) {
      onContinue()
      return
    }
    setSwitching(membership.tenant_slug)
    onSelect(membership)
  }

  return (
    <Dialog
      open={open}
      maxWidth="xs"
      fullWidth
      disableEscapeKeyDown
      PaperProps={{ 'data-testid': 'tenant-picker' }}
    >
      <DialogTitle sx={{ textAlign: 'center', pt: 4 }}>
        <BusinessIcon color="primary" sx={{ fontSize: 40, mb: 1, display: 'block', mx: 'auto' }} />
        {t('auth.tenantPicker.title')}
      </DialogTitle>
      <DialogContent>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}
        <Typography variant="body2" color="text.secondary" mb={2} textAlign="center">
          {t('auth.tenantPicker.subtitle')}
        </Typography>
        {loading ? (
          <Box sx={{ textAlign: 'center', py: 4 }}>
            <CircularProgress size={28} />
          </Box>
        ) : (
          <List disablePadding>
            {memberships.map((m) => (
              <ListItemButton
                key={m.tenant_id}
                onClick={() => handleSelect(m)}
                selected={m.tenant_slug === currentTenantSlug}
                disabled={switching !== null}
                sx={{ borderRadius: 1, mb: 0.5 }}
              >
                <ListItemText
                  primary={
                    <>
                      {m.tenant_name}
                      {m.is_default && (
                        <Chip
                          size="small"
                          label={t('auth.tenantPicker.default')}
                          sx={{ ml: 1 }}
                        />
                      )}
                    </>
                  }
                  secondary={t(ROLE_KEY[m.tenant_role])}
                />
                {switching === m.tenant_slug && <CircularProgress size={18} />}
              </ListItemButton>
            ))}
          </List>
        )}
        {currentMembership && (
          <Typography variant="caption" color="text.secondary" display="block" mt={2} textAlign="center">
            {t('auth.tenantPicker.signedInAs', { name: currentMembership.tenant_name })}
          </Typography>
        )}
      </DialogContent>
    </Dialog>
  )
}
