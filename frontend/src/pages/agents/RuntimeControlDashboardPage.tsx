import { useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  Paper,
  Stack,
  Typography,
} from '@mui/material'
import DeleteSweepIcon from '@mui/icons-material/DeleteSweep'
import RefreshIcon from '@mui/icons-material/Refresh'
import LogoutIcon from '@mui/icons-material/Logout'
import { useTranslation } from 'react-i18next'
import { useRuntimeTopology } from '../../hooks/useRuntimeTopology'
import {
  useNodeTermination,
  usePurgeTerminalJobs,
  useTerminationOutcomes,
} from '../../hooks/useNodeTermination'
import { useModelUsagePosture } from '../../hooks/useModelUsagePosture'
import { useAvailableModels } from '../../hooks/useAvailableModels'
import { useEndConversationSession } from '../../hooks/useConversationSessions'
import { RuntimeTopologyDiagram } from '../../components/agents/RuntimeTopologyDiagram'
import { VendorModelGuardrailPanel } from '../../components/agents/VendorModelGuardrailPanel'
import { NodeTerminationDialog } from '../../components/agents/NodeTerminationDialog'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import type { RuntimeTerminationRequest, TerminationScope } from '../../types'

// Phase 3.16: the default set of (kind, status) keys visible
// in the runtime topology.  "sleep" conversations are hidden
// by default because there can be many of them (every open
// chat the user hasn't sent a message to) and they tend to
// dominate the diagram.
const DEFAULT_VISIBLE_KEYS: ReadonlySet<string> = new Set([
  'agent:running',
  'agent:queued',
  'agent:completed',
  'agent:failed',
  'agent:terminated',
  'conversation:active',
  // 'conversation:sleep' is intentionally excluded
  'conversation:closed',
  'conversation:archived',
  'conversation:error',
  'instance:active',
  'instance:created',
  'instance:closed',
  'instance:error',
])

