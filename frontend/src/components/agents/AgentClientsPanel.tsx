import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  MenuItem,
  Paper,
  Select,
  Switch,
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
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import DeleteIcon from '@mui/icons-material/Delete'
import EditIcon from '@mui/icons-material/Edit'
import {
  createAgentClient,
  deleteAgentClient,
  fetchAgentClients,
  fetchAgentTypeOptions,
  updateAgentClient,
  updateAgentClientStatus,
  type AgentTypeOption,
} from '../../api/agentClientsApi'
import type {
  AgentClient,
  AgentClientCredentialResponse,
  AgentClientKeyType,
  AgentClientRateLimitWindow,
} from '../../types/agentClients'

interface AgentClientsPanelProps {
  /** When set, the panel is scoped to this agent type (e.g. inside the agent type dialog). */
  agentTypeId?: string
}

function statusColor(status: string): 'success' | 'default' | 'error' {
  if (status === 'active') return 'success'
  if (status === 'revoked') return 'error'
  return 'default'
}

/**
 * Clients management for third-party agent integration.
 *
 * A client is an access grant bound to one agent type (input-interface only) —
 * NOT an agent identity. A publishable client is safe in a browser but exposes
 * the agent type's full behaviour publicly, so creating one shows a soft warning.
 */
export function AgentClientsPanel({ agentTypeId }: AgentClientsPanelProps) {
  const { t } = useTranslation()
  const [clients, setClients] = useState<AgentClient[]>([])
  const [agentTypeOptions, setAgentTypeOptions] = useState<AgentTypeOption[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<unknown>(null)

  const [dialogOpen, setDialogOpen] = useState(false)
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [form, setForm] = useState({
    name: '',
    agent_type_id: agentTypeId ?? '',
    key_type: 'publishable' as AgentClientKeyType,
    origins: '',
    rate_limit: 100,
  })
  const [saving, setSaving] = useState(false)

  const [issued, setIssued] = useState<AgentClientCredentialResponse | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<AgentClient | null>(null)
  const [editTarget, setEditTarget] = useState<AgentClient | null>(null)
  const [editForm, setEditForm] = useState({
    origins: '',
    rate_limit: 100,
    rate_limit_window: 'per_minute' as AgentClientRateLimitWindow,
  })
  const [editError, setEditError] = useState<unknown>(null)
  const [editSaving, setEditSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      setClients(await fetchAgentClients(agentTypeId))
    } catch (err) {
      setLoadError(err)
    } finally {
      setLoading(false)
    }
  }, [agentTypeId])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (agentTypeId) return
    void fetchAgentTypeOptions()
      .then(setAgentTypeOptions)
      .catch(() => setAgentTypeOptions([]))
  }, [agentTypeId])

  const openCreate = () => {
    setDialogError(null)
    setForm({
      name: '',
      agent_type_id: agentTypeId ?? '',
      key_type: 'publishable',
      origins: '',
      rate_limit: 100,
    })
    setDialogOpen(true)
  }

  const closeCreate = () => {
    setDialogOpen(false)
    setDialogError(null)
  }

  const save = async () => {
    setSaving(true)
    setDialogError(null)
    try {
      const origins = form.origins
        .split('\n')
        .map((o) => o.trim())
        .filter(Boolean)
      const result = await createAgentClient({
        name: form.name,
        agent_type_id: agentTypeId ?? form.agent_type_id,
        key_type: form.key_type,
        allowed_origins: origins.length ? origins : undefined,
        rate_limit: form.rate_limit || undefined,
        rate_limit_window: 'per_minute',
      })
      setDialogOpen(false)
      setIssued(result)
      await load()
    } catch (err) {
      setDialogError(err)
    } finally {
      setSaving(false)
    }
  }

  const toggleStatus = async (client: AgentClient) => {
    try {
      await updateAgentClientStatus(client.id, client.status === 'active' ? 'inactive' : 'active')
      await load()
    } catch (err) {
      setLoadError(err)
    }
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    try {
      await deleteAgentClient(deleteTarget.id)
      setDeleteTarget(null)
      await load()
    } catch (err) {
      setDialogError(err)
    }
  }

  const openEdit = (client: AgentClient) => {
    setEditError(null)
    setEditTarget(client)
    setEditForm({
      origins: (client.allowed_origins ?? []).join('\n'),
      rate_limit: client.rate_limit ?? 100,
      rate_limit_window: (client.rate_limit_window ?? 'per_minute') as AgentClientRateLimitWindow,
    })
  }

  const saveEdit = async () => {
    if (!editTarget) return
    setEditSaving(true)
    setEditError(null)
    try {
      const origins = editForm.origins
        .split('\n')
        .map((o) => o.trim())
        .filter(Boolean)
      await updateAgentClient(editTarget.id, {
        allowed_origins: origins,
        rate_limit: editForm.rate_limit || null,
        rate_limit_window: editForm.rate_limit_window,
      })
      setEditTarget(null)
      await load()
    } catch (err) {
      setEditError(err)
    } finally {
      setEditSaving(false)
    }
  }

  const copy = (text: string) => {
    void navigator.clipboard?.writeText(text)
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
        <Typography variant="body2" color="text.secondary">
          {t(
            'agentClients.subtitle',
            'Access grants bound to an agent type (secret or publishable). Not an agent identity.',
          )}
        </Typography>
        <Button variant="contained" size="small" startIcon={<AddIcon />} onClick={openCreate}>
          {t('agentClients.new', 'New Client')}
        </Button>
      </Box>

      {loadError ? (
        <Alert severity="error" sx={{ mb: 2 }}>
          {t('agentClients.loadError', 'Failed to load clients.')}
        </Alert>
      ) : null}

      {loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      ) : (
        <TableContainer component={Paper}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t('agentClients.colName', 'Client')}</TableCell>
                <TableCell>{t('agentClients.colAgentType', 'Agent Type')}</TableCell>
                <TableCell>{t('agentClients.colCredential', 'Credential')}</TableCell>
                <TableCell>{t('agentClients.colOrigins', 'Origins')}</TableCell>
                <TableCell>{t('agentClients.colRate', 'Rate Limit')}</TableCell>
                <TableCell>{t('agentClients.colStatus', 'Status')}</TableCell>
                <TableCell align="right">{t('agentClients.colActions', 'Actions')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {clients.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} align="center">
                    {t('agentClients.empty', 'No clients yet. Create one to expose this agent type.')}
                  </TableCell>
                </TableRow>
              ) : (
                clients.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell>
                      <Typography variant="body2" fontWeight={600}>
                        {c.name}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {c.slug}
                      </Typography>
                    </TableCell>
                    <TableCell>{c.agent_type_name ?? c.agent_type_id}</TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        label={c.key_type}
                        color={c.key_type === 'publishable' ? 'warning' : 'default'}
                      />
                    </TableCell>
                    <TableCell>{c.allowed_origins?.join(', ') || '—'}</TableCell>
                    <TableCell>{c.rate_limit ? `${c.rate_limit} / ${c.rate_limit_window}` : '—'}</TableCell>
                    <TableCell>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Switch
                          size="small"
                          checked={c.status === 'active'}
                          disabled={c.status === 'revoked'}
                          onChange={() => void toggleStatus(c)}
                          inputProps={{ 'aria-label': t('agentClients.toggleStatus', 'Toggle active') }}
                        />
                        <Chip size="small" label={c.status} color={statusColor(c.status)} />
                      </Box>
                    </TableCell>
                    <TableCell align="right">
                      <IconButton size="small" onClick={() => openEdit(c)} aria-label="edit">
                        <EditIcon fontSize="small" />
                      </IconButton>
                      <IconButton
                        size="small"
                        onClick={() => setDeleteTarget(c)}
                        aria-label="delete"
                        color="error"
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Integration guide */}
      <Paper sx={{ mt: 2, p: 2 }}>
        <Typography variant="subtitle1" gutterBottom>
          {t('agentClients.guideTitle', 'Integration guide')}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          {t(
            'agentClients.guideIntro',
            'Use a publishable credential in the browser and a secret credential server-side. The client is not an identity — it only invokes the agent type’s input interface.',
          )}
        </Typography>
        <Typography variant="subtitle2" sx={{ mt: 1 }}>
          JavaScript
        </Typography>
        <Box
          component="pre"
          sx={{ bgcolor: '#1E293B', color: '#E2E8F0', p: 2, borderRadius: 1, overflowX: 'auto', fontSize: 12 }}
        >
          {`const client = new ParthenonClient({ baseUrl: 'https://<host>', credential: 'phn_cl_pk_…' });\nawait client.chat({ message: 'Hello' });`}
        </Box>
        <Typography variant="subtitle2" sx={{ mt: 2 }}>
          Python
        </Typography>
        <Box
          component="pre"
          sx={{ bgcolor: '#1E293B', color: '#E2E8F0', p: 2, borderRadius: 1, overflowX: 'auto', fontSize: 12 }}
        >
          {`from parthenon import Client\nclient = Client(base_url="https://<host>", credential="phn_cl_sk_…")\nclient.submit({"email_body": "…"})`}
        </Box>
      </Paper>

      {/* Create dialog */}
      <Dialog open={dialogOpen} onClose={closeCreate} fullWidth maxWidth="sm">
        <DialogTitle>{t('agentClients.new', 'New Client')}</DialogTitle>
        <DialogContent>
          {dialogError ? (
            <Alert severity="error" sx={{ mb: 2 }}>
              {t('agentClients.saveError', 'Failed to create client. Check the fields and your permissions.')}
            </Alert>
          ) : null}
          <TextField
            fullWidth
            margin="dense"
            label={t('agentClients.name', 'Client name')}
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          {!agentTypeId ? (
            <Autocomplete
              options={agentTypeOptions}
              getOptionLabel={(o) => o.name}
              value={agentTypeOptions.find((o) => o.id === form.agent_type_id) ?? null}
              onChange={(_, value) => setForm({ ...form, agent_type_id: value?.id ?? '' })}
              renderInput={(params) => (
                <TextField
                  {...params}
                  margin="dense"
                  label={t('agentClients.agentType', 'Agent type')}
                  placeholder={t('agentClients.agentTypePlaceholder', 'Search agent types…')}
                />
              )}
            />
          ) : null}
          <Select
            fullWidth
            margin="dense"
            value={form.key_type}
            onChange={(e) => setForm({ ...form, key_type: e.target.value as AgentClientKeyType })}
          >
            <MenuItem value="publishable">{t('agentClients.publishable', 'publishable (browser-safe)')}</MenuItem>
            <MenuItem value="secret">{t('agentClients.secret', 'secret (server-side)')}</MenuItem>
          </Select>
          {form.key_type === 'publishable' ? (
            <Alert severity="warning" sx={{ mt: 1 }}>
              {t(
                'agentClients.publishableWarning',
                'A publishable client is safe in the browser but exposes this agent type’s full behaviour publicly. At least one allowed origin is required. The client is not an identity — it can only invoke the agent type’s input interface.',
              )}
            </Alert>
          ) : null}
          <TextField
            fullWidth
            margin="dense"
            multiline
            minRows={2}
            label={t('agentClients.origins', 'Allowed origins (one per line)')}
            placeholder={'https://acme.com\nhttps://*.acme.com'}
            helperText={t(
              'agentClients.originsHelper',
              'One origin per line. Wildcards are supported (e.g. https://*.acme.com). Leave empty to allow any origin.',
            )}
            value={form.origins}
            onChange={(e) => setForm({ ...form, origins: e.target.value })}
          />
          <TextField
            fullWidth
            margin="dense"
            type="number"
            label={t('agentClients.rateLimit', 'Rate limit (req/min)')}
            value={form.rate_limit}
            onChange={(e) => setForm({ ...form, rate_limit: Number(e.target.value) })}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={closeCreate}>{t('common.cancel', 'Cancel')}</Button>
          <Button
            variant="contained"
            onClick={save}
            disabled={
              saving ||
              !form.name ||
              (!agentTypeId && !form.agent_type_id) ||
              (form.key_type === 'publishable' && !form.origins.trim())
            }
          >
            {t('common.save', 'Save')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Credential shown once */}
      <Dialog open={!!issued} onClose={() => setIssued(null)} fullWidth maxWidth="sm">
        <DialogTitle>{t('agentClients.credentialTitle', 'Client credential (shown once)')}</DialogTitle>
        <DialogContent>
          <Alert severity="info" sx={{ mb: 2 }}>
            {t('agentClients.credentialNote', 'Copy this now — it will not be shown again.')}
          </Alert>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <TextField fullWidth value={issued?.client_key ?? ''} InputProps={{ readOnly: true }} />
            <IconButton onClick={() => copy(issued?.client_key ?? '')} aria-label="copy">
              <ContentCopyIcon />
            </IconButton>
          </Box>
          <Typography variant="caption" color="text.secondary">
            {t('agentClients.credentialType', 'Type')}: {issued?.key_type}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setIssued(null)}>{t('common.done', 'Done')}</Button>
        </DialogActions>
      </Dialog>

      {/* Edit dialog — allowed origins + rate limit only */}
      <Dialog open={!!editTarget} onClose={() => setEditTarget(null)} fullWidth maxWidth="sm">
        <DialogTitle>{t('agentClients.editTitle', 'Edit client')}</DialogTitle>
        <DialogContent>
          {editError ? (
            <Alert severity="error" sx={{ mb: 2 }}>
              {t('agentClients.editError', 'Failed to save changes.')}
            </Alert>
          ) : null}
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            {t('agentClients.editSubtitle', 'Only allowed origins and rate limit can be changed.')}
          </Typography>
          <TextField
            fullWidth
            margin="dense"
            multiline
            minRows={2}
            label={t('agentClients.origins', 'Allowed origins (one per line)')}
            placeholder={'https://acme.com\nhttps://*.acme.com'}
            helperText={t(
              'agentClients.originsHelper',
              'One origin per line. Wildcards are supported (e.g. https://*.acme.com). Leave empty to allow any origin.',
            )}
            value={editForm.origins}
            onChange={(e) => setEditForm({ ...editForm, origins: e.target.value })}
          />
          <Box sx={{ display: 'flex', gap: 2 }}>
            <TextField
              margin="dense"
              type="number"
              label={t('agentClients.rateLimit', 'Rate limit')}
              value={editForm.rate_limit}
              onChange={(e) => setEditForm({ ...editForm, rate_limit: Number(e.target.value) })}
              sx={{ flex: 1 }}
            />
            <Select
              margin="dense"
              value={editForm.rate_limit_window}
              onChange={(e) =>
                setEditForm({
                  ...editForm,
                  rate_limit_window: e.target.value as AgentClientRateLimitWindow,
                })
              }
              sx={{ flex: 1 }}
            >
              <MenuItem value="per_minute">{t('agentClients.perMinute', 'per minute')}</MenuItem>
              <MenuItem value="per_hour">{t('agentClients.perHour', 'per hour')}</MenuItem>
              <MenuItem value="per_day">{t('agentClients.perDay', 'per day')}</MenuItem>
            </Select>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditTarget(null)}>{t('common.cancel', 'Cancel')}</Button>
          <Button
            variant="contained"
            onClick={saveEdit}
            disabled={editSaving || (editTarget?.key_type === 'publishable' && !editForm.origins.trim())}
          >
            {t('common.save', 'Save')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete confirmation */}
      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>{t('agentClients.deleteTitle', 'Remove client?')}</DialogTitle>
        <DialogContent>
          {dialogError ? (
            <Alert severity="error" sx={{ mb: 2 }}>
              {t('agentClients.deleteError', 'Failed to remove client.')}
            </Alert>
          ) : null}
          <Typography>
            {t(
              'agentClients.deleteBody',
              'This permanently removes the client and its credential. To temporarily disable it instead, use the status toggle.',
            )}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>{t('common.cancel', 'Cancel')}</Button>
          <Button color="error" variant="contained" onClick={confirmDelete}>
            {t('agentClients.delete', 'Remove')}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
