import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  CircularProgress,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  IconButton,
  Chip,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import type { Sop } from '../../types'

/**
 * SOP list page with step count and management actions.
 */
export function SopListPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [editSop, setEditSop] = useState<Sop | null>(null)
  const [form, setForm] = useState({ name: '', description: '' })

  const { data: sops, isLoading, error } = useQuery<Sop[]>({
    queryKey: ['sops'],
    queryFn: async () => {
      const { data } = await apiClient.get<Sop[]>('/sops')
      return data
    },
  })

  const handleOpenCreate = () => {
    setEditSop(null)
    setForm({ name: '', description: '' })
    setDialogError(null)
    setDialogOpen(true)
  }

  const handleOpenEdit = (sop: Sop) => {
    setEditSop(sop)
    setForm({ name: sop.name, description: sop.description ?? '' })
    setDialogError(null)
    setDialogOpen(true)
  }

  const handleSave = async () => {
    try {
      setDialogError(null)
      if (editSop) {
        await apiClient.put(`/sops/${editSop.id}`, form)
      } else {
        await apiClient.post('/sops', form)
      }
      setDialogOpen(false)
      await queryClient.invalidateQueries({ queryKey: ['sops'] })
    } catch (err) {
      setDialogError(err)
    }
  }

  const handleDelete = async (id: string) => {
    if (confirm(t('app.confirm'))) {
      await apiClient.delete(`/sops/${id}`)
      await queryClient.invalidateQueries({ queryKey: ['sops'] })
    }
  }

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4" fontWeight={700}>{t('sops.title')}</Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={handleOpenCreate}>
          {t('sops.createSop')}
        </Button>
      </Box>

      {error && <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />}

      {isLoading ? (
        <CircularProgress />
      ) : (
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>{t('app.name')}</TableCell>
                <TableCell>{t('app.description')}</TableCell>
                <TableCell>{t('app.status')}</TableCell>
                <TableCell>{t('app.actions')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(sops ?? []).map((sop) => (
                <TableRow key={sop.id}>
                  <TableCell>{sop.name}</TableCell>
                  <TableCell>{sop.description ?? '—'}</TableCell>
                  <TableCell>
                    <Chip
                      label={sop.is_active ? t('app.active') : t('app.inactive')}
                      color={sop.is_active ? 'success' : 'default'}
                      size="small"
                    />
                  </TableCell>
                  <TableCell>
                    <IconButton size="small" onClick={() => handleOpenEdit(sop)}>
                      <EditIcon />
                    </IconButton>
                    <IconButton size="small" onClick={() => handleDelete(sop.id)}>
                      <DeleteIcon />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
              {(sops ?? []).length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} align="center">{t('app.noData')}</TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Dialog open={dialogOpen} onClose={() => { setDialogOpen(false); setDialogError(null) }} maxWidth="sm" fullWidth>
        <DialogTitle>{editSop ? t('sops.editSop') : t('sops.createSop')}</DialogTitle>
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
              label={t('app.description')}
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              fullWidth
              multiline
              rows={2}
            />
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
