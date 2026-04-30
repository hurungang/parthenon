import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
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
  Paper,
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
import SendIcon from '@mui/icons-material/Send'
import DeleteIcon from '@mui/icons-material/Delete'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import type { NotificationChannel, NotificationEvent } from '../../types'

/**
 * Notification configuration page — channel CRUD, test-send, and event history.
 */
export function NotificationConfigPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [testSuccess, setTestSuccess] = useState<string | null>(null)
  const [form, setForm] = useState({
    name: '',
    channel_type: 'webhook' as 'email' | 'slack' | 'teams' | 'webhook',
    description: '',
    config: {} as Record<string, string>,
  })

  const { data: channels, isLoading } = useQuery<NotificationChannel[]>({
    queryKey: ['notifications', 'channels'],
    queryFn: async () => {
      const { data } = await apiClient.get<NotificationChannel[]>('/notifications/channels')
      return data
    },
  })

  const { data: events } = useQuery<NotificationEvent[]>({
    queryKey: ['notifications', 'events'],
    queryFn: async () => {
      const { data } = await apiClient.get<NotificationEvent[]>('/notifications/events')
      return data
    },
  })

  const handleSave = async () => {
    try {
      setDialogError(null)
      await apiClient.post('/notifications/channels', form)
      setDialogOpen(false)
      await queryClient.invalidateQueries({ queryKey: ['notifications', 'channels'] })
    } catch (err) {
      setDialogError(err)
    }
  }

  const handleTestSend = async (channelId: string) => {
    await apiClient.post(`/notifications/channels/${channelId}/test`, {
      subject: 'Test from Parthenon',
      body: 'This is a test notification.',
    })
    setTestSuccess(channelId)
    setTimeout(() => setTestSuccess(null), 3000)
    await queryClient.invalidateQueries({ queryKey: ['notifications', 'events'] })
  }

  const handleDelete = async (id: string) => {
    if (confirm(t('app.confirm'))) {
      await apiClient.delete(`/notifications/channels/${id}`)
      await queryClient.invalidateQueries({ queryKey: ['notifications', 'channels'] })
    }
  }

  const statusColor = (status: string) => {
    if (status === 'delivered') return 'success'
    if (status === 'failed') return 'error'
    return 'warning'
  }

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4" fontWeight={700}>{t('notifications.title')}</Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setDialogOpen(true)}>
          {t('app.create')}
        </Button>
      </Box>

      {testSuccess && (
        <Alert severity="success" sx={{ mb: 2 }}>{t('notifications.testSent')}</Alert>
      )}

      {/* Channels table */}
      <Typography variant="h6" mb={1}>{t('notifications.channels')}</Typography>
      {isLoading ? (
        <CircularProgress />
      ) : (
        <TableContainer component={Paper} sx={{ mb: 3 }}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>{t('app.name')}</TableCell>
                <TableCell>{t('notifications.channelType')}</TableCell>
                <TableCell>{t('app.status')}</TableCell>
                <TableCell>{t('app.actions')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(channels ?? []).map((ch) => (
                <TableRow key={ch.id}>
                  <TableCell>{ch.name}</TableCell>
                  <TableCell>{ch.channel_type}</TableCell>
                  <TableCell>
                    <Chip
                      label={ch.is_active ? t('app.active') : t('app.inactive')}
                      color={ch.is_active ? 'success' : 'default'}
                      size="small"
                    />
                  </TableCell>
                  <TableCell>
                    <Button
                      size="small"
                      startIcon={<SendIcon />}
                      onClick={() => handleTestSend(ch.id)}
                      sx={{ mr: 1 }}
                    >
                      {t('notifications.testSend')}
                    </Button>
                    <IconButton size="small" color="error" onClick={() => handleDelete(ch.id)}>
                      <DeleteIcon />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
              {(channels ?? []).length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} align="center">{t('app.noData')}</TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Events history */}
      <Typography variant="h6" mb={1}>{t('notifications.events')}</Typography>
      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{t('notifications.subject')}</TableCell>
              <TableCell>{t('app.status')}</TableCell>
              <TableCell>{t('app.createdAt')}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {(events ?? []).map((ev) => (
              <TableRow key={ev.id}>
                <TableCell>{ev.subject ?? '—'}</TableCell>
                <TableCell>
                  <Chip
                    label={ev.status}
                    color={statusColor(ev.status) as 'success' | 'error' | 'warning'}
                    size="small"
                  />
                </TableCell>
                <TableCell>{new Date(ev.created_at).toLocaleString()}</TableCell>
              </TableRow>
            ))}
            {(events ?? []).length === 0 && (
              <TableRow>
                <TableCell colSpan={3} align="center">{t('app.noData')}</TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Create Channel Dialog */}
      <Dialog open={dialogOpen} onClose={() => { setDialogOpen(false); setDialogError(null) }} maxWidth="sm" fullWidth>
        <DialogTitle>{t('app.create')}</DialogTitle>
        <DialogContent>
          {dialogError ? <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} /> : null}
          <Box display="flex" flexDirection="column" gap={2} mt={1}>
            <TextField
              label={t('app.name')}
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              fullWidth
            />
            <FormControl fullWidth>
              <InputLabel>{t('notifications.channelType')}</InputLabel>
              <Select
                value={form.channel_type}
                label={t('notifications.channelType')}
                onChange={(e) => setForm((f) => ({ ...f, channel_type: e.target.value as typeof form.channel_type }))}
              >
                <MenuItem value="email">{t('notifications.email')}</MenuItem>
                <MenuItem value="slack">{t('notifications.slack')}</MenuItem>
                <MenuItem value="teams">{t('notifications.teams')}</MenuItem>
                <MenuItem value="webhook">{t('notifications.webhook')}</MenuItem>
              </Select>
            </FormControl>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>{t('app.cancel')}</Button>
          <Button variant="contained" onClick={handleSave}>{t('app.save')}</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
