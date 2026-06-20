import { useCallback, useEffect, useRef, useState } from 'react'
import { Box, Dialog, DialogContent, DialogTitle, IconButton, Paper, Tab, Tabs, Typography } from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import { useTranslation } from 'react-i18next'
import { LogViewer } from '../executions/LogViewer'

import { InterventionPendingBanner } from '../executions/InterventionPendingBanner'
import { OutputTypeResultTab } from '../executions/OutputTypeResultTab'
import { InterveneResponseDialog } from './InterveneResponseDialog'
import { useExecutionLogs } from '../../hooks/useExecutionLogs'
import { useSessionExecutionLogStream } from '../../hooks/useSessionExecutionLogStream'
import * as interveneApi from '../../api/interveneApi'
import apiClient from '../../api/apiClient'
import type { AgentJob, AgentJobStatus, AgentOutputType, ExecutionLogEntry, InterveneRequest } from '../../types'

// ── Props ─────────────────────────────────────────────────────────────────────

interface AgentExecutionDetailsDialogProps {
  open: boolean
  onClose: () => void
  sessionId: string
}

// ── Tab definition ─────────────────────────────────────────────────────────────

interface TabDef {
  key: string
  label: string
  badge?: string
}

// ── Constants ──────────────────────────────────────────────────────────────────

const TERMINAL_STATUSES: AgentJobStatus[] = ['completed', 'failed', 'terminated']

