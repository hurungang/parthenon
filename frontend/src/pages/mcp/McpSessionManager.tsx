import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  IconButton,
  InputLabel,
  MenuItem,
  Radio,
  Select,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import LoginIcon from '@mui/icons-material/Login'
import RefreshIcon from '@mui/icons-material/Refresh'
import WarningIcon from '@mui/icons-material/Warning'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import StarIcon from '@mui/icons-material/Star'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import type { McpSession, McpSessionAuthType } from '../../types'

interface McpSessionManagerProps {
  serverId: string
}

const AUTH_TYPES: McpSessionAuthType[] = ['api_key', 'bearer_token', 'basic_auth', 'oauth2', 'none', 'passthrough']

const AUTH_TYPE_LABELS: Record<McpSessionAuthType, string> = {
  api_key: 'mcp.sessions.authTypeApiKey',
  bearer_token: 'mcp.sessions.authTypeBearerToken',
  basic_auth: 'mcp.sessions.authTypeBasicAuth',
  oauth2: 'mcp.sessions.authTypeOAuth2',
  none: 'mcp.sessions.authTypeNone',
  passthrough: 'mcp.sessions.authTypePassthrough',
}

const AUTH_TYPE_DESCS: Record<McpSessionAuthType, string> = {
  api_key: 'mcp.sessions.authTypeApiKeyDesc',
  bearer_token: 'mcp.sessions.authTypeBearerTokenDesc',
  basic_auth: 'mcp.sessions.authTypeBasicAuthDesc',
  oauth2: 'mcp.sessions.authTypeOAuth2Desc',
  none: 'mcp.sessions.authTypeNoneDesc',
  passthrough: 'mcp.sessions.authTypePassthroughDesc',
}

interface SessionForm {
  name: string
  description: string
  auth_type: McpSessionAuthType
  is_active: boolean
  // Simplified credential fields
  api_key_value: string
  bearer_token_value: string
  basic_auth_username: string
  basic_auth_password: string
  oauth2_authenticated: boolean
  // OAuth2 manual config (optional — used when server has no pre-configured OAuth)
  oauth_metadata_url: string
  oauth_authorization_url: string
  oauth_token_url: string
  oauth_client_id: string
  oauth_client_secret: string
  oauth_scope: string
  // API key option: send as Bearer token instead of X-API-Key
  api_key_as_bearer: boolean
}

const defaultForm: SessionForm = {
  name: '',
  description: '',
  auth_type: 'api_key',
  is_active: true,
  api_key_value: '',
  bearer_token_value: '',
  basic_auth_username: '',
  basic_auth_password: '',
  oauth2_authenticated: false,
  oauth_metadata_url: '',
  oauth_authorization_url: '',
  oauth_token_url: '',
  oauth_client_id: '',
  oauth_client_secret: '',
  oauth_scope: '',
  api_key_as_bearer: false,
}

const extractError = (err: unknown): string => {
  if (err && typeof err === 'object' && 'response' in err) {
    const axiosErr = err as { response?: { data?: { detail?: string } } }
    return axiosErr.response?.data?.detail ?? String(err)
  }
  if (err instanceof Error) return err.message
  return String(err)
}

