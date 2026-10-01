/**
 * PlatformAuditPage — cross-tenant security view for the platform admin.
 *
 * Lists TenantAuditEvents (lifecycle + security-relevant) with filters
 * for tenant, event type, security relevance, and date range.  Shows
 * tenant attribution only — never tenant business data.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Chip,
  MenuItem,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import {
  listAuditEvents,
  listTenants,
  type TenantAuditEventType,
} from '../../api/platformAdminApi'

const EVENT_TYPES: TenantAuditEventType[] = [
  'tenant_created',
  'tenant_updated',
  'tenant_suspended',
  'tenant_resumed',
  'tenant_deleted',
  'cross_tenant_access_denied',
  'tenant_boundary_violation',
  'platform_setting_updated',
]

export function PlatformAuditPage() {
  const { t } = useTranslation()
  const [tenantId, setTenantId] = useState('')
  const [eventType, setEventType] = useState<TenantAuditEventType | ''>('')
  const [securityOnly, setSecurityOnly] = useState(false)
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const tenantsQuery = useQuery({
    queryKey: ['platform', 'tenants'],
    queryFn: () => listTenants(),
  })

  const eventsQuery = useQuery({
    queryKey: [
      'platform',
      'audit-events',
      tenantId,
      eventType,
      securityOnly,
      dateFrom,
      dateTo,
    ],
    queryFn: () =>
      listAuditEvents({
        tenant_id: tenantId || undefined,
        event_type: eventType || undefined,
        security_only: securityOnly || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        limit: 100,
      }),
  })

  const events = eventsQuery.data?.items ?? []

  return (
    <Box p={3}>
      <Typography variant="h5" mb={2}>
        {t('platform.audit.title')}
      </Typography>

      <Paper sx={{ p: 2, mb: 2 }} data-testid="audit-filters">
        <Box display="flex" gap={2} flexWrap="wrap">
          <TextField
            select
            size="small"
            label={t('platform.audit.tenant')}
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            sx={{ minWidth: 200 }}
          >
            <MenuItem value="">{t('platform.audit.allTenants')}</MenuItem>
            {(tenantsQuery.data?.items ?? []).map((tenant) => (
              <MenuItem key={tenant.id} value={tenant.id}>
                {tenant.name}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            size="small"
            label={t('platform.audit.eventType')}
            value={eventType}
            onChange={(e) => setEventType(e.target.value as TenantAuditEventType | '')}
            sx={{ minWidth: 240 }}
          >
            <MenuItem value="">{t('platform.audit.allEvents')}</MenuItem>
            {EVENT_TYPES.map((et) => (
              <MenuItem key={et} value={et}>
                {t(`platform.audit.event.${et}`)}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            size="small"
            label={t('platform.audit.severity')}
            value={securityOnly ? 'security' : 'all'}
            onChange={(e) => setSecurityOnly(e.target.value === 'security')}
            sx={{ minWidth: 160 }}
          >
            <MenuItem value="all">{t('platform.audit.allSeverities')}</MenuItem>
            <MenuItem value="security">{t('platform.audit.securityOnly')}</MenuItem>
          </TextField>
          <TextField
            size="small"
            type="date"
            label={t('platform.audit.from')}
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            slotProps={{ inputLabel: { shrink: true } }}
          />
          <TextField
            size="small"
            type="date"
            label={t('platform.audit.to')}
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            slotProps={{ inputLabel: { shrink: true } }}
          />
        </Box>
      </Paper>

      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{t('platform.audit.time')}</TableCell>
              <TableCell>{t('platform.audit.eventType')}</TableCell>
              <TableCell>{t('platform.audit.tenant')}</TableCell>
              <TableCell>{t('platform.audit.target')}</TableCell>
              <TableCell>{t('platform.audit.actor')}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {eventsQuery.isLoading ? (
              <TableRow>
                <TableCell colSpan={5} align="center">
                  {t('app.loading')}
                </TableCell>
              </TableRow>
            ) : events.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} align="center">
                  {t('platform.audit.empty')}
                </TableCell>
              </TableRow>
            ) : (
              events.map((event) => (
                <TableRow key={event.id}>
                  <TableCell>
                    {event.created_at ? new Date(event.created_at).toLocaleString() : '—'}
                  </TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      color={event.is_security_relevant ? 'error' : 'default'}
                      label={t(`platform.audit.event.${event.event_type}`)}
                    />
                  </TableCell>
                  <TableCell>{event.tenant_slug ?? t('platform.audit.platform')}</TableCell>
                  <TableCell>{event.target_resource ?? '—'}</TableCell>
                  <TableCell>{t(`platform.audit.actor.${event.actor_type}`)}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  )
}
