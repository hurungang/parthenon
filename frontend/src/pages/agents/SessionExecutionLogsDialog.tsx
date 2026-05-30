import { useEffect, useState } from 'react'
import {
  Box,
  Dialog,
  DialogContent,
  DialogTitle,
  IconButton,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import RefreshIcon from '@mui/icons-material/Refresh'
import { useTranslation } from 'react-i18next'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { LogViewer } from '../../components/executions/LogViewer'
import { useExecutionLogs } from '../../hooks/useExecutionLogs'
import { useSessionExecutionLogStream } from '../../hooks/useSessionExecutionLogStream'
import type { AgentJobStatus, ExecutionLogEntry } from '../../types'

function mergeLogEntries(existing: ExecutionLogEntry[], incoming: ExecutionLogEntry[]): ExecutionLogEntry[] {
  const map = new Map<string, ExecutionLogEntry>()
  for (const entry of existing) {
    map.set(entry.id, entry)
  }
  for (const entry of incoming) {
    map.set(entry.id, entry)
  }
  return Array.from(map.values()).sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
  )
}

interface Props {
  open: boolean
  sessionId: string | null
  onClose: () => void
}

export function SessionExecutionLogsDialog({ open, sessionId, onClose }: Props) {
  const { t } = useTranslation()
  const [logs, setLogs] = useState<ExecutionLogEntry[]>([])
  const [sessionStatus, setSessionStatus] = useState<AgentJobStatus | undefined>(undefined)
  const [loading, setLoading] = useState(false)
  const [dialogError, setDialogError] = useState<unknown>(null)
  const { logs: execLogs, loading: execLogsLoading } = useExecutionLogs(sessionId)

  const { entries: streamedEntries } = useSessionExecutionLogStream({
    sessionId,
    enabled: open,
    sessionStatus,
  })

  const fetchLogs = async () => {
    if (!sessionId) return
    try {
      setLoading(true)
      setDialogError(null)
      const { data } = await apiClient.get<ExecutionLogEntry[]>(
        `/agents/sessions/${sessionId}/logs`
      )
      setLogs(data)
      const statusResponse = await apiClient.get<{ status: AgentJobStatus }>(`/agents/sessions/${sessionId}`)
      setSessionStatus(statusResponse.data.status)
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

  useEffect(() => {
    if (!streamedEntries.length) {
      return
    }
    setLogs((prev) => mergeLogEntries(prev, streamedEntries))
  }, [streamedEntries])

  const handleClose = () => {
    setDialogError(null)
    onClose()
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
        {!loading && !dialogError && !execLogsLoading && logs.length === 0 && execLogs.length === 0 && (
          <Typography color="text.secondary">{t('agents.sessions.noLogsAvailable')}</Typography>
        )}
        {!loading && !dialogError && !execLogsLoading && (logs.length > 0 || execLogs.length > 0) && (
          <LogViewer
            executionLog={execLogs[0] ?? null}
            entries={logs}
            sessionStatus={sessionStatus}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