export function McpSessionManager({ serverId }: McpSessionManagerProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [editSession, setEditSession] = useState<McpSession | null>(null)
  const [form, setForm] = useState<SessionForm>(defaultForm)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [autoDiscovery, setAutoDiscovery] = useState(true)

  const { data: sessions, isLoading, error } = useQuery<McpSession[]>({
    queryKey: ['mcp', 'servers', serverId, 'sessions'],
    queryFn: async () => {
      const { data } = await apiClient.get<McpSession[]>(`/mcp/servers/${serverId}/sessions`)
      return data
    },
    enabled: !!serverId,
  })

  // Set-default mutation
  const setDefaultMutation = useMutation({
    mutationFn: async (sessionId: string) => {
      await apiClient.put(`/mcp/servers/${serverId}/sessions/${sessionId}`, { is_default: true })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mcp', 'servers', serverId, 'sessions'] })
      queryClient.invalidateQueries({ queryKey: ['mcp', 'servers'] })
    },
    onError: (err) => {
      setDeleteError(extractError(err))
    },
  })

  const sessionCount = sessions?.length ?? 0
  const isAutoDefault = sessionCount === 1

  const handleOpenCreate = () => {
    setEditSession(null)
    setForm(defaultForm)
    setDialogError(null)
    setAutoDiscovery(true)
    setDialogOpen(true)
  }

  const handleOpenEdit = (session: McpSession) => {
    setEditSession(session)
    // Determine if this session has stored credentials (has cred config or is non-passthrough with encrypted_creds)
    const hasCreds = session.auth_type !== 'none' && session.auth_type !== 'passthrough'
    setForm({
      name: session.name,
      description: session.description ?? '',
      auth_type: session.auth_type,
      is_active: session.is_active,
      // Show placeholder for existing credentials; empty = no change, non-empty = update
      api_key_value: hasCreds && session.auth_type === 'api_key' ? '__saved__' : '',
      bearer_token_value: hasCreds && session.auth_type === 'bearer_token' ? '__saved__' : '',
      basic_auth_username: hasCreds && session.auth_type === 'basic_auth' ? '__saved__' : '',
      basic_auth_password: hasCreds && session.auth_type === 'basic_auth' ? '__saved__' : '',
      oauth2_authenticated: false,
      oauth_metadata_url: '',
      oauth_authorization_url: '',
      oauth_token_url: '',
      oauth_client_id: '',
      oauth_client_secret: '',
      oauth_scope: '',
      api_key_as_bearer: false,
    })
    setDialogError(null)
    setDialogOpen(true)
  }

  const buildCredentials = (): Record<string, unknown> | null => {
    switch (form.auth_type) {
      case 'api_key':
        if (form.api_key_value === '__saved__') return null  // keep existing
        if (!form.api_key_value.trim()) return null
        if (form.api_key_as_bearer) {
          return { api_key: form.api_key_value.trim(), as_bearer: true }
        }
        return { api_key: form.api_key_value.trim() }
      case 'bearer_token':
        if (form.bearer_token_value === '__saved__') return null  // keep existing
        return form.bearer_token_value.trim() ? { token: form.bearer_token_value.trim() } : null
      case 'basic_auth':
        if (form.basic_auth_username === '__saved__') return null  // keep existing
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
      case 'passthrough':
      default:
        return null
    }
  }

  const handleOAuthAuthenticate = async () => {
    try {
      setDialogError(null)

      // Get OAuth authorization URL from backend
      const body: Record<string, unknown> = {
        session_name: form.name,
        session_description: form.description,
      }
      if (form.oauth_metadata_url) body.metadata_url = form.oauth_metadata_url
      if (form.oauth_authorization_url) body.authorization_url = form.oauth_authorization_url
      if (form.oauth_token_url) body.token_url = form.oauth_token_url
      if (form.oauth_client_id) body.client_id = form.oauth_client_id
      if (form.oauth_client_secret) body.client_secret = form.oauth_client_secret
      if (form.oauth_scope) body.scope = form.oauth_scope
      const { data } = await apiClient.post<{ authorization_url: string }>(
        `/mcp/servers/${serverId}/oauth/authorize`,
        body
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
      const creds = form.auth_type === 'passthrough' ? null : buildCredentials()
      const payload: Record<string, unknown> = {
        name: form.name,
        description: form.description || null,
        auth_type: form.auth_type,
        is_active: form.is_active,
        // Passthrough sessions never include credentials
        credentials: creds,
      }
      if (editSession) {
        await apiClient.put(`/mcp/servers/${serverId}/sessions/${editSession.id}`, payload)
      } else {
        await apiClient.post(`/mcp/servers/${serverId}/sessions`, payload)
      }
      setDialogOpen(false)
      await queryClient.invalidateQueries({ queryKey: ['mcp', 'servers', serverId, 'sessions'] })
      await queryClient.invalidateQueries({ queryKey: ['mcp', 'servers'] })
    } catch (err) {
      setDialogError(err)
    }
  }

  const handleDelete = async (session: McpSession) => {
    setDeleteError(null)
    // Block deletion of default session when other sessions exist
    if (session.is_default && sessionCount > 1) {
      setDeleteError(t('mcp.sessions.deleteDefaultBlocked'))
      return
    }
    if (confirm(t('app.confirm'))) {
      try {
        await apiClient.delete(`/mcp/servers/${serverId}/sessions/${session.id}`)
        await queryClient.invalidateQueries({ queryKey: ['mcp', 'servers', serverId, 'sessions'] })
        await queryClient.invalidateQueries({ queryKey: ['mcp', 'servers'] })
        setDeleteError(null)
      } catch (err) {
        setDeleteError(extractError(err))
      }
    }
  }

  const handleSetDefault = (session: McpSession) => {
    if (session.is_default) return // Already default
    if (isAutoDefault) return // Cannot change auto-default on sole session
    setDefaultMutation.mutate(session.id)
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

  /** Returns true if the OAuth refresh token is still valid (not expired). */
  const isRefreshTokenValid = (session: McpSession): boolean => {
    if (!session.oauth_refresh_expires_at) return false
    return new Date(session.oauth_refresh_expires_at) > new Date()
  }

  /** Triggers the OAuth re-authorization popup flow for an existing session. */
  const handleSessionReauth = async (session: McpSession) => {
    try {
      const { data } = await apiClient.post<{ authorization_url: string }>(
        `/mcp/servers/${serverId}/oauth/authorize`,
        { session_name: session.name, session_description: session.description }
      )
      const popup = window.open(
        data.authorization_url,
        'mcpReauth',
        'width=600,height=700,menubar=no,toolbar=no,location=yes,status=no'
      )
      const handleMessage = async (event: MessageEvent) => {
        if (event.origin !== window.location.origin) return
        if (event.data?.type === 'MCP_OAUTH_SUCCESS') {
          window.removeEventListener('message', handleMessage)
          popup?.close()
          await queryClient.invalidateQueries({ queryKey: ['mcp', 'servers', serverId, 'sessions'] })
        }
      }
      window.addEventListener('message', handleMessage)
      const check = setInterval(() => {
        if (popup?.closed) {
          clearInterval(check)
          window.removeEventListener('message', handleMessage)
        }
      }, 500)
    } catch {
      // Reauth initiation failed
    }
  }

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

      {/* Delete error display */}
      {deleteError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setDeleteError(null)}>
          {deleteError}
        </Alert>
      )}

      {/* Auto-default info alert for sole session */}
      {isAutoDefault && sessions && sessions.length > 0 && (
        <Alert severity="info" icon={<StarIcon />} sx={{ mb: 2 }}>
          {t('mcp.sessions.autoDefaultInfo')} {t('mcp.sessions.autoDefaultAddMore')}
        </Alert>
      )}

      {/* Multi-session default hint */}
      {!isAutoDefault && sessionCount > 1 && (
        <Alert severity="info" icon={<StarIcon />} sx={{ mb: 2 }}>
          {t('mcp.sessions.selectDefaultHint')}
        </Alert>
      )}

      {isLoading ? (
        <CircularProgress size={24} />
      ) : (
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={{ width: 40 }}></TableCell>
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
                const isDefault = s.is_default || isAutoDefault
                return (
                  <TableRow
                    key={s.id}
                  >
                    <TableCell>
                      <Radio
                        checked={isDefault}
                        disabled={isAutoDefault || !s.is_active}
                        size="small"
                        sx={{
                          color: isAutoDefault ? 'violet' : undefined,
                          '&.Mui-disabled': {
                            color: isAutoDefault ? 'violet' : undefined,
                          },
                        }}
                        onClick={() => handleSetDefault(s)}
                      />
                    </TableCell>
                    <TableCell>
                      <Box display="flex" alignItems="center" gap={1}>
                        <Typography variant="body2" fontWeight={500}>{s.name}</Typography>
                        {isDefault && (
                          <Chip
                            label={t('mcp.sessions.default')}
                            color="secondary"
                            size="small"
                            variant="outlined"
                            sx={{ fontSize: '0.65rem', height: 20 }}
                          />
                        )}
                      </Box>
                      {s.description && (
                        <Typography variant="caption" color="text.secondary">{s.description}</Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      {t(AUTH_TYPE_LABELS[s.auth_type])}
                      {s.auth_type === 'passthrough' && (
                        <Chip label={t('mcp.sessions.passthrough')} color="info" size="small" sx={{ ml: 1 }} />
                      )}
                    </TableCell>
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
                      <Tooltip title={!s.is_active ? t('mcp.sessions.inactiveCantDefault') : s.is_default ? '' : t('mcp.sessions.setDefault')}>
                        <span>
                          <IconButton
                            size="small"
                            color={isDefault ? 'secondary' : 'default'}
                            onClick={() => handleSetDefault(s)}
                            disabled={!s.is_active || isDefault}
                          >
                            <StarIcon fontSize="small" />
                          </IconButton>
                        </span>
                      </Tooltip>
                      {s.auth_type === 'oauth2' && (
                        isRefreshTokenValid(s) ? (
                          /* Refresh token is valid — green refresh button */
                          <IconButton
                            size="small"
                            color="success"
                            onClick={(e) => { e.stopPropagation(); refreshTokenMutation.mutate(s.id) }}
                            disabled={refreshTokenMutation.isPending}
                            title={t('mcp.sessions.refreshToken')}
                          >
                            <RefreshIcon fontSize="small" />
                          </IconButton>
                        ) : (
                          /* Refresh token expired or missing — red reauth button */
                          <IconButton
                            size="small"
                            color="error"
                            onClick={(e) => { e.stopPropagation(); handleSessionReauth(s) }}
                            title={t('mcp.sessions.reauthenticate')}
                          >
                            <LoginIcon fontSize="small" />
                          </IconButton>
                        )
                      )}
                      <IconButton size="small" onClick={(e) => { e.stopPropagation(); handleOpenEdit(s) }}>
                        <EditIcon fontSize="small" />
                      </IconButton>
                      <Tooltip
                        title={s.is_default && sessionCount > 1 ? t('mcp.sessions.cannotDeleteDefault') : ''}
                      >
                        <span>
                          <IconButton
                            size="small"
                            onClick={(e) => { e.stopPropagation(); handleDelete(s) }}
                          >
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        </span>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                )
              })}
              {(sessions ?? []).length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} align="center">{t('app.noData')}</TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Default session footer hint */}
      <Box display="flex" alignItems="center" gap={1} mt={2}>
        <StarIcon fontSize="small" color="secondary" />
        <Typography variant="caption" color="text.secondary">
          {t('mcp.sessions.defaultFooterHint')}
        </Typography>
      </Box>

      <Dialog open={dialogOpen} onClose={() => { setDialogOpen(false); setDialogError(null); setAutoDiscovery(true) }} maxWidth="sm" fullWidth>
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
            <Box display="flex" alignItems="center" gap={1}>
              <FormControl fullWidth>
                <InputLabel>{t('mcp.sessions.authType')}</InputLabel>
                <Select
                  value={form.auth_type}
                  label={t('mcp.sessions.authType')}
                  onChange={(e) => setForm((f) => ({ ...f, auth_type: e.target.value as McpSessionAuthType }))}
                >
                  {AUTH_TYPES.map((at) => (
                    <MenuItem key={at} value={at}>{t(AUTH_TYPE_LABELS[at])}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <Tooltip title={t(AUTH_TYPE_DESCS[form.auth_type])} arrow placement="left">
                <IconButton size="small">
                  <InfoOutlinedIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Box>

            <FormControlLabel
              control={
                <Switch
                  checked={form.is_active}
                  onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
                />
              }
              label={form.is_active ? t('app.active') : t('app.inactive')}
            />

            {/* Credentials based on auth type */}
            {form.auth_type === 'api_key' && (
              <>
                <TextField
                  label={t('mcp.sessions.apiKey')}
                  value={form.api_key_value}
                  onChange={(e) => setForm((f) => ({ ...f, api_key_value: e.target.value }))}
                  onFocus={(e) => { if (form.api_key_value === '__saved__') { setForm((f) => ({ ...f, api_key_value: '' })); e.target.value = '' } }}
                  fullWidth
                  type="password"
                  helperText={form.api_key_value === '__saved__' ? t('mcp.sessions.credentialSavedHint') : t('mcp.sessions.apiKeyHint')}
                />
                <FormControlLabel
                  control={
                    <Switch
                      checked={form.api_key_as_bearer}
                      onChange={(e) => setForm((f) => ({ ...f, api_key_as_bearer: e.target.checked }))}
                      size="small"
                    />
                  }
                  label={t('mcp.sessions.apiKeyAsBearer')}
                />
              </>
            )}

            {form.auth_type === 'bearer_token' && (
              <TextField
                label={t('mcp.sessions.bearerToken')}
                value={form.bearer_token_value}
                onChange={(e) => setForm((f) => ({ ...f, bearer_token_value: e.target.value }))}
                onFocus={(e) => { if (form.bearer_token_value === '__saved__') { setForm((f) => ({ ...f, bearer_token_value: '' })); e.target.value = '' } }}
                fullWidth
                type="password"
                helperText={form.bearer_token_value === '__saved__' ? t('mcp.sessions.credentialSavedHint') : t('mcp.sessions.bearerTokenHint')}
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
                <FormControlLabel
                  control={
                    <Switch
                      checked={autoDiscovery}
                      onChange={(e) => setAutoDiscovery(e.target.checked)}
                    />
                  }
                  label={t('mcp.sessions.oauthAutoDiscovery')}
                />
                <Collapse in={!autoDiscovery}>
                  <Box display="flex" flexDirection="column" gap={2} mt={1}>
                    <TextField
                      label={t('mcp.sessions.oauthMetadataUrl')}
                      value={form.oauth_metadata_url}
                      onChange={(e) => setForm((f) => ({ ...f, oauth_metadata_url: e.target.value }))}
                      fullWidth
                      placeholder="https://..."
                      helperText={t('mcp.sessions.oauthMetadataUrlHint')}
                    />
                    <TextField
                      label={t('mcp.sessions.oauthAuthUrl')}
                      value={form.oauth_authorization_url}
                      onChange={(e) => setForm((f) => ({ ...f, oauth_authorization_url: e.target.value }))}
                      fullWidth
                      placeholder="https://..."
                    />
                    <TextField
                      label={t('mcp.sessions.oauthTokenUrl')}
                      value={form.oauth_token_url}
                      onChange={(e) => setForm((f) => ({ ...f, oauth_token_url: e.target.value }))}
                      fullWidth
                      placeholder="https://..."
                    />
                    <TextField
                      label={t('mcp.sessions.oauthClientId')}
                      value={form.oauth_client_id}
                      onChange={(e) => setForm((f) => ({ ...f, oauth_client_id: e.target.value }))}
                      fullWidth
                    />
                    <TextField
                      label={t('mcp.sessions.oauthClientSecret')}
                      value={form.oauth_client_secret}
                      onChange={(e) => setForm((f) => ({ ...f, oauth_client_secret: e.target.value }))}
                      fullWidth
                      type="password"
                    />
                    <TextField
                      label={t('mcp.sessions.oauthScope')}
                      value={form.oauth_scope}
                      onChange={(e) => setForm((f) => ({ ...f, oauth_scope: e.target.value }))}
                      fullWidth
                      placeholder="openid profile"
                    />
                  </Box>
                </Collapse>
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

            {form.auth_type === 'passthrough' && (
              <Alert severity="info">
                {t('mcp.sessions.passthroughInfo')}
              </Alert>
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
