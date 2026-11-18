import type { ReactNode } from 'react'
import { Box, Typography, Button, Alert } from '@mui/material'
import { useTranslation } from 'react-i18next'
import Grid from '@mui/material/Grid'
import SmartToyIcon from '@mui/icons-material/SmartToy'
import PanToolIcon from '@mui/icons-material/PanTool'
import SettingsIcon from '@mui/icons-material/Settings'
import ScheduleIcon from '@mui/icons-material/Schedule'
import BadgeIcon from '@mui/icons-material/Badge'
import PersonIcon from '@mui/icons-material/Person'
import HubIcon from '@mui/icons-material/Hub'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import GppBadIcon from '@mui/icons-material/GppBad'
import EmailIcon from '@mui/icons-material/Email'
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings'
import { useDashboardMetrics } from '../hooks/useDashboardMetrics'
import { useTokenHealth } from '../hooks/useTokenHealth'
import {
  StatCard,
  type CardStatusTone,
  type StatCardProps,
} from '../components/dashboard/StatCard'
import { TimeSensitiveCard } from '../components/dashboard/TimeSensitiveCard'
import { DateRangePicker } from '../components/dashboard/DateRangePicker'

/** Severity of a single dashboard tile (FIX-20261116-214714). */
export type DashboardSeverity = 'critical' | 'warning' | 'normal'

type DashboardSectionKey = 'operational' | 'token' | 'time'

interface DashboardCardItem {
  /** Stable key used by the `dashboard-card-<key>` test wrapper. */
  key: string
  severity: DashboardSeverity
  node: ReactNode
}

interface DashboardSectionItem {
  key: DashboardSectionKey
  title: string
  gridSize: { xs: number; sm: number; md?: number; lg: number }
  cards: DashboardCardItem[]
}

const SEVERITY_RANK: Record<DashboardSeverity, number> = {
  critical: 0,
  warning: 1,
  normal: 2,
}

/** Count > 0 ⇒ the given severity, otherwise `normal`. */
function severityFromCount(
  count: number | undefined,
  positive: DashboardSeverity,
): DashboardSeverity {
  return (count ?? 0) > 0 ? positive : 'normal'
}

/** Actionable tiles are critical/warning; `success` alone never requires action. */
function isActionable(severity: DashboardSeverity): boolean {
  return severity !== 'normal'
}

/** `error` for critical, `warning` for warning, no tone for informational tiles. */
function actionableTone(severity: DashboardSeverity): CardStatusTone | undefined {
  if (severity === 'critical') return 'error'
  if (severity === 'warning') return 'warning'
  return undefined
}

/** Stable sort: critical → warning → normal (equal severities keep author order). */
function sortBySeverity<T extends { severity: DashboardSeverity }>(items: T[]): T[] {
  return [...items].sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity])
}

function highestSeverity(cards: DashboardCardItem[]): DashboardSeverity {
  return cards.reduce<DashboardSeverity>(
    (highest, card) =>
      SEVERITY_RANK[card.severity] < SEVERITY_RANK[highest] ? card.severity : highest,
    'normal',
  )
}

