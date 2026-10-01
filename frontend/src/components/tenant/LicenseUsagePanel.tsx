/**
 * LicenseUsagePanel — tenant license & usage panel (Phase 10).
 *
 * Shows the tenant's tier (free default when unlicensed), effective
 * limits and per-limit usage meters (users, agent types, executions
 * this month) fed by the tenant usage API.  Server state only — React
 * Query refetches on mount, so license changes made on the platform
 * side are reflected the next time the panel is shown without any
 * manual reload.
 */
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Card,
  CardContent,
  Chip,
  LinearProgress,
  Typography,
} from '@mui/material'
import WorkspacePremiumIcon from '@mui/icons-material/WorkspacePremium'
import { getTenantUsage } from '../../api/tenantApi'
import type { TenantUsageRead } from '../../types'

interface LicenseUsagePanelProps {
  /** Optional externally-loaded usage (defaults to self-fetching) */
  usage?: TenantUsageRead
}

function UsageMeter({
  label,
  used,
  limit,
}: {
  label: string
  used: number
  limit: number
}) {
  const { t } = useTranslation()
  const percent = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0
  const nearLimit = percent >= 80
  return (
    <Box sx={{ mt: 2 }} data-testid="usage-meter">
      <Box display="flex" justifyContent="space-between" mb={0.5}>
        <Typography variant="body2">{label}</Typography>
        <Typography
          variant="body2"
          color={nearLimit ? 'warning.main' : 'text.secondary'}
        >
          {t('tenant.usage.of', { used, limit })}
        </Typography>
      </Box>
      <LinearProgress
        variant="determinate"
        value={percent}
        color={nearLimit ? 'warning' : 'primary'}
        sx={{ height: 8, borderRadius: 4 }}
      />
    </Box>
  )
}

export function LicenseUsagePanel({ usage: external }: LicenseUsagePanelProps = {}) {
  const { t } = useTranslation()

  const usageQuery = useQuery({
    queryKey: ['tenant', 'usage'],
    queryFn: getTenantUsage,
    enabled: external === undefined,
  })

  const usage = external ?? usageQuery.data

  if (usage === undefined) {
    return null
  }

  return (
    <Card sx={{ mt: 2 }} data-testid="license-usage-panel">
      <CardContent>
        <Box display="flex" alignItems="center" gap={1} mb={1}>
          <WorkspacePremiumIcon color="primary" />
          <Typography variant="h6">{t('tenant.usage.title')}</Typography>
          <Chip
            size="small"
            color={usage.tier === 'free' ? 'default' : 'primary'}
            label={t(`tenant.quota.tier.${usage.tier}`)}
            data-testid="license-tier-chip"
          />
        </Box>
        {usage.tier === 'free' && (
          <Typography variant="body2" color="text.secondary" gutterBottom>
            {t('tenant.usage.freeDefaults')}
          </Typography>
        )}
        <UsageMeter
          label={t('tenant.usage.users')}
          used={usage.users}
          limit={usage.max_users}
        />
        <UsageMeter
          label={t('tenant.usage.agentTypes')}
          used={usage.agent_types}
          limit={usage.max_agent_types}
        />
        <UsageMeter
          label={t('tenant.usage.executionsThisMonth')}
          used={usage.executions_this_month}
          limit={usage.monthly_agent_executions}
        />
      </CardContent>
    </Card>
  )
}

export default LicenseUsagePanel
