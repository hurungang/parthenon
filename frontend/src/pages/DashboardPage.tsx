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
import { StatCard } from '../components/dashboard/StatCard'
import { TimeSensitiveCard } from '../components/dashboard/TimeSensitiveCard'
import { DateRangePicker } from '../components/dashboard/DateRangePicker'

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

  const snapshot = dashboardData?.snapshot_counts
  const timeData = dashboardData?.time_sensitive
  const flags = dashboardData?.permission_flags

  const startDate = new Date(startTime)
  const endDate = new Date(endTime)

  function handleDateRangeChange(start: Date, end: Date) {
    setDateRange(start.toISOString(), end.toISOString())
  }

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

      {/* ═══════ OPERATIONAL METRICS ═══════ */}
      <Typography
        variant="overline"
        sx={{
          fontWeight: 600, letterSpacing: 0.5, color: 'text.secondary',
          borderBottom: '1px solid', borderColor: 'divider',
          display: 'block', pb: 0.75, mb: 1.5,
        }}
      >
        {t('dashboard.operationalMetrics')}
      </Typography>

      <Grid container spacing={1.5} mb={3}>
        <Grid size={{ xs: 12, sm: 6, md: 6, lg: 3 }}>
          <StatCard
            icon={<SmartToyIcon fontSize="inherit" />}
            label={t('dashboard.agentTypes')}
            value={snapshot?.agent_types ?? 0}
            subBreakdowns={[
              { label: `${snapshot?.agent_types_active ?? 0} ${t('dashboard.activeBreakdown')}`, color: '#15803D' },
              { label: `${snapshot?.agent_types_running ?? 0} ${t('dashboard.runningBreakdown')}`, color: '#1D4ED8' },
            ]}
            isLoading={dashboardLoading}
            isPermissionDenied={flags?.agent_types ?? false}
            colorVariant="blue"
          />
        </Grid>

        <Grid size={{ xs: 12, sm: 6, md: 6, lg: 3 }}>
          <StatCard
            icon={<PanToolIcon fontSize="inherit" />}
            label={t('dashboard.pendingInterventions')}
            value={snapshot?.pending_interventions ?? 0}
            subLabel={t('dashboard.pendingBreakdown')}
            isLoading={dashboardLoading}
            isPermissionDenied={flags?.interventions ?? false}
            colorVariant="orange"
            navigateTo="/agents/intervene"
          />
        </Grid>

        <Grid size={{ xs: 12, sm: 6, md: 6, lg: 3 }}>
          <StatCard
            icon={<SettingsIcon fontSize="inherit" />}
            label={t('dashboard.modelConfigs')}
            value={snapshot?.model_counts ?? 0}
            subLabel={`${snapshot?.model_configs ?? 0} ${t('dashboard.vendorsBreakdown')}`}
            isLoading={dashboardLoading}
            isPermissionDenied={flags?.model_configs ?? false}
            colorVariant="purple"
            navigateTo="/agents/model-configs"
          />
        </Grid>

        <Grid size={{ xs: 12, sm: 6, md: 6, lg: 3 }}>
          <StatCard
            icon={<ScheduleIcon fontSize="inherit" />}
            label={t('dashboard.activeSchedules')}
            value={snapshot?.active_schedules ?? 0}
            subLabel={t('app.active')}
            isLoading={dashboardLoading}
            isPermissionDenied={flags?.schedules ?? false}
            colorVariant="green"
            navigateTo="/schedules"
          />
        </Grid>

        <Grid size={{ xs: 12, sm: 6, md: 6, lg: 3 }}>
          <StatCard
            icon={<BadgeIcon fontSize="inherit" />}
            label={t('dashboard.agentIdentities')}
            value={snapshot?.agent_identities ?? 0}
            subLabel={t('dashboard.provisionedBreakdown')}
            isLoading={dashboardLoading}
            isPermissionDenied={flags?.identities ?? false}
            colorVariant="teal"
          />
        </Grid>

        <Grid size={{ xs: 12, sm: 6, md: 6, lg: 3 }}>
          <StatCard
            icon={<PersonIcon fontSize="inherit" />}
            label={t('dashboard.agentRoles')}
            value={snapshot?.agent_roles ?? 0}
            subLabel={t('dashboard.definedBreakdown')}
            isLoading={dashboardLoading}
            isPermissionDenied={flags?.roles ?? false}
            colorVariant="amber"
          />
        </Grid>

        <Grid size={{ xs: 12, sm: 6, md: 6, lg: 3 }}>
          <StatCard
            icon={<HubIcon fontSize="inherit" />}
            label={t('dashboard.mcpServers')}
            value={snapshot?.mcp_servers ?? 0}
            subLabel={t('dashboard.registeredBreakdown')}
            isLoading={dashboardLoading}
            isPermissionDenied={flags?.mcp_servers ?? false}
            colorVariant="red"
            navigateTo="/mcp"
          />
        </Grid>

        <Grid size={{ xs: 12, sm: 6, md: 6, lg: 3 }}>
          <StatCard
            icon={<AdminPanelSettingsIcon fontSize="inherit" />}
            label={t('dashboard.permissionRequests')}
            value={snapshot?.pending_access_requests ?? 0}
            subLabel={t('dashboard.pendingBreakdown')}
            isLoading={dashboardLoading}
            isPermissionDenied={flags?.permission_requests ?? false}
            colorVariant="slate"
            navigateTo="/permissions/access-requests"
          />
        </Grid>
      </Grid>

      {/* ═══════ TIME-SENSITIVE METRICS ═══════ */}
      <Typography
        variant="overline"
        sx={{
          fontWeight: 600, letterSpacing: 0.5, color: 'text.secondary',
          borderBottom: '1px solid', borderColor: 'divider',
          display: 'block', pb: 0.75, mb: 1.5, mt: 1,
        }}
      >
        {t('dashboard.timeSensitiveMetrics')}
      </Typography>

      <DateRangePicker
        startTime={startDate}
        endTime={endDate}
        onChange={handleDateRangeChange}
        isRefreshing={dashboardLoading}
      />

      <Grid container spacing={1.5} mb={3}>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <TimeSensitiveCard
            variant="single"
            icon={<GppBadIcon fontSize="inherit" />}
            label={t('dashboard.guardrailBreachEvents')}
            value={timeData?.guardrail_breaches ?? 0}
            isLoading={dashboardLoading}
            isPermissionDenied={flags?.guardrail_breaches ?? false}
            colorVariant="red"
          />
        </Grid>

        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <TimeSensitiveCard
            variant="dual"
            icon={<PlayArrowIcon fontSize="inherit" />}
            label={t('dashboard.agentExecutions')}
            completed={timeData?.agent_executions?.completed ?? 0}
            failed={timeData?.agent_executions?.failed ?? 0}
            isLoading={dashboardLoading}
            isPermissionDenied={flags?.executions ?? false}
            colorVariant="blue"
          />
        </Grid>

        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <TimeSensitiveCard
            variant="single"
            icon={<WarningAmberIcon fontSize="inherit" />}
            label={t('dashboard.modelUsagePostureBreaches')}
            value={timeData?.posture_breaches ?? 0}
            isLoading={dashboardLoading}
            isPermissionDenied={flags?.posture_breaches ?? false}
            colorVariant="purple"
          />
        </Grid>

        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <TimeSensitiveCard
            variant="dual"
            icon={<EmailIcon fontSize="inherit" />}
            label={t('dashboard.notificationDelivery')}
            completed={timeData?.notification_delivered ?? 0}
            failed={timeData?.notification_failed ?? 0}
            isLoading={dashboardLoading}
            isPermissionDenied={flags?.notifications ?? false}
            colorVariant="teal"
          />
        </Grid>
      </Grid>
    </Box>
  )
}
