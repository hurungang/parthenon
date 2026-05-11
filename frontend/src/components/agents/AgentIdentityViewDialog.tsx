import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Typography,
} from '@mui/material'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import type { AgentIdentity } from '../../types'

function statusColor(status: string): 'success' | 'warning' | 'error' | 'default' {
  if (status === 'active') return 'success'
  if (status === 'suspended') return 'warning'
  if (status === 'deprovisioned') return 'error'
  return 'default'
}

interface AgentIdentityViewDialogProps {
  open: boolean
  identityId: string | null
  onClose: () => void
}

/**
 * Read-only view dialog for a single AgentIdentity.
 * Displays identity details and provides an Edit button that navigates to the
 * identity management page (identities are managed via OAuth flow, not inline forms).
 */
export function AgentIdentityViewDialog({
  open,
  identityId,
  onClose,
}: AgentIdentityViewDialogProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const {
    data: identity,
    isLoading,
    error,
  } = useQuery<AgentIdentity>({
    queryKey: ['agents', 'identities', identityId],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentIdentity>(`/agents/identities/${identityId}`)
      return data
    },
    enabled: open && !!identityId,
  })

  const handleEdit = () => {
    onClose()
    navigate('/agents/identities')
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="xl"
      fullWidth
      PaperProps={{ sx: { width: { xs: '100%', sm: '90%', lg: '95%' } } }}
    >
      <DialogTitle>{t('agents.identities.viewTitle')}</DialogTitle>

      <DialogContent dividers>
        {error != null && (
          <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />
        )}
        {isLoading && (
          <Box display="flex" justifyContent="center" p={4}>
            <CircularProgress />
          </Box>
        )}
        {identity && (
          <Box display="flex" flexWrap="wrap" gap={2}>
            <Box sx={{ flex: '1 1 40%', minWidth: 160 }}>
              <Typography variant="caption" color="text.secondary" display="block">
                {t('app.name')}
              </Typography>
              <Typography variant="body2" fontWeight={500} mt={0.25}>
                {identity.name}
              </Typography>
            </Box>

            <Box sx={{ flex: '1 1 40%', minWidth: 160 }}>
              <Typography variant="caption" color="text.secondary" display="block">
                {t('app.status')}
              </Typography>
              <Box mt={0.25}>
                <Chip
                  label={t(
                    `agents.identities.status${identity.status.replace(/^./, (c: string) => c.toUpperCase())}`,
                  )}
                  size="small"
                  color={statusColor(identity.status)}
                />
              </Box>
            </Box>

            <Box sx={{ flex: '1 1 40%', minWidth: 160 }}>
              <Typography variant="caption" color="text.secondary" display="block">
                {t('agents.identities.realmName')}
              </Typography>
              <Typography variant="body2" mt={0.25}>
                {identity.realm_name ?? '—'}
              </Typography>
            </Box>

            <Box sx={{ flex: '1 1 40%', minWidth: 160 }}>
              <Typography variant="caption" color="text.secondary" display="block">
                {t('agents.identities.realmUsername')}
              </Typography>
              <Typography variant="body2" mt={0.25}>
                {identity.realm_username ?? '—'}
              </Typography>
            </Box>
          </Box>
        )}
      </DialogContent>

      <DialogActions>
        <Button variant="outlined" onClick={handleEdit}>
          {t('app.edit')}
        </Button>
        <Button onClick={onClose}>{t('app.close')}</Button>
      </DialogActions>
    </Dialog>
  )
}
