import { Box, Button, Chip, Divider, Paper, Stack, Typography } from '@mui/material'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import type { RuntimeTopologyProjection } from '../../types'

interface RuntimeTopologyPanelProps {
  topology: RuntimeTopologyProjection | undefined
  selectedSessionId: string | null
  onSelectSession: (sessionId: string) => void
  onTerminate: (sessionId: string) => void
  canTerminate: boolean
}

function statusColor(
  status: string,
  kind: string,
): 'default' | 'info' | 'success' | 'error' | 'warning' | 'primary' {
  // Phase 3.14: conversation nodes use the primary colour
  // (teal-ish) when a live agent is driving them, default
  // (grey) when sleeping, success/error/... for terminal states.
  if (kind === 'conversation') {
    if (status === 'active') return 'primary'
    if (status === 'sleep') return 'default'
    if (status === 'closed' || status === 'archived') return 'success'
    if (status === 'error') return 'error'
    return 'default'
  }
  if (status === 'running') return 'info'
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'error'
  // Phase 3.12: terminated is amber/warning, distinct from failed.
  if (status === 'terminated') return 'warning'
  return 'default'
}

export function RuntimeTopologyPanel({
  topology,
  selectedSessionId,
  onSelectSession,
  onTerminate,
  canTerminate,
}: RuntimeTopologyPanelProps) {
  const { t } = useTranslation()

  const groupedByDepth = useMemo(() => {
    const groups = new Map<number, RuntimeTopologyProjection['nodes']>()
    for (const node of topology?.nodes ?? []) {
      const existing = groups.get(node.depth_from_root) ?? []
      existing.push(node)
      groups.set(node.depth_from_root, existing)
    }
    return [...groups.entries()].sort((a, b) => a[0] - b[0])
  }, [topology])

  const selectedNode = (topology?.nodes ?? []).find((n) => n.session_id === selectedSessionId) ?? null

  return (
    <Paper sx={{ p: 2, mb: 3 }}>
      <Typography variant="h6" fontWeight={700} mb={1}>
        {t('agents.sessions.runtimeTopologyTitle')}
      </Typography>
      <Typography variant="body2" color="text.secondary" mb={2}>
        {t('agents.sessions.runtimeTopologySubtitle')}
      </Typography>

      {groupedByDepth.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {t('agents.sessions.runtimeTopologyEmpty')}
        </Typography>
      ) : (
        <Box sx={{ display: 'flex', gap: 2, overflowX: 'auto', pb: 1 }}>
          {groupedByDepth.map(([depth, nodes]) => (
            <Paper key={depth} variant="outlined" sx={{ minWidth: 260, p: 1.5 }}>
              <Typography variant="subtitle2" fontWeight={700} mb={1}>
                {t('agents.sessions.runtimeDepthLabel', { depth })}
              </Typography>
              <Stack spacing={1}>
                {nodes.map((node) => {
                  const kind = node.kind ?? 'agent'
                  return (
                  <Paper
                    key={node.session_id}
                    variant={selectedSessionId === node.session_id ? 'elevation' : 'outlined'}
                    elevation={selectedSessionId === node.session_id ? 2 : 0}
                    sx={{ p: 1.25, cursor: 'pointer' }}
                    onClick={() => onSelectSession(node.session_id)}
                  >
                    <Stack direction="row" justifyContent="space-between" alignItems="center" mb={0.5}>
                      <Typography variant="body2" fontWeight={600}>
                        {/* Phase 3.15: show the agent type name (e.g.
                            "support-agent") consistently for both
                            agent and conversation nodes.  The
                            conversation title (auto-generated
                            conversation name) is shown as a smaller
                            caption below. */}
                        {node.agent_type_name ?? t('agents.sessions.runtimeUnknownAgent')}
                      </Typography>
                      <Chip
                        size="small"
                        color={statusColor(node.status, kind)}
                        label={kind === 'conversation'
                          // Phase 3.14: the topology may return
                          // synthetic "active" / "sleep" / "closed" /
                          // "error" statuses for conversation nodes
                          // (or the literal ConversationStatus
                          // values).  Use the new runtime status
                          // i18n keys; fall back to the literal
                          // status string if the key is missing.
                          ? (t(`agents.sessions.runtimeStatus${node.status.charAt(0).toUpperCase()}${node.status.slice(1)}`, node.status))
                          : t(`agents.sessions.status${node.status.replace(/^./, (c: string) => c.toUpperCase())}`, node.status)}
                      />
                    </Stack>
                    <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
                      {node.session_id.slice(0, 8)}…
                    </Typography>
                    {kind === 'conversation' && node.title && (
                      <Typography
                        variant="caption"
                        display="block"
                        color="text.secondary"
                        sx={{
                          fontStyle: 'italic',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                        }}
                      >
                        {node.title}
                      </Typography>
                    )}
                    {node.parent_session_id && (
                      <Typography variant="caption" display="block" color="text.secondary">
                        {t('agents.sessions.runtimeParentLabel')}: {node.parent_session_id.slice(0, 8)}…
                      </Typography>
                    )}
                  </Paper>
                  )
                })}
              </Stack>
            </Paper>
          ))}
        </Box>
      )}

      {selectedNode && (
        <>
          <Divider sx={{ my: 2 }} />
          <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', sm: 'center' }} gap={2}>
            <Box>
              <Typography variant="subtitle2" fontWeight={700}>
                {t('agents.sessions.runtimeSelectedNode')}
              </Typography>
              <Typography variant="body2">{selectedNode.agent_type_name ?? t('agents.sessions.runtimeUnknownAgent')}</Typography>
              <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
                {selectedNode.session_id}
              </Typography>
            </Box>
            <Button
              variant="contained"
              color="error"
              disabled={!canTerminate}
              onClick={() => onTerminate(selectedNode.session_id)}
            >
              {t('agents.sessions.runtimeTerminateNode')}
            </Button>
          </Stack>
        </>
      )}
    </Paper>
  )
}
