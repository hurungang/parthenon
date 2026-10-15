import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useQueryClient } from '@tanstack/react-query'
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
import DeleteIcon from '@mui/icons-material/Delete'
import EditIcon from '@mui/icons-material/Edit'
import { useDialogErrorHandler } from '../../hooks/useDialogErrorHandler'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { DecisionToolForm } from '../../components/decisionTools/DecisionToolForm'
import {
  listDecisionTools,
  deleteDecisionTool,
} from '../../api/decisionToolsApi'
import type { DecisionTool } from '../../api/decisionToolsApi'
import { DECISION_SERVER_SLUG, buildToolName } from '../../utils/toolNaming'

/**
 * Decision Tools admin page — list and author tenant-scoped decision tools.
 * Lives under the Agent module navigation. Tool names are unique within the
 * caller's tenant and exposed as `decision____<name>` MCP tools with
 * auto-generated descriptions.
 */
export function DecisionToolsPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()

  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<DecisionTool | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<DecisionTool | null>(null)
  const [saveSuccessOpen, setSaveSuccessOpen] = useState(false)

  const { data: tools, isLoading, error } = useQuery<DecisionTool[]>({
    queryKey: ['decision-tools'],
    queryFn: () => listDecisionTools(),
  })

  const openCreate = () => {
    setEditing(null)
    setFormOpen(true)
  }

  const openEdit = (tool: DecisionTool) => {
    setEditing(tool)
    setFormOpen(true)
  }

  const closeForm = () => {
    setFormOpen(false)
    setEditing(null)
    clearDialogError()
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    try {
      setDeletingId(deleteTarget.id)
      await deleteDecisionTool(deleteTarget.id)
      await queryClient.invalidateQueries({ queryKey: ['decision-tools'] })
    } catch (err) {
      setDialogError(err)
    } finally {
      setDeletingId(null)
      setDeleteTarget(null)
    }
  }

  return (
    <Box>
      <Typography variant="h4" fontWeight={700}>
        {t('decisionTools.title')}
      </Typography>
      <Typography variant="body2" color="text.secondary" mb={3}>
        {t('decisionTools.subtitle')}
      </Typography>

      {dialogError != null && (
        <Alert severity="error" sx={{ mb: 2 }}>
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
        </Alert>
      )}

      {error != null && (
        <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />
      )}

      <Box display="flex" justifyContent="flex-end" mb={2}>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
          {t('decisionTools.addTool')}
        </Button>
      </Box>

      {isLoading ? (
        <CircularProgress />
      ) : (
        <TableContainer component={Paper} sx={{ overflowX: 'auto' }}>
          {/* Fixed layout + constrained columns keeps the actions column
              on-screen; horizontal scroll handles narrow viewports. */}
          <Table size="small" sx={{ minWidth: 880, tableLayout: 'fixed' }}>
            <TableHead>
              <TableRow>
                <TableCell sx={{ width: 230 }}>{t('decisionTools.name')}</TableCell>
                <TableCell>{t('decisionTools.purpose')}</TableCell>
                <TableCell>{t('decisionTools.generatedDescription')}</TableCell>
                <TableCell sx={{ width: 200 }}>
                  {t('decisionTools.modelSelection')}
                </TableCell>
                <TableCell sx={{ width: 100 }}>{t('decisionTools.status')}</TableCell>
                <TableCell
                  sx={{
                    width: 110,
                    position: 'sticky',
                    right: 0,
                    bgcolor: 'background.paper',
                    zIndex: 2,
                  }}
                >
                  {t('app.actions')}
                </TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(tools ?? []).map((tool) => (
                <TableRow key={tool.id}>
                  <TableCell>
                    <Tooltip title={buildToolName(DECISION_SERVER_SLUG, tool.name)}>
                      <Typography
                        variant="body2"
                        sx={{
                          fontFamily: 'monospace',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                        }}
                      >
                        {buildToolName(DECISION_SERVER_SLUG, tool.name)}
                      </Typography>
                    </Tooltip>
                  </TableCell>
                  <TableCell>
                    <Tooltip title={tool.purpose ?? ''}>
                      <Typography
                        variant="body2"
                        sx={{
                          maxWidth: 280,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {tool.purpose ?? '—'}
                      </Typography>
                    </Tooltip>
                  </TableCell>
                  <TableCell>
                    <Tooltip title={tool.description ?? ''}>
                      <Typography
                        variant="body2"
                        color="text.secondary"
                        sx={{
                          maxWidth: 320,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {tool.description ?? '—'}
                      </Typography>
                    </Tooltip>
                  </TableCell>
                  <TableCell>
                    <Tooltip
                      title={
                        tool.model_name
                          ? `${tool.model_name}${
                              tool.provider_display_name
                                ? ` — ${tool.provider_display_name}`
                                : ''
                            }`
                          : ''
                      }
                    >
                      <Chip
                        size="small"
                        variant="outlined"
                        sx={{
                          maxWidth: '100%',
                          '& .MuiChip-label': {
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                          },
                        }}
                        label={
                          tool.model_name
                            ? `${tool.model_name}${
                                tool.provider_display_name
                                  ? ` — ${tool.provider_display_name}`
                                  : ''
                              }`
                            : '—'
                        }
                      />
                    </Tooltip>
                  </TableCell>
                  <TableCell>
                    {tool.ready === false ? (
                      <Tooltip title={t('decisionTools.notReadyDetail')}>
                        <Chip
                          label={t('decisionTools.notReady')}
                          size="small"
                          color="warning"
                        />
                      </Tooltip>
                    ) : tool.enabled ? (
                      <Chip
                        label={t('decisionTools.statusActive')}
                        size="small"
                        color="success"
                      />
                    ) : (
                      <Chip
                        label={t('decisionTools.status')}
                        size="small"
                        color="default"
                      />
                    )}
                  </TableCell>
                  <TableCell
                    sx={{
                      position: 'sticky',
                      right: 0,
                      bgcolor: 'background.paper',
                      zIndex: 1,
                    }}
                  >
                    <Tooltip title={t('app.edit')}>
                      <IconButton size="small" onClick={() => openEdit(tool)}>
                        <EditIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title={t('app.delete')}>
                      <span>
                        <IconButton
                          size="small"
                          disabled={deletingId === tool.id}
                          onClick={() => setDeleteTarget(tool)}
                        >
                          {deletingId === tool.id ? (
                            <CircularProgress size={16} />
                          ) : (
                            <DeleteIcon fontSize="small" />
                          )}
                        </IconButton>
                      </span>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
              {(tools ?? []).length === 0 && (
                <TableRow>
                  <TableCell colSpan={6}>
                    <Typography variant="body2" color="text.secondary">
                      {t('decisionTools.noTools')}
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <DecisionToolForm
        open={formOpen}
        editing={editing}
        onClose={closeForm}
        onSaved={() => {
          void queryClient.invalidateQueries({ queryKey: ['decision-tools'] })
          setSaveSuccessOpen(true)
        }}
      />

      {/* Delete confirmation */}
      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>{t('app.delete')}</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            {t('decisionTools.deleteConfirm', { name: deleteTarget?.name ?? '' })}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>{t('app.cancel')}</Button>
          <Button
            color="error"
            variant="contained"
            onClick={() => void handleDelete()}
            disabled={deletingId != null}
          >
            {t('app.delete')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Simple success snackbar */}
      {saveSuccessOpen && (
        <Alert severity="success" sx={{ mt: 2 }} onClose={() => setSaveSuccessOpen(false)}>
          {t('decisionTools.saveSuccess')}
        </Alert>
      )}
    </Box>
  )
}
