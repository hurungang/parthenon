import {
  Box,
  Chip,
  CircularProgress,
  IconButton,
  Paper,
  Stack,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import PersonIcon from '@mui/icons-material/Person'
import ScheduleIcon from '@mui/icons-material/Schedule'
import { useQuery } from '@tanstack/react-query'
import cronstrue from 'cronstrue'
import { useTranslation } from 'react-i18next'
import apiClient from '../../api/apiClient'
import { statusChipColor, statusLabelKey } from './runtimeNodeMeta'

/** One execution (session) the trigger entity launched. */
export interface TriggerExecution {
  sessionId: string
  /** Agent-type display name (already resolved by the caller). */
  label: string
  status: string
}

interface TriggerDetailBubbleProps {
  /** Key of the focused trigger entity (e.g. `person:Alice`). */
  entityKey: string
  kind: 'person' | 'schedule'
  /** Person display name, or the schedule name. */
  name: string
  /** For schedules: the creator's display name (null when unknown). */
  creator: string | null
  /** Person: Identity id — fetches the user's own details (email, type). */
  userId?: string | null
  /** Schedule: id — fetches the schedule's own details (cron, status…). */
  scheduleId?: string | null
  /** Schedule cron expression from the topology payload (fallback to fetch). */
  cron?: string | null
  /** Schedule description from the topology payload. */
  description?: string | null
  /** Executions (sessions) the entity triggered, newest first. */
  executions: TriggerExecution[]
  /** Screen-space position (already viewport-clamped by the canvas). */
  position: { left: number; top: number }
  /** Selecting an execution row focuses that tile + opens the agent bubble. */
  onSelectExecution: (sessionId: string) => void
  onDismiss: () => void
}

/**
 * Dismissible detail bubble shown beside a clicked trigger entity card
 * (person or schedule) in the Agent Runtime Monitor's leftmost column.
 *
 * The bubble describes the TRIGGER ITSELF: person cards fetch the human's
 * identity details (email, identity type); schedule cards fetch the
 * schedule's own details (cron expression — humanised, description, status)
 * plus the creating human — rendered only when the creator is known,
 * mirroring the backend's creator-attribution contract (the schedule name is
 * never presented as a person).  Both cards also list every execution the
 * entity triggered; clicking a row selects that session on the map.
 */
export function TriggerDetailBubble({
  entityKey,
  kind,
  name,
  creator,
  userId,
  scheduleId,
  cron,
  description,
  executions,
  position,
  onSelectExecution,
  onDismiss,
}: TriggerDetailBubbleProps) {
  const { t } = useTranslation()
  const kindLabelKey =
    kind === 'schedule'
      ? 'agents.sessions.runtimeMonitorTriggerScheduleKind'
      : 'agents.sessions.runtimeMonitorTriggerPersonKind'

  // ── The trigger's own details, fetched on open (silent on failure) ──────
  const scheduleQuery = useQuery({
    queryKey: ['trigger-detail', 'schedule', scheduleId],
    enabled: kind === 'schedule' && scheduleId != null,
    staleTime: 30_000,
    retry: false,
    queryFn: async () => {
      const { data } = await apiClient.get(`/schedules/${scheduleId}`)
      return data as {
        cron_expression?: string | null
        description?: string | null
        status?: string | null
      }
    },
  })

  const identityQuery = useQuery({
    queryKey: ['trigger-detail', 'identity', userId],
    enabled: kind === 'person' && userId != null,
    staleTime: 30_000,
    retry: false,
    queryFn: async () => {
      const { data } = await apiClient.get(`/identities/${userId}`)
      return data as {
        display_name?: string | null
        email?: string | null
        identity_type?: string | null
      }
    },
  })

  const scheduleCron = scheduleQuery.data?.cron_expression ?? cron ?? null
  const scheduleDescription = scheduleQuery.data?.description ?? description ?? null
  const scheduleStatus = scheduleQuery.data?.status ?? null
  const personEmail = identityQuery.data?.email ?? null
  const personType = identityQuery.data?.identity_type ?? null
  const detailRows: Array<{ key: string; label: string; value: string; testid: string }> = []
  if (kind === 'schedule') {
    if (scheduleCron) {
      let humanized = ''
      try {
        humanized = cronstrue.toString(scheduleCron)
      } catch {
        humanized = ''
      }
      detailRows.push({
        key: 'cron',
        label: t('agents.sessions.runtimeMonitorTriggerDetailCron'),
        value: humanized ? `${scheduleCron} — ${humanized}` : scheduleCron,
        testid: 'trigger-detail-cron',
      })
    }
    if (scheduleDescription) {
      detailRows.push({
        key: 'desc',
        label: t('agents.sessions.runtimeMonitorTriggerDetailDescription'),
        value: scheduleDescription,
        testid: 'trigger-detail-description',
      })
    }
    if (scheduleStatus) {
      detailRows.push({
        key: 'status',
        label: t('agents.sessions.runtimeMonitorTriggerDetailStatus'),
        value: scheduleStatus,
        testid: 'trigger-detail-status',
      })
    }
  } else {
    if (personEmail) {
      detailRows.push({
        key: 'email',
        label: t('agents.sessions.runtimeMonitorTriggerDetailEmail'),
        value: personEmail,
        testid: 'trigger-detail-email',
      })
    }
    if (personType) {
      detailRows.push({
        key: 'type',
        label: t('agents.sessions.runtimeMonitorTriggerDetailUserType'),
        value: personType,
        testid: 'trigger-detail-user-type',
      })
    }
  }
  const detailRowsLoading =
    (kind === 'schedule' && scheduleId != null && scheduleQuery.isLoading) ||
    (kind === 'person' && userId != null && identityQuery.isLoading)

  return (
    <Paper
      elevation={4}
      role="dialog"
      aria-label={name}
      data-testid="trigger-detail-bubble"
      data-trigger-entity={entityKey}
      sx={{
        position: 'absolute',
        left: position.left,
        top: position.top,
        width: 288,
        zIndex: 30,
        p: 1.75,
        borderRadius: 2,
      }}
    >
      <Box display="flex" alignItems="flex-start" justifyContent="space-between" gap={1} mb={0.5}>
        <Box display="flex" alignItems="center" gap={0.75} minWidth={0}>
          <Box
            sx={{
              width: 22,
              height: 22,
              borderRadius: '50%',
              bgcolor: kind === 'schedule' ? '#FFF3E0' : '#E3F2FD',
              color: kind === 'schedule' ? '#EF6C00' : '#1565C0',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            {kind === 'schedule' ? <ScheduleIcon sx={{ fontSize: 14 }} /> : <PersonIcon sx={{ fontSize: 14 }} />}
          </Box>
          <Typography variant="subtitle1" fontWeight={700} sx={{ wordBreak: 'break-word' }}>
            {name}
          </Typography>
        </Box>
        <IconButton
          size="small"
          onClick={onDismiss}
          aria-label={t('agents.sessions.runtimeMonitorDismiss')}
          data-testid="trigger-detail-bubble-close"
        >
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>

      <Typography variant="caption" color="text.secondary" data-testid="trigger-detail-kind">
        {t(kindLabelKey)}
      </Typography>

      {/* The trigger's own details (schedule cron/status/description; person
          email/type) — fetched on open, hidden when unavailable. */}
      {(detailRowsLoading || detailRows.length > 0) && (
        <Box
          component="dl"
          sx={{ m: 0, mt: 0.75, display: 'grid', gridTemplateColumns: '82px 1fr', gap: 0.5 }}
          data-testid="trigger-detail-rows"
        >
          {detailRowsLoading && detailRows.length === 0 && <CircularProgress size={14} />}
          {detailRows.map((row) => (
            <Box key={row.key} sx={{ display: 'contents' }}>
              <Typography component="dt" variant="caption" color="text.secondary">
                {row.label}
              </Typography>
              <Typography
                component="dd"
                variant="caption"
                sx={{ m: 0, wordBreak: 'break-word' }}
                data-testid={row.testid}
              >
                {row.value}
              </Typography>
            </Box>
          ))}
        </Box>
      )}

      {/* Creator row — schedules only, and ONLY when the creator human is
          known (the schedule name itself is never a creator). */}
      {kind === 'schedule' && creator && (
        <Box
          component="dl"
          sx={{ m: 0, mt: 0.75, mb: 0.5, display: 'grid', gridTemplateColumns: '82px 1fr', gap: 0.5 }}
          data-testid="trigger-detail-creator"
        >
          <Typography component="dt" variant="caption" color="text.secondary">
            {t('agents.sessions.runtimeMonitorTriggerDetailCreator')}
          </Typography>
          <Typography component="dd" variant="caption" sx={{ m: 0, wordBreak: 'break-word' }}>
            {creator}
          </Typography>
        </Box>
      )}

      {executions.length > 0 && (
        <>
          <Typography
            variant="caption"
            fontWeight={700}
            color="text.secondary"
            sx={{ display: 'block', mt: 1, mb: 0.5 }}
            data-testid="trigger-detail-executions-heading"
          >
            {t('agents.sessions.runtimeMonitorTriggerDetailExecutions', { count: executions.length })}
          </Typography>
          <Stack spacing={0.5}>
            {executions.map((execution) => (
              <Box
                key={execution.sessionId}
                role="button"
                tabIndex={0}
                aria-label={execution.label}
                data-testid={`trigger-detail-execution-${execution.sessionId}`}
                onClick={() => onSelectExecution(execution.sessionId)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onSelectExecution(execution.sessionId)
                  }
                }}
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 0.75,
                  px: 0.75,
                  py: 0.5,
                  border: '1px solid',
                  borderColor: 'divider',
                  borderRadius: 1,
                  bgcolor: 'action.hover',
                  cursor: 'pointer',
                  minWidth: 0,
                  '&:hover': { borderColor: '#90CAF9' },
                }}
              >
                <Typography
                  variant="caption"
                  fontWeight={600}
                  sx={{ flex: 1, minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                >
                  {execution.label}
                </Typography>
                <Chip
                  size="small"
                  label={t(statusLabelKey(execution.status, 'agent'), execution.status)}
                  color={statusChipColor(execution.status, 'agent')}
                  sx={{ height: 20, flexShrink: 0 }}
                />
              </Box>
            ))}
          </Stack>
        </>
      )}
    </Paper>
  )
}
