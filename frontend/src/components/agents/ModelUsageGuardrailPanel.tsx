import { type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Box, Button, Chip, IconButton, Paper, Stack, Typography } from '@mui/material'
import DeleteIcon from '@mui/icons-material/Delete'
import EditIcon from '@mui/icons-material/Edit'
import type { ModelUsageGuardrailLimit, ModelUsagePosture } from '../../types'
import { VendorModelGuardrailPanel } from './VendorModelGuardrailPanel'
import { useModelAvailability } from '../../hooks/useModelAvailability'
import { useModelUsageLimits } from '../../hooks/useModelUsagePosture'

interface ModelUsageGuardrailPanelProps {
  limits: ModelUsageGuardrailLimit[]
  posture: ModelUsagePosture[]
  onAdd: () => void
  onEdit: (limit: ModelUsageGuardrailLimit) => void
  onDelete: (limit: ModelUsageGuardrailLimit) => void
}

function postureColor(state: string): 'default' | 'warning' | 'error' | 'success' {
  if (state === 'breached') return 'error'
  if (state === 'approaching_limit') return 'warning'
  if (state === 'within_limit') return 'success'
  return 'default'
}

/**
 * @deprecated Superseded by `VendorModelGuardrailPanel`. This shim renders
 * the new hierarchy panel and exposes the legacy flat posture view as a
 * hidden compatibility surface for any remaining consumer. New code should
 * use the hierarchy panel directly.
 */
export function ModelUsageGuardrailPanel({
  limits,
  posture,
  onAdd,
  onEdit,
  onDelete,
}: ModelUsageGuardrailPanelProps): ReactNode {
  const { t } = useTranslation()
  // Warm the new hooks so consumers that no longer pass a hierarchy can still
  // render the panel without breaking (best-effort; failures fall through to
  // the empty state).
  void useModelAvailability()
  void useModelUsageLimits()

  return (
    <Box>
      <Paper sx={{ p: 2, mb: 3 }}>
        <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
          <Typography variant="h6" fontWeight={700}>
            {t('agents.sessions.modelUsageTitle')}
          </Typography>
          <Button variant="outlined" size="small" onClick={onAdd}>
            {t('agents.sessions.modelUsageAddLimit')}
          </Button>
        </Box>
        <Typography variant="body2" color="text.secondary" mb={2}>
          {t('agents.sessions.modelUsageSubtitle')}
        </Typography>

        {posture.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            {t('agents.sessions.modelUsageEmpty')}
          </Typography>
        ) : (
          <Stack spacing={1.25}>
            {posture.map((p) => {
              const limit = limits.find((l) => l.id === p.model_guardrail_configuration_id) ?? null
              return (
                <Paper key={p.id} variant="outlined" sx={{ p: 1.25 }}>
                  <Box display="flex" justifyContent="space-between" alignItems="center" mb={0.5}>
                    <Typography variant="body2" fontWeight={600}>
                      {limit?.model_name ?? p.model_id}
                    </Typography>
                    <Box display="flex" gap={0.5} alignItems="center">
                      <Chip
                        size="small"
                        color={postureColor(p.posture_state)}
                        label={t(`agents.sessions.modelUsageState.${p.posture_state}`)}
                      />
                      {limit && (
                        <>
                          <IconButton
                            size="small"
                            onClick={() => onEdit(limit)}
                            aria-label={t('agents.sessions.modelUsageEditLimit')}
                          >
                            <EditIcon fontSize="small" />
                          </IconButton>
                          <IconButton
                            size="small"
                            onClick={() => onDelete(limit)}
                            aria-label={t('agents.sessions.modelUsageDeleteLimit')}
                          >
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        </>
                      )}
                    </Box>
                  </Box>
                  <Typography variant="caption" color="text.secondary" display="block">
                    {t('agents.sessions.modelUsagePeriodLabel')}: {p.posture_period}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" display="block">
                    {t('agents.sessions.modelUsageValueLabel')}: {p.usage_value} / {p.limit_value}{' '}
                    {limit?.unit ?? 'k'}
                  </Typography>
                </Paper>
              )
            })}
          </Stack>
        )}
      </Paper>
      <VendorModelGuardrailPanel />
    </Box>
  )
}