export function DashboardPage() {
  const { t } = useTranslation()

  const {
    data: dashboardData,
    isLoading: dashboardLoading,
    isError: dashboardError,
    startTime,
    endTime,
    setDateRange,
    refetch,
  } = useDashboardMetrics()

  const {
    data: tokenHealthData,
    isLoading: tokenHealthLoading,
    isError: tokenHealthError,
  } = useTokenHealth()

  const snapshot = dashboardData?.snapshot_counts
  const timeData = dashboardData?.time_sensitive
  const flags = dashboardData?.permission_flags

  const startDate = new Date(startTime)
  const endDate = new Date(endTime)

  function handleDateRangeChange(start: Date, end: Date) {
    setDateRange(start.toISOString(), end.toISOString())
  }

  // ── Token-health severities (+ tones: green only when nothing needs action) ──
  const identityExpired = tokenHealthData?.identities.expired_count ?? 0
  const identityExpiring = tokenHealthData?.identities.expiring_count ?? 0
  const identitySeverity: DashboardSeverity =
    identityExpired > 0 ? 'critical' : identityExpiring > 0 ? 'warning' : 'normal'

  const mcpExpired = tokenHealthData?.mcp_sessions.expired_count ?? 0
  const mcpExpiring = tokenHealthData?.mcp_sessions.expiring_count ?? 0
  const mcpSeverity: DashboardSeverity =
    mcpExpired > 0 ? 'critical' : mcpExpiring > 0 ? 'warning' : 'normal'

  // Only claim a green "healthy" tone once the health payload has actually
  // loaded — missing data or a failed fetch must stay neutral, never reassuring.
  const tokenHealthReady = !tokenHealthLoading && !tokenHealthError && !!tokenHealthData

  /** Healthy token tiles are green (success) but never "action required". */
  const tokenTone = (severity: DashboardSeverity): CardStatusTone | undefined => {
    if (!tokenHealthReady) return undefined
    return severity === 'normal' ? 'success' : (actionableTone(severity) as CardStatusTone)
  }

  // Operational tiles keep their authored order for equal severities; the
  // severity-derived tone/action-required props are applied at render time.
  const operationalTiles: Array<{
    key: string
    severity: DashboardSeverity
    props: StatCardProps
  }> = [
    {
      key: 'agent-types',
      severity: 'normal',
      props: {
        icon: <SmartToyIcon fontSize="inherit" />,
        label: t('dashboard.agentTypes'),
        value: snapshot?.agent_types ?? 0,
        subBreakdowns: [
          { label: `${snapshot?.agent_types_active ?? 0} ${t('dashboard.activeBreakdown')}`, color: '#15803D' },
          { label: `${snapshot?.agent_types_running ?? 0} ${t('dashboard.runningBreakdown')}`, color: '#1D4ED8' },
        ],
        isLoading: dashboardLoading,
        isPermissionDenied: flags?.agent_types ?? false,
        colorVariant: 'blue',
      },
    },
    {
      key: 'pending-interventions',
      severity: severityFromCount(snapshot?.pending_interventions, 'critical'),
      props: {
        icon: <PanToolIcon fontSize="inherit" />,
        label: t('dashboard.pendingInterventions'),
        value: snapshot?.pending_interventions ?? 0,
        subLabel: t('dashboard.pendingBreakdown'),
        isLoading: dashboardLoading,
        isPermissionDenied: flags?.interventions ?? false,
        colorVariant: 'orange',
        navigateTo: '/agents/intervene',
      },
    },
    {
      key: 'model-configs',
      severity: 'normal',
      props: {
        icon: <SettingsIcon fontSize="inherit" />,
        label: t('dashboard.modelConfigs'),
        value: snapshot?.model_counts ?? 0,
        subLabel: `${snapshot?.model_configs ?? 0} ${t('dashboard.vendorsBreakdown')}`,
        isLoading: dashboardLoading,
        isPermissionDenied: flags?.model_configs ?? false,
        colorVariant: 'purple',
        navigateTo: '/agents/model-configs',
      },
    },
    {
      key: 'active-schedules',
      severity: 'normal',
      props: {
        icon: <ScheduleIcon fontSize="inherit" />,
        label: t('dashboard.activeSchedules'),
        value: snapshot?.active_schedules ?? 0,
        subLabel: t('app.active'),
        isLoading: dashboardLoading,
        isPermissionDenied: flags?.schedules ?? false,
        colorVariant: 'green',
        navigateTo: '/schedules',
      },
    },
    {
      key: 'agent-identities',
      severity: 'normal',
      props: {
        icon: <BadgeIcon fontSize="inherit" />,
        label: t('dashboard.agentIdentities'),
        value: snapshot?.agent_identities ?? 0,
        subLabel: t('dashboard.provisionedBreakdown'),
        isLoading: dashboardLoading,
        isPermissionDenied: flags?.identities ?? false,
        colorVariant: 'teal',
      },
    },
    {
      key: 'agent-roles',
      severity: 'normal',
      props: {
        icon: <PersonIcon fontSize="inherit" />,
        label: t('dashboard.agentRoles'),
        value: snapshot?.agent_roles ?? 0,
        subLabel: t('dashboard.definedBreakdown'),
        isLoading: dashboardLoading,
        isPermissionDenied: flags?.roles ?? false,
        colorVariant: 'amber',
      },
    },
    {
      key: 'mcp-servers',
      severity: 'normal',
      props: {
        icon: <HubIcon fontSize="inherit" />,
        label: t('dashboard.mcpServers'),
        value: snapshot?.mcp_servers ?? 0,
        subLabel: t('dashboard.registeredBreakdown'),
        isLoading: dashboardLoading,
        isPermissionDenied: flags?.mcp_servers ?? false,
        colorVariant: 'red',
        navigateTo: '/mcp',
      },
    },
    {
      key: 'permission-requests',
      severity: severityFromCount(snapshot?.pending_access_requests, 'critical'),
      props: {
        icon: <AdminPanelSettingsIcon fontSize="inherit" />,
        label: t('dashboard.permissionRequests'),
        value: snapshot?.pending_access_requests ?? 0,
        subLabel: t('dashboard.pendingBreakdown'),
        isLoading: dashboardLoading,
        isPermissionDenied: flags?.permission_requests ?? false,
        colorVariant: 'slate',
        navigateTo: '/permissions/access-requests',
      },
    },
  ]

  const operationalCards: DashboardCardItem[] = operationalTiles.map((tile) => ({
    key: tile.key,
    severity: tile.severity,
    node: (
      <StatCard
        {...tile.props}
        statusTone={actionableTone(tile.severity)}
        actionRequired={isActionable(tile.severity)}
      />
    ),
  }))

  const tokenCards: DashboardCardItem[] = [
    {
      key: 'token-identities',
      severity: identitySeverity,
      node: (
        <StatCard
          icon={<GppBadIcon fontSize="inherit" />}
          label={t('dashboard.tokenHealthIdentities')}
          value={identityExpired}
          subBreakdowns={[
            {
              label: `${identityExpiring} ${t('dashboard.expiringWithin7Days')}`,
              color: '#C2410C',
            },
          ]}
          isLoading={tokenHealthLoading}
          isPermissionDenied={tokenHealthData?.permission_flags.identities ?? false}
          colorVariant={identitySeverity === 'critical' ? 'red' : identitySeverity === 'warning' ? 'amber' : 'green'}
          statusTone={tokenTone(identitySeverity)}
          actionRequired={tokenHealthReady && isActionable(identitySeverity)}
          navigateTo="/agents/identities"
        />
      ),
    },
    {
      key: 'token-mcp-sessions',
      severity: mcpSeverity,
      node: (
        <StatCard
          icon={<WarningAmberIcon fontSize="inherit" />}
          label={t('dashboard.tokenHealthMcpSessions')}
          value={mcpExpired}
          subBreakdowns={[
            {
              label: `${mcpExpiring} ${t('dashboard.expiringWithin7Days')}`,
              color: '#C2410C',
            },
          ]}
          isLoading={tokenHealthLoading}
          isPermissionDenied={tokenHealthData?.permission_flags.mcp_sessions ?? false}
          colorVariant={mcpSeverity === 'critical' ? 'red' : mcpSeverity === 'warning' ? 'orange' : 'green'}
          statusTone={tokenTone(mcpSeverity)}
          actionRequired={tokenHealthReady && isActionable(mcpSeverity)}
          navigateTo="/mcp"
        />
      ),
    },
  ]

  const timeSeverity = {
    guardrail: severityFromCount(timeData?.guardrail_breaches, 'critical'),
    executions: severityFromCount(timeData?.agent_executions?.failed, 'critical'),
    posture: severityFromCount(timeData?.posture_breaches, 'critical'),
    notifications: severityFromCount(timeData?.notification_failed, 'warning'),
  }

  const timeCards: DashboardCardItem[] = [
    {
      key: 'guardrail-breaches',
      severity: timeSeverity.guardrail,
      node: (
        <TimeSensitiveCard
          variant="single"
          icon={<GppBadIcon fontSize="inherit" />}
          label={t('dashboard.guardrailBreachEvents')}
          value={timeData?.guardrail_breaches ?? 0}
          isLoading={dashboardLoading}
          isPermissionDenied={flags?.guardrail_breaches ?? false}
          colorVariant="red"
          statusTone={actionableTone(timeSeverity.guardrail)}
          actionRequired={isActionable(timeSeverity.guardrail)}
        />
      ),
    },
    {
      key: 'agent-executions',
      severity: timeSeverity.executions,
      node: (
        <TimeSensitiveCard
          variant="dual"
          icon={<PlayArrowIcon fontSize="inherit" />}
          label={t('dashboard.agentExecutions')}
          completed={timeData?.agent_executions?.completed ?? 0}
          failed={timeData?.agent_executions?.failed ?? 0}
          isLoading={dashboardLoading}
          isPermissionDenied={flags?.executions ?? false}
          colorVariant="blue"
          statusTone={actionableTone(timeSeverity.executions)}
          actionRequired={isActionable(timeSeverity.executions)}
        />
      ),
    },
    {
      key: 'posture-breaches',
      severity: timeSeverity.posture,
      node: (
        <TimeSensitiveCard
          variant="single"
          icon={<WarningAmberIcon fontSize="inherit" />}
          label={t('dashboard.modelUsagePostureBreaches')}
          value={timeData?.posture_breaches ?? 0}
          isLoading={dashboardLoading}
          isPermissionDenied={flags?.posture_breaches ?? false}
          colorVariant="purple"
          statusTone={actionableTone(timeSeverity.posture)}
          actionRequired={isActionable(timeSeverity.posture)}
        />
      ),
    },
    {
      key: 'notification-delivery',
      severity: timeSeverity.notifications,
      node: (
        <TimeSensitiveCard
          variant="dual"
          icon={<EmailIcon fontSize="inherit" />}
          label={t('dashboard.notificationDelivery')}
          completed={timeData?.notification_delivered ?? 0}
          failed={timeData?.notification_failed ?? 0}
          isLoading={dashboardLoading}
          isPermissionDenied={flags?.notifications ?? false}
          colorVariant="teal"
          statusTone={actionableTone(timeSeverity.notifications)}
          actionRequired={isActionable(timeSeverity.notifications)}
        />
      ),
    },
  ]

  // Declared order is the stable tie-break for equal section severity.
  const sections: DashboardSectionItem[] = [
    {
      key: 'operational',
      title: t('dashboard.operationalMetrics'),
      gridSize: { xs: 12, sm: 6, md: 6, lg: 3 },
      cards: operationalCards,
    },
    {
      key: 'token',
      title: t('dashboard.tokenHealthSection'),
      gridSize: { xs: 12, sm: 6, md: 6, lg: 3 },
      cards: tokenCards,
    },
    {
      key: 'time',
      title: t('dashboard.timeSensitiveMetrics'),
      gridSize: { xs: 12, sm: 6, lg: 3 },
      cards: timeCards,
    },
  ]

  const rankedSections = [...sections].sort(
    (a, b) =>
      SEVERITY_RANK[highestSeverity(a.cards)] - SEVERITY_RANK[highestSeverity(b.cards)],
  )

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} gutterBottom>
        {t('nav.dashboard')}
      </Typography>
      <Typography variant="body1" color="text.secondary" mb={3}>
        {t('app.tagline')}
      </Typography>

      {dashboardError && (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          action={
            <Button color="inherit" size="small" onClick={() => refetch()}>
              {t('dashboard.retry')}
            </Button>
          }
        >
          {t('dashboard.loadingError')}
        </Alert>
      )}

      {rankedSections.map((section, index) => (
        <Box key={section.key} data-testid={`dashboard-section-${section.key}`}>
          <Typography
            variant="overline"
            sx={{
              fontWeight: 600, letterSpacing: 0.5, color: 'text.secondary',
              borderBottom: '1px solid', borderColor: 'divider',
              display: 'block', pb: 0.75, mb: 1.5, mt: index === 0 ? 0 : 1,
            }}
          >
            {section.title}
          </Typography>

          {/* The date-range picker belongs to the time-sensitive section. */}
          {section.key === 'time' && (
            <DateRangePicker
              startTime={startDate}
              endTime={endDate}
              onChange={handleDateRangeChange}
              isRefreshing={dashboardLoading}
            />
          )}

          <Grid container spacing={1.5} mb={3}>
            {sortBySeverity(section.cards).map((card) => (
              <Grid key={card.key} size={section.gridSize}>
                <Box
                  data-testid={`dashboard-card-${card.key}`}
                  data-severity={card.severity}
                  data-action-required={isActionable(card.severity) ? 'true' : 'false'}
                  sx={{ height: '100%' }}
                >
                  {card.node}
                </Box>
              </Grid>
            ))}
          </Grid>
        </Box>
      ))}
    </Box>
  )
}
