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
  TablePagination,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import VisibilityIcon from '@mui/icons-material/Visibility'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import { usePagination } from '../../hooks/usePagination'
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
  const pag = usePagination()
  const [search, setSearch] = useState('')
  const [editorSop, setEditorSop] = useState<SopDetail | null | undefined>(undefined)
  const [editorMode, setEditorMode] = useState<'create' | 'edit' | 'view'>('create')
  const [editorOpen, setEditorOpen] = useState(false)
  const [loadingEditId, setLoadingEditId] = useState<string | null>(null)

  const { data: sops, isLoading, error } = useQuery<Sop[]>({
    queryKey: ['sops', pag.limit, pag.offset],
    queryFn: async () => {
      const { data } = await apiClient.get<Sop[]>('/sops', {
        params: { limit: pag.limit, offset: pag.offset },
      })
      return data
    },
  })

  const filteredSops = (sops ?? []).filter(
    (s) =>
      !search ||
      s.name.toLowerCase().includes(search.toLowerCase()) ||
      (s.description ?? '').toLowerCase().includes(search.toLowerCase()),
  )

  const handleOpen = async (sop: Sop, mode: 'edit' | 'view') => {
    setLoadingEditId(sop.id)
    setEditorMode(mode)
    try {
      const { data } = await apiClient.get<SopDetail>(`/sops/${sop.id}`)
      setEditorSop(data)
      setEditorOpen(true)
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
    <Box>
      {/* Main list */}
      <Box flex={1} minWidth={0}>
        <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
          <Typography variant="h4" fontWeight={700}>
            {t('sops.title')}
          </Typography>
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => {
              setEditorMode('create')
              setEditorSop(null)
              setEditorOpen(true)
            }}
          >
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
                  <TableCell>{t('app.description')}</TableCell>
                  <TableCell sx={{ width: 100 }}>{t('app.status')}</TableCell>
                  <TableCell sx={{ width: 130, whiteSpace: 'nowrap' }}>{t('app.actions')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {filteredSops.map((sop) => (
                  <TableRow key={sop.id}>
                    <TableCell sx={{ maxWidth: 200 }}>
                      <Tooltip title={sop.name} arrow placement="top">
                        <Typography noWrap variant="body2" fontWeight={500}>
                          {sop.name}
                        </Typography>
                      </Tooltip>
                    </TableCell>
                    <TableCell sx={{ maxWidth: 300 }}>
                      {sop.description ? (
                        <Tooltip title={sop.description} arrow placement="top">
                          <Typography noWrap variant="body2" color="text.secondary">
                            {sop.description}
                          </Typography>
                        </Tooltip>
                      ) : (
                        <Typography variant="body2" color="text.secondary">—</Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={sop.is_active ? t('app.active') : t('app.inactive')}
                        color={sop.is_active ? 'success' : 'default'}
                        size="small"
                      />
                    </TableCell>
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>
                      <IconButton
                        size="small"
                        onClick={() => void handleOpen(sop, 'edit')}
                        disabled={loadingEditId === sop.id}
                      >
                        {loadingEditId === sop.id ? (
                          <CircularProgress size={16} />
                        ) : (
                          <EditIcon fontSize="small" />
                        )}
                      </IconButton>
                      <IconButton
                        size="small"
                        onClick={() => void handleOpen(sop, 'view')}
                        disabled={loadingEditId === sop.id}
                      >
                        <VisibilityIcon fontSize="small" />
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
      </Box>

      <SopEditor
        open={editorOpen}
        sop={editorSop ?? null}
        mode={editorMode}
        onClose={() => { setEditorOpen(false); setEditorSop(undefined) }}
        onSaved={() => { setEditorOpen(false); setEditorSop(undefined) }}
      />
    </Box>
  )
}
