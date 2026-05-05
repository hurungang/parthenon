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
  TextField,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { SopEditor } from './SopEditor'
import type { Sop, SopDetail } from '../../types'

/**
 * SOP list page with inline SopEditor side panel.
 *
 * editorSop:
 *   undefined  → editor hidden
 *   null       → create mode
 *   SopDetail  → edit mode (full detail fetched on click)
 */
export function SopListPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [editorSop, setEditorSop] = useState<SopDetail | null | undefined>(undefined)
  const [loadingEditId, setLoadingEditId] = useState<string | null>(null)

  const { data: sops, isLoading, error } = useQuery<Sop[]>({
    queryKey: ['sops'],
    queryFn: async () => {
      const { data } = await apiClient.get<Sop[]>('/sops')
      return data
    },
  })

  const filteredSops = (sops ?? []).filter(
    (s) =>
      !search ||
      s.name.toLowerCase().includes(search.toLowerCase()) ||
      (s.description ?? '').toLowerCase().includes(search.toLowerCase()),
  )

  const handleEdit = async (sop: Sop) => {
    setLoadingEditId(sop.id)
    try {
      const { data } = await apiClient.get<SopDetail>(`/sops/${sop.id}`)
      setEditorSop(data)
    } finally {
      setLoadingEditId(null)
    }
  }

  const handleDelete = async (id: string) => {
    if (confirm(t('app.confirm'))) {
      await apiClient.delete(`/sops/${id}`)
      await queryClient.invalidateQueries({ queryKey: ['sops'] })
    }
  }

  return (
    <Box display="flex" gap={2} alignItems="flex-start">
      {/* Main list */}
      <Box flex={1} minWidth={0}>
        <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
          <Typography variant="h4" fontWeight={700}>
            {t('sops.title')}
          </Typography>
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setEditorSop(null)}>
            {t('sops.createSop')}
          </Button>
        </Box>

        <TextField
          placeholder={t('app.search')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          size="small"
          sx={{ mb: 2, width: 320 }}
        />

        {isLoading && <CircularProgress />}
        {error && <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />}

        {!isLoading && !error && (
          <TableContainer component={Paper}>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>{t('app.name')}</TableCell>
                  <TableCell>{t('sops.stepCount')}</TableCell>
                  <TableCell>{t('app.status')}</TableCell>
                  <TableCell>{t('app.actions')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {filteredSops.map((sop) => (
                  <TableRow
                    key={sop.id}
                    selected={
                      editorSop !== null &&
                      editorSop !== undefined &&
                      editorSop.id === sop.id
                    }
                  >
                    <TableCell>
                      <Typography variant="body2" fontWeight={500}>
                        {sop.name}
                      </Typography>
                      {sop.description && (
                        <Typography variant="caption" color="text.secondary">
                          {sop.description}
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      {/* Step count requires detail fetch — shown in editor */}
                      <Chip label="—" size="small" variant="outlined" />
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={sop.is_active ? t('app.active') : t('app.inactive')}
                        color={sop.is_active ? 'success' : 'default'}
                        size="small"
                      />
                    </TableCell>
                    <TableCell>
                      <IconButton
                        size="small"
                        onClick={() => handleEdit(sop)}
                        disabled={loadingEditId === sop.id}
                      >
                        {loadingEditId === sop.id ? (
                          <CircularProgress size={16} />
                        ) : (
                          <EditIcon fontSize="small" />
                        )}
                      </IconButton>
                      <IconButton size="small" onClick={() => handleDelete(sop.id)}>
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </TableCell>
                  </TableRow>
                ))}
                {filteredSops.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={4} align="center">
                      {t('app.noData')}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Box>

      {/* In-page editor panel */}
      {editorSop !== undefined && (
        <SopEditor
          sop={editorSop}
          onClose={() => setEditorSop(undefined)}
          onSaved={() => setEditorSop(undefined)}
        />
      )}
    </Box>
  )
}
