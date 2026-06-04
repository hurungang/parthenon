import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
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
  TablePagination,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { useRecipientGroups } from '../../hooks/useRecipientGroups'
import { usePagination } from '../../hooks/usePagination'
import { deleteRecipientGroup } from '../../services/notificationService'
import type { RecipientGroup } from '../../types'
import { RecipientGroupFormDialog } from './RecipientGroupFormDialog'

export function RecipientGroupListPage() {
  const { t } = useTranslation()
  const pag = usePagination()
  const { groups, isLoading, error, refetch } = useRecipientGroups(pag.limit, pag.offset)

  const [dialogOpen, setDialogOpen] = useState(false)
  const [selected, setSelected] = useState<RecipientGroup | null>(null)
  const [deleteError, setDeleteError] = useState<unknown>(null)

  const openCreate = () => {
    setSelected(null)
    setDialogOpen(true)
  }

  const openEdit = (g: RecipientGroup) => {
    setSelected(g)
    setDialogOpen(true)
  }

  const handleDelete = async (id: string) => {
    if (!confirm(t('app.confirm'))) return
    setDeleteError(null)
    try {
      await deleteRecipientGroup(id)
      void refetch()
    } catch (err) {
      setDeleteError(err)
    }
  }

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h4" fontWeight={700}>
          {t('notifications.groups.title')}
        </Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
          {t('notifications.groups.add')}
        </Button>
      </Box>

      {!!deleteError && (
        <PermissionDeniedAlert error={deleteError} fallbackMessage={t('app.error')} />
      )}

      {!!error && (
        <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />
      )}

      <Alert severity="info" sx={{ mb: 2 }}>
        Notifications use recipient group <strong>slug</strong> (not display name). When writing Skill or SOP instructions for
        <strong> send_notification</strong> and <strong>get_recipient_group</strong>, reference the group slug.
      </Alert>

      {isLoading ? (
        <Box display="flex" justifyContent="center" mt={4}>
          <CircularProgress />
        </Box>
      ) : (
        <>
          <TableContainer component={Paper}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t('notifications.groups.name')}</TableCell>
                  <TableCell>{t('notifications.groups.slug')}</TableCell>
                  <TableCell>{t('notifications.groups.channels')}</TableCell>
                  <TableCell>{t('notifications.groups.status')}</TableCell>
                  <TableCell>{t('notifications.channels.created')}</TableCell>
                  <TableCell align="right">{t('app.actions')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {groups.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6} align="center">
                      <Typography variant="body2" color="text.secondary">
                        {t('notifications.groups.empty')}
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
                {groups.map((g) => (
                  <TableRow key={g.id} hover>
                    <TableCell>{g.name}</TableCell>
                    <TableCell>
                      <Typography variant="body2" fontFamily="monospace">
                        {g.slug}
                      </Typography>
                    </TableCell>
                    <TableCell>{g.channel_mappings.length}</TableCell>
                    <TableCell>
                      <Chip
                        label={g.is_active ? t('app.active') : t('app.inactive')}
                        size="small"
                        color={g.is_active ? 'success' : 'default'}
                      />
                    </TableCell>
                    <TableCell>
                      {new Date(g.created_at).toLocaleDateString()}
                    </TableCell>
                    <TableCell align="right">
                      <Tooltip title={t('app.edit')}>
                        <IconButton size="small" onClick={() => openEdit(g)}>
                          <EditIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title={t('app.delete')}>
                        <IconButton size="small" onClick={() => handleDelete(g.id)} color="error">
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
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
        </>
      )}

      <RecipientGroupFormDialog
        open={dialogOpen}
        group={selected}
        onClose={() => setDialogOpen(false)}
        onSaved={() => void refetch()}
      />
    </Box>
  )
}
