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
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import { usePagination } from '../../hooks/usePagination'
import { useMcpServers, useSyncServer } from '../../hooks/useMcpServers'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { McpSessionManager } from './McpSessionManager'
import { McpToolBrowser } from './McpToolBrowser'
import apiClient from '../../api/apiClient'
import { useQueryClient } from '@tanstack/react-query'
import type { McpServer } from '../../types'

const SLUG_PATTERN = /^[a-z0-9-]+$/
const SYSTEM_SERVER_ID = '00000000-0000-0000-0000-000000000001'

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
  const [form, setForm] = useState({ name: '', slug: '', base_url: '', description: '' })
  const [sessionServerId, setSessionServerId] = useState<string | null>(null)
  const [syncWarnings, setSyncWarnings] = useState<string | null>(null)
  const invalidName = !!form.name && !SLUG_PATTERN.test(form.name)
  const invalidSlug = !!form.slug && !SLUG_PATTERN.test(form.slug)

  const handleOpenCreate = () => {
    setEditServer(null)
    setForm({ name: '', slug: '', base_url: '', description: '' })
    setDialogError(null)
    setDialogOpen(true)
  }

  const handleOpenEdit = (server: McpServer) => {
    setEditServer(server)
    setForm({ name: server.name, slug: server.slug, base_url: server.base_url, description: server.description ?? '' })
    setDialogError(null)
    setDialogOpen(true)
  }

  const handleSave = async () => {
    try {
      setDialogError(null)
      if (!SLUG_PATTERN.test(form.name)) {
        setDialogError(new Error('Server name must use lowercase letters, numbers, and hyphens only'))
        return
      }
      if (!SLUG_PATTERN.test(form.slug)) {
        setDialogError(new Error('Server slug must use lowercase letters, numbers, and hyphens only'))
        return
      }
      if (editServer) {
        await apiClient.put(`/mcp/servers/${editServer.id}`, form)
      } else {
        await apiClient.post('/mcp/servers', form)
      }
      setDialogOpen(false)
      await queryClient.invalidateQueries({ queryKey: ['mcp', 'servers'] })
    } catch (err) {
      setDialogError(err)
    }
  }

  const handleDelete = async (id: string) => {
    if (confirm(t('app.confirm'))) {
      await apiClient.delete(`/mcp/servers/${id}`)
      await queryClient.invalidateQueries({ queryKey: ['mcp', 'servers'] })
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

          {/* System entry contextual info banner */}
          <Box sx={{
            display: 'flex', alignItems: 'flex-start', gap: 1.5,
            p: 1.5, borderRadius: 2, mb: 2.5,
            bgcolor: 'rgba(255,123,114,0.06)',
            border: '1px solid rgba(255,123,114,0.15)',
          }}>
            <InfoOutlinedIcon fontSize="small" sx={{ color: 'text.secondary', mt: 0.2 }} />
            <Box>
              <Typography variant="subtitle2" fontWeight={600}>{t('mcp.system.aboutTitle')}</Typography>
              <Typography variant="body2" color="text.secondary">{t('mcp.system.aboutBody')}</Typography>
            </Box>
          </Box>

          {!isLoading && !error && (
            <TableContainer component={Paper}>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>{t('app.name')}</TableCell>
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
                    const isSystem = isSystemServer(server)
                    return (
                    <TableRow key={server.id}>
                      <TableCell>
                        <Box display="flex" alignItems="center" gap={1}>
                          <Typography variant="body2" fontWeight={500}>{server.name}</Typography>
                          {isSystem && (
                            <Chip label={t('mcp.system.builtIn')} color="error" size="small" variant="outlined" />
                          )}
                        </Box>
                      </TableCell>
                      <TableCell>
                        <code>{server.slug}</code>
                      </TableCell>
                      <TableCell>{isSystem ? '' : server.base_url}</TableCell>
                      <TableCell>
                        <Chip
                          label={server.status}
                          color={statusColor(server.status) as 'success' | 'error' | 'default'}
                          size="small"
                        />
                      </TableCell>
                      <TableCell>
                        {isSystem ? '—' : (server.session_count ?? 0)}
                      </TableCell>
                      <TableCell>
                        {server.last_synced_at
                          ? new Date(server.last_synced_at).toLocaleString()
                          : '—'}
                      </TableCell>
                      <TableCell>
                        {/* Session management button */}
                        {!isSystem && (
                          <Tooltip title={t('mcp.manageSessions')}>
                            <IconButton size="small" onClick={() => setSessionServerId(server.id)}>
                              <StorageIcon />
                            </IconButton>
                          </Tooltip>
                        )}
                        {/* Sync button */}
                        {isSystem ? (
                          <Tooltip title={t('mcp.system.systemManaged')}>
                            <span>
                              <IconButton size="small" disabled>
                                <SyncIcon />
                              </IconButton>
                            </span>
                          </Tooltip>
                        ) : (server.session_count ?? 0) === 0 ? (
                          <Tooltip title={t('mcp.sync.noSessions')}>
                            <span>
                              <IconButton size="small" disabled>
                                <SyncIcon />
                              </IconButton>
                            </span>
                          </Tooltip>
                        ) : (
                          <Tooltip title={t('mcp.syncNow')}>
                            <IconButton
                              size="small"
                              onClick={() => {
                                setSyncWarnings(null)
                                syncServer.mutate(server.id, {
                                  onSuccess: (result) => {
                                    if (result.warnings && result.warnings.length > 0) {
                                      setSyncWarnings(result.warnings.join('; '))
                                    }
                                  },
                                })
                              }}
                              disabled={syncServer.isPending && syncServer.variables === server.id}
                            >
                              <SyncIcon />
                            </IconButton>
                          </Tooltip>
                        )}
                        {/* Edit/Delete — disabled for System */}
                        {isSystem ? (
                          <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                            {t('mcp.system.systemManaged')}
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

      {/* Create/Edit Server Dialog */}
      <Dialog open={dialogOpen} onClose={() => { setDialogOpen(false); setDialogError(null) }} maxWidth="sm" fullWidth>
        <DialogTitle>{editServer ? t('mcp.editServer') : t('mcp.registerServer')}</DialogTitle>
        <DialogContent>
          {dialogError ? <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} /> : null}
          <Box display="flex" flexDirection="column" gap={2} mt={1}>
            <TextField
              label={t('app.name')}
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              fullWidth
              error={invalidName}
              helperText={invalidName ? 'Lowercase letters, numbers, hyphens only' : undefined}
            />
            <TextField
              label={t('mcp.slug')}
              value={form.slug}
              onChange={(e) => setForm((f) => ({ ...f, slug: e.target.value }))}
              fullWidth
              disabled={!!editServer}
              error={invalidSlug}
              helperText="Lowercase letters, numbers, hyphens only"
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
        </DialogContent>
        <Box display="flex" justifyContent="flex-end" gap={1} p={2} pt={0}>
          <Button onClick={() => setDialogOpen(false)}>{t('app.cancel')}</Button>
          <Button variant="contained" onClick={handleSave} disabled={invalidName || invalidSlug}>{t('app.save')}</Button>
        </Box>
      </Dialog>
    </Box>
  )
}