// ── Component ──────────────────────────────────────────────────────────────────

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
  const [subAgentDialogSessionId, setSubAgentDialogSessionId] = useState<string | null>(null)
  const logEndRef = useRef<HTMLDivElement | null>(null)
  const prevLogCountRef = useRef(0)
  const interventionRef = useRef<HTMLDivElement | null>(null)
  const handleViewSubAgentExecution = useCallback((sid: string) => {
    setSubAgentDialogSessionId(sid)
  }, [])

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

  // ── Helpers ──────────────────────────────────────────────────────────────────

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

  // ── Initial load ─────────────────────────────────────────────────────────────

  useEffect(() => {
    if (open) {
      setLoading(true)
      setInlineDialogDismissed(false)
      setInlineInterventionRequest(null)
      setAutoDialogOpen(false)
      setAutoDialogRequest(null)
      autoDialogShownRef.current = null
      Promise.all([
        fetchLogEntries(),
        fetchSession(),
        fetchConversationHistory(),
      ]).finally(() => setLoading(false))
    }
  }, [open, sessionId, fetchLogEntries, fetchSession, fetchConversationHistory])

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

  // Reset tab on session change
  useEffect(() => {
    if (open) {
      setActiveTab(0)
    }
  }, [open, sessionId])

  // Auto-scroll log to bottom on new entries
  useEffect(() => {
    const previousCount = prevLogCountRef.current
    const currentCount = logEntries.length
    prevLogCountRef.current = currentCount
    if (!open || currentCount <= previousCount) return
    logEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [open, logEntries.length])

  // ── Determine available tabs ─────────────────────────────────────────────────

  const hasExecutionLogs = logEntries.length > 0 || execLogs.length > 0
  const hasResult = !!session && TERMINAL_STATUSES.includes(session.status)
  const hasConversationHistory = !!conversationHistory && conversationHistory.length > 0

  const allTabs: TabDef[] = []
  if (hasExecutionLogs) {
    allTabs.push({ key: 'execution', label: t('agents.executionLogs.title', { defaultValue: 'Execution' }) })
  }
  if (hasResult) {
    const outputType = session?.output_data?.['__output_type'] as AgentOutputType | undefined
    const label = outputType
      ? `${t('agents.sessions.result', { defaultValue: 'Result' })}`
      : t('agents.sessions.result', { defaultValue: 'Result' })
    allTabs.push({ key: 'result', label, badge: outputType })
  }
  if (hasConversationHistory) {
    allTabs.push({ key: 'history', label: t('agents.sessions.conversationHistory', { defaultValue: 'Conversation History' }) })
  }

  const safeActiveTab = allTabs.length > 0 ? Math.min(activeTab, allTabs.length - 1) : 0

  // ── Inline intervention dialog state (for execution tab) ────────────────────

  const [inlineInterventionRequest, setInlineInterventionRequest] = useState<InterveneRequest | null>(null)
  const [inlineDialogDismissed, setInlineDialogDismissed] = useState(false)
  const inlineDialogShownRef = useRef<string | null>(null)

  // ── Auto-popup modal intervene dialog ───────────────────────────────────────

  const [autoDialogOpen, setAutoDialogOpen] = useState(false)
  const [autoDialogRequest, setAutoDialogRequest] = useState<InterveneRequest | null>(null)
  const autoDialogShownRef = useRef<string | null>(null)

  // ── Stream event → show inline or modal dialog ─────────────────────────────

  useEffect(() => {
    if (!humanInterveneEvent) return
    const showDialog = async () => {
      try {
        const request = await interveneApi.getInterveneRequest(humanInterveneEvent.request_id)
        if (request && request.status === 'pending') {
          autoDialogShownRef.current = request.id
          // Show as inline dialog if we're on the execution tab
          setInlineInterventionRequest(request)
          setInlineDialogDismissed(false)
          inlineDialogShownRef.current = request.id
          setAutoDialogRequest(request)
          setAutoDialogOpen(true)
        }
      } catch {
        // Best-effort
      } finally {
        clearHumanInterveneEvent()
      }
    }
    void showDialog()
  }, [humanInterveneEvent, clearHumanInterveneEvent])

  // ── Session status waiting_for_human → fetch pending interventions ──────────

  useEffect(() => {
    if (sessionStatus !== 'waiting_for_human') return
    const fetchAndShow = async () => {
      try {
        const pending = await interveneApi.getPendingInterventionForSession(sessionId)
        if (pending && pending.status === 'pending') {
          if (autoDialogShownRef.current !== pending.id && inlineDialogShownRef.current !== pending.id) {
            autoDialogShownRef.current = pending.id
            inlineDialogShownRef.current = pending.id
            setAutoDialogRequest(pending)
            setAutoDialogOpen(true)
            setInlineInterventionRequest(pending)
            setInlineDialogDismissed(false)
          }
        }
      } catch {
        // Best-effort
      }
    }
    void fetchAndShow()
  }, [sessionStatus, sessionId])

  // ── Pending intervention check on dialog open ───────────────────────────────

  useEffect(() => {
    if (!open) return
    const checkPending = async () => {
      try {
        const pending = await interveneApi.getPendingInterventionForSession(sessionId)
        if (pending && pending.status === 'pending') {
          if (autoDialogShownRef.current !== pending.id && inlineDialogShownRef.current !== pending.id) {
            autoDialogShownRef.current = pending.id
            inlineDialogShownRef.current = pending.id
            setInlineInterventionRequest(pending)
            setInlineDialogDismissed(false)
            setAutoDialogRequest(pending)
            setAutoDialogOpen(true)
          }
        }
      } catch {
        // Best-effort
      }
    }
    void checkPending()
    // Only run on initial open, not on every render
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // ── Handlers ────────────────────────────────────────────────────────────────

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

  const handleTerminateSession = useCallback(
    async (sessionId: string, _requestId: string) => {
      await interveneApi.terminateSession(sessionId, 'Operator terminated from sub-agent execution dialog')
      handleAutoDialogClose()
      setInlineDialogDismissed(true)
      setInlineInterventionRequest(null)
    },
    [handleAutoDialogClose],
  )

  const handleInlineSubmit = useCallback(
    async (requestId: string, value: {
      approval_value?: boolean
      selected_choice?: string
      text_value?: string
    }) => {
      await interveneApi.submitInterveneResponse(requestId, {
        request_id: requestId,
        ...value,
      })
      // Update local state to reflect responded status so the pending banner hides
      setInlineInterventionRequest((prev) =>
        prev && prev.id === requestId
          ? { ...prev, status: 'responded' }
          : prev,
      )
      setAutoDialogRequest((prev) =>
        prev && prev.id === requestId
          ? { ...prev, status: 'responded' }
          : prev,
      )
      // Close the modal dialog if open
      setAutoDialogOpen(false)
    },
    [],
  )

  const handleInlineDismiss = useCallback(() => {
    setInlineDialogDismissed(true)
  }, [])

  const handleRespondNow = useCallback(() => {
    setInlineDialogDismissed(false)
    // Scroll to the inline intervention dialog after a brief delay for re-render
    setTimeout(() => {
      interventionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 100)
  }, [])

  // ── Computed state for pending banner ───────────────────────────────────────

  const isInterventionPending = !!inlineInterventionRequest && inlineInterventionRequest.status === 'pending'
  const showPendingBanner = isInterventionPending && (inlineDialogDismissed || safeActiveTab !== 0)

  // Extract output_type from session data
  const outputType: AgentOutputType = (session?.output_data?.['__output_type'] as AgentOutputType) ?? 'auto'
  const outputSchema = (session?.output_data?.['__schema'] as Record<string, unknown> | undefined) ?? undefined

  // ── Render ──────────────────────────────────────────────────────────────────

  return (<>
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
            <Tab
              key={tab.key}
              label={
                tab.badge ? (
                  <Box display="flex" alignItems="center" gap={0.75}>
                    <span>{tab.label}</span>
                    <Box
                      component="span"
                      sx={{
                        fontSize: 9.5,
                        px: 0.75,
                        py: 0.25,
                        borderRadius: 1.5,
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        letterSpacing: 0.3,
                        lineHeight: 1.4,
                        bgcolor: tab.badge === 'markdown'
                          ? '#EDE9FE'
                          : tab.badge === 'typed'
                            ? '#DBEAFE'
                            : '#DCFCE7',
                        color: tab.badge === 'markdown'
                          ? '#7C3AED'
                          : tab.badge === 'typed'
                            ? '#1D4ED8'
                            : '#15803D',
                      }}
                    >
                      {tab.badge}
                    </Box>
                  </Box>
                ) : (
                  tab.label
                )
              }
            />
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

        {/* ═══════════════════════════════ Execution tab ═══════════════════════ */}
        {allTabs[safeActiveTab]?.key === 'execution' && !execLogsLoading && (
          <>
            {/* Pending intervention banner (shown when modal is dismissed) */}
            <InterventionPendingBanner
              pending={showPendingBanner}
              subAgentName={inlineInterventionRequest?.agent_name ?? ''}
              interventionType={inlineInterventionRequest?.intervention_type ?? ''}
              pendingSince={inlineInterventionRequest?.created_at ?? ''}
              onRespond={handleRespondNow}
            />

            {/* Main LogViewer */}
            <LogViewer
              executionLog={execLogs[0] ?? null}
              entries={logEntries}
              sessionStatus={sessionStatus}
              onViewSubAgentExecution={handleViewSubAgentExecution}
            />

            {/* Inline intervention dialog is NOT rendered here — the modal
                InterveneResponseDialog (rendered below the Dialog) is used
                for all tabs, ensuring the user always sees a prominent popup. */}

            <div ref={logEndRef} aria-hidden="true" />
          </>
        )}

        {/* ═══════════════════════════════ Result tab ══════════════════════════ */}
        {allTabs[safeActiveTab]?.key === 'result' && session && (
          <Paper sx={{ p: 3, mt: 1 }}>
            <OutputTypeResultTab
              outputType={outputType}
              outputData={session.output_data}
              outputSchema={outputSchema}
            />
          </Paper>
        )}

        {/* ═══════════════════════════════ History tab ════════════════════════ */}
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

      {/* Modal intervene dialog (always shown as popup when triggered) */}
      <InterveneResponseDialog
        open={autoDialogOpen}
        request={autoDialogRequest}
        onClose={handleAutoDialogClose}
        onSubmit={handleAutoDialogSubmit}
        onTerminate={handleTerminateSession}
      />
    </Dialog>

      {/* Sub-agent execution log dialog (opened from delegation entry) */}
      {subAgentDialogSessionId && (
        <AgentExecutionDetailsDialog
          open
          onClose={() => setSubAgentDialogSessionId(null)}
          sessionId={subAgentDialogSessionId}
        />
      )}
    </>)
}
