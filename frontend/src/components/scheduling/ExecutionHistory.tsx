import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
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
  TablePagination,
  TableRow,
  Typography,
  Button,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import { useQuery } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import { AgentExecutionDetailsDialog } from '../agents/AgentExecutionDetailsDialog'
import type { JobExecution } from '../../types'

interface ExecutionHistoryProps {
  jobId: string
  open: boolean
  onClose: () => void
}

export default function ExecutionHistory({ jobId, open, onClose }: ExecutionHistoryProps) {
  const { t } = useTranslation()
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(25)
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)

  const { data: executions, isLoading, error } = useQuery<JobExecution[]>({
    queryKey: ['executions', jobId, page, rowsPerPage],
    queryFn: async () => {
      const { data } = await apiClient.get<JobExecution[]>(`/schedules/${jobId}/executions`, {
        params: { limit: rowsPerPage, offset: page * rowsPerPage },
      })
      return data
    },
    enabled: open,
  })

  const statusColor = (status: string) => {
    if (status === 'success') return 'success'
    if (status === 'failure') return 'error'
    if (status === 'running') return 'info'
    return 'default'
  }

  const agentStatusColor = (status: string) => {
    if (status === 'completed') return 'success'
    if (status === 'failed' || status === 'terminated') return 'error'
    if (status === 'running') return 'info'
    if (status === 'waiting_for_human') return 'warning'
    return 'default'
  }

  return (
    <>
      <Dialog open={open} onClose={() => { setPage(0); onClose() }} maxWidth="md" fullWidth>
        <DialogTitle>
          {t('schedules.executions')}
          <IconButton
            aria-label="close"
            onClick={() => { setPage(0); onClose() }}
            sx={{ position: 'absolute', right: 8, top: 8 }}
          >
            <CloseIcon />
          </IconButton>
        </DialogTitle>
        <DialogContent>
          {error && <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />}
          {isLoading ? (
            <CircularProgress />
          ) : !executions || executions.length === 0 ? (
            <Typography color="text.secondary">{t('schedules.noExecutions')}</Typography>
          ) : (
            <TableContainer component={Paper} variant="outlined">
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>{t('schedules.startedAt')}</TableCell>
                    <TableCell>{t('schedules.finishedAt')}</TableCell>
                    <TableCell>{t('app.status')}</TableCell>
                    <TableCell>{t('schedules.agentSession')}</TableCell>
                    <TableCell>{t('app.description')}</TableCell>
                    <TableCell align="center">{t('app.actions')}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {executions.map((exec) => (
                    <TableRow key={exec.id}>
                      <TableCell>{new Date(exec.started_at).toLocaleString()}</TableCell>
                      <TableCell>
                        {exec.finished_at ? new Date(exec.finished_at).toLocaleString() : '-'}
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={exec.status}
                          color={statusColor(exec.status) as 'success' | 'error' | 'info' | 'default'}
                          size="small"
                        />
                      </TableCell>
                      <TableCell>
                        {exec.agent_session ? (
                          <Chip
                            label={exec.agent_session.status}
                            color={agentStatusColor(exec.agent_session.status) as 'success' | 'error' | 'info' | 'warning' | 'default'}
                            size="small"
                            variant="outlined"
                          />
                        ) : (
                          <Typography variant="body2" color="text.secondary">-</Typography>
                        )}
                      </TableCell>
                      <TableCell sx={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {exec.error || (exec.agent_session?.error_message) || '-'}
                      </TableCell>
                      <TableCell align="center">
                        {exec.agent_session && (
                          <IconButton
                            size="small"
                            data-testid={`view-agent-session-${exec.id}`}
                            onClick={() => setSelectedSessionId(exec.agent_session!.id)}
                            title={t('schedules.viewAgentSession')}
                          >
                            <OpenInNewIcon fontSize="small" />
                          </IconButton>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
          {executions && executions.length > 0 && (
            <TablePagination
              component="div"
              count={-1}
              page={page}
              onPageChange={(_, newPage) => setPage(newPage)}
              rowsPerPage={rowsPerPage}
              onRowsPerPageChange={(e) => {
                setRowsPerPage(parseInt(e.target.value, 10))
                setPage(0)
              }}
              rowsPerPageOptions={[10, 25, 50, 100]}
              labelRowsPerPage={t('app.rowsPerPage')}
            />
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setPage(0); onClose() }}>{t('app.close')}</Button>
        </DialogActions>
      </Dialog>
      {selectedSessionId && (
        <AgentExecutionDetailsDialog
          open={!!selectedSessionId}
          onClose={() => setSelectedSessionId(null)}
          sessionId={selectedSessionId}
        />
      )}
    </>
  )
}
