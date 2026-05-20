import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
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
import KeyIcon from '@mui/icons-material/Key'
import RefreshIcon from '@mui/icons-material/Refresh'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { AgentIdentityDialog } from './AgentIdentityDialog'
import { AssignRolesToIdentityDialog } from './AssignRolesToIdentityDialog'
import { ConfirmDialog } from '../../components/common/ConfirmDialog'
import { ErrorSnackbar } from '../../components/common/ErrorSnackbar'
import type { AgentIdentity } from '../../types'

interface ConflictError {
  agentTypeId: string
  agentTypeName: string
  message: string
}

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
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [refreshingId, setRefreshingId] = useState<string | null>(null)
  const [reauthingId, setReauthingId] = useState<string | null>(null)
  const [assignRolesIdentity, setAssignRolesIdentity] = useState<AgentIdentity | null>(null)
  
  // Confirmation dialog state
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false)
  const [identityToDelete, setIdentityToDelete] = useState<{ id: string; name: string } | null>(null)
  
  // Error snackbar state
  const [errorMessage, setErrorMessage] = useState('')
  const [conflictError, setConflictError] = useState<ConflictError | null>(null)

  /**
   * Parse structured error from backend: "agent_type_id:{uuid}|agent_type_name:{name}|{message}"
   */
  const parseConflictError = (detail: string): ConflictError | null => {
    const match = detail.match(/agent_type_id:([^|]+)\|agent_type_name:([^|]+)\|(.+)/)
    if (match) {
      return {
        agentTypeId: match[1],
        agentTypeName: match[2],
        message: match[3],
      }
    }
    return null
  }

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

  const handleDeleteClick = (id: string, name: string) => {
    setIdentityToDelete({ id, name })
    setConfirmDeleteOpen(true)
  }

  const handleConfirmDelete = async () => {
    if (!identityToDelete) return
    
    try {
      await apiClient.delete(`/agents/identities/${identityToDelete.id}`)
      await queryClient.invalidateQueries({ queryKey: ['agents', 'identities'] })
      setConfirmDeleteOpen(false)
      setIdentityToDelete(null)
    } catch (err: any) {
      setConfirmDeleteOpen(false)
      // Check for conflict error (409) when identity is referenced by AgentType
      if (err.response?.status === 409) {
        const detail = err.response?.data?.detail || `Identity ${identityToDelete.name} is referenced by one or more agent types`
        const parsed = parseConflictError(detail)
        if (parsed) {
          setConflictError(parsed)
          setErrorMessage(parsed.message)
        } else {
          setErrorMessage(detail)
          setConflictError(null)
        }
      } else {
        const errorDetail = err.response?.data?.detail || err.message || t('app.error')
        setErrorMessage(t('agents.identities.deleteError', { name: identityToDelete.name, error: errorDetail }))
        setConflictError(null)
      }
      setIdentityToDelete(null)
    }
  }

  const handleCancelDelete = () => {
    setConfirmDeleteOpen(false)
    setIdentityToDelete(null)
  }

  const handleRefreshToken = async (identity: AgentIdentity) => {
    setRefreshingId(identity.id)
    try {
      await apiClient.post(`/agents/identities/${identity.id}/refresh-token`)
      await queryClient.invalidateQueries({ queryKey: ['agents', 'identities'] })
    } catch (err: any) {
      // Display token refresh failure to user and refetch identity to update has_refresh_token status
      const errorDetail = err.response?.data?.detail || err.message || t('app.error')
      setErrorMessage(t('agents.identities.refreshTokenError', { name: identity.name, error: errorDetail }))
      // Refetch identities to update the has_refresh_token field (backend may have invalidated it)
      await queryClient.invalidateQueries({ queryKey: ['agents', 'identities'] })
    } finally {
      setRefreshingId(null)
    }
  }

  const handleReauth = async (identity: AgentIdentity) => {
    setReauthingId(identity.id)
    try {
      const { data } = await apiClient.get<{ authorization_url: string }>(
        `/agents/identities/${identity.id}/reauth-url`
      )
      // Open re-authentication in a popup so the user can complete the OAuth flow
      const popup = window.open(
        data.authorization_url,
        'agentReauth',
        'width=600,height=700,menubar=no,toolbar=no,location=yes,status=no'
      )
      const handleMessage = async (event: MessageEvent) => {
        if (event.origin !== window.location.origin) return
        if (event.data?.type === 'AGENT_OAUTH_SUCCESS' || event.data?.type === 'MCP_OAUTH_SUCCESS') {
          window.removeEventListener('message', handleMessage)
          popup?.close()
          await queryClient.invalidateQueries({ queryKey: ['agents', 'identities'] })
        }
      }
      window.addEventListener('message', handleMessage)
      // Cleanup listener if popup is closed without completing
      const check = setInterval(() => {
        if (popup?.closed) {
          clearInterval(check)
          window.removeEventListener('message', handleMessage)
        }
      }, 500)
    } catch {
      // Reauth URL fetch failed
    } finally {
      setReauthingId(null)
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
                const isReathing = reauthingId === identity.id
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
                        {/* Show green refresh if refresh token is available, red reauth if not */}
                        {identity.has_refresh_token ? (
                          <Tooltip title={t('agents.identities.refreshToken')}>
                            <span>
                              <IconButton
                                size="small"
                                color="success"
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
                        ) : (
                          <Tooltip title={t('agents.identities.reauthenticate')}>
                            <span>
                              <IconButton
                                size="small"
                                color="error"
                                onClick={() => handleReauth(identity)}
                                disabled={isReathing}
                              >
                                {isReathing ? (
                                  <CircularProgress size={16} />
                                ) : (
                                  <KeyIcon fontSize="small" />
                                )}
                              </IconButton>
                            </span>
                          </Tooltip>
                        )}
                        <Tooltip title={t('app.delete')}>
                          <IconButton
                            size="small"
                            color="error"
                            onClick={() => handleDeleteClick(identity.id, identity.name)}
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

      <ConfirmDialog
        open={confirmDeleteOpen}
        title={t('agents.identities.deleteConfirmTitle')}
        message={t('agents.identities.deleteConfirm', { name: identityToDelete?.name || '' })}
        confirmText={t('app.delete')}
        confirmColor="error"
        onConfirm={handleConfirmDelete}
        onCancel={handleCancelDelete}
      />

      <ErrorSnackbar
        open={!!errorMessage}
        message={errorMessage}
        severity="error"
        onClose={() => {
          setErrorMessage('')
          setConflictError(null)
        }}
        actionLabel={conflictError ? t('agents.identities.goToAgentType') : undefined}
        onAction={
          conflictError
            ? () => {
                // Navigate to agents page and auto-open details dialog for the conflicting agent type
                navigate('/agents', { state: { openDialogFor: conflictError.agentTypeId } })
                setErrorMessage('')
                setConflictError(null)
              }
            : undefined
        }
      />
    </Box>
  )
}
