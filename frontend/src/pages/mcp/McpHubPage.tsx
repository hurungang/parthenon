import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
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
import { useMcpServers, useSyncServer } from '../../hooks/useMcpServers'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { McpSessionManager } from './McpSessionManager'
import { McpToolBrowser } from './McpToolBrowser'
import apiClient from '../../api/apiClient'
import { useQueryClient } from '@tanstack/react-query'
import type { McpServer } from '../../types'

/**
 * MCP Hub management page — Servers tab and Tool Repository tab.
 */
export function McpHubPage() {
  const { t } = useTranslation()
  const { data: servers, isLoading, error } = useMcpServers()
  const syncServer = useSyncServer()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<'servers' | 'tools'>('servers')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [editServer, setEditServer] = useState<McpServer | null>(null)
  const [form, setForm] = useState({ name: '', slug: '', base_url: '', description: '' })
  const [sessionServerId, setSessionServerId] = useState<string | null>(null)

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

          {!isLoading && !error && (
            <TableContainer component={Paper}>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>{t('app.name')}</TableCell>
                    <TableCell>{t('mcp.slug')}</TableCell>
                    <TableCell>{t('mcp.baseUrl')}</TableCell>
                    <TableCell>{t('app.status')}</TableCell>
                    <TableCell>{t('mcp.lastSynced')}</TableCell>
                    <TableCell>{t('app.actions')}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(servers ?? []).map((server) => (
                    <TableRow key={server.id}>
                      <TableCell>{server.name}</TableCell>
                      <TableCell><code>{server.slug}</code></TableCell>
                      <TableCell>{server.base_url}</TableCell>
                      <TableCell>
                        <Chip
                          label={server.status}
                          color={statusColor(server.status) as 'success' | 'error' | 'default'}
                          size="small"
                        />
                      </TableCell>
                      <TableCell>
                        {server.last_synced_at
                          ? new Date(server.last_synced_at).toLocaleString()
                          : '—'}
                      </TableCell>
                      <TableCell>
                        <Tooltip title={t('mcp.sessions.title')}>
                          <IconButton size="small" onClick={() => setSessionServerId(server.id)}>
                            <StorageIcon />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title={t('mcp.syncNow')}>
                          <IconButton
                            size="small"
                            onClick={() => syncServer.mutate(server.id)}
                            disabled={syncServer.isPending && syncServer.variables === server.id}
                          >
                            <SyncIcon />
                          </IconButton>
                        </Tooltip>
                        <IconButton size="small" onClick={() => handleOpenEdit(server)}>
                          <EditIcon />
                        </IconButton>
                        <IconButton size="small" onClick={() => handleDelete(server.id)}>
                          <DeleteIcon />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))}
                  {(servers ?? []).length === 0 && (
                    <TableRow>
                      <TableCell colSpan={6} align="center">{t('app.noData')}</TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
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
            />
            <TextField
              label={t('mcp.slug')}
              value={form.slug}
              onChange={(e) => setForm((f) => ({ ...f, slug: e.target.value }))}
              fullWidth
              disabled={!!editServer}
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
          <Button variant="contained" onClick={handleSave}>{t('app.save')}</Button>
        </Box>
      </Dialog>
    </Box>
  )
}
