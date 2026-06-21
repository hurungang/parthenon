import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
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
import { useDataTypes, useDeleteDataType, fetchDataTypeUsage } from '../../hooks/useDataTypes'
import { usePagination } from '../../hooks/usePagination'
import { DataTypeFormDialog } from './DataTypeFormDialog'
import type { AgentDataType, ReferencingAgentType } from '../../types'

/**
 * Data Types admin page — list, create, edit, delete data types
 * with pagination and delete-usage guard.
 */
export function DataTypesPage() {
  const { t } = useTranslation()
  const pag = usePagination()
  const deleteMutation = useDeleteDataType()

  const { data: dataTypesResponse, isLoading, error } = useDataTypes({
    page: pag.page + 1,
    page_size: pag.rowsPerPage,
  })

  // Form dialog state
  const [formOpen, setFormOpen] = useState(false)
  const [editDataType, setEditDataType] = useState<AgentDataType | null>(null)

  // Delete confirmation state
  const [deleteTarget, setDeleteTarget] = useState<AgentDataType | null>(null)
  const [deleteUsageInfo, setDeleteUsageInfo] = useState<ReferencingAgentType[] | null>(null)
  const [deleteLoading, setDeleteLoading] = useState(false)
  const [deleteError, setDeleteError] = useState<unknown>(null)

  const items = dataTypesResponse?.items ?? []

  const handleOpenCreate = () => {
    setEditDataType(null)
    setFormOpen(true)
  }

  const handleOpenEdit = (dt: AgentDataType) => {
    setEditDataType(dt)
    setFormOpen(true)
  }

  const handleCloseForm = () => {
    setFormOpen(false)
    setEditDataType(null)
  }

  const handleSaved = async () => {
    // Data is refreshed automatically via React Query cache invalidation
  }

  const handleDeleteClick = async (dt: AgentDataType) => {
    setDeleteTarget(dt)
    setDeleteError(null)
    setDeleteUsageInfo(null)
    try {
      const usage = await fetchDataTypeUsage(dt.id)
      setDeleteUsageInfo(usage)
    } catch {
      // If usage fetch fails, allow delete without guard info
      setDeleteUsageInfo([])
    }
  }

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return
    try {
      setDeleteError(null)
      setDeleteLoading(true)
      await deleteMutation.mutateAsync(deleteTarget.id)
      setDeleteTarget(null)
      setDeleteUsageInfo(null)
    } catch (err) {
      setDeleteError(err)
    } finally {
      setDeleteLoading(false)
    }
  }

  const handleCloseDelete = () => {
    setDeleteTarget(null)
    setDeleteUsageInfo(null)
    setDeleteError(null)
  }

  const isReferenced = (deleteUsageInfo ?? []).length > 0

  const total = dataTypesResponse?.total ?? items.length

  return (
    <Box>
      {/* Page header */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4" fontWeight={700}>
          {t('admin.dataTypes.title')}
        </Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={handleOpenCreate}
        >
          {t('admin.dataTypes.create')}
        </Button>
      </Box>

      {/* Error state */}
      {error && <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />}

      {/* Loading state */}
      {isLoading ? (
        <Box display="flex" justifyContent="center" py={4}>
          <CircularProgress />
        </Box>
      ) : (
        <Box>
          <TableContainer component={Paper}>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>{t('admin.dataTypes.name')}</TableCell>
                  <TableCell>{t('admin.dataTypes.slug')}</TableCell>
                  <TableCell>{t('admin.dataTypes.fieldCount')}</TableCell>
                  <TableCell>{t('app.createdAt')}</TableCell>
                  <TableCell>{t('app.actions')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {items.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} align="center">
                      {t('app.noData')}
                    </TableCell>
                  </TableRow>
                ) : (
                  items.map((dt) => {
                    return (
                      <TableRow key={dt.id}>
                        <TableCell>
                          <Typography fontWeight={500}>{dt.name}</Typography>
                          {dt.description && (
                            <Typography variant="body2" color="text.secondary" noWrap sx={{ maxWidth: 300 }}>
                              {dt.description}
                            </Typography>
                          )}
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2" fontFamily="monospace" color="text.secondary">
                            {dt.slug}
                          </Typography>
                        </TableCell>
                        <TableCell>{dt.fields.length}</TableCell>
                        <TableCell>
                          {new Date(dt.created_at).toLocaleString()}
                        </TableCell>
                        <TableCell>
                          <Box display="flex" gap={0.5}>
                            <Tooltip title={t('app.edit')}>
                              <IconButton
                                size="small"
                                onClick={() => handleOpenEdit(dt)}
                              >
                                <EditIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                            <Tooltip title={t('app.delete')}>
                              <span>
                                <IconButton
                                  size="small"
                                  color="error"
                                  onClick={() => handleDeleteClick(dt)}
                                >
                                  <DeleteIcon fontSize="small" />
                                </IconButton>
                              </span>
                            </Tooltip>
                          </Box>
                        </TableCell>
                      </TableRow>
                    )
                  })
                )}
              </TableBody>
            </Table>
          </TableContainer>
          <TablePagination
            component="div"
            count={total}
            page={pag.page}
            onPageChange={pag.onPageChange}
            rowsPerPage={pag.rowsPerPage}
            onRowsPerPageChange={pag.onRowsPerPageChange}
            rowsPerPageOptions={pag.rowsPerPageOptions}
            labelRowsPerPage={t('app.rowsPerPage')}
          />
        </Box>
      )}

      {/* Create/Edit Dialog */}
      <DataTypeFormDialog
        open={formOpen}
        editDataType={editDataType}
        onClose={handleCloseForm}
        onSaved={handleSaved}
      />

      {/* Delete Confirmation Dialog with Usage Guard */}
      <Dialog
        open={!!deleteTarget}
        onClose={handleCloseDelete}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>{t('admin.dataTypes.confirmDelete')}</DialogTitle>
        <DialogContent>
          {deleteError !== null && (
            <PermissionDeniedAlert error={deleteError} fallbackMessage={t('app.error')} />
          )}

          {isReferenced ? (
            <Box>
              <Alert severity="warning" sx={{ mb: 2 }}>
                {t('admin.dataTypes.inUse')}
              </Alert>
              <DialogContentText sx={{ mb: 1 }}>
                {t('admin.dataTypes.referencedBy')}
              </DialogContentText>
              <Box component="ul" sx={{ mt: 0, pl: 2 }}>
                {deleteUsageInfo!.map((ref) => (
                  <li key={ref.id}>
                    <Typography variant="body2">{ref.name}</Typography>
                  </li>
                ))}
              </Box>
            </Box>
          ) : (
            <DialogContentText>
              {t('admin.dataTypes.confirmDeleteMessage', {
                name: deleteTarget?.name ?? '',
              })}
            </DialogContentText>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDelete}>{t('app.cancel')}</Button>
          <Button
            variant="contained"
            color="error"
            onClick={handleDeleteConfirm}
            disabled={isReferenced || deleteLoading}
          >
            {deleteLoading ? t('app.saving') : t('app.delete')}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
