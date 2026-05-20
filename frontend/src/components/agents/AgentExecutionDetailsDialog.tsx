import { useCallback, useEffect, useState } from 'react'
import { Dialog, DialogContent, DialogTitle, IconButton, Tab, Tabs, Typography } from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import { useTranslation } from 'react-i18next'
import { AgentJobPage } from '../../pages/agents/AgentJobPage'
import { LogViewer } from '../logs/LogViewer'
import { useExecutionLogs } from '../../hooks/useExecutionLogs'
import apiClient from '../../api/apiClient'
import type { ExecutionLogEntry } from '../../types'

interface AgentExecutionDetailsDialogProps {
  open: boolean
  onClose: () => void
  sessionId: string
}

/**
 * Dialog wrapper for AgentJobPage + span-based execution logs (LogViewer).
 * Tab 0 — Session Details (AgentJobPage)
 * Tab 1 — Execution Logs  (LogViewer with WorkingStepsPanel - proper span visualization)
 */
export function AgentExecutionDetailsDialog({
  open,
  onClose,
  sessionId,
}: AgentExecutionDetailsDialogProps) {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState(0)
  const [logEntries, setLogEntries] = useState<ExecutionLogEntry[]>([])

  // Fetch execution logs (system instruction + user prompt)
  const { logs: execLogs, loading: execLogsLoading } = useExecutionLogs(sessionId)

  // Fetch log entries for detailed span visualization
  const fetchLogEntries = useCallback(async () => {
    try {
      const { data } = await apiClient.get<ExecutionLogEntry[]>(`/agents/sessions/${sessionId}/logs`)
      setLogEntries(data)
    } catch {
      setLogEntries([])
    }
  }, [sessionId])

  useEffect(() => {
    if (open && activeTab === 1) {
      void fetchLogEntries()
    }
  }, [open, activeTab, fetchLogEntries])

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="xl"
      fullWidth
      PaperProps={{ sx: { width: { xs: '100%', sm: '90%', lg: '95%' } } }}
    >
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Typography variant="h6" component="span">
          {t('agents.sessions.detailsTitle')}
        </Typography>
        <IconButton edge="end" onClick={onClose} size="small">
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <Tabs
        value={activeTab}
        onChange={(_, v: number) => setActiveTab(v)}
        sx={{ px: 3, borderBottom: 1, borderColor: 'divider' }}
      >
        <Tab label={t('agents.sessions.detailsTitle')} />
        <Tab label={t('agents.executionLogs.title', { defaultValue: 'Execution Logs' })} />
      </Tabs>
      <DialogContent>
        {activeTab === 0 && <AgentJobPage sessionId={sessionId} hideResults={true} hideLogs={true} />}
        {activeTab === 1 && !execLogsLoading && (logEntries.length > 0 || execLogs.length > 0) ? (
          <LogViewer
            executionLog={execLogs[0] ?? null}
            entries={logEntries}
          />
        ) : activeTab === 1 && !execLogsLoading ? (
          <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
            {t('agents.executionLogs.noLogs', { defaultValue: 'No execution logs available.' })}
          </Typography>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
