import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Chip,
  Divider,
  Drawer,
  IconButton,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'
import { TypedOutputRenderer } from '../../components/executions/TypedOutputRenderer'
import type { AgentDataType, AgentOutputResponse } from '../../types'

// ── Props ─────────────────────────────────────────────────────────────────────

interface AgentOutputDetailDrawerProps {
  open: boolean
  output: AgentOutputResponse | null
  dataType: AgentDataType | null
  onClose: () => void
}

// ── Component ──────────────────────────────────────────────────────────────────

/**
 * Detail drawer for a single agent output.
 *
 * Shows the full output record with:
 * - Session link (agent type name and session ID)
 * - Data type badge
 * - Validation status
 * - Full field-by-field rendering using TypedOutputRenderer
 * - Raw output fallback for validation errors
 */
export function AgentOutputDetailDrawer({
  open,
  output,
  dataType,
  onClose,
}: AgentOutputDetailDrawerProps) {
  const { t } = useTranslation()

  if (!output) return null

  const statusValid = output.validation_status === 'valid'
  const fields = dataType?.fields ?? []
  const hasFields = fields.length > 0

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      slotProps={{
        backdrop: { invisible: false },
      }}
    >
      <Box sx={{ width: 520, maxWidth: '100vw', p: 3 }}>
        {/* Header */}
        <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
          <Typography variant="h6" fontWeight={700}>
            {t('admin.agentOutputs.detailTitle', { defaultValue: 'Output Detail' })}
          </Typography>
          <IconButton onClick={onClose} size="small">
            <CloseIcon />
          </IconButton>
        </Box>

        <Divider sx={{ mb: 2 }} />

        {/* Metadata */}
        <Box display="flex" flexDirection="column" gap={1.5} mb={3}>
          <Box display="flex" alignItems="center" gap={1}>
            <Typography variant="body2" fontWeight={600} sx={{ minWidth: 100 }}>
              {t('admin.agentOutputs.columnAgentType')}
            </Typography>
            <Typography variant="body2">
              {output.agent_type_name ?? output.agent_type_id}
            </Typography>
          </Box>

          <Box display="flex" alignItems="center" gap={1}>
            <Typography variant="body2" fontWeight={600} sx={{ minWidth: 100 }}>
              {t('admin.agentOutputs.columnDataType')}
            </Typography>
            <Chip
              label={output.data_type_name ?? output.data_type_id.slice(0, 8)}
              size="small"
              variant="outlined"
              color="primary"
            />
          </Box>

          <Box display="flex" alignItems="center" gap={1}>
            <Typography variant="body2" fontWeight={600} sx={{ minWidth: 100 }}>
              {t('app.createdAt')}
            </Typography>
            <Typography variant="body2">
              {new Date(output.created_at).toLocaleString()}
            </Typography>
          </Box>

          <Box display="flex" alignItems="center" gap={1}>
            <Typography variant="body2" fontWeight={600} sx={{ minWidth: 100 }}>
              {t('admin.agentOutputs.columnStatus')}
            </Typography>
            <Chip
              icon={statusValid ? <CheckCircleIcon /> : <ErrorIcon />}
              label={
                statusValid
                  ? t('admin.agentOutputs.statusValid')
                  : t('admin.agentOutputs.statusError')
              }
              color={statusValid ? 'success' : 'error'}
              size="small"
              variant="outlined"
            />
          </Box>
        </Box>

        <Divider sx={{ mb: 2 }} />

        {/* Validation error banner */}
        {!statusValid && (
          <Alert severity="error" sx={{ mb: 2 }}>
            <Typography variant="body2" fontWeight={600} sx={{ mb: 0.5 }}>
              {t('executionLog.result.validationErrorTitle', {
                defaultValue: 'Output Validation Failed',
              })}
            </Typography>
            <Typography variant="body2">
              {t('executionLog.result.validationErrorHint', {
                defaultValue:
                  'The agent output did not match the expected schema. Raw output is shown below as fallback.',
              })}
            </Typography>
          </Alert>
        )}

        {/* Field values */}
        <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1 }}>
          {t('executionLog.result.structuredOutput', {
            defaultValue: 'Structured Output',
          })}
        </Typography>

        {hasFields ? (
          <Box sx={{ mb: 3 }}>
            <TypedOutputRenderer
              fields={fields}
              values={output.field_values ?? {}}
            />
          </Box>
        ) : (
          <Typography
            variant="body2"
            color="text.secondary"
            fontStyle="italic"
            sx={{ mb: 2 }}
          >
            {t('admin.agentOutputs.noDataTypeSchema', {
              defaultValue: 'No data type schema available for this output.',
            })}
          </Typography>
        )}

        {/* Raw output fallback */}
        {output.raw_output && (
          <Box sx={{ mt: 2 }}>
            <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1 }}>
              {t('executionLog.result.rawFallback', {
                defaultValue: 'Raw Output (Fallback)',
              })}
            </Typography>
            <Box
              sx={{
                bgcolor: '#FAFBFC',
                border: 1,
                borderColor: 'divider',
                borderRadius: 1,
                p: 1.5,
                maxHeight: 300,
                overflow: 'auto',
              }}
            >
              <Typography
                variant="body2"
                component="pre"
                sx={{
                  fontFamily: 'monospace',
                  fontSize: 12,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  m: 0,
                }}
              >
                {output.raw_output}
              </Typography>
            </Box>
          </Box>
        )}
      </Box>
    </Drawer>
  )
}
