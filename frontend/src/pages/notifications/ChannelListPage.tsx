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
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { useNotificationChannels } from '../../hooks/useNotificationChannels'
import { deleteChannel } from '../../services/notificationService'
import type { NotificationChannel } from '../../types'
import { ChannelFormDialog } from './ChannelFormDialog'

export function ChannelListPage() {
  const { t } = useTranslation()
  const { channels, isLoading, error, refetch } = useNotificationChannels()

  const [dialogOpen, setDialogOpen] = useState(false)
  const [selected, setSelected] = useState<NotificationChannel | null>(null)
  const [deleteError, setDeleteError] = useState<unknown>(null)

  const openCreate = () => {
    setSelected(null)
    setDialogOpen(true)
  }

  const openEdit = (ch: NotificationChannel) => {
    setSelected(ch)
    setDialogOpen(true)
  }

  const handleDelete = async (id: string) => {
    if (!confirm(t('app.confirm'))) return
    setDeleteError(null)
    try {
      await deleteChannel(id)
      void refetch()
    } catch (err) {
      setDeleteError(err)
    }
  }

  const typeColor = (ct: string) => {
    if (ct === 'SMTP' || ct === 'EMAIL_API') return 'primary'
    if (ct === 'WEBHOOK') return 'secondary'
    return 'default'
  }

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h4" fontWeight={700}>
          {t('notifications.channels.title')}
        </Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
          {t('notifications.channels.add')}
        </Button>
      </Box>

      {!!deleteError && (
        <PermissionDeniedAlert error={deleteError} fallbackMessage={t('app.error')} />
      )}

      {!!error && (
        <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />
      )}

      {isLoading ? (
        <Box display="flex" justifyContent="center" mt={4}>
          <CircularProgress />
        </Box>
      ) : (
        <TableContainer component={Paper}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t('notifications.channels.name')}</TableCell>
                <TableCell>{t('notifications.channels.type')}</TableCell>
                <TableCell>{t('notifications.channels.status')}</TableCell>
                <TableCell>{t('notifications.channels.properties')}</TableCell>
                <TableCell>{t('notifications.channels.created')}</TableCell>
                <TableCell align="right">{t('app.actions')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {channels.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} align="center">
                    <Typography variant="body2" color="text.secondary">
                      {t('notifications.channels.empty')}
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
              {channels.map((ch) => (
                <TableRow key={ch.id} hover>
                  <TableCell>{ch.name}</TableCell>
                  <TableCell>
                    <Chip
                      label={t(`notifications.channelTypes.${ch.channel_type}`, ch.channel_type)}
                      size="small"
                      color={typeColor(ch.channel_type) as 'primary' | 'secondary' | 'default'}
                    />
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={ch.is_active ? t('app.active') : t('app.inactive')}
                      size="small"
                      color={ch.is_active ? 'success' : 'default'}
                    />
                  </TableCell>
                  <TableCell>{ch.properties.length}</TableCell>
                  <TableCell>
                    {new Date(ch.created_at).toLocaleDateString()}
                  </TableCell>
                  <TableCell align="right">
                    <Tooltip title={t('app.edit')}>
                      <IconButton size="small" onClick={() => openEdit(ch)}>
                        <EditIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title={t('app.delete')}>
                      <IconButton size="small" onClick={() => handleDelete(ch.id)} color="error">
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <ChannelFormDialog
        open={dialogOpen}
        channel={selected}
        onClose={() => setDialogOpen(false)}
        onSaved={() => void refetch()}
      />
    </Box>
  )
}
