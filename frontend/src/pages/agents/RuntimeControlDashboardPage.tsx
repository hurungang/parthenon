import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  Paper,
  Stack,
  Typography,
} from '@mui/material'
import DeleteSweepIcon from '@mui/icons-material/DeleteSweep'
import RefreshIcon from '@mui/icons-material/Refresh'
import { useTranslation } from 'react-i18next'
import { useRuntimeTopology } from '../../hooks/useRuntimeTopology'
import {
  useNodeTermination,
  usePurgeTerminalJobs,
  useTerminationOutcomes,
} from '../../hooks/useNodeTermination'
import * as interveneApi from '../../api/interveneApi'
import { AgentRuntimeMapCanvas } from '../../components/agents/AgentRuntimeMapCanvas'
import { NodeTerminationDialog } from '../../components/agents/NodeTerminationDialog'
import { InterveneResponseDialog } from '../../components/agents/InterveneResponseDialog'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import type {
  InterveneRequest,
  RuntimeTerminationRequest,
  RuntimeTopologyNode,
  TerminationScope,
} from '../../types'

/**
 * Agent Runtime Monitor — full-page, interactive, map-style canvas.
 *
 * Replaces the static runtime topology diagram.  Sleeping agents awaiting
 * human intervention are surfaced by default with an alert indicator.
 * The model guardrail panel has been removed from this page entirely.
 */
