import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Box, Button, CircularProgress, Dialog, DialogContent, DialogTitle, IconButton, Paper, Tab, Tabs, Typography } from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import { useTranslation } from 'react-i18next'
import { LogViewer } from '../executions/LogViewer'

import { OutputTypeResultTab } from '../executions/OutputTypeResultTab'
import { InterveneResponseDialog } from './InterveneResponseDialog'
import { useExecutionLogs } from '../../hooks/useExecutionLogs'
import { useSessionExecutionLogStream } from '../../hooks/useSessionExecutionLogStream'
import { useTypedOutput } from '../../hooks/useTypedOutput'
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
  
  // ── All state declarations first (React Rules of Hooks) ─────────────────────
  const [activeTab, setActiveTab] = useState(0)
  const [logEntries, setLogEntries] = useState<ExecutionLogEntry[]>([])
  const [session, setSession] = useState<AgentJob | null>(null)
  const [sessionStatus, setSessionStatus] = useState<AgentJobStatus | undefined>(undefined)
  const [conversationHistory, setConversationHistory] = useState<Array<{ role: string; content: string }> | null>(null)
  const [loading, setLoading] = useState(true)
  const [subAgentDialogSessionId, setSubAgentDialogSessionId] = useState<string | null>(null)
  const [, setInlineInterventionRequest] = useState<InterveneRequest | null>(null)
  const [, setInlineDialogDismissed] = useState(false)
  const [autoDialogOpen, setAutoDialogOpen] = useState(false)
  const [autoDialogRequest, setAutoDialogRequest] = useState<InterveneRequest | null>(null)
  const [terminating, setTerminating] = useState(false)

  // ── Typed output management hook ──────────────────────────────────────────
  const { outputId, typedOutput, outputLoading, extractAndSetOutputId, fetchTypedOutput, reset: resetTypedOutput } = useTypedOutput(session)

  // ── Ref declarations ──────────────────────────────────────────────────────
  const logEndRef = useRef<HTMLDivElement | null>(null)
  const prevLogCountRef = useRef(0)
  const inlineDialogShownRef = useRef<string | null>(null)
  const autoDialogShownRef = useRef<string | null>(null)

  // ── Callback declarations ─────────────────────────────────────────────────
  const handleViewSubAgentExecution = useCallback((sid: string) => {
    setSubAgentDialogSessionId(sid)
  }, [])

  // ── Custom hooks ──────────────────────────────────────────────────────────
  const { logs: execLogs, loading: execLogsLoading } = useExecutionLogs(sessionId)

  const {
    entries: streamedEntries,
    humanInterveneEvent,
    clearHumanInterveneEvent,
  } = useSessionExecutionLogStream({
    sessionId,
    enabled: open,
    onComplete: () => {
      void fetchSession()
      void fetchLogEntries()
    },
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
      resetTypedOutput()
      autoDialogShownRef.current = null
      Promise.all([
        fetchLogEntries(),
        fetchSession(),
        fetchConversationHistory(),
      ]).finally(() => setLoading(false))
    }
  }, [open, sessionId, fetchLogEntries, fetchSession, fetchConversationHistory, resetTypedOutput])

  // Poll session status while non-terminal for live updates
  useEffect(() => {
    if (!open) return
    if (sessionStatus && TERMINAL_STATUSES.includes(sessionStatus)) return
    const pollHandle = window.setInterval(() => {
      void apiClient
        .get<AgentJob>(`/agents/sessions/${sessionId}`)
        .then(({ data }) => {
          setSessionStatus(data.status)
          if (TERMINAL_STATUSES.includes(data.status)) {
            setSession(data)
            void fetchLogEntries()
          }
        })
        .catch(() => {})
    }, 3000)
    return () => {
      window.clearInterval(pollHandle)
    }
  }, [open, sessionId, sessionStatus, fetchLogEntries])

  // Stream → human intervention handler (instead of polling for pending interventions)
  useEffect(() => {
    if (!humanInterveneEvent) return
    const handleStreamIntervention = async () => {
      try {
        const request = await interveneApi.getInterveneRequest(humanInterveneEvent.request_id)
        if (request && request.status === 'pending') {
          autoDialogShownRef.current = request.id
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
    void handleStreamIntervention()
  }, [humanInterveneEvent, clearHumanInterveneEvent])

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

  // Extract output_id from session when it changes
  useEffect(() => {
    extractAndSetOutputId(session)
  }, [session, extractAndSetOutputId])

  // Fetch typed output whenever output_id becomes available
  useEffect(() => {
    if (outputId) {
      void fetchTypedOutput(outputId)
    }
  }, [outputId, fetchTypedOutput])

  // ── Determine available tabs ─────────────────────────────────────────────────

  const hasResult = !!session && TERMINAL_STATUSES.includes(session.status)
  const isErrorSession = session?.status === 'failed' || session?.status === 'terminated'
  // Extract the most recent error message from execution logs for error sessions
  const errorMessage: string | null = isErrorSession
    ? ([...logEntries].filter(
        (e) =>
          e.event_type === 'error' ||
          e.log_level.toUpperCase() === 'ERROR' ||
          e.log_level.toUpperCase() === 'CRITICAL',
      )
        .map((e) => e.message)
        .slice(-1)[0] ?? null)
    : null
  // Always show execution tab when there are logs, or when result is shown (so user can inspect logs after completion)
  const hasExecutionLogs = logEntries.length > 0 || execLogs.length > 0 || hasResult
  const hasConversationHistory = !!conversationHistory && conversationHistory.length > 0
  const allTabs: TabDef[] = []
  if (hasResult) {
    const outputType = session?.output_data?.['__output_type'] as AgentOutputType | undefined
    const label = outputType
      ? `${t('agents.sessions.result', { defaultValue: 'Result' })}`
      : t('agents.sessions.result', { defaultValue: 'Result' })
    allTabs.push({ key: 'result', label, badge: outputType })
  }
  if (hasExecutionLogs) {
    allTabs.push({ key: 'execution', label: t('agents.executionLogs.title', { defaultValue: 'Execution' }) })
  }
  if (hasConversationHistory) {
    allTabs.push({ key: 'history', label: t('agents.sessions.conversationHistory', { defaultValue: 'Conversation History' }) })
  }

  // Auto-switch to result tab when it first becomes available
  useEffect(() => {
    if (hasResult) {
      const resultIndex = allTabs.findIndex((tab) => tab.key === 'result')
      if (resultIndex >= 0) {
        setActiveTab(resultIndex)
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasResult])

  const safeActiveTab = allTabs.length > 0 ? Math.min(activeTab, allTabs.length - 1) : 0

  // ── Auto-popup modal intervene dialog ───────────────────────────────────────

  // Remove old polling-based intervention check on initial open (now handled by stream)
  // Keeping only the session-status-change handler for completeness, but the stream should be primary
  useEffect(() => {
    if (!open) return
    const checkInitialPending = async () => {
      try {
        // Only check on initial open; stream will handle ongoing events
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
        // Best-effort — stream is primary, this is just a fallback
      }
    }
    void checkInitialPending()
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

  const handleTerminateFromHeader = useCallback(async () => {
    setTerminating(true)
    try {
      await interveneApi.terminateSession(sessionId, 'Operator terminated from execution dialog header')
    } finally {
      setTerminating(false)
    }
  }, [sessionId])

  // ── Computed state ─────────────────────────────────────────────────────────
  const outputType: AgentOutputType = (session?.output_data?.['__output_type'] as AgentOutputType) ?? 'auto'
  const outputSchema = (session?.output_data?.['__schema'] as Record<string, unknown> | undefined) ?? undefined

  // Extract typed output data type info
  const dataTypeId = (session?.output_data?.['__data_type_id'] as string | undefined) ?? null
  const dataTypeName = (session?.output_data?.['__data_type_name'] as string | undefined) ?? null
  const validationStatus = (session?.output_data?.['validation_status'] as 'valid' | 'validation_error' | undefined) ?? null
  const rawOutput = (session?.output_data?.['raw_output'] as string | undefined) ?? null

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
        <Box>
          <Typography variant="h6" component="span">
            {t('agents.sessions.detailsTitle')}
          </Typography>
          {session?.agent_type_name && (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>
              {session.agent_type_name}
            </Typography>
          )}
        </Box>
        <Box display="flex" alignItems="center" gap={1}>
          {sessionStatus && !TERMINAL_STATUSES.includes(sessionStatus) && (
            <Button
              size="small"
              variant="outlined"
              color="error"
              disabled={terminating}
              onClick={() => void handleTerminateFromHeader()}
              startIcon={terminating ? <CircularProgress size={14} color="error" /> : undefined}
              sx={{ fontSize: 12 }}
            >
              {terminating ? 'Terminating…' : 'Terminate'}
            </Button>
          )}
          <IconButton edge="end" onClick={onClose} size="small">
            <CloseIcon />
          </IconButton>
        </Box>
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
        {!loading && allTabs.length === 0 && (sessionStatus === 'queued' || sessionStatus === 'running') && (
          <Box display="flex" flexDirection="column" alignItems="center" gap={2} py={5}>
            <Box
              sx={{
                width: 36,
                height: 36,
                borderRadius: '50%',
                border: '3px solid',
                borderColor: 'primary.light',
                borderTopColor: 'primary.main',
                animation: 'spin 0.9s linear infinite',
                '@keyframes spin': { to: { transform: 'rotate(360deg)' } },
              }}
            />
            <Typography variant="body2" color="text.secondary">
              {sessionStatus === 'queued'
                ? t('agents.sessions.startingAgent', { defaultValue: 'Starting agent…' })
                : t('agents.sessions.waitingForLogs', { defaultValue: 'Agent is running, waiting for activity…' })}
            </Typography>
          </Box>
        )}
        {!loading && allTabs.length === 0 && sessionStatus !== 'queued' && sessionStatus !== 'running' && (
          <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
            {t('agents.sessions.noData', { defaultValue: 'No data available for this session.' })}
          </Typography>
        )}

        {/* ═══════════════════════════════ Execution tab ═══════════════════════ */}
        {allTabs[safeActiveTab]?.key === 'execution' && !execLogsLoading && (
          <>
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
            {outputLoading ? (
              <Box display="flex" justifyContent="center" alignItems="center" py={4}>
                <Typography variant="body2" color="text.secondary">
                  Loading typed output...
                </Typography>
              </Box>
            ) : typedOutput ? (
              <OutputTypeResultTab
                outputType="typed"
                outputData={typedOutput.field_values}
                dataTypeId={typedOutput.data_type_id}
                dataTypeName={typedOutput.data_type_name}
                validationStatus={typedOutput.validation_status}
                rawOutput={typedOutput.raw_output}
              />
            ) : isErrorSession ? (
              <Box>
                <Alert severity={session.status === 'terminated' ? 'warning' : 'error'} sx={{ mb: 1 }}>
                  {session.status === 'terminated'
                    ? t('agents.sessions.terminatedUnexpectedly', { defaultValue: 'Session was terminated before completing.' })
                    : t('agents.sessions.failedUnexpectedly', { defaultValue: 'Session failed before completing.' })}
                  {errorMessage && (
                    <Typography variant="body2" sx={{ mt: 0.5, fontFamily: 'monospace', fontSize: '0.75rem', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                      {errorMessage}
                    </Typography>
                  )}
                </Alert>
              </Box>
            ) : (
              <OutputTypeResultTab
                outputType={outputType}
                outputData={session.output_data}
                outputSchema={outputSchema}
                dataTypeId={dataTypeId}
                dataTypeName={dataTypeName}
                validationStatus={validationStatus}
                rawOutput={rawOutput}
              />
            )}
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
