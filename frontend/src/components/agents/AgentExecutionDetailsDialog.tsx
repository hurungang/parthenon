import { useCallback, useEffect, useRef, useState } from 'react'
import { Dialog, DialogContent, DialogTitle, IconButton, Tab, Tabs, Typography } from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import { useTranslation } from 'react-i18next'
import { AgentJobPage } from '../../pages/agents/AgentJobPage'
import { LogViewer } from '../executions/LogViewer'
import { useExecutionLogs } from '../../hooks/useExecutionLogs'
import { useSessionExecutionLogStream } from '../../hooks/useSessionExecutionLogStream'
import apiClient from '../../api/apiClient'
import type { AgentJobStatus, ExecutionLogEntry } from '../../types'

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
  const [activeTab, setActiveTab] = useState(1)
  const [logEntries, setLogEntries] = useState<ExecutionLogEntry[]>([])
  const [sessionStatus, setSessionStatus] = useState<AgentJobStatus | undefined>(undefined)
  const logEndRef = useRef<HTMLDivElement | null>(null)
  const prevLogCountRef = useRef(0)

  // Fetch execution logs (system instruction + user prompt)
  const { logs: execLogs, loading: execLogsLoading } = useExecutionLogs(sessionId)

  const { entries: streamedEntries } = useSessionExecutionLogStream({
    sessionId,
    enabled: open && activeTab === 1,
    sessionStatus,
  })

  const mergeLogEntries = (existing: ExecutionLogEntry[], incoming: ExecutionLogEntry[]) => {
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
      void apiClient
        .get<{ status: AgentJobStatus }>(`/agents/sessions/${sessionId}`)
        .then(({ data }) => setSessionStatus(data.status))
        .catch(() => setSessionStatus(undefined))
    }
  }, [open, activeTab, fetchLogEntries])

  // Re-fetch sessionStatus while the dialog is open and the session is
  // not yet in a terminal state.  Without this, the LogSummaryPanel's
  // status badge would stay stuck on "running" even after the session
  // fails — the working-steps log would show "failed" (because the
  // log entries were emitted) but the badge would be stale.
  useEffect(() => {
    if (!open || activeTab !== 1) {
      return
    }
    if (
      sessionStatus === 'completed' ||
      sessionStatus === 'failed' ||
      sessionStatus === 'terminated'
    ) {
      return
    }
    const pollHandle = window.setInterval(() => {
      void apiClient
        .get<{ status: AgentJobStatus }>(`/agents/sessions/${sessionId}`)
        .then(({ data }) => {
          setSessionStatus(data.status)
        })
        .catch(() => {
          /* ignore transient errors — the next tick will retry */
        })
    }, 3000)
    return () => {
      window.clearInterval(pollHandle)
    }
  }, [open, activeTab, sessionId, sessionStatus])

  useEffect(() => {
    if (!streamedEntries.length) {
      return
    }
    setLogEntries((prev) => mergeLogEntries(prev, streamedEntries))
  }, [streamedEntries])

  useEffect(() => {
    if (open) {
      setActiveTab(1)
    }
  }, [open, sessionId])

  useEffect(() => {
    const previousCount = prevLogCountRef.current
    const currentCount = logEntries.length
    prevLogCountRef.current = currentCount

    if (!open || activeTab !== 1 || currentCount <= previousCount) {
      return
    }

    logEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [open, activeTab, logEntries.length])

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
          <>
            <LogViewer
              executionLog={execLogs[0] ?? null}
              entries={logEntries}
              sessionStatus={sessionStatus}
            />
            <div ref={logEndRef} aria-hidden="true" />
          </>
        ) : activeTab === 1 && !execLogsLoading ? (
          <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
            {t('agents.executionLogs.noLogs', { defaultValue: 'No execution logs available.' })}
          </Typography>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