export function RuntimeControlDashboardPage() {
  const { t } = useTranslation()

  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [terminationDialogOpen, setTerminationDialogOpen] = useState(false)
  const [lastTerminationRequest, setLastTerminationRequest] =
    useState<RuntimeTerminationRequest | null>(null)
  const [interventionRequest, setInterventionRequest] = useState<InterveneRequest | null>(null)
  const [interventionOpen, setInterventionOpen] = useState(false)

  // ── Recently-completed window (drives the `recent_minutes` fetch param) ──
  // ON by default with a 30-minute window.  The page owns both values; the
  // canvas filter panel edits them.  Window changes are debounced (~500ms)
  // so typing in the numeric input does not trigger a refetch per keystroke
  // (React Query re-fetches whenever the query key changes).
  const [recentEnabled, setRecentEnabled] = useState(true)
  const [recentMinutes, setRecentMinutes] = useState(30)
  const recentMinutesTimerRef = useRef<number | null>(null)
  const commitRecentMinutes = useCallback((value: number) => {
    if (recentMinutesTimerRef.current !== null) {
      window.clearTimeout(recentMinutesTimerRef.current)
    }
    recentMinutesTimerRef.current = window.setTimeout(() => {
      setRecentMinutes(Math.max(1, Math.floor(value)))
      recentMinutesTimerRef.current = null
    }, 500)
  }, [])
  useEffect(
    () => () => {
      if (recentMinutesTimerRef.current !== null) {
        window.clearTimeout(recentMinutesTimerRef.current)
      }
    },
    [],
  )

  const { data: topology, error: topologyError, refetch } = useRuntimeTopology(
    false,
    recentEnabled ? recentMinutes : 0,
  )

  const terminateMutation = useNodeTermination()
  const purgeMutation = usePurgeTerminalJobs()
  const { data: terminationOutcomes = [] } = useTerminationOutcomes(
    lastTerminationRequest?.id ?? null,
  )

  const selectedNode = useMemo(
    () => (topology?.nodes ?? []).find((n) => n.session_id === selectedSessionId) ?? null,
    [topology, selectedSessionId],
  )

  const interventionCount = useMemo(
    () => (topology?.nodes ?? []).filter((n) => n.needs_intervention === true).length,
    [topology],
  )

  const openIntervention = async (node: RuntimeTopologyNode) => {
    try {
      const request = await interveneApi.getPendingInterventionForNode(node)
      if (request) {
        setInterventionRequest(request)
        setInterventionOpen(true)
      }
    } catch {
      // Nothing to surface — the dialog simply won't open.
    }
  }

  const handleSubmitIntervention = async (
    requestId: string,
    value: { approval_value?: boolean; selected_choice?: string; text_value?: string },
  ) => {
    await interveneApi.submitInterveneResponse(requestId, {
      request_id: requestId,
      ...value,
    })
    setInterventionOpen(false)
    setInterventionRequest(null)
    await refetch()
  }

  return (
    <Box>
      {!isFullscreen && (
        <Box display="flex" justifyContent="space-between" alignItems="flex-start" mb={3}>
          <Box>
            <Typography variant="h4" fontWeight={700} mb={0.5}>
              {t('agents.sessions.runtimeControlTitle')}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {t('agents.sessions.runtimeControlSubtitle')}
            </Typography>
          </Box>
          <Stack direction="row" spacing={1}>
            {interventionCount > 0 && (
              <Chip
                label={t('agents.sessions.runtimeMonitorAwaitingIntervention')}
                color="warning"
                size="small"
                sx={{ alignSelf: 'center' }}
              />
            )}
            <Chip
              label={t('agents.sessions.runtimeMonitorLiveRefresh')}
              size="small"
              color="info"
              variant="outlined"
              sx={{ alignSelf: 'center' }}
            />
            <Button
              variant="outlined"
              color="warning"
              startIcon={<DeleteSweepIcon />}
              disabled={purgeMutation.isPending}
              onClick={async () => {
                const result = await purgeMutation.mutateAsync({ olderThanHours: 0 })
                setLastTerminationRequest({
                  id: `purge-${Date.now()}`,
                  request_status: 'purge_completed',
                  termination_scope: 'cascade_subtree',
                  target_session_id: '00000000-0000-0000-0000-000000000000',
                  operator_reason: `Purged ${result.purged_count} completed/failed job(s)`,
                  created_at: new Date().toISOString(),
                  requested_by_user_id: '00000000-0000-0000-0000-000000000000',
                } as unknown as RuntimeTerminationRequest)
              }}
              data-testid="purge-terminal-jobs-button"
            >
              {t('agents.sessions.runtimePurgeCompletedJobs')}
            </Button>
            <Button
              variant="outlined"
              startIcon={<RefreshIcon />}
              onClick={() => void refetch()}
            >
              {t('app.refresh')}
            </Button>
          </Stack>
        </Box>
      )}

      {topologyError != null && (
        <PermissionDeniedAlert error={topologyError} fallbackMessage={t('app.error')} />
      )}

      {!!lastTerminationRequest && (
        <Alert
          severity={lastTerminationRequest.request_status === 'failed' ? 'error' : 'info'}
          sx={{ mb: 2 }}
        >
          {t('agents.sessions.runtimeTerminationStatus', {
            status: lastTerminationRequest.request_status,
            requestId: lastTerminationRequest.id,
          })}
          {terminationOutcomes.length > 0 && ` (${terminationOutcomes.length})`}
        </Alert>
      )}

      <Paper sx={{ p: isFullscreen ? 0 : 2 }}>
        <Box display="flex" justifyContent="space-between" alignItems="center" mb={isFullscreen ? 0 : 1.5}>
          {!isFullscreen && (
            <Typography variant="h6" fontWeight={700}>
              {t('agents.sessions.runtimeTopologyTitle')}
            </Typography>
          )}
        </Box>

        <AgentRuntimeMapCanvas
          topology={topology}
          selectedSessionId={selectedSessionId}
          onSelectSession={setSelectedSessionId}
          onOpenIntervention={(node) => void openIntervention(node)}
          onTerminateNode={() => setTerminationDialogOpen(true)}
          isFullscreen={isFullscreen}
          onToggleFullscreen={() => setIsFullscreen((v) => !v)}
          recentEnabled={recentEnabled}
          recentMinutes={recentMinutes}
          onRecentEnabledChange={setRecentEnabled}
          onRecentMinutesChange={commitRecentMinutes}
          onChanged={async () => {
            await refetch()
          }}
        />
      </Paper>

      <NodeTerminationDialog
        open={terminationDialogOpen}
        onClose={() => setTerminationDialogOpen(false)}
        selectedNode={selectedNode}
        isSubmitting={terminateMutation.isPending}
        onConfirm={async (scope: TerminationScope, reason: string) => {
          if (!selectedNode) return
          const requestRecord = await terminateMutation.mutateAsync({
            target_session_id: selectedNode.session_id,
            termination_scope: scope,
            operator_reason: reason,
          })
          setLastTerminationRequest(requestRecord)
          await refetch()
        }}
      />

      <InterveneResponseDialog
        open={interventionOpen}
        request={interventionRequest}
        onClose={() => {
          setInterventionOpen(false)
          setInterventionRequest(null)
        }}
        onSubmit={handleSubmitIntervention}
        onTerminate={async (sessionId: string) => {
          const requestRecord = await terminateMutation.mutateAsync({
            target_session_id: sessionId,
            termination_scope: 'cascade_subtree',
            operator_reason: 'Operator terminated via intervention dialog',
          })
          setLastTerminationRequest(requestRecord)
          await refetch()
        }}
      />
    </Box>
  )
}