export function RuntimeControlDashboardPage() {
  const { t } = useTranslation()

  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const [terminationDialogOpen, setTerminationDialogOpen] = useState(false)
  const [lastTerminationRequest, setLastTerminationRequest] =
    useState<RuntimeTerminationRequest | null>(null)
  // Phase 3.16: status filter.  ``visibleKeys`` is the set of
  // (kind, status) keys that are currently displayed.  Default
  // excludes "conversation:sleep" because the live view tends
  // to be dominated by idle chats.
  const [visibleKeys, setVisibleKeys] = useState<Set<string>>(
    new Set(DEFAULT_VISIBLE_KEYS),
  )
  const toggleStatusKey = (key: string) => {
    setVisibleKeys((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // Phase 3.16: hook for "End session" on sleep conversations.
  // Note: the conversation-agnostic runtime dashboard may not
  // have a stable agent_type_id for the hook, so we call it
  // lazily on demand using the selected node's id.
  const [endingSessionId, setEndingSessionId] = useState<string | null>(null)

  const { data: topology, isLoading: topologyLoading, error: topologyError, refetch } =
    useRuntimeTopology(false)
  // The hierarchy panel uses its own useModelUsagePosture() internally via
  // the new hooks. We still fetch here so the data is warm and we can pass
  // posture in if the panel needs it later.
  void useModelUsagePosture()
  void useAvailableModels()

  const terminateMutation = useNodeTermination()
  const purgeMutation = usePurgeTerminalJobs()
  const { data: terminationOutcomes = [] } = useTerminationOutcomes(
    lastTerminationRequest?.id ?? null,
  )

  const selectedNode = useMemo(
    () => (topology?.nodes ?? []).find((n) => n.session_id === selectedSessionId) ?? null,
    [topology, selectedSessionId],
  )

  return (
    <Box>
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
                // Display-friendly summary
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

      {/* Topology diagram and selected-node details */}
      <Paper sx={{ p: 2, mb: 3 }}>
        <Box
          display="flex"
          justifyContent="space-between"
          alignItems="center"
          mb={1.5}
        >
          <Typography variant="h6" fontWeight={700}>
            {t('agents.sessions.runtimeTopologyTitle')}
          </Typography>
          <Chip
            label={t('agents.sessions.runtimeTopologyLiveRefresh')}
            size="small"
            color="info"
            variant="outlined"
          />
        </Box>
        <Typography variant="body2" color="text.secondary" mb={2}>
          {t('agents.sessions.runtimeTopologySubtitle')}
        </Typography>

        {topologyLoading ? (
          <Box display="flex" justifyContent="center" py={4}>
            <CircularProgress />
          </Box>
        ) : (
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: {
                xs: 'minmax(0, 1fr)',
                md: 'minmax(0, 1.4fr) minmax(0, 1fr)',
              },
              gap: 2,
              alignItems: 'start',
            }}
          >
            <Box>
              <RuntimeTopologyDiagram
                topology={topology}
                selectedSessionId={selectedSessionId}
                onSelectSession={setSelectedSessionId}
                visibleKeys={visibleKeys}
                onToggleKey={toggleStatusKey}
              />
            </Box>
            <Box>
              {selectedNode ? (
                <Paper variant="outlined" sx={{ p: 2 }}>
                  <Typography variant="subtitle2" fontWeight={700} mb={1}>
                    {t('agents.sessions.runtimeSelectedNode')}
                  </Typography>
                  <Stack spacing={0.5} mb={2}>
                    <Row k={t('agents.sessions.runtimeAgentType')}>
                      {selectedNode.agent_type_name ?? t('agents.sessions.runtimeUnknownAgent')}
                    </Row>
                    <Row k={t('agents.sessions.runtimeSession')}>
                      <span style={{ fontFamily: 'monospace' }}>{selectedNode.session_id}</span>
                    </Row>
                    <Row k={t('agents.sessions.runtimeParent')}>
                      {selectedNode.parent_session_id ?? '—'}
                    </Row>
                    <Row k={t('agents.sessions.runtimeStatus')}>
                      <Chip
                        size="small"
                        label={selectedNode.status}
                        color={
                          selectedNode.status === 'running'
                            ? 'info'
                            : selectedNode.status === 'completed'
                              ? 'success'
                              : selectedNode.status === 'failed'
                                ? 'error'
                                : selectedNode.status === 'terminated'
                                  ? 'warning'
                                  : 'default'
                        }
                      />
                    </Row>
                    <Row k={t('agents.sessions.runtimeDepth')}>
                      {selectedNode.depth_from_root}
                    </Row>
                  </Stack>
                  <Divider sx={{ my: 1.5 }} />
                  {/* Phase 3.16: sleep conversations have no live
                      agent_job to cancel, so the operator's only
                      option is to end the chat.  All other node
                      kinds use the regular terminate dialog. */}
                  {selectedNode.kind === 'conversation' && selectedNode.status === 'sleep' ? (
                    <SleepConversationActions
                      agentTypeId={selectedNode.agent_type_id}
                      sessionId={selectedNode.session_id}
                      isSubmitting={endingSessionId === selectedNode.session_id}
                      onSubmittingChange={setEndingSessionId}
                      onCompleted={async () => {
                        await refetch()
                      }}
                    />
                  ) : (
                    <Button
                      variant="contained"
                      color="error"
                      fullWidth
                      data-testid="terminate-node-button"
                      onClick={() => setTerminationDialogOpen(true)}
                    >
                      {t('agents.sessions.runtimeTerminateNode')}
                    </Button>
                  )}
                </Paper>
              ) : (
                <Paper variant="outlined" sx={{ p: 2, textAlign: 'center' }}>
                  <Typography variant="body2" color="text.secondary">
                    {t('agents.sessions.runtimeSelectNodeHint')}
                  </Typography>
                </Paper>
              )}
            </Box>
          </Box>
        )}
      </Paper>

      {/* Vendor → model → guardrail hierarchy (read-only dashboard on this surface) */}
      <VendorModelGuardrailPanel readonly />

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
    </Box>
  )
}

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <Box display="flex" gap={1} alignItems="center">
      <Typography variant="caption" color="text.secondary" sx={{ minWidth: 90, flexShrink: 0 }}>
        {k}
      </Typography>
      <Typography variant="body2" sx={{ minWidth: 0, overflowWrap: 'anywhere' }}>
        {children}
      </Typography>
    </Box>
  )
}

// Phase 3.16: separate component so the ``useEndConversationSession``
// hook is only mounted when a sleep conversation is selected.  The
// hook requires an ``agentTypeId`` so it has to be tied to the
// selected node's value, not the page-level scope.
function SleepConversationActions({
  agentTypeId,
  sessionId,
  isSubmitting,
  onSubmittingChange,
  onCompleted,
}: {
  agentTypeId: string
  sessionId: string
  isSubmitting: boolean
  onSubmittingChange: (id: string | null) => void
  onCompleted: () => Promise<void> | void
}) {
  const { t } = useTranslation()
  const endConversation = useEndConversationSession(agentTypeId)
  const [error, setError] = useState<string | null>(null)
  return (
    <Stack spacing={1}>
      {error != null && (
        <Alert severity="error" onClose={() => setError(null)}>
          {error}
        </Alert>
      )}
      <Button
        variant="contained"
        color="warning"
        fullWidth
        startIcon={<LogoutIcon />}
        disabled={isSubmitting}
        data-testid="end-conversation-button"
        onClick={async () => {
          onSubmittingChange(sessionId)
          setError(null)
          try {
            await endConversation.mutateAsync(sessionId)
            await onCompleted()
          } catch (err) {
            setError(err instanceof Error ? err.message : t('app.error'))
          } finally {
            onSubmittingChange(null)
          }
        }}
      >
        {t('agents.sessions.runtimeEndSession')}
      </Button>
    </Stack>
  )
}
