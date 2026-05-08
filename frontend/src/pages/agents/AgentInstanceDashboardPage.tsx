import { useState } from 'react'
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import apiClient from '../../api/apiClient'
import type { AgentJob, AgentJobStatus } from '../../types'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'

const STATUS_OPTIONS: AgentJobStatus[] = ['queued', 'running', 'completed', 'failed']

function statusColor(
  status: AgentJobStatus,
): 'default' | 'warning' | 'info' | 'success' | 'error' {
  if (status === 'queued') return 'default'
  if (status === 'running') return 'info'
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'error'
  return 'warning'
}

export function AgentInstanceDashboardPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const [filterStatus, setFilterStatus] = useState<AgentJobStatus | ''>('')
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')

  const queryParams = new URLSearchParams()
  if (filterStatus) queryParams.set('status', filterStatus)
  if (fromDate) queryParams.set('from_date', new Date(fromDate).toISOString())
  if (toDate) queryParams.set('to_date', new Date(toDate).toISOString())

  const {
    data: sessions,
    isLoading,
    error,
    refetch,
  } = useQuery<AgentJob[]>({
    queryKey: ['agents', 'sessions', 'dashboard', filterStatus, fromDate, toDate],
    queryFn: async () => {
      const qs = queryParams.toString()
      const { data } = await apiClient.get<AgentJob[]>(`/agents/sessions${qs ? `?${qs}` : ''}`)
      return data
    },
  })

  const handleClearFilters = () => {
    setFilterStatus('')
    setFromDate('')
    setToDate('')
  }

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="flex-start" mb={3}>
        <Box>
          <Typography variant="h4" fontWeight={700} mb={0.5}>
            {t('agents.sessions.dashboardTitle')}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t('agents.sessions.dashboardSubtitle')}
          </Typography>
        </Box>
        <Button variant="outlined" onClick={() => void refetch()}>
          {t('app.refresh')}
        </Button>
      </Box>

      {/* Filter controls */}
      <Paper sx={{ p: 2, mb: 3 }}>
        <Box display="flex" gap={2} flexWrap="wrap" alignItems="center">
          <FormControl size="small" sx={{ minWidth: 160 }}>
            <InputLabel>{t('agents.sessions.filterStatus')}</InputLabel>
            <Select
              value={filterStatus}
              label={t('agents.sessions.filterStatus')}
              onChange={(e) => setFilterStatus(e.target.value as AgentJobStatus | '')}
            >
              <MenuItem value=""><em>{t('agents.sessions.allStatuses')}</em></MenuItem>
              {STATUS_OPTIONS.map((s) => (
                <MenuItem key={s} value={s}>
                  {t(`agents.sessions.status${s.replace(/^./, (c: string) => c.toUpperCase())}`)}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <TextField
            label={t('agents.sessions.filterFrom')}
            type="datetime-local"
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
            size="small"
            InputLabelProps={{ shrink: true }}
          />

          <TextField
            label={t('agents.sessions.filterTo')}
            type="datetime-local"
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
            size="small"
            InputLabelProps={{ shrink: true }}
          />

          {(filterStatus || fromDate || toDate) && (
            <Button variant="text" size="small" onClick={handleClearFilters}>
              {t('agents.sessions.clearFilters')}
            </Button>
          )}
        </Box>
      </Paper>

      {error && <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />}

      {isLoading ? (
        <Box display="flex" justifyContent="center" pt={4}>
          <CircularProgress />
        </Box>
      ) : sessions && sessions.length === 0 ? (
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography color="text.secondary">{t('agents.sessions.dashboardEmpty')}</Typography>
        </Paper>
      ) : (
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>{t('agents.sessions.sessionId')}</TableCell>
                <TableCell>{t('app.status')}</TableCell>
                <TableCell>{t('agents.sessions.createdAt')}</TableCell>
                <TableCell>{t('agents.sessions.startedAt')}</TableCell>
                <TableCell>{t('agents.sessions.completedAt')}</TableCell>
                <TableCell align="right">{t('app.actions')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(sessions ?? []).map((session) => (
                <TableRow key={session.id} hover>
                  <TableCell>
                    <Typography variant="body2" fontFamily="monospace" fontSize={12}>
                      {session.id.slice(0, 8)}…
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={t(`agents.sessions.status${session.status.replace(/^./, (c: string) => c.toUpperCase())}`)}
                      color={statusColor(session.status)}
                      size="small"
                    />
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">
                      {new Date(session.created_at).toLocaleString()}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">
                      {session.started_at ? new Date(session.started_at).toLocaleString() : '—'}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">
                      {session.completed_at ? new Date(session.completed_at).toLocaleString() : '—'}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">
                    <Button
                      size="small"
                      endIcon={<OpenInNewIcon fontSize="small" />}
                      onClick={() => navigate(`/agents/sessions/${session.id}`)}
                    >
                      {t('agents.sessions.view')}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Box>
  )
}
