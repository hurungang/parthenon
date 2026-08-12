import { useMemo, useState } from 'react'
import { Box, Divider, Paper, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { presentLog } from '../../services/LogPresenter'
import { LogSummaryPanel } from './LogSummaryPanel'
import { WorkingStepsPanel } from './WorkingStepsPanel'
import { RawLogToggle } from './RawLogToggle'
import type { AgentJobStatus, ExecutionLogEntry, ExecutionLogRead, InterveneRequest } from '../../types'

const EMPTY_EXECUTION_LOG: ExecutionLogRead = {
  id: '',
  session_id: '',
  system_instruction: null,
  user_prompt: null,
  logged_at: '',
}

interface Props {
  executionLog?: ExecutionLogRead | null
  entries: ExecutionLogEntry[]
  sessionStatus?: AgentJobStatus
  onViewSubAgentExecution?: (sessionId: string) => void
  pendingInterventionsByChildSession?: Record<string, InterveneRequest>
  onOpenIntervention?: (request: InterveneRequest) => void
}

export function LogViewer({ executionLog, entries, sessionStatus, onViewSubAgentExecution, pendingInterventionsByChildSession, onOpenIntervention }: Props) {
  const resolvedLog = executionLog ?? EMPTY_EXECUTION_LOG
  const { t } = useTranslation()
  const [rawMode, setRawMode] = useState(false)

  const structured = useMemo(
    () => presentLog(resolvedLog, entries, { sessionStatus }),
    [resolvedLog, entries, sessionStatus]
  )

  return (
    <Paper sx={{ p: 3, mt: 3 }}>
      {/* Header row */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h6" fontWeight={600}>
          {t('agents.sessions.logViewer.title')}
        </Typography>
        <RawLogToggle
          checked={rawMode}
          onChange={setRawMode}
          rawLogText={structured.rawLog}
        />
      </Box>

      <Divider sx={{ mb: 2 }} />

      {/* Friendly view */}
      {!rawMode && (
        <Box>
          <LogSummaryPanel summary={structured.summary} />
          <WorkingStepsPanel spans={structured.spans} onViewSubAgentExecution={onViewSubAgentExecution} pendingInterventionsByChildSession={pendingInterventionsByChildSession} onOpenIntervention={onOpenIntervention} />
        </Box>
      )}

      {/* Raw log view */}
      {rawMode && (
        <Box
          component="pre"
          sx={{
            bgcolor: 'grey.900',
            color: 'grey.100',
            border: 1,
            borderColor: 'divider',
            borderRadius: 1,
            p: 2,
            overflow: 'auto',
            maxHeight: 600,
            fontSize: 12,
            fontFamily: 'monospace',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            m: 0,
          }}
          aria-label={t('agents.sessions.logViewer.rawLogAriaLabel')}
        >
          {structured.rawLog || t('agents.sessions.logViewer.noLogs')}
        </Box>
      )}
    </Paper>
  )
}
