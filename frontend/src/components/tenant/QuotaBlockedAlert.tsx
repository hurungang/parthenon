/**
 * QuotaBlockedAlert — shared blocked-action alert (Phase 10).
 *
 * Renders the structured quota refusal payload (tier, quota type,
 * limit, current usage, upgrade path) whenever an API call returns the
 * backend `quota_exhausted` contract; any OTHER error falls through to
 * the standard PermissionDeniedAlert, so this component can be dropped
 * in place of it at every enforcement surface (invitation creation,
 * agent type creation, execution launch).
 */
import { useTranslation } from 'react-i18next'
import { Alert, Box, LinearProgress, Typography } from '@mui/material'
import BlockIcon from '@mui/icons-material/Block'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import { extractQuotaBlocked } from '../../utils/quotaErrorUtils'

interface QuotaBlockedAlertProps {
  error: unknown
  fallbackMessage?: string
}

const QUOTA_TYPE_KEY: Record<string, string> = {
  users: 'tenant.quota.quotaType.users',
  agent_types: 'tenant.quota.quotaType.agentTypes',
  monthly_executions: 'tenant.quota.quotaType.monthlyExecutions',
}

export default function QuotaBlockedAlert({
  error,
  fallbackMessage,
}: QuotaBlockedAlertProps) {
  const { t } = useTranslation()
  const payload = extractQuotaBlocked(error)

  if (!payload) {
    // Not a quota refusal — standard dialog error handling applies.
    return (
      <PermissionDeniedAlert error={error} fallbackMessage={fallbackMessage} />
    )
  }

  const percent =
    payload.limit > 0
      ? Math.min(100, Math.round((payload.used / payload.limit) * 100))
      : 100

  return (
    <Alert
      severity="warning"
      icon={<BlockIcon />}
      data-testid="quota-blocked-alert"
      sx={{
        mb: 2,
        '& .MuiAlert-message': { width: '100%' },
      }}
    >
      <Typography variant="subtitle2" fontWeight={700} gutterBottom>
        {t('tenant.quota.blockedTitle')}
      </Typography>
      <Typography variant="body2" gutterBottom>
        {t('tenant.quota.blockedBody', {
          quotaType: t(QUOTA_TYPE_KEY[payload.quota_type] ?? payload.quota_type),
          used: payload.used,
          limit: payload.limit,
          tier: t(`tenant.quota.tier.${payload.tier}`),
        })}
      </Typography>
      <Box sx={{ mt: 1, mb: 1 }}>
        <LinearProgress
          variant="determinate"
          value={percent}
          color="warning"
          sx={{ height: 8, borderRadius: 4 }}
        />
        <Typography variant="caption" color="text.secondary">
          {t('tenant.quota.usageMeters', { used: payload.used, limit: payload.limit })}
        </Typography>
      </Box>
      <Typography variant="body2">{t('tenant.quota.upgradePath')}</Typography>
    </Alert>
  )
}
