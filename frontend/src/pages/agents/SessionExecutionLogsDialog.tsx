import { useEffect, useState } from 'react'
import {
  Box,
  Chip,
  Dialog,
  DialogContent,
  DialogTitle,
  IconButton,
  Paper,
  Stack,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import RefreshIcon from '@mui/icons-material/Refresh'
import { useTranslation } from 'react-i18next'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'

interface ExecutionLogEntry {
  id: string
  timestamp: string
  event_type: string
  log_level: string
  message: string
  data: Record<string, unknown>
}

interface Props {
  open: boolean
  sessionId: string | null
  onClose: () => void
}

export function SessionExecutionLogsDialog({ open, sessionId, onClose }: Props) {
  const { t } = useTranslation()
  const [logs, setLogs] = useState<ExecutionLogEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [dialogError, setDialogError] = useState<unknown>(null)

  const fetchLogs = async () => {
    if (!sessionId) return
    try {
      setLoading(true)
      setDialogError(null)
      const { data } = await apiClient.get<ExecutionLogEntry[]>(
        `/agents/sessions/${sessionId}/logs`
      )
      setLogs(data)
    } catch (err) {
      setDialogError(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open && sessionId) {
      void fetchLogs()
    }
  }, [open, sessionId])

  const handleClose = () => {
    setDialogError(null)
    onClose()
  }

  const getEventTypeColor = (
    eventType: string
  ): 'primary' | 'secondary' | 'error' | 'default' => {
    switch (eventType) {
      case 'llm_call':
        return 'primary'
      case 'tool_call':
        return 'secondary'
      case 'error':
        return 'error'
      default:
        return 'default'
    }
  }

  const formatTimestamp = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      fractionalSecondDigits: 3,
    } as Intl.DateTimeFormatOptions)
  }

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="lg" fullWidth>
      <DialogTitle>
        <Box display="flex" alignItems="center" justifyContent="space-between">
          <Typography variant="h6">{t('agents.sessions.executionLogs')}</Typography>
          <Box>
            <IconButton
              onClick={() => void fetchLogs()}
              disabled={loading}
              aria-label={t('agents.sessions.refreshLogs')}
            >
              <RefreshIcon />
            </IconButton>
            <IconButton onClick={handleClose} aria-label={t('app.close')}>
              <CloseIcon />
            </IconButton>
          </Box>
        </Box>
      </DialogTitle>
      <DialogContent>
        {dialogError != null && (
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
        )}
        {loading && (
          <Typography color="text.secondary">{t('app.loading')}</Typography>
        )}
        {!loading && !dialogError && logs.length === 0 && (
          <Typography color="text.secondary">{t('agents.sessions.noLogsAvailable')}</Typography>
        )}
        <Stack spacing={1} mt={dialogError || logs.length > 0 ? 2 : 0}>
          {logs.map((log) => (
            <Paper key={log.id} sx={{ p: 2 }} variant="outlined">
              <Box display="flex" gap={1} alignItems="center" mb={1}>
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ minWidth: 100 }}
                >
                  {formatTimestamp(log.timestamp)}
                </Typography>
                <Chip
                  label={log.event_type}
                  size="small"
                  color={getEventTypeColor(log.event_type)}
                />
                <Typography variant="body2" sx={{ flex: 1 }}>
                  {log.message}
                </Typography>
              </Box>
              {Object.keys(log.data).length > 0 && (
                <Box
                  component="pre"
                  sx={{
                    bgcolor: 'grey.100',
                    p: 1,
                    borderRadius: 1,
                    fontSize: '0.75rem',
                    overflow: 'auto',
                    maxHeight: 200,
                    m: 0,
                  }}
                >
                  {JSON.stringify(log.data, null, 2)}
                </Box>
              )}
            </Paper>
          ))}
        </Stack>
      </DialogContent>
    </Dialog>
  )
}
