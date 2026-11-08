import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  IconButton,
  Paper,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import SyncIcon from '@mui/icons-material/Sync'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import StorageIcon from '@mui/icons-material/Storage'
import { usePagination } from '../../hooks/usePagination'
import { useMcpServers, useSyncServer, useServerTools } from '../../hooks/useMcpServers'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { McpSessionManager } from './McpSessionManager'
import { McpToolBrowser } from './McpToolBrowser'
import apiClient from '../../api/apiClient'
import { isReservedServerName, isControlCenterServer } from '../../utils/toolNaming'
import { useQueryClient } from '@tanstack/react-query'
import type { McpServer } from '../../types'

const SLUG_PATTERN = /^[a-z0-9-]+$/
const SYSTEM_SERVER_ID = '00000000-0000-0000-0000-000000000001'

type ServerDialogTab = 'details' | 'tools'

/**
 * Tools tab inside the add/update server dialog. For a saved server it
 * lists that server's tools (GET /mcp/servers/{id}/tools) and offers a
 * "Load Tools" action that runs the same sync endpoint as the row-level
 * sync button, then refreshes the list. Errors surface through the
 * dialog's dialogError + PermissionDeniedAlert pattern via onError.
 */
function ServerToolsPanel({
  serverId,
  onError,
}: {
  serverId: string | null
  onError: (err: unknown) => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: tools, isLoading, refetch } = useServerTools(serverId ?? '')
  const [syncing, setSyncing] = useState(false)

  const handleLoadTools = async () => {
    if (!serverId) return
    setSyncing(true)
    onError(null)
    try {
      await apiClient.post(`/mcp/servers/${serverId}/sync`)
      await queryClient.invalidateQueries({ queryKey: ['mcp', 'servers', serverId, 'tools'] })
      await refetch()
    } catch (err) {
      onError(err)
    } finally {
      setSyncing(false)
    }
  }

  return (
    <Box display="flex" flexDirection="column" gap={2} mt={1}>
      <Box display="flex" justifyContent="flex-end">
        <Button
          variant="outlined"
          startIcon={<SyncIcon data-testid="LoadToolsSyncIcon" />}
          onClick={handleLoadTools}
          disabled={!serverId || syncing}
        >
          {t('mcp.dialog.loadTools')}
        </Button>
      </Box>

      {!serverId && <Alert severity="info">{t('mcp.dialog.saveFirstHint')}</Alert>}

      {serverId && isLoading && <CircularProgress size={24} />}

      {serverId && !isLoading && (tools ?? []).length === 0 && (
        <Typography color="text.secondary">{t('mcp.dialog.noTools')}</Typography>
      )}

      {serverId && (tools ?? []).length > 0 && (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t('app.name')}</TableCell>
                <TableCell>{t('app.description')}</TableCell>
                <TableCell>{t('app.status')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(tools ?? []).map((tool) => (
                <TableRow key={tool.id}>
                  <TableCell sx={{ whiteSpace: 'nowrap' }}><code>{tool.name}</code></TableCell>
                  <TableCell>
                    <Typography variant="caption" sx={{ wordBreak: 'break-word' }}>{tool.description ?? '—'}</Typography>
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={tool.is_active ? t('app.active') : t('app.inactive')}
                      color={tool.is_active ? 'success' : 'default'}
                      size="small"
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Box>
  )
}

/**
 * MCP Hub management page — Servers tab and Tool Repository tab.
 */
export function McpHubPage() {
  const { t } = useTranslation()
  const pag = usePagination()
  const { data: servers, isLoading, error } = useMcpServers(pag.limit, pag.offset)
  const syncServer = useSyncServer()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<'servers' | 'tools'>('servers')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [editServer, setEditServer] = useState<McpServer | null>(null)
  const [form, setForm] = useState({ slug: '', base_url: '', description: '' })
  const [sessionServerId, setSessionServerId] = useState<string | null>(null)
  const [syncWarnings, setSyncWarnings] = useState<string | null>(null)
  const [dialogTab, setDialogTab] = useState<ServerDialogTab>('details')
  // True when the dialog was opened read-only (e.g. from a tool row click in
  // the Tool Repository tab) — the Save action is hidden in this mode.
  const [dialogViewOnly, setDialogViewOnly] = useState(false)
  // FIX-20261101-014511: surfaces 403s from row-level actions (e.g. mutating
  // the protected Control Center entity without integration::control_center:
  // manage) via the standard PermissionDeniedAlert — never a silent failure.
  const [actionError, setActionError] = useState<unknown>(null)
  const invalidSlug = !!form.slug && !SLUG_PATTERN.test(form.slug)

  const handleOpenCreate = () => {
    setEditServer(null)
    setForm({ slug: '', base_url: '', description: '' })
    setDialogError(null)
    setDialogTab('details')
    setDialogViewOnly(false)
    setDialogOpen(true)
  }

  const handleOpenEdit = (server: McpServer) => {
    setEditServer(server)
    setForm({ slug: server.slug, base_url: server.base_url, description: server.description ?? '' })
    setDialogError(null)
    setDialogTab('details')
    setDialogViewOnly(false)
    setDialogOpen(true)
  }

  // Opened when a server row in the servers table is clicked —
  // view-only mode, Details tab selected by default.
  const handleOpenView = (server: McpServer) => {
    setEditServer(server)
    setForm({ slug: server.slug, base_url: server.base_url, description: server.description ?? '' })
    setDialogError(null)
    setDialogTab('details')
    setDialogViewOnly(true)
    setDialogOpen(true)
  }

  const closeDialog = () => {
    setDialogOpen(false)
    setDialogError(null)
    setDialogTab('details')
    setDialogViewOnly(false)
  }

  const handleSave = async () => {
    try {
      setDialogError(null)
      if (!SLUG_PATTERN.test(form.slug)) {
        setDialogError(new Error('Server slug must use lowercase letters, numbers, and hyphens only'))
        return
      }
      const payload = { ...form, name: form.slug }
      if (editServer) {
        await apiClient.put(`/mcp/servers/${editServer.id}`, payload)
      } else {
        await apiClient.post('/mcp/servers', payload)
      }
      setDialogOpen(false)
      await queryClient.invalidateQueries({ queryKey: ['mcp', 'servers'] })
    } catch (err) {
      setDialogError(err)
    }
  }

  const handleDelete = async (id: string) => {
    if (confirm(t('app.confirm'))) {
      try {
        setActionError(null)
        await apiClient.delete(`/mcp/servers/${id}`)
        await queryClient.invalidateQueries({ queryKey: ['mcp', 'servers'] })
      } catch (err) {
        setActionError(err)
      }
    }
  }

  const isSystemServer = (server: McpServer) => server.id === SYSTEM_SERVER_ID

  const statusColor = (status: string) => {
    if (status === 'active') return 'success'
    if (status === 'error') return 'error'
    return 'default'
  }

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h4" fontWeight={700}>{t('mcp.title')}</Typography>
        {activeTab === 'servers' && (
          <Button variant="contained" startIcon={<AddIcon />} onClick={handleOpenCreate}>
            {t('mcp.registerServer')}
          </Button>
        )}
      </Box>

      <Tabs value={activeTab} onChange={(_e, v: 'servers' | 'tools') => setActiveTab(v)} sx={{ mb: 2 }}>
        <Tab value="servers" label={t('mcp.tabs.servers')} />
        <Tab value="tools" label={t('mcp.tabs.toolRepository')} />
      </Tabs>

      {activeTab === 'servers' && (
        <>
          {isLoading && <CircularProgress />}
          {error && <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />}
          {actionError && (
            <PermissionDeniedAlert error={actionError} fallbackMessage={t('app.error')} />
          )}

          {/* System entry contextual info banner */}
          {!error && (
            <TableContainer component={Paper}>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>{t('mcp.slug')}</TableCell>
                    <TableCell>{t('mcp.baseUrl')}</TableCell>
                    <TableCell>{t('app.status')}</TableCell>
                    <TableCell>{t('mcp.servers.sessions')}</TableCell>
                    <TableCell>{t('mcp.lastSynced')}</TableCell>
                    <TableCell>{t('app.actions')}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(servers ?? []).map((server) => {
                    // Reserved namespaces (system, decision) are built-in
                    // virtual servers — no base URL, sessions, sync, or edit.
                    const isSystem = isSystemServer(server) || isReservedServerName(server.slug)
                    // Control Center entity (cc) — a protected integration:
                    // visible only to roles granted the entity-view
                    // permission (the API omits it otherwise).
                    const isCc = isControlCenterServer(server.slug)
                    // FIX-20261101-090438: cc is system-managed & sessionless
                    // — prefer the API flag, fall back to the slug.
                    const systemManaged =
                      server.is_system_managed === true || isCc
                    const aboutTitle = server.slug === 'decision' ? t('mcp.decision.aboutTitle') : t('mcp.system.aboutTitle')
                    const aboutBody = server.slug === 'decision' ? t('mcp.decision.aboutBody') : t('mcp.system.aboutBody')
                    return (
                    <TableRow
                      key={server.id}
                      hover
                      tabIndex={0}
                      role="button"
                      aria-label={`${server.slug} — ${t('mcp.servers.openServerDetails')}`}
                      onClick={() => handleOpenView(server)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          handleOpenView(server)
                        }
                      }}
                      sx={{ cursor: 'pointer' }}
                    >
                      <TableCell>
                        <Box display="flex" alignItems="center" gap={1}>
                          <code>{server.slug}</code>
                          {isSystem && (
                            <Tooltip title={
                              <Box>
                                <Typography variant="subtitle2">{aboutTitle}</Typography>
                                <Typography variant="body2">{aboutBody}</Typography>
                              </Box>
                            } arrow placement="top">
                              <Chip label={t('mcp.system.builtIn')} color="error" size="small" variant="outlined" />
                            </Tooltip>
                          )}
                          {isCc && (
                            <Tooltip title={t('mcp.controlCenter.tooltip')} arrow placement="top">
                              <Chip label={t('mcp.controlCenter.chip')} color="warning" size="small" variant="outlined" />
                            </Tooltip>
                          )}
                        </Box>
                      </TableCell>
                      <TableCell sx={{ maxWidth: 240 }}>
                        <Tooltip title={server.base_url || ''} arrow placement="top">
                          <Typography
                            noWrap
                            component="span"
                            variant="body2"
                            sx={{ display: 'block', maxWidth: 240 }}
                          >
                            {isSystem ? '—' : server.base_url}
                          </Typography>
                        </Tooltip>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={server.status}
                          color={statusColor(server.status) as 'success' | 'error' | 'default'}
                          size="small"
                        />
                      </TableCell>
                      <TableCell>
                        {isSystem || systemManaged ? '—' : (server.session_count ?? 0)}
                      </TableCell>
                      <TableCell>
                        {server.last_synced_at
                          ? new Date(server.last_synced_at).toLocaleString()
                          : '—'}
                      </TableCell>
                      <TableCell onClick={(e) => e.stopPropagation()}>
                        {/* Session management button — hidden for system-managed entities (cc has NO sessions) */}
                        {!isSystem && !systemManaged && (
                          <Tooltip title={t('mcp.manageSessions')}>
                            <IconButton size="small" onClick={() => setSessionServerId(server.id)}>
                              <StorageIcon />
                            </IconButton>
                          </Tooltip>
                        )}
                        {/* Sync button — disabled for system-managed entities */}
                        {isSystem || systemManaged ? (
                          <Tooltip title={isCc ? t('mcp.controlCenter.systemManaged') : t('mcp.system.systemManaged')}>
                            <span>
                              <IconButton size="small" disabled>
                                <SyncIcon data-testid="SyncIcon" />
                              </IconButton>
                            </span>
                          </Tooltip>
                        ) : (server.session_count ?? 0) === 0 ? (
                          <Tooltip title={t('mcp.sync.noSessions')}>
                            <span>
                              <IconButton size="small" disabled>
                                <SyncIcon data-testid="SyncIcon" />
                              </IconButton>
                            </span>
                          </Tooltip>
                        ) : (
                          <Tooltip title={t('mcp.syncNow')}>
                            <IconButton
                              size="small"
                              onClick={() => {
                                setSyncWarnings(null)
                                setActionError(null)
                                syncServer.mutate(server.id, {
                                  onSuccess: (result) => {
                                    if (result.warnings && result.warnings.length > 0) {
                                      setSyncWarnings(result.warnings.join('; '))
                                    }
                                  },
                                  onError: (err) => setActionError(err),
                                })
                              }}
                              disabled={syncServer.isPending && syncServer.variables === server.id}
                            >
                              <SyncIcon data-testid="SyncIcon" />
                            </IconButton>
                          </Tooltip>
                        )}
                        {/* Edit/Delete — hidden for system-managed entities */}
                        {isSystem || systemManaged ? (
                          <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                            {isCc ? t('mcp.controlCenter.systemManaged') : t('mcp.system.systemManaged')}
                          </Typography>
                        ) : (
                          <>
                            <IconButton size="small" onClick={() => handleOpenEdit(server)}>
                              <EditIcon />
                            </IconButton>
                            <IconButton size="small" onClick={() => handleDelete(server.id)}>
                              <DeleteIcon />
                            </IconButton>
                          </>
                        )}
                      </TableCell>
                    </TableRow>
                  )})}
                  {(servers ?? []).length === 0 && (
                    <TableRow>
                      <TableCell colSpan={7} align="center">{t('app.noData')}</TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          )}

          {/* Sync warnings display */}
          {syncWarnings && (
            <Alert severity="warning" sx={{ mt: 2 }} onClose={() => setSyncWarnings(null)}>
              {t('mcp.sync.warnings')}: {syncWarnings}
            </Alert>
          )}

          {!isLoading && !error && (
            <TablePagination
              component="div"
              count={-1}
              page={pag.page}
              onPageChange={pag.onPageChange}
              rowsPerPage={pag.rowsPerPage}
              onRowsPerPageChange={pag.onRowsPerPageChange}
              rowsPerPageOptions={pag.rowsPerPageOptions}
              labelRowsPerPage={t('app.rowsPerPage')}
            />
          )}
        </>
      )}

      {activeTab === 'tools' && <McpToolBrowser />}

      {/* Sessions Dialog */}
      <Dialog
        open={!!sessionServerId}
        onClose={() => setSessionServerId(null)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>{t('mcp.sessions.title')}</DialogTitle>
        <DialogContent>
          {sessionServerId && <McpSessionManager serverId={sessionServerId} />}
        </DialogContent>
      </Dialog>

      {/* Create/Edit/View Server Dialog — responsive width (wider when the
          screen allows, capped at the md breakpoint) for readable tool lists */}
      <Dialog open={dialogOpen} onClose={closeDialog} maxWidth="md" fullWidth>
        <DialogTitle>
          {dialogViewOnly
            ? t('mcp.dialog.viewServerTitle')
            : editServer ? t('mcp.editServer') : t('mcp.registerServer')}
        </DialogTitle>
        <DialogContent>
          {dialogError ? <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} /> : null}
          <Tabs
            value={dialogTab}
            onChange={(_e, v: ServerDialogTab) => setDialogTab(v)}
            sx={{ mb: 1 }}
          >
            <Tab value="details" label={t('mcp.dialog.tabs.details')} />
            <Tab value="tools" label={t('mcp.dialog.tabs.tools')} />
          </Tabs>

          {dialogTab === 'tools' ? (
            <ServerToolsPanel serverId={editServer?.id ?? null} onError={setDialogError} />
          ) : (
            <Box display="flex" flexDirection="column" gap={2} mt={1}>
              <TextField
                label={t('mcp.slug')}
                value={form.slug}
                onChange={(e) => setForm((f) => ({ ...f, slug: e.target.value }))}
                fullWidth
                disabled={!!editServer}
                error={invalidSlug}
                helperText={invalidSlug ? 'Lowercase letters, numbers, hyphens only' : undefined}
              />
              <TextField
                label={t('mcp.baseUrl')}
                value={form.base_url}
                onChange={(e) => setForm((f) => ({ ...f, base_url: e.target.value }))}
                fullWidth
              />
              <TextField
                label={t('app.description')}
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                fullWidth
                multiline
                rows={2}
              />
            </Box>
          )}
        </DialogContent>
        <Box display="flex" justifyContent="flex-end" gap={1} p={2} pt={0}>
          <Button onClick={closeDialog}>{t('app.cancel')}</Button>
          {!dialogViewOnly && (
            <Button
              variant="contained"
              onClick={handleSave}
              disabled={invalidSlug}
            >
              {t('app.save')}
            </Button>
          )}
        </Box>
      </Dialog>
    </Box>
  )
}
