import { useState } from 'react'
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
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import LoginIcon from '@mui/icons-material/Login'
import RefreshIcon from '@mui/icons-material/Refresh'
import WarningIcon from '@mui/icons-material/Warning'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import type { McpSession, McpSessionAuthType } from '../../types'

interface McpSessionManagerProps {
  serverId: string
}

const AUTH_TYPES: McpSessionAuthType[] = ['api_key', 'bearer_token', 'basic_auth', 'oauth2', 'none']

interface SessionForm {
  name: string
  description: string
  auth_type: McpSessionAuthType
  // Simplified credential fields
  api_key_value: string
  bearer_token_value: string
  basic_auth_username: string
  basic_auth_password: string
  oauth2_authenticated: boolean
}

const defaultForm: SessionForm = {
  name: '',
  description: '',
  auth_type: 'api_key',
  api_key_value: '',
  bearer_token_value: '',
  basic_auth_username: '',
  basic_auth_password: '',
  oauth2_authenticated: false,
}
export function McpSessionManager({ serverId }: McpSessionManagerProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [editSession, setEditSession] = useState<McpSession | null>(null)
  const [form, setForm] = useState<SessionForm>(defaultForm)

  const { data: sessions, isLoading, error } = useQuery<McpSession[]>({
    queryKey: ['mcp', 'servers', serverId, 'sessions'],
    queryFn: async () => {
      const { data } = await apiClient.get<McpSession[]>(`/mcp/servers/${serverId}/sessions`)
      return data
    },
    enabled: !!serverId,
  })

  const handleOpenCreate = () => {
    setEditSession(null)
    setForm(defaultForm)
    setDialogError(null)
    setDialogOpen(true)
  }

  const handleOpenEdit = (session: McpSession) => {
    setEditSession(session)
    setForm({
      name: session.name,
      description: session.description ?? '',
      auth_type: session.auth_type,
      // Never pre-populate credentials for security
      api_key_value: '',
      bearer_token_value: '',
      basic_auth_username: '',
      basic_auth_password: '',
      oauth2_authenticated: false,
    })
    setDialogError(null)
    setDialogOpen(true)
  }

  const buildCredentials = (): Record<string, unknown> | null => {
    switch (form.auth_type) {
      case 'api_key':
        return form.api_key_value.trim() ? { api_key: form.api_key_value.trim() } : null
      case 'bearer_token':
        return form.bearer_token_value.trim() ? { token: form.bearer_token_value.trim() } : null
      case 'basic_auth':
        if (form.basic_auth_username.trim() && form.basic_auth_password) {
          const encoded = btoa(`${form.basic_auth_username}:${form.basic_auth_password}`)
          return {
            username: form.basic_auth_username.trim(),
            password: form.basic_auth_password,
            encoded: encoded,
          }
        }
        return null
      case 'oauth2':
        // For OAuth2, credentials are set via popup flow, not here
        return null
      case 'none':
      default:
        return null
    }
  }

  const handleOAuthAuthenticate = async () => {
    try {
      setDialogError(null)
      
      // Get OAuth authorization URL from backend
      const { data } = await apiClient.post<{ authorization_url: string }>(
        `/mcp/servers/${serverId}/oauth/authorize`,
        {
          session_name: form.name,
          session_description: form.description,
        }
      )
      
      // Open popup for OAuth
      const popup = window.open(
        data.authorization_url,
        'mcpOAuth',
        'width=600,height=700,menubar=no,toolbar=no,location=yes,status=no'
      )
      
      // Listen for OAuth callback
      const handleMessage = async (event: MessageEvent) => {
        if (event.origin !== window.location.origin) return
        
        if (event.data?.type === 'MCP_OAUTH_SUCCESS') {
          window.removeEventListener('message', handleMessage)
          // OAuth successful - session was created on backend
          setDialogOpen(false)
          await queryClient.invalidateQueries({ queryKey: ['mcp', 'servers', serverId, 'sessions'] })
          popup?.close()
        } else if (event.data?.type === 'MCP_OAUTH_ERROR') {
          window.removeEventListener('message', handleMessage)
          const desc = event.data.errorDescription ?? event.data.error ?? 'OAuth authentication failed'
          setDialogError(new Error(desc))
          popup?.close()
        }
      }
      
      window.addEventListener('message', handleMessage)
      
      // Cleanup if popup is closed without completing
      const checkPopup = setInterval(() => {
        if (popup?.closed) {
          clearInterval(checkPopup)
          window.removeEventListener('message', handleMessage)
        }
      }, 500)
    } catch (err) {
      setDialogError(err)
    }
  }

  const handleSave = async () => {
    try {
      setDialogError(null)
      const payload: Record<string, unknown> = {
        name: form.name,
        description: form.description || null,
        auth_type: form.auth_type,
        credentials: buildCredentials(),
      }
      if (editSession) {
        await apiClient.put(`/mcp/servers/${serverId}/sessions/${editSession.id}`, payload)
      } else {
        await apiClient.post(`/mcp/servers/${serverId}/sessions`, payload)
      }
      setDialogOpen(false)
      await queryClient.invalidateQueries({ queryKey: ['mcp', 'servers', serverId, 'sessions'] })
    } catch (err) {
      setDialogError(err)
    }
  }

  const handleDelete = async (sessionId: string) => {
    if (confirm(t('app.confirm'))) {
      await apiClient.delete(`/mcp/servers/${serverId}/sessions/${sessionId}`)
      await queryClient.invalidateQueries({ queryKey: ['mcp', 'servers', serverId, 'sessions'] })
    }
  }

  const refreshTokenMutation = useMutation({
    mutationFn: async (sessionId: string) => {
      const { data } = await apiClient.post(`/mcp/servers/${serverId}/sessions/${sessionId}/refresh-token`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mcp', 'servers', serverId, 'sessions'] })
    },
  })

  const getTokenStatus = (session: McpSession): { label: string; color: 'success' | 'warning' | 'error'; icon: React.ReactElement | undefined } => {
    if (session.auth_type !== 'oauth2') {
      return { label: 'N/A', color: 'success', icon: undefined }
    }

    if (!session.oauth_expires_at) {
      return { label: t('mcp.sessions.tokenStatusUnknown'), color: 'warning', icon: <WarningIcon fontSize="small" /> }
    }

    const now = new Date()
    const expiresAt = new Date(session.oauth_expires_at)
    const hoursUntilExpiry = (expiresAt.getTime() - now.getTime()) / (1000 * 60 * 60)

    if (hoursUntilExpiry < 0) {
      return { label: t('mcp.sessions.tokenExpired'), color: 'error', icon: <WarningIcon fontSize="small" /> }
    } else if (hoursUntilExpiry < 1) {
      return { label: t('mcp.sessions.tokenExpiringSoon'), color: 'warning', icon: <WarningIcon fontSize="small" /> }
    } else {
      const expiryText = hoursUntilExpiry < 24
        ? `${Math.floor(hoursUntilExpiry)}h`
        : `${Math.floor(hoursUntilExpiry / 24)}d`
      return { label: t('mcp.sessions.tokenValid', { time: expiryText }), color: 'success', icon: <CheckCircleIcon fontSize="small" /> }
    }
  }

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h6">{t('mcp.sessions.title')}</Typography>
        <Button variant="contained" size="small" startIcon={<AddIcon />} onClick={handleOpenCreate}>
          {t('mcp.sessions.create')}
        </Button>
      </Box>

      {error && <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />}

      {isLoading ? (
        <CircularProgress size={24} />
      ) : (
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t('app.name')}</TableCell>
                <TableCell>{t('mcp.sessions.authType')}</TableCell>
                <TableCell>{t('mcp.sessions.tokenStatus')}</TableCell>
                <TableCell>{t('app.status')}</TableCell>
                <TableCell>{t('app.actions')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(sessions ?? []).map((s) => {
                const tokenStatus = getTokenStatus(s)
                return (
                  <TableRow key={s.id}>
                    <TableCell>
                      <Typography variant="body2" fontWeight={500}>{s.name}</Typography>
                      {s.description && (
                        <Typography variant="caption" color="text.secondary">{s.description}</Typography>
                      )}
                    </TableCell>
                    <TableCell><code>{s.auth_type}</code></TableCell>
                    <TableCell>
                      {s.auth_type === 'oauth2' ? (
                        <Chip
                          label={tokenStatus.label}
                          color={tokenStatus.color}
                          size="small"
                          icon={tokenStatus.icon}
                        />
                      ) : (
                        <Typography variant="body2" color="text.secondary">—</Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={s.is_active ? t('app.active') : t('app.inactive')}
                        color={s.is_active ? 'success' : 'default'}
                        size="small"
                      />
                    </TableCell>
                    <TableCell>
                      {s.auth_type === 'oauth2' && (
                        <IconButton
                          size="small"
                          onClick={() => refreshTokenMutation.mutate(s.id)}
                          disabled={refreshTokenMutation.isPending}
                          title={t('mcp.sessions.refreshToken')}
                        >
                          <RefreshIcon fontSize="small" />
                        </IconButton>
                      )}
                      <IconButton size="small" onClick={() => handleOpenEdit(s)}>
                        <EditIcon fontSize="small" />
                      </IconButton>
                      <IconButton size="small" onClick={() => handleDelete(s.id)}>
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </TableCell>
                  </TableRow>
                )
              })}
              {(sessions ?? []).length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} align="center">{t('app.noData')}</TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Dialog open={dialogOpen} onClose={() => { setDialogOpen(false); setDialogError(null) }} maxWidth="sm" fullWidth>
        <DialogTitle>{editSession ? t('mcp.sessions.edit') : t('mcp.sessions.create')}</DialogTitle>
        <DialogContent>
          {dialogError != null && <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />}
          <Box display="flex" flexDirection="column" gap={2} mt={1}>
            <TextField
              label={t('app.name')}
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              fullWidth
              required
            />
            <TextField
              label={t('app.description')}
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              fullWidth
              multiline
              rows={2}
            />
            <FormControl fullWidth>
              <InputLabel>{t('mcp.sessions.authType')}</InputLabel>
              <Select
                value={form.auth_type}
                label={t('mcp.sessions.authType')}
                onChange={(e) => setForm((f) => ({ ...f, auth_type: e.target.value as McpSessionAuthType }))}
              >
                {AUTH_TYPES.map((at) => (
                  <MenuItem key={at} value={at}>{at}</MenuItem>
                ))}
              </Select>
            </FormControl>

            {/* Credentials based on auth type */}
            {form.auth_type === 'api_key' && (
              <TextField
                label={t('mcp.sessions.apiKey')}
                value={form.api_key_value}
                onChange={(e) => setForm((f) => ({ ...f, api_key_value: e.target.value }))}
                fullWidth
                type="password"
                placeholder="sk-..."
                helperText={t('mcp.sessions.apiKeyHint')}
              />
            )}

            {form.auth_type === 'bearer_token' && (
              <TextField
                label={t('mcp.sessions.bearerToken')}
                value={form.bearer_token_value}
                onChange={(e) => setForm((f) => ({ ...f, bearer_token_value: e.target.value }))}
                fullWidth
                type="password"
                placeholder="eyJ..."
                helperText={t('mcp.sessions.bearerTokenHint')}
              />
            )}

            {form.auth_type === 'basic_auth' && (
              <>
                <TextField
                  label={t('mcp.sessions.username')}
                  value={form.basic_auth_username}
                  onChange={(e) => setForm((f) => ({ ...f, basic_auth_username: e.target.value }))}
                  fullWidth
                  autoComplete="username"
                />
                <TextField
                  label={t('mcp.sessions.password')}
                  value={form.basic_auth_password}
                  onChange={(e) => setForm((f) => ({ ...f, basic_auth_password: e.target.value }))}
                  fullWidth
                  type="password"
                  autoComplete="current-password"
                  helperText={t('mcp.sessions.basicAuthHint')}
                />
              </>
            )}

            {form.auth_type === 'oauth2' && (
              <>
                <Typography variant="body2" color="text.secondary">
                  {t('mcp.sessions.oauthInstructions')}
                </Typography>
                <Box display="flex" gap={2} alignItems="center">
                  <Button
                  variant="contained"
                  startIcon={<LoginIcon />}
                  onClick={handleOAuthAuthenticate}
                  size="large"
                  fullWidth
                >
                  {t('mcp.sessions.authenticateWithOAuth')}
                </Button>
                </Box>
                <Typography variant="caption" color="text.secondary">
                  {t('mcp.sessions.oauthNote')}
                </Typography>
              </>
            )}

            {form.auth_type === 'none' && (
              <Typography variant="body2" color="text.secondary">
                {t('mcp.sessions.noAuthRequired')}
              </Typography>
            )}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setDialogOpen(false); setDialogError(null) }}>{t('app.cancel')}</Button>
          <Button variant="contained" onClick={handleSave}>{t('app.save')}</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

