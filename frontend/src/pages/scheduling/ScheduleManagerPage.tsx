import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
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
  TablePagination,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import HistoryIcon from '@mui/icons-material/History'
import PauseIcon from '@mui/icons-material/Pause'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import DeleteIcon from '@mui/icons-material/Delete'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import CronEditor from '../../components/scheduling/CronEditor'
import ExecutionHistory from '../../components/scheduling/ExecutionHistory'
import { DynamicSchemaForm } from '../../components/DynamicSchemaForm'
import { usePagination } from '../../hooks/usePagination'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import type { AgentType, ScheduledJob } from '../../types'

export function ScheduleManagerPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const pag = usePagination()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [historyJobId, setHistoryJobId] = useState<string | null>(null)
  const [editingJob, setEditingJob] = useState<ScheduledJob | null>(null)
  const [form, setForm] = useState({
    name: '',
    cron_expression: '0 * * * *',
    target_id: '',
    description: '',
    payload: {} as Record<string, unknown>,
  })

  const { data: jobs, isLoading, error } = useQuery<ScheduledJob[]>({
    queryKey: ['schedules', pag.limit, pag.offset],
    queryFn: async () => {
      const { data } = await apiClient.get<ScheduledJob[]>('/schedules', {
        params: { limit: pag.limit, offset: pag.offset },
      })
      return data
    },
  })

  const { data: agentTypes } = useQuery<AgentType[]>({
    queryKey: ['agent-types'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentType[]>('/agents/types')
      return data
    },
    enabled: dialogOpen,
  })

  const openCreateDialog = () => {
    setEditingJob(null)
    setForm({ name: '', cron_expression: '0 * * * *', target_id: '', description: '', payload: {} })
    setDialogError(null)
    setDialogOpen(true)
  }

  const openEditDialog = (job: ScheduledJob) => {
    setEditingJob(job)
    setForm({
      name: job.name,
      cron_expression: job.cron_expression,
      target_id: job.target_id,
      description: job.description ?? '',
      payload: job.payload ?? {},
    })
    setDialogError(null)
    setDialogOpen(true)
  }

  const closeDialog = () => {
    setDialogOpen(false)
    setEditingJob(null)
    setDialogError(null)
  }

  const handleSave = async () => {
    try {
      setDialogError(null)
      const body = {
        name: form.name,
        description: form.description || undefined,
        cron_expression: form.cron_expression,
        target_type: 'agent' as const,
        target_id: form.target_id,
        payload: Object.keys(form.payload).length > 0 ? form.payload : undefined,
      }
      if (editingJob) {
        await apiClient.put(`/schedules/${editingJob.id}`, body)
      } else {
        await apiClient.post('/schedules', body)
      }
      closeDialog()
      await queryClient.invalidateQueries({ queryKey: ['schedules'] })
    } catch (err) {
      setDialogError(err)
    }
  }

  const handlePause = async (id: string) => {
    await apiClient.post(`/schedules/${id}/pause`)
    await queryClient.invalidateQueries({ queryKey: ['schedules'] })
  }

  const handleResume = async (id: string) => {
    await apiClient.post(`/schedules/${id}/resume`)
    await queryClient.invalidateQueries({ queryKey: ['schedules'] })
  }

  const handleDelete = async (id: string) => {
    if (confirm(t('app.confirm'))) {
      await apiClient.delete(`/schedules/${id}`)
      await queryClient.invalidateQueries({ queryKey: ['schedules'] })
    }
  }

  const statusColor = (status: string) => {
    if (status === 'active') return 'success'
    if (status === 'paused') return 'warning'
    return 'default'
  }

  const selectedAgent = agentTypes?.find((a) => a.id === form.target_id)

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4" fontWeight={700}>{t('schedules.title')}</Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openCreateDialog}>
          {t('schedules.createSchedule')}
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
                <TableCell>{t('schedules.cronExpression')}</TableCell>
                <TableCell>{t('schedules.targetType')}</TableCell>
                <TableCell>{t('app.status')}</TableCell>
                <TableCell>{t('app.actions')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(jobs ?? []).map((job) => (
                <TableRow key={job.id}>
                  <TableCell>{job.name}</TableCell>
                  <TableCell><code>{job.cron_expression}</code></TableCell>
                  <TableCell>{job.target_type}</TableCell>
                  <TableCell>
                    <Chip
                      label={job.status}
                      color={statusColor(job.status) as 'success' | 'warning' | 'default'}
                      size="small"
                    />
                  </TableCell>
                  <TableCell>
                    <IconButton size="small" onClick={() => setHistoryJobId(job.id)} title={t('schedules.executions')}>
                      <HistoryIcon />
                    </IconButton>
                    <IconButton size="small" onClick={() => openEditDialog(job)}>
                      <EditIcon />
                    </IconButton>
                    {job.status === 'active' ? (
                      <IconButton size="small" onClick={() => handlePause(job.id)}>
                        <PauseIcon />
                      </IconButton>
                    ) : (
                      <IconButton size="small" onClick={() => handleResume(job.id)}>
                        <PlayArrowIcon />
                      </IconButton>
                    )}
                    <IconButton size="small" color="error" onClick={() => handleDelete(job.id)}>
                      <DeleteIcon />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
              {(jobs ?? []).length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} align="center">{t('app.noData')}</TableCell>
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

      <Dialog open={dialogOpen} onClose={closeDialog} maxWidth="sm" fullWidth>
        <DialogTitle>{editingJob ? t('schedules.editSchedule') : t('schedules.createSchedule')}</DialogTitle>
        <DialogContent>
          {dialogError ? <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} /> : null}
          <Box display="flex" flexDirection="column" gap={2} mt={1}>
            <TextField
              label={t('app.name')}
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              fullWidth
            />
            <CronEditor
              value={form.cron_expression}
              onChange={(cron) => setForm((f) => ({ ...f, cron_expression: cron }))}
            />
            <FormControl fullWidth>
              <InputLabel>{t('schedules.agentType')}</InputLabel>
              <Select
                value={form.target_id}
                label={t('schedules.agentType')}
                onChange={(e) => setForm((f) => ({ ...f, target_id: e.target.value, payload: {} }))}
              >
                {(agentTypes ?? []).map((opt) => (
                  <MenuItem key={opt.id} value={opt.id}>
                    {opt.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            {selectedAgent && selectedAgent.input_type === 'typed' && selectedAgent.input_schema && (
              <DynamicSchemaForm
                schema={selectedAgent.input_schema}
                value={form.payload}
                onChange={(payload) => setForm((f) => ({ ...f, payload }))}
              />
            )}
            {selectedAgent && selectedAgent.input_type === 'conversation' && (
              <TextField
                label={t('schedules.inputPrompt')}
                value={(form.payload as Record<string, string>).prompt ?? ''}
                onChange={(e) => setForm((f) => ({ ...f, payload: { prompt: e.target.value } }))}
                multiline
                minRows={3}
                fullWidth
              />
            )}
            {selectedAgent && selectedAgent.input_type === 'none' && (
              <Typography variant="body2" color="text.secondary">
                {t('schedules.noInputRequired')}
              </Typography>
            )}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={closeDialog}>{t('app.cancel')}</Button>
          <Button variant="contained" onClick={handleSave}>{t('app.save')}</Button>
        </DialogActions>
      </Dialog>

      {historyJobId && (
        <ExecutionHistory
          jobId={historyJobId}
          open={true}
          onClose={() => setHistoryJobId(null)}
        />
      )}
    </Box>
  )
}
