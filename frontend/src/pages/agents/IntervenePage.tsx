import { useState, type SyntheticEvent } from 'react'
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Paper,
  Tab,
  Tabs,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import RecordVoiceOverIcon from '@mui/icons-material/RecordVoiceOver'
import { useTranslation } from 'react-i18next'
import { useInterveneRequests } from '../../hooks/useInterveneRequests'
import { InterveneResponseDialog } from '../../components/agents/InterveneResponseDialog'
import { AgentExecutionDetailsDialog } from '../../components/agents/AgentExecutionDetailsDialog'
import type { InterveneRequest, InterventionType } from '../../types'

const TYPE_FILTERS: { key: string; value: InterventionType | '' }[] = [
  { key: 'intervene.filterAll', value: '' },
  { key: 'intervene.filterApproval', value: 'approval' },
  { key: 'intervene.filterChoice', value: 'choice' },
  { key: 'intervene.filterText', value: 'text' },
]

function timeAgo(dateStr: string): string {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ${minutes % 60}m`
}

function formatReceived(dateStr: string): string {
  const d = new Date(dateStr)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function secondsToDuration(totalSeconds: number): string {
  if (totalSeconds < 60) return `${Math.round(totalSeconds)}s`
  const minutes = Math.floor(totalSeconds / 60)
  const secs = Math.round(totalSeconds % 60)
  return `${minutes}m ${secs}s`
}

const typeChipConfig: Record<string, { color: 'warning' | 'info' | 'secondary'; labelKey: string }> = {
  approval: { color: 'warning', labelKey: 'intervene.typeApproval' },
  choice: { color: 'info', labelKey: 'intervene.typeChoice' },
  text: { color: 'secondary', labelKey: 'intervene.typeText' },
}

interface TabPanelProps {
  children: React.ReactNode
  index: number
  value: number
}

function TabPanel({ children, value, index }: TabPanelProps) {
  return (
    <Box role="tabpanel" hidden={value !== index} sx={{ pt: 2 }}>
      {value === index && children}
    </Box>
  )
}

interface RequestsTableProps {
  requests: InterveneRequest[]
  onRespond: (req: InterveneRequest) => void
  empty: boolean
}

function RequestsTable({ requests, onRespond, empty }: RequestsTableProps) {
  const { t } = useTranslation()
  if (empty) {
    return (
      <Paper sx={{ p: 6, textAlign: 'center' }}>
        <RecordVoiceOverIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />
        <Typography variant="h6" color="text.primary" gutterBottom>
          {t('intervene.emptyTitle', 'All caught up!')}
        </Typography>
        <Typography color="text.secondary">
          {t('intervene.emptyDesc', 'No pending intervene requests.')}
        </Typography>
      </Paper>
    )
  }

  return (
    <Paper>
      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{t('intervene.agent', 'Agent')}</TableCell>
              <TableCell>{t('intervene.executionId', 'Execution ID')}</TableCell>
              <TableCell>{t('intervene.reason', 'Reason')}</TableCell>
              <TableCell>{t('intervene.type', 'Type')}</TableCell>
              <TableCell>{t('intervene.received', 'Received')}</TableCell>
              <TableCell>{t('intervene.waitTime', 'Wait Time')}</TableCell>
              <TableCell align="right">{t('app.actions')}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {requests.map((req) => {
              const chip = typeChipConfig[req.intervention_type] ?? { color: 'default' as const, labelKey: '' }
              return (
                  <TableRow key={req.id} hover>
                    <TableCell>
                      <Typography variant="body2" fontWeight={500}>
                        {req.agent_name ?? (req.agent_type_id ? req.agent_type_id.slice(0, 8) + '…' : '—')}
                      </Typography>
                      {req.triggered_by_user_name && (
                        <Typography variant="caption" color="text.secondary" display="block">
                          by {req.triggered_by_user_name}
                        </Typography>
                      )}
                    </TableCell>
                  <TableCell>
                    <Typography variant="body2" fontFamily="monospace" fontSize={12} color="text.secondary">
                      {req.agent_session_id.slice(0, 8)}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography
                      variant="body2"
                      sx={{
                        maxWidth: 280,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {req.reason}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Chip label={t(chip.labelKey)} color={chip.color} size="small" />
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" color="text.secondary">
                      {formatReceived(req.created_at)}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={timeAgo(req.created_at)}
                      color="warning"
                      size="small"
                      variant="outlined"
                    />
                  </TableCell>
                  <TableCell align="right">
                    <Button
                      size="small"
                      variant="outlined"
                      onClick={() => onRespond(req)}
                    >
                      {t('intervene.respond', 'Respond')}
                    </Button>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  )
}

export function IntervenePage() {
  const { t } = useTranslation()
  const [tab, setTab] = useState(0)
  const [typeFilter, setTypeFilter] = useState<InterventionType | ''>('')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [selectedRequest, setSelectedRequest] = useState<InterveneRequest | null>(null)
  const [executionDialogOpen, setExecutionDialogOpen] = useState(false)
  const [executionSessionId, setExecutionSessionId] = useState<string | null>(null)

  const {
    pendingRequests,
    respondedRequests,
    metrics,
    isLoading,
    error,
    submitResponse,
    refetch,
  } = useInterveneRequests({ typeFilter: typeFilter || undefined })

  const handleTabChange = (_: SyntheticEvent, newValue: number) => setTab(newValue)

  const handleOpenDialog = (req: InterveneRequest) => {
    setSelectedRequest(req)
    setDialogOpen(true)
  }

  const handleCloseDialog = () => {
    setDialogOpen(false)
    setSelectedRequest(null)
  }

  const handleSubmitResponse = async (requestId: string, value: {
    approval_value?: boolean
    selected_choice?: string
    text_value?: string
  }) => {
    await submitResponse(requestId, value)
    // Auto-open execution dialog for the session after response
    const req = selectedRequest
    if (req?.agent_session_id) {
      setExecutionSessionId(req.agent_session_id)
      setExecutionDialogOpen(true)
    }
  }

  const handleCloseExecutionDialog = () => {
    setExecutionDialogOpen(false)
    setExecutionSessionId(null)
  }

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="flex-start" mb={3}>
        <Box>
          <Typography variant="h4" fontWeight={700} mb={0.5}>
            {t('intervene.pageTitle', 'Intervene Requests')}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t('intervene.pageDesc', 'Review and respond to agent requests for human input.')}
          </Typography>
        </Box>
        <Button variant="outlined" onClick={() => void refetch()}>
          {t('app.refresh')}
        </Button>
      </Box>

      {/* Stats row */}
      <Box display="flex" gap={2} mb={3} flexWrap="wrap">
        <Paper sx={{ p: 2, flex: 1, minWidth: 160, display: 'flex', alignItems: 'center', gap: 2 }}>
          <Box
            sx={{
              width: 40,
              height: 40,
              borderRadius: 1,
              bgcolor: 'warning.light',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 20,
            }}
          >
            🛑
          </Box>
          <Box>
            <Typography variant="h5" fontWeight={700} lineHeight={1.2}>
              {isLoading ? '—' : metrics?.pending_count ?? 0}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {t('intervene.metricsPendingCount', 'Pending Requests')}
            </Typography>
          </Box>
        </Paper>
        <Paper sx={{ p: 2, flex: 1, minWidth: 160, display: 'flex', alignItems: 'center', gap: 2 }}>
          <Box
            sx={{
              width: 40,
              height: 40,
              borderRadius: 1,
              bgcolor: 'info.light',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 20,
            }}
          >
            ⏳
          </Box>
          <Box>
            <Typography variant="h5" fontWeight={700} lineHeight={1.2}>
              {isLoading ? '—' : metrics ? secondsToDuration(metrics.avg_response_time_seconds) : '—'}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {t('intervene.metricsAvgResponseTime', 'Avg. Response Time')}
            </Typography>
          </Box>
        </Paper>
        <Paper sx={{ p: 2, flex: 1, minWidth: 160, display: 'flex', alignItems: 'center', gap: 2 }}>
          <Box
            sx={{
              width: 40,
              height: 40,
              borderRadius: 1,
              bgcolor: 'success.light',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 20,
            }}
          >
            ✅
          </Box>
          <Box>
            <Typography variant="h5" fontWeight={700} lineHeight={1.2}>
              {isLoading ? '—' : respondedRequests.length}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {t('intervene.metricsResolvedToday', 'Resolved Today')}
            </Typography>
          </Box>
        </Paper>
        <Paper sx={{ p: 2, flex: 1, minWidth: 160, display: 'flex', alignItems: 'center', gap: 2 }}>
          <Box
            sx={{
              width: 40,
              height: 40,
              borderRadius: 1,
              bgcolor: 'secondary.light',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 20,
            }}
          >
            📊
          </Box>
          <Box>
            <Typography variant="h5" fontWeight={700} lineHeight={1.2}>
              {isLoading ? '—' : metrics ? `${Math.round(metrics.resolution_rate * 100)}%` : '—'}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {t('intervene.metricsResolutionRate', 'Resolution Rate')}
            </Typography>
          </Box>
        </Paper>
      </Box>

      {/* Tabs: Pending | History */}
      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 2 }}>
        <Tabs value={tab} onChange={handleTabChange}>
          <Tab
            label={
              <Box display="flex" alignItems="center" gap={1}>
                <span>{t('intervene.title', 'Pending')}</span>
                {pendingRequests.length > 0 && (
                  <Chip label={pendingRequests.length} size="small" color="warning" sx={{ height: 20, minWidth: 20, '& .MuiChip-label': { px: 0.5, fontSize: 11 } }} />
                )}
              </Box>
            }
          />
          <Tab label={t('intervene.historyTitle', 'Response History')} />
        </Tabs>
      </Box>

      {/* Error state */}
      {!!error && (
        <Paper sx={{ p: 3, mb: 2, bgcolor: 'error.light' }}>
          <Typography color="error.dark">{t('app.error')}</Typography>
        </Paper>
      )}

      {/* Loading state */}
      {isLoading && (
        <Box display="flex" justifyContent="center" py={8}>
          <CircularProgress />
        </Box>
      )}

      {!isLoading && (
        <>
          {/* Pending tab */}
          <TabPanel value={tab} index={0}>
            {/* Type filter chips */}
            <Box display="flex" gap={1} mb={2}>
              {TYPE_FILTERS.map((f) => (
                <Button
                  key={f.key}
                  size="small"
                  variant={typeFilter === f.value ? 'contained' : 'outlined'}
                  onClick={() => setTypeFilter(f.value)}
                  sx={{ minWidth: 0 }}
                >
                  {t(f.key)}
                </Button>
              ))}
            </Box>

            <RequestsTable
              requests={pendingRequests}
              onRespond={handleOpenDialog}
              empty={pendingRequests.length === 0}
            />
          </TabPanel>

          {/* History tab */}
          <TabPanel value={tab} index={1}>
            {respondedRequests.length === 0 ? (
              <Paper sx={{ p: 6, textAlign: 'center' }}>
                <RecordVoiceOverIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />
                <Typography color="text.secondary">
                  {t('intervene.noPendingRequests', 'No responded requests yet.')}
                </Typography>
              </Paper>
            ) : (
              <Paper>
                <TableContainer>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>{t('intervene.agent', 'Agent')}</TableCell>
                        <TableCell>{t('intervene.executionId', 'Execution ID')}</TableCell>
                        <TableCell>{t('intervene.type', 'Type')}</TableCell>
                        <TableCell>{t('intervene.responseDetails', 'Response')}</TableCell>
                        <TableCell>{t('intervene.respondedBy', 'Responded by')}</TableCell>
                        <TableCell>{t('intervene.respondedAt', 'Responded at')}</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {respondedRequests.map((req) => {
                        const chip = typeChipConfig[req.intervention_type] ?? { color: 'default' as const, labelKey: '' }
                        const isApproved = req.response?.approval_value === true
                        const isRejected = req.response?.approval_value === false
                        let responseLabel = '—'
                        if (isApproved) responseLabel = t('intervene.approvalValue', 'Approved')
                        else if (isRejected) responseLabel = t('intervene.rejectionValue', 'Rejected')
                        else if (req.response?.selected_choice) responseLabel = req.response.selected_choice
                        else if (req.response?.text_value) responseLabel = req.response.text_value.slice(0, 60)

                        return (
                          <TableRow key={req.id}>
                            <TableCell>
                              <Typography variant="body2" fontWeight={500}>
                                {req.agent_name ?? (req.agent_type_id ? req.agent_type_id.slice(0, 8) + '…' : '—')}
                              </Typography>
                            </TableCell>
                            <TableCell>
                              <Typography variant="body2" fontFamily="monospace" fontSize={12} color="text.secondary">
                                {req.agent_session_id.slice(0, 8)}
                              </Typography>
                            </TableCell>
                            <TableCell>
                              <Chip label={t(chip.labelKey)} color={chip.color} size="small" />
                            </TableCell>
                            <TableCell>
                              <Chip
                                label={responseLabel}
                                color={isApproved ? 'success' : isRejected ? 'error' : 'info'}
                                size="small"
                                variant="outlined"
                              />
                            </TableCell>
                            <TableCell>
                              <Typography variant="body2">{req.response?.operator_user_name ?? req.response?.operator_user_id?.slice(0, 12) ?? '—'}</Typography>
                            </TableCell>
                            <TableCell>
                              <Typography variant="body2" color="text.secondary">
                                {req.responded_at ? new Date(req.responded_at).toLocaleString() : '—'}
                              </Typography>
                            </TableCell>
                          </TableRow>
                        )
                      })}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Paper>
            )}
          </TabPanel>
        </>
      )}

      {/* Response dialog */}
      <InterveneResponseDialog
        open={dialogOpen}
        request={selectedRequest}
        onClose={handleCloseDialog}
        onSubmit={handleSubmitResponse}
      />

      {/* Auto-open execution dialog after response */}
      {executionSessionId && (
        <AgentExecutionDetailsDialog
          open={executionDialogOpen}
          onClose={handleCloseExecutionDialog}
          sessionId={executionSessionId}
        />
      )}
    </Box>
  )
}
