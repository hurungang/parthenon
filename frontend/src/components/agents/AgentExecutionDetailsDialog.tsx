import { useCallback, useEffect, useRef, useState } from 'react'
import { Box, Dialog, DialogContent, DialogTitle, IconButton, Paper, Tab, Tabs, Typography } from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import { useTranslation } from 'react-i18next'
import { AgentJobPage } from '../../pages/agents/AgentJobPage'
import { LogViewer } from '../executions/LogViewer'
import { useExecutionLogs } from '../../hooks/useExecutionLogs'
import { useSessionExecutionLogStream } from '../../hooks/useSessionExecutionLogStream'
import { InterveneResponseDialog } from './InterveneResponseDialog'
import * as interveneApi from '../../api/interveneApi'
import apiClient from '../../api/apiClient'
import type { AgentJob, AgentJobStatus, ExecutionLogEntry, InterveneRequest } from '../../types'

interface AgentExecutionDetailsDialogProps {
  open: boolean
  onClose: () => void
  sessionId: string
}

interface TabDef {
  key: string
  label: string
}

const TERMINAL_STATUSES: AgentJobStatus[] = ['completed', 'failed', 'terminated']

export function AgentExecutionDetailsDialog({
  open,
  onClose,
  sessionId,
}: AgentExecutionDetailsDialogProps) {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState(0)
  const [logEntries, setLogEntries] = useState<ExecutionLogEntry[]>([])
  const [session, setSession] = useState<AgentJob | null>(null)
  const [sessionStatus, setSessionStatus] = useState<AgentJobStatus | undefined>(undefined)
  const [conversationHistory, setConversationHistory] = useState<Array<{ role: string; content: string }> | null>(null)
  const [loading, setLoading] = useState(true)
  const logEndRef = useRef<HTMLDivElement | null>(null)
  const prevLogCountRef = useRef(0)

  // Fetch execution logs (system instruction + user prompt)
  const { logs: execLogs, loading: execLogsLoading } = useExecutionLogs(sessionId)

  const {
    entries: streamedEntries,
    humanInterveneEvent,
    clearHumanInterveneEvent,
  } = useSessionExecutionLogStream({
    sessionId,
    enabled: open,
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

  const fetchLogEntries = useCallback(async () => {
    try {
      const { data } = await apiClient.get<ExecutionLogEntry[]>(`/agents/sessions/${sessionId}/logs`)
      setLogEntries(data)
    } catch {
      setLogEntries([])
    }
  }, [sessionId])

  const fetchSession = useCallback(async () => {
    try {
      const { data } = await apiClient.get<AgentJob>(`/agents/sessions/${sessionId}`)
      setSession(data)
      setSessionStatus(data.status)
    } catch {
      setSession(null)
      setSessionStatus(undefined)
    }
  }, [sessionId])

  const fetchConversationHistory = useCallback(async () => {
    try {
      const { data } = await apiClient.get<Array<{ role: string; content: string }>>(
        `/agents/sessions/${sessionId}/history`,
      )
      setConversationHistory(data)
    } catch {
      setConversationHistory(null)
    }
  }, [sessionId])

  useEffect(() => {
    if (open) {
      setLoading(true)
      Promise.all([
        fetchLogEntries(),
        fetchSession(),
        fetchConversationHistory(),
      ]).finally(() => setLoading(false))
    }
  }, [open, fetchLogEntries, fetchSession, fetchConversationHistory])

  // Poll session status while non-terminal for live updates
  useEffect(() => {
    if (!open) return
    if (sessionStatus && TERMINAL_STATUSES.includes(sessionStatus)) return
    const pollHandle = window.setInterval(() => {
      void apiClient
        .get<{ status: AgentJobStatus }>(`/agents/sessions/${sessionId}`)
        .then(({ data }) => {
          setSessionStatus(data.status)
        })
        .catch(() => {})
    }, 3000)
    return () => {
      window.clearInterval(pollHandle)
    }
  }, [open, sessionId, sessionStatus])

  useEffect(() => {
    if (!streamedEntries.length) return
    setLogEntries((prev) => mergeLogEntries(prev, streamedEntries))
  }, [streamedEntries])

  useEffect(() => {
    if (open) {
      setActiveTab(0)
    }
  }, [open, sessionId])

  useEffect(() => {
    const previousCount = prevLogCountRef.current
    const currentCount = logEntries.length
    prevLogCountRef.current = currentCount
    if (!open || currentCount <= previousCount) return
    logEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [open, logEntries.length])

  // Determine available tabs
  const hasExecutionLogs = logEntries.length > 0 || execLogs.length > 0
  const hasResult = !!session && TERMINAL_STATUSES.includes(session.status)
  const hasConversationHistory = !!conversationHistory && conversationHistory.length > 0

  const allTabs: TabDef[] = []
  if (hasExecutionLogs) allTabs.push({ key: 'execution', label: t('agents.executionLogs.title', { defaultValue: 'Execution' }) })
  if (hasResult) allTabs.push({ key: 'result', label: t('agents.sessions.result', { defaultValue: 'Result' }) })
  if (hasConversationHistory) allTabs.push({ key: 'history', label: t('agents.sessions.conversationHistory', { defaultValue: 'Conversation History' }) })

  const safeActiveTab = allTabs.length > 0 ? Math.min(activeTab, allTabs.length - 1) : 0

  // ── Auto-popup intervene dialog ──
  const [autoDialogOpen, setAutoDialogOpen] = useState(false)
  const [autoDialogRequest, setAutoDialogRequest] = useState<InterveneRequest | null>(null)
  const autoDialogShownRef = useRef<string | null>(null)

  useEffect(() => {
    if (!humanInterveneEvent) return
    const showDialog = async () => {
      try {
        const request = await interveneApi.getInterveneRequest(humanInterveneEvent.request_id)
        if (request && request.status === 'pending') {
          autoDialogShownRef.current = request.id
          setAutoDialogRequest(request)
          setAutoDialogOpen(true)
        }
      } catch {
      } finally {
        clearHumanInterveneEvent()
      }
    }
    void showDialog()
  }, [humanInterveneEvent, clearHumanInterveneEvent])

  useEffect(() => {
    if (sessionStatus !== 'waiting_for_human') return
    const fetchAndShow = async () => {
      try {
        const requests = await interveneApi.getInterveneRequests({
          agent_session_id: sessionId,
          status: 'pending',
        })
        if (requests.length > 0) {
          const req = requests[0]
          if (autoDialogShownRef.current !== req.id) {
            autoDialogShownRef.current = req.id
            setAutoDialogRequest(req)
            setAutoDialogOpen(true)
          }
        }
      } catch {
      }
    }
    void fetchAndShow()
  }, [sessionStatus, sessionId])

  const handleAutoDialogClose = useCallback(() => {
    setAutoDialogOpen(false)
    setAutoDialogRequest(null)
  }, [])

  const handleAutoDialogSubmit = useCallback(
    async (requestId: string, value: {
      approval_value?: boolean
      selected_choice?: string
      text_value?: string
    }) => {
      await interveneApi.submitInterveneResponse(requestId, {
        request_id: requestId,
        ...value,
      })
      handleAutoDialogClose()
    },
    [handleAutoDialogClose],
  )

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
      {allTabs.length > 1 && (
        <Tabs
          value={safeActiveTab}
          onChange={(_, v: number) => setActiveTab(v)}
          sx={{ px: 3, borderBottom: 1, borderColor: 'divider' }}
        >
          {allTabs.map((tab) => (
            <Tab key={tab.key} label={tab.label} />
          ))}
        </Tabs>
      )}
      <DialogContent>
        {loading && allTabs.length === 0 && (
          <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
            {t('agents.sessions.loading', { defaultValue: 'Loading session data…' })}
          </Typography>
        )}
        {!loading && allTabs.length === 0 && (
          <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
            {t('agents.sessions.noData', { defaultValue: 'No data available for this session.' })}
          </Typography>
        )}

        {/* Execution tab */}
        {allTabs[safeActiveTab]?.key === 'execution' && !execLogsLoading && (
          <>
            <LogViewer
              executionLog={execLogs[0] ?? null}
              entries={logEntries}
              sessionStatus={sessionStatus}
            />
            <div ref={logEndRef} aria-hidden="true" />
          </>
        )}

        {/* Result tab */}
        {allTabs[safeActiveTab]?.key === 'result' && (
          <AgentJobPage
            sessionId={sessionId}
            hideLogs={true}
            hideResults={false}
          />
        )}

        {/* Conversation History tab */}
        {allTabs[safeActiveTab]?.key === 'history' && (
          <Box sx={{ py: 2 }}>
            {conversationHistory && conversationHistory.length > 0 ? (
              <Box display="flex" flexDirection="column" gap={1.5}>
                {conversationHistory.map((msg, idx) => (
                  <Box
                    key={idx}
                    alignSelf={msg.role === 'user' ? 'flex-end' : 'flex-start'}
                    sx={{ maxWidth: '80%' }}
                  >
                    <Typography variant="caption" color="text.secondary" display="block" mb={0.25}
                      textAlign={msg.role === 'user' ? 'right' : 'left'}>
                      {msg.role}
                    </Typography>
                    <Paper
                      variant="outlined"
                      sx={{
                        px: 1.5,
                        py: 1,
                        bgcolor: msg.role === 'user' ? 'primary.50' : msg.role === 'tool' ? 'grey.100' : 'background.paper',
                        borderRadius: 2,
                      }}
                    >
                      <Typography
                        variant="body2"
                        sx={{ whiteSpace: 'pre-wrap', fontFamily: msg.role === 'tool' ? 'monospace' : undefined }}
                      >
                        {msg.content}
                      </Typography>
                    </Paper>
                  </Box>
                ))}
              </Box>
            ) : (
              <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
                {t('agents.sessions.noHistory', { defaultValue: 'No conversation history available.' })}
              </Typography>
            )}
          </Box>
        )}
      </DialogContent>
      <InterveneResponseDialog
        open={autoDialogOpen}
        request={autoDialogRequest}
        onClose={handleAutoDialogClose}
        onSubmit={handleAutoDialogSubmit}
      />
    </Dialog>
  )
}
