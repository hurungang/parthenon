import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Chip,
  CircularProgress,
  Drawer,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  Typography,
} from '@mui/material'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { listNotificationLogs } from '../../services/notificationService'
import type { DeliveryStatus, NotificationLog } from '../../types'

const STATUS_OPTIONS: DeliveryStatus[] = ['pending', 'delivered', 'failed']

export function NotificationLogPage() {
  const { t } = useTranslation()

  const [logs, setLogs] = useState<NotificationLog[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)

  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(25)
  const [statusFilter, setStatusFilter] = useState<string>('')

  const [selectedLog, setSelectedLog] = useState<NotificationLog | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  const fetchLogs = async () => {
    setIsLoading(true)
    setError(null)
    try {
      const data = await listNotificationLogs({
        log_status: statusFilter || undefined,
        limit: rowsPerPage,
        offset: page * rowsPerPage,
      })
      setLogs(data)
    } catch (err) {
      setError(err)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    void fetchLogs()
  }, [page, rowsPerPage, statusFilter])

  const handleStatusFilter = (s: string) => {
    setStatusFilter(s === statusFilter ? '' : s)
    setPage(0)
  }

  const openDetail = (log: NotificationLog) => {
    setSelectedLog(log)
    setDrawerOpen(true)
  }

  const statusColor = (status: DeliveryStatus) => {
    if (status === 'delivered') return 'success'
    if (status === 'failed') return 'error'
    return 'warning'
  }

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h4" fontWeight={700}>
          {t('notifications.logs.title')}
        </Typography>
      </Box>

      {!!error && (
        <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />
      )}

      {/* Filters */}
      <Stack direction="row" spacing={1} mb={2} flexWrap="wrap">
        <Typography variant="body2" alignSelf="center">
          {t('notifications.logs.filterStatus')}:
        </Typography>
        {STATUS_OPTIONS.map((s) => (
          <Chip
            key={s}
            label={t(`notifications.status.${s}`)}
            onClick={() => handleStatusFilter(s)}
            color={statusFilter === s ? statusColor(s) : 'default'}
            variant={statusFilter === s ? 'filled' : 'outlined'}
            size="small"
          />
        ))}
        {statusFilter && (
          <Chip
            label={t('app.clearFilter')}
            onClick={() => setStatusFilter('')}
            size="small"
            variant="outlined"
          />
        )}
      </Stack>

      {isLoading ? (
        <Box display="flex" justifyContent="center" mt={4}>
          <CircularProgress />
        </Box>
      ) : (
        <Paper>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t('notifications.logs.timestamp')}</TableCell>
                  <TableCell>{t('notifications.logs.source')}</TableCell>
                  <TableCell>{t('notifications.logs.subject')}</TableCell>
                  <TableCell>{t('notifications.logs.recipient')}</TableCell>
                  <TableCell>{t('notifications.logs.status')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {logs.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} align="center">
                      <Typography variant="body2" color="text.secondary">
                        {t('notifications.logs.empty')}
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
                {logs.map((log) => (
                  <TableRow
                    key={log.id}
                    hover
                    sx={{ cursor: 'pointer' }}
                    onClick={() => openDetail(log)}
                  >
                    <TableCell>
                      {new Date(log.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={t(`notifications.sourceTypes.${log.source_type}`, log.source_type)}
                        size="small"
                        variant="outlined"
                      />
                    </TableCell>
                    <TableCell>
                      {log.subject ?? <Typography color="text.secondary" variant="body2">—</Typography>}
                    </TableCell>
                    <TableCell>
                      {log.recipient ?? <Typography color="text.secondary" variant="body2">—</Typography>}
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={t(`notifications.status.${log.status}`)}
                        size="small"
                        color={statusColor(log.status)}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
          <TablePagination
            component="div"
            count={-1}
            page={page}
            onPageChange={(_, p) => setPage(p)}
            rowsPerPage={rowsPerPage}
            onRowsPerPageChange={(e) => { setRowsPerPage(parseInt(e.target.value, 10)); setPage(0) }}
            rowsPerPageOptions={[10, 25, 50, 100]}
            labelRowsPerPage={t('app.rowsPerPage')}
          />
        </Paper>
      )}

      {/* Detail drawer */}
      <Drawer
        anchor="right"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        PaperProps={{ sx: { width: 420, p: 3 } }}
      >
        {selectedLog && (
          <Box>
            <Typography variant="h6" mb={2}>
              {t('notifications.logs.detail')}
            </Typography>
            <Stack spacing={1.5}>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  {t('notifications.logs.status')}
                </Typography>
                <Box mt={0.5}>
                  <Chip
                    label={t(`notifications.status.${selectedLog.status}`)}
                    size="small"
                    color={statusColor(selectedLog.status)}
                  />
                </Box>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  {t('notifications.logs.source')}
                </Typography>
                <Typography variant="body2">
                  {t(`notifications.sourceTypes.${selectedLog.source_type}`, selectedLog.source_type)}
                </Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  {t('notifications.logs.timestamp')}
                </Typography>
                <Typography variant="body2">
                  {new Date(selectedLog.created_at).toLocaleString()}
                </Typography>
              </Box>
              {selectedLog.subject && (
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    {t('notifications.logs.subject')}
                  </Typography>
                  <Typography variant="body2">{selectedLog.subject}</Typography>
                </Box>
              )}
              {selectedLog.recipient && (
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    {t('notifications.logs.recipient')}
                  </Typography>
                  <Typography variant="body2">{selectedLog.recipient}</Typography>
                </Box>
              )}
              <Box>
                <Typography variant="caption" color="text.secondary">
                  {t('notifications.logs.body')}
                </Typography>
                <Typography variant="body2" whiteSpace="pre-wrap">
                  {selectedLog.body}
                </Typography>
              </Box>
              {selectedLog.error && (
                <Box>
                  <Typography variant="caption" color="error">
                    {t('notifications.logs.error')}
                  </Typography>
                  <Typography variant="body2" color="error">
                    {selectedLog.error}
                  </Typography>
                </Box>
              )}
              {selectedLog.metadata_ && (
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    {t('notifications.logs.metadata')}
                  </Typography>
                  <Typography
                    variant="body2"
                    component="pre"
                    sx={{ fontSize: '0.75rem', overflow: 'auto' }}
                  >
                    {JSON.stringify(selectedLog.metadata_, null, 2)}
                  </Typography>
                </Box>
              )}
            </Stack>
          </Box>
        )}
      </Drawer>
    </Box>
  )
}
