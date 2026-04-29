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
  Select,
  MenuItem,
  FormControl,
  InputLabel,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import PauseIcon from '@mui/icons-material/Pause'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import DeleteIcon from '@mui/icons-material/Delete'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import type { ScheduledJob } from '../../types'

/**
 * Schedule manager page — cron job list, create/edit, pause/resume/delete.
 */
export function ScheduleManagerPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [form, setForm] = useState({
    name: '',
    cron_expression: '0 * * * *',
    target_type: 'agent' as 'agent' | 'sop',
    target_id: '',
    description: '',
  })

  const { data: jobs, isLoading } = useQuery<ScheduledJob[]>({
    queryKey: ['schedules'],
    queryFn: async () => {
      const { data } = await apiClient.get<ScheduledJob[]>('/schedules')
      return data
    },
  })

  const handleSave = async () => {
    await apiClient.post('/schedules', form)
    setDialogOpen(false)
    await queryClient.invalidateQueries({ queryKey: ['schedules'] })
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

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4" fontWeight={700}>{t('schedules.title')}</Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setDialogOpen(true)}>
          {t('schedules.createSchedule')}
        </Button>
      </Box>

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

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{t('schedules.createSchedule')}</DialogTitle>
        <DialogContent>
          <Box display="flex" flexDirection="column" gap={2} mt={1}>
            <TextField
              label={t('app.name')}
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              fullWidth
            />
            <TextField
              label={t('schedules.cronExpression')}
              value={form.cron_expression}
              onChange={(e) => setForm((f) => ({ ...f, cron_expression: e.target.value }))}
              fullWidth
              helperText="Example: 0 * * * * (every hour)"
            />
            <FormControl fullWidth>
              <InputLabel>{t('schedules.targetType')}</InputLabel>
              <Select
                value={form.target_type}
                label={t('schedules.targetType')}
                onChange={(e) => setForm((f) => ({ ...f, target_type: e.target.value as 'agent' | 'sop' }))}
              >
                <MenuItem value="agent">{t('schedules.targetAgent')}</MenuItem>
                <MenuItem value="sop">{t('schedules.targetSop')}</MenuItem>
              </Select>
            </FormControl>
            <TextField
              label="Target ID"
              value={form.target_id}
              onChange={(e) => setForm((f) => ({ ...f, target_id: e.target.value }))}
              fullWidth
              helperText="UUID of the agent type or SOP"
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
