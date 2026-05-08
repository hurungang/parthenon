import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import AssignmentIcon from '@mui/icons-material/Assignment'
import DeleteIcon from '@mui/icons-material/Delete'
import RefreshIcon from '@mui/icons-material/Refresh'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { AgentIdentityDialog } from './AgentIdentityDialog'
import { AssignRolesToIdentityDialog } from './AssignRolesToIdentityDialog'
import type { AgentIdentity } from '../../types'

function statusColor(
  status: string,
): 'success' | 'warning' | 'error' | 'default' {
  if (status === 'active') return 'success'
  if (status === 'suspended') return 'warning'
  if (status === 'deprovisioned') return 'error'
  return 'default'
}

function tokenStatusColor(
  expiresAt: string,
): 'success' | 'warning' | 'error' {
  const diff = new Date(expiresAt).getTime() - Date.now()
  if (diff <= 0) return 'error'
  if (diff < 5 * 60 * 1000) return 'warning'
  return 'success'
}

/**
 * Agent Identity list page — displays all OAuth-created agent identities.
 * Identities are created automatically via OAuth flow, not manually edited.
 */
export function AgentIdentityListPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [refreshingId, setRefreshingId] = useState<string | null>(null)
  const [assignRolesIdentity, setAssignRolesIdentity] = useState<AgentIdentity | null>(null)

  const { data: identities, isLoading, error } = useQuery<AgentIdentity[]>({
    queryKey: ['agents', 'identities'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentIdentity[]>('/agents/identities')
      return data
    },
  })

  const handleOpenCreate = () => {
    setDialogOpen(true)
  }

  const handleDelete = async (id: string, name: string) => {
    if (confirm(t('agents.identities.deleteConfirm', { name }))) {
      await apiClient.delete(`/agents/identities/${id}`)
      await queryClient.invalidateQueries({ queryKey: ['agents', 'identities'] })
    }
  }

  const handleRefreshToken = async (identity: AgentIdentity) => {
    setRefreshingId(identity.id)
    try {
      await apiClient.post(`/agents/identities/${identity.id}/refresh-token`)
      await queryClient.invalidateQueries({ queryKey: ['agents', 'identities'] })
    } catch {
      // Token refresh failure — identity may need re-auth
    } finally {
      setRefreshingId(null)
    }
  }

  const handleDialogClose = () => {
    setDialogOpen(false)
  }

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Box>
          <Typography variant="h4" fontWeight={700}>{t('agents.identities.title')}</Typography>
          <Typography variant="body2" color="text.secondary" mt={0.5}>
            {t('agents.identities.subtitle')}
          </Typography>
        </Box>
        <Button variant="contained" startIcon={<AddIcon />} onClick={handleOpenCreate}>
          {t('agents.identities.create')}
        </Button>
      </Box>

      {isLoading && <CircularProgress />}
      {error && <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />}

      {!isLoading && !error && (
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>{t('app.name')}</TableCell>
                <TableCell>{t('agents.identities.realmName')}</TableCell>
                <TableCell>{t('agents.identities.realmUsername')}</TableCell>
                <TableCell>{t('app.status')}</TableCell>
                <TableCell>{t('agents.identities.tokenStatus')}</TableCell>
                <TableCell>{t('app.actions')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(identities ?? []).map((identity) => {
                const isTokenExpired =
                  identity.token_expires_at == null ||
                  new Date(identity.token_expires_at) <= new Date()
                const isRefreshing = refreshingId === identity.id
                return (
                  <TableRow key={identity.id} hover>
                    <TableCell>
                      <Typography fontWeight={500}>{identity.name}</Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" color="text.secondary">
                        {identity.realm_name ?? '—'}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" color="text.secondary">
                        {identity.realm_username ?? '—'}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={t(`agents.identities.status${identity.status.replace(/^./, (c: string) => c.toUpperCase())}`)}
                        size="small"
                        color={statusColor(identity.status)}
                      />
                    </TableCell>
                    <TableCell>
                      {identity.token_expires_at ? (
                        <Chip
                          size="small"
                          color={tokenStatusColor(identity.token_expires_at)}
                          label={isTokenExpired ? t('agents.identities.tokenExpired') : t('agents.identities.tokenActive')}
                        />
                      ) : (
                        <Typography variant="caption" color="text.secondary">
                          {t('agents.identities.noToken')}
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      <Box display="flex" gap={0.5}>
                        <Tooltip title={t('agents.identities.assignRoles')}>
                          <IconButton
                            size="small"
                            onClick={() => setAssignRolesIdentity(identity)}
                          >
                            <AssignmentIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        {identity.token_expires_at && (
                          <Tooltip title={t('agents.identities.refreshToken')}>
                            <span>
                              <IconButton
                                size="small"
                                onClick={() => handleRefreshToken(identity)}
                                disabled={isRefreshing}
                              >
                                {isRefreshing ? (
                                  <CircularProgress size={16} />
                                ) : (
                                  <RefreshIcon fontSize="small" />
                                )}
                              </IconButton>
                            </span>
                          </Tooltip>
                        )}
                        <Tooltip title={t('app.delete')}>
                          <IconButton
                            size="small"
                            color="error"
                            onClick={() => handleDelete(identity.id, identity.name)}
                          >
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </Box>
                    </TableCell>
                  </TableRow>
                )
              })}
              {(identities ?? []).length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} align="center">
                    <Typography color="text.secondary" py={3}>
                      {t('agents.identities.empty')}
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <AgentIdentityDialog
        open={dialogOpen}
        onClose={handleDialogClose}
        onSaved={async () => {
          await queryClient.invalidateQueries({ queryKey: ['agents', 'identities'] })
        }}
      />

      {assignRolesIdentity && (
        <AssignRolesToIdentityDialog
          open={!!assignRolesIdentity}
          identity={assignRolesIdentity}
          onClose={() => setAssignRolesIdentity(null)}
          onSaved={async () => {
            setAssignRolesIdentity(null)
          }}
        />
      )}
    </Box>
  )
}
