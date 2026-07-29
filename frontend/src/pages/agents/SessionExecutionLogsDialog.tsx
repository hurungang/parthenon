import { useEffect, useRef, useState } from 'react'
import {
  Alert,
  Box,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  IconButton,
  Stack,
  Tab,
  Tabs,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import RefreshIcon from '@mui/icons-material/Refresh'
import { useTranslation } from 'react-i18next'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { LogViewer } from '../../components/executions/LogViewer'
import { OutputTypeResultTab } from '../../components/executions/OutputTypeResultTab'
import { useExecutionLogs } from '../../hooks/useExecutionLogs'
import { useSessionExecutionLogStream } from '../../hooks/useSessionExecutionLogStream'
import type { AgentJobStatus, AgentJob, AgentOutputType, ExecutionLogEntry, AgentOutputResponse } from '../../types'

const TAB_LOGS = 0
const TAB_RESULT = 1

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
  const [outputId, setOutputId] = useState<string | undefined>(undefined)
  const [outputType, setOutputType] = useState<AgentOutputType | null>(null)
  const [markdownOutputData, setMarkdownOutputData] = useState<Record<string, unknown> | null>(null)
  const [typedOutput, setTypedOutput] = useState<AgentOutputResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [outputLoading, setOutputLoading] = useState(false)
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [tabValue, setTabValue] = useState(TAB_LOGS)
  // Track whether we've already auto-switched to the result tab, so a user
  // switching back to the logs tab is not overridden.
  const hasAutoSwitchedRef = useRef(false)

  const { logs: execLogs, loading: execLogsLoading } = useExecutionLogs(sessionId)

  const fetchLogs = async () => {
    if (!sessionId) return
    try {
      setLoading(true)
      setDialogError(null)
      const { data } = await apiClient.get<ExecutionLogEntry[]>(
        `/agents/sessions/${sessionId}/logs`
      )
      setLogs(data)
      const statusResponse = await apiClient.get<AgentJob>(
        `/agents/sessions/${sessionId}`
      )
      console.log('[SessionExecutionLogsDialog] fetchLogs response:', statusResponse.data)
      setSessionStatus(statusResponse.data.status)
      const jobOutputType = statusResponse.data.output_type ?? null
      setOutputType(jobOutputType)
      if (statusResponse.data.output_id) {
        console.log('[SessionExecutionLogsDialog] Setting outputId:', statusResponse.data.output_id)
        setOutputId(statusResponse.data.output_id)
      } else if (jobOutputType === 'markdown' || jobOutputType === 'auto') {
        // Non-typed outputs: result lives in output_data on the job
        const jobOutputData = statusResponse.data.output_data ?? null
        if (jobOutputData) {
          console.log('[SessionExecutionLogsDialog] Markdown/auto output_data found')
          setMarkdownOutputData(jobOutputData)
        } else {
          console.log('[SessionExecutionLogsDialog] No output_id and no output_data in response')
        }
      } else {
        console.log('[SessionExecutionLogsDialog] No output_id in response')
      }
    } catch (err) {
      console.error('[SessionExecutionLogsDialog] fetchLogs error:', err)
      setDialogError(err)
    } finally {
      setLoading(false)
    }
  }

  const fetchTypedOutput = async (id: string) => {
    try {
      setOutputLoading(true)
      console.log('[SessionExecutionLogsDialog] Fetching typed output for id:', id)
      const { data } = await apiClient.get<AgentOutputResponse>(`/agent-outputs/${id}`)
      console.log('[SessionExecutionLogsDialog] Typed output fetched:', data)
      setTypedOutput(data)
    } catch (err) {
      console.error('[SessionExecutionLogsDialog] Failed to fetch typed output:', err)
    } finally {
      setOutputLoading(false)
    }
  }

  const { entries: streamedEntries } = useSessionExecutionLogStream({
    sessionId,
    enabled: open,
    // When the stream signals completion, re-fetch session state to get output_id
    onComplete: () => {
      console.log('[SessionExecutionLogsDialog] Stream completed, fetching logs to get output_id')
      void fetchLogs()
    },
  })

  // Reset per-session state when dialog opens with a new session
  useEffect(() => {
    if (open && sessionId) {
      setLogs([])
      setTypedOutput(null)
      setOutputId(undefined)
      setOutputType(null)
      setMarkdownOutputData(null)
      setSessionStatus(undefined)
      setTabValue(TAB_LOGS)
      hasAutoSwitchedRef.current = false
      void fetchLogs()
    }
  }, [open, sessionId])

  // Fetch typed output whenever output_id becomes available
  useEffect(() => {
    if (outputId) {
      console.log('[SessionExecutionLogsDialog] outputId changed, fetching typed output:', outputId)
      void fetchTypedOutput(outputId)
    }
  }, [outputId])

  // Merge streamed log entries
  useEffect(() => {
    if (!streamedEntries.length) return
    setLogs((prev) => mergeLogEntries(prev, streamedEntries))
  }, [streamedEntries])

  // Auto-switch to Result tab once typed or markdown output is loaded (only once per session)
  useEffect(() => {
    if ((typedOutput || markdownOutputData) && !hasAutoSwitchedRef.current) {
      hasAutoSwitchedRef.current = true
      setTabValue(TAB_RESULT)
    }
  }, [typedOutput, markdownOutputData])

  const handleClose = () => {
    setDialogError(null)
    onClose()
  }

  const hasLogs = logs.length > 0 || execLogs.length > 0
  const isErrorSession = sessionStatus === 'failed' || sessionStatus === 'terminated'
  const hasResult = outputId != null || markdownOutputData != null
  const showTabs = hasLogs && (hasResult || isErrorSession)

  // Extract the most recent error message from execution logs for error sessions
  const errorMessage: string | null = isErrorSession
    ? ([
        ...logs.filter(
          (e) =>
            e.event_type === 'error' ||
            e.log_level.toUpperCase() === 'ERROR' ||
            e.log_level.toUpperCase() === 'CRITICAL',
        ),
      ]
        .map((e) => e.message)
        .slice(-1)[0] ?? null)
    : null

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
        {!loading && !dialogError && !execLogsLoading && !hasLogs && !typedOutput && !markdownOutputData && (
          <Typography color="text.secondary">{t('agents.sessions.noLogsAvailable')}</Typography>
        )}
        {!loading && !dialogError && (hasLogs || typedOutput || markdownOutputData) && (
          <Stack spacing={2}>
            {showTabs && (
              <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
                <Tabs value={tabValue} onChange={(_, value: number) => setTabValue(value)}>
                  <Tab
                    label={t('agents.sessions.tabs.executionLogs')}
                    id="tab-logs"
                    aria-controls="tabpanel-logs"
                  />
                  <Tab
                    label={t('agents.sessions.tabs.typedOutput')}
                    id="tab-result"
                    aria-controls="tabpanel-result"
                  />
                </Tabs>
              </Box>
            )}

            {/* Execution logs panel */}
            {(!showTabs || tabValue === TAB_LOGS) && hasLogs && !execLogsLoading && (
              <Box role="tabpanel" id="tabpanel-logs" aria-labelledby="tab-logs">
                <LogViewer
                  executionLog={execLogs[0] ?? null}
                  entries={logs}
                  sessionStatus={sessionStatus}
                />
              </Box>
            )}

            {/* Result panel — only rendered when tabs are shown and Result tab is active */}
            {showTabs && tabValue === TAB_RESULT && (
              <Box role="tabpanel" id="tabpanel-result" aria-labelledby="tab-result">
                {outputLoading && (
                  <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
                    <CircularProgress size={28} />
                  </Box>
                )}
                {!outputLoading && typedOutput && (
                  <OutputTypeResultTab
                    outputType="typed"
                    outputData={typedOutput.field_values}
                    dataTypeId={typedOutput.data_type_id}
                    validationStatus={typedOutput.validation_status}
                    rawOutput={typedOutput.raw_output}
                    dataTypeName={typedOutput.data_type_name}
                  />
                )}
                {!outputLoading && !typedOutput && markdownOutputData && (
                  <OutputTypeResultTab
                    outputType={outputType === 'markdown' ? 'markdown' : 'auto'}
                    outputData={markdownOutputData}
                  />
                )}
                {!outputLoading && !typedOutput && isErrorSession && (
                  <Box sx={{ py: 2 }}>
                    <Alert severity={sessionStatus === 'terminated' ? 'warning' : 'error'} sx={{ mb: 1 }}>
                      {sessionStatus === 'terminated'
                        ? t('agents.sessions.terminatedUnexpectedly', { defaultValue: 'Session was terminated before completing.' })
                        : t('agents.sessions.failedUnexpectedly', { defaultValue: 'Session failed before completing.' })}
                      {errorMessage && (
                        <Box component="div" sx={{ mt: 0.5, fontFamily: 'monospace', fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                          {errorMessage}
                        </Box>
                      )}
                    </Alert>
                  </Box>
                )}
                {!outputLoading && !typedOutput && !isErrorSession && (
                  <Typography color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
                    {t('agents.sessions.typedOutput.noFields')}
                  </Typography>
                )}
              </Box>
            )}
          </Stack>
        )}
      </DialogContent>
    </Dialog>
  )
}



