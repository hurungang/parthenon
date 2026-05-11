import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  Link,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import { useQuery } from '@tanstack/react-query'
import { useAgentType } from '../../hooks/useAgentTypes'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import AgentPlanContent from './AgentPlanContent'
import { AgentJobLaunchDialog } from '../../pages/agents/AgentJobLaunchDialog'
import { AgentRoleViewDialog } from './AgentRoleViewDialog'
import { AgentIdentityViewDialog } from './AgentIdentityViewDialog'
import { AgentExecutionsDialog } from './AgentExecutionsDialog'
import { AgentExecutionDetailsDialog } from './AgentExecutionDetailsDialog'
import apiClient from '../../api/apiClient'
import type { AgentIdentity, AgentJob, AgentJobStatus, AgentRole } from '../../types'

// ── Helpers ────────────────────────────────────────────────────────────────────

function statusColor(
  status: AgentJobStatus,
): 'default' | 'warning' | 'info' | 'success' | 'error' {
  if (status === 'queued') return 'default'
  if (status === 'running') return 'info'
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'error'
  return 'warning'
}

// ── Tab Panel ─────────────────────────────────────────────────────────────────

interface TabPanelProps {
  children?: React.ReactNode
  index: number
  value: number
}

function TabPanel({ children, value, index }: TabPanelProps) {
  return (
    <Box
      role="tabpanel"
      hidden={value !== index}
      id={`agent-details-tabpanel-${index}`}
      aria-labelledby={`agent-details-tab-${index}`}
      sx={{ pt: 2 }}
    >
      {value === index && children}
    </Box>
  )
}

// ── Props ──────────────────────────────────────────────────────────────────────

interface AgentTypeDetailsDialogProps {
  open: boolean
  agentTypeId: string | null
  onClose: () => void
}

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * Dialog showing agent type details, plan preview, and execution logs.
 * Follows the Dialog Error Handling Standard from docs/config.yaml.
 */
export function AgentTypeDetailsDialog({
  open,
  agentTypeId,
  onClose,
}: AgentTypeDetailsDialogProps) {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState(0)
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [launchOpen, setLaunchOpen] = useState(false)
  const [roleViewOpen, setRoleViewOpen] = useState(false)
  const [identityViewOpen, setIdentityViewOpen] = useState(false)
  const [executionsDialogOpen, setExecutionsDialogOpen] = useState(false)
  const [executionDetailsDialogOpen, setExecutionDetailsDialogOpen] = useState(false)
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)

  // Reset tab and error when dialog opens
  useEffect(() => {
    if (open) {
      setActiveTab(0)
      setDialogError(null)
    }
  }, [open])

  const {
    data: agentType,
    isLoading,
    error: fetchError,
  } = useAgentType(agentTypeId ?? '')

  // Show fetch errors via dialogError pattern
  useEffect(() => {
    if (fetchError) {
      setDialogError(fetchError)
    }
  }, [fetchError])

  // Execution Logs tab query — keyed separately from the page-level cache
  const { data: dialogSessions, isLoading: sessionsLoading } = useQuery<AgentJob[]>({
    queryKey: ['agents', 'sessions', 'dialog', agentTypeId],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentJob[]>(
        `/agents/sessions?agent_type_id=${agentTypeId}&limit=10`,
      )
      return data
    },
    enabled: !!agentTypeId && open && activeTab === 2,
  })

  // Role/identity name resolution — fetches all roles/identities (uses cached React Query data)
  const { data: allRoles } = useQuery<AgentRole[]>({
    queryKey: ['agents', 'roles'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentRole[]>('/agents/roles')
      return data
    },
    enabled: open && !!agentType?.role_id,
  })

  const { data: allIdentities } = useQuery<AgentIdentity[]>({
    queryKey: ['agents', 'identities'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentIdentity[]>('/agents/identities')
      return data
    },
    enabled: open && !!agentType?.identity_id,
  })

  const roleName = agentType?.role_id
    ? (allRoles?.find((r) => r.id === agentType.role_id)?.name ?? agentType.role_id)
    : null

  const identityName = agentType?.identity_id
    ? (allIdentities?.find((i) => i.id === agentType.identity_id)?.name ?? agentType.identity_id)
    : null

  const handleClose = () => {
    setDialogError(null)
    onClose()
  }

  const handleViewAllExecutions = () => {
    setExecutionsDialogOpen(true)
  }

  return (
    <>
      <Dialog
        open={open}
        onClose={handleClose}
        maxWidth="xl"
        fullWidth
        PaperProps={{ sx: { width: { xs: '100%', sm: '90%', lg: '95%' } } }}
      >
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Typography variant="h6" component="span">
            {agentType ? agentType.name : t('agents.types.dialogTitle')}
          </Typography>
          <IconButton size="small" onClick={handleClose} aria-label={t('app.close')}>
            <CloseIcon />
          </IconButton>
        </DialogTitle>

        <DialogContent dividers sx={{ p: 0 }}>
          {/* Error display — always first in DialogContent per project standard */}
          {dialogError != null && (
            <Box sx={{ p: 2, pb: 0 }}>
              <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
            </Box>
          )}

          {isLoading && !agentType && (
            <Box display="flex" justifyContent="center" p={4}>
              <CircularProgress />
            </Box>
          )}

          {agentType && (
            <>
              <Box sx={{ borderBottom: 1, borderColor: 'divider', px: 2 }}>
                <Tabs
                  value={activeTab}
                  onChange={(_, v: number) => setActiveTab(v)}
                  aria-label={t('agents.types.dialogTitle')}
                >
                  <Tab
                    label={t('agents.types.detailsTab')}
                    id="agent-details-tab-0"
                    aria-controls="agent-details-tabpanel-0"
                  />
                  <Tab
                    label={t('agents.types.planPreviewTab')}
                    id="agent-details-tab-1"
                    aria-controls="agent-details-tabpanel-1"
                  />
                  <Tab
                    label={t('agents.types.executionLogsTab')}
                    id="agent-details-tab-2"
                    aria-controls="agent-details-tabpanel-2"
                  />
                </Tabs>
              </Box>

              <Box sx={{ px: 2, pb: 2 }}>
                {/* ── Tab 0: Details ──────────────────────────────────────── */}
                <TabPanel value={activeTab} index={0}>
                  <Box display="flex" flexWrap="wrap" gap={2}>
                    <Box sx={{ flex: '1 1 30%', minWidth: 140 }}>
                      <Typography variant="caption" color="text.secondary" display="block">
                        {t('app.name')}
                      </Typography>
                      <Typography variant="body2" fontWeight={500} mt={0.25}>
                        {agentType.name}
                      </Typography>
                    </Box>
                    <Box sx={{ flex: '1 1 30%', minWidth: 140 }}>
                      <Typography variant="caption" color="text.secondary" display="block">
                        {t('app.status')}
                      </Typography>
                      <Box mt={0.25}>
                        <Chip
                          label={agentType.is_active ? t('app.active') : t('app.inactive')}
                          color={agentType.is_active ? 'success' : 'default'}
                          size="small"
                        />
                      </Box>
                    </Box>
                    <Box sx={{ flex: '1 1 30%', minWidth: 140 }}>
                      <Typography variant="caption" color="text.secondary" display="block">
                        {t('agents.llmModel')}
                      </Typography>
                      <Typography variant="body2" mt={0.25}>
                        {agentType.model_id ?? '—'}
                      </Typography>
                    </Box>
                    <Box sx={{ flex: '1 1 40%', minWidth: 140 }}>
                      <Typography variant="caption" color="text.secondary" display="block">
                        {t('agents.types.inputType')}
                      </Typography>
                      <Box mt={0.25}>
                        <Chip label={agentType.input_type} size="small" variant="outlined" />
                      </Box>
                    </Box>
                    <Box sx={{ flex: '1 1 40%', minWidth: 140 }}>
                      <Typography variant="caption" color="text.secondary" display="block">
                        {t('agents.types.outputType')}
                      </Typography>
                      <Box mt={0.25}>
                        <Chip label={agentType.output_type} size="small" variant="outlined" />
                      </Box>
                    </Box>

                    {/* Role — clickable name opening AgentRoleViewDialog */}
                    <Box sx={{ flex: '1 1 40%', minWidth: 140 }}>
                      <Typography variant="caption" color="text.secondary" display="block">
                        {t('agents.types.role')}
                      </Typography>
                      <Box mt={0.25}>
                        {roleName ? (
                          <Link
                            component="button"
                            variant="body2"
                            underline="hover"
                            sx={{ cursor: 'pointer', fontWeight: 500 }}
                            onClick={() => setRoleViewOpen(true)}
                          >
                            {roleName}
                          </Link>
                        ) : (
                          <Typography variant="body2" color="text.secondary">—</Typography>
                        )}
                      </Box>
                    </Box>

                    {/* Identity — clickable name opening AgentIdentityViewDialog */}
                    <Box sx={{ flex: '1 1 40%', minWidth: 140 }}>
                      <Typography variant="caption" color="text.secondary" display="block">
                        {t('agents.types.identity')}
                      </Typography>
                      <Box mt={0.25}>
                        {identityName ? (
                          <Link
                            component="button"
                            variant="body2"
                            underline="hover"
                            sx={{ cursor: 'pointer', fontWeight: 500 }}
                            onClick={() => setIdentityViewOpen(true)}
                          >
                            {identityName}
                          </Link>
                        ) : (
                          <Typography variant="body2" color="text.secondary">—</Typography>
                        )}
                      </Box>
                    </Box>
                  </Box>

                  {agentType.description && (
                    <Box mt={2}>
                      <Typography variant="caption" color="text.secondary" display="block">
                        {t('app.description')}
                      </Typography>
                      <Typography variant="body2" mt={0.25}>{agentType.description}</Typography>
                    </Box>
                  )}

                  {agentType.system_instruction && (
                    <Box mt={2}>
                      <Typography variant="caption" color="text.secondary" display="block">
                        {t('agents.types.systemPrompt')}
                      </Typography>
                      <Box
                        component="pre"
                        sx={{
                          mt: 0.5,
                          p: 1,
                          bgcolor: 'grey.100',
                          borderRadius: 1,
                          fontSize: 12,
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                          maxHeight: 160,
                          overflow: 'auto',
                        }}
                      >
                        {agentType.system_instruction}
                      </Box>
                    </Box>
                  )}

                  <Divider sx={{ my: 2 }} />

                  {/* Action buttons */}
                  <Box display="flex" gap={1} flexWrap="wrap">
                    <Button
                      variant="contained"
                      size="small"
                      onClick={() => setLaunchOpen(true)}
                    >
                      {t('agents.types.runAgent')}
                    </Button>
                  </Box>
                </TabPanel>

                {/* ── Tab 1: Plan Preview ──────────────────────────────────── */}
                <TabPanel value={activeTab} index={1}>
                  <AgentPlanContent
                    plan={agentType.plan}
                    noPlanMessage={t('agents.types.noPlan')}
                  />
                </TabPanel>

                {/* ── Tab 2: Execution Logs ────────────────────────────────── */}
                <TabPanel value={activeTab} index={2}>
                  {sessionsLoading ? (
                    <Box display="flex" justifyContent="center" pt={2}>
                      <CircularProgress size={24} />
                    </Box>
                  ) : !dialogSessions || dialogSessions.length === 0 ? (
                    <Typography variant="body2" color="text.secondary">
                      {t('agents.sessions.dashboardEmpty')}
                    </Typography>
                  ) : (
                    <TableContainer>
                      <Table size="small">
                        <TableHead>
                          <TableRow>
                            <TableCell>{t('agents.sessions.sessionId')}</TableCell>
                            <TableCell>{t('app.status')}</TableCell>
                            <TableCell>{t('agents.sessions.createdAt')}</TableCell>
                            <TableCell align="right">{t('app.actions')}</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {dialogSessions.map((session) => (
                            <TableRow key={session.id} hover>
                              <TableCell>
                                <Typography variant="body2" fontFamily="monospace" fontSize={12}>
                                  {session.id.slice(0, 8)}…
                                </Typography>
                              </TableCell>
                              <TableCell>
                                <Chip
                                  label={t(
                                    `agents.sessions.status${session.status.replace(/^./, (c: string) => c.toUpperCase())}`,
                                  )}
                                  color={statusColor(session.status)}
                                  size="small"
                                />
                              </TableCell>
                              <TableCell>
                                <Typography variant="body2" fontSize={12}>
                                  {new Date(session.created_at).toLocaleString()}
                                </Typography>
                              </TableCell>
                              <TableCell align="right">
                                <Button
                                  size="small"
                                  endIcon={<OpenInNewIcon fontSize="small" />}
                                  onClick={() => {
                                    setSelectedSessionId(session.id)
                                    setExecutionDetailsDialogOpen(true)
                                  }}
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

                  <Box display="flex" justifyContent="flex-end" mt={2}>
                    <Button
                      variant="outlined"
                      size="small"
                      endIcon={<OpenInNewIcon fontSize="small" />}
                      onClick={handleViewAllExecutions}
                    >
                      {t('agents.sessions.viewAllExecutions')}
                    </Button>
                  </Box>
                </TabPanel>
              </Box>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* Launch dialog — mounted inside so it shares the agent type context */}
      {agentType && (
        <AgentJobLaunchDialog
          open={launchOpen}
          agentType={agentType}
          onClose={() => setLaunchOpen(false)}
          onLaunched={(sessionId) => {
            setLaunchOpen(false)
            setSelectedSessionId(sessionId)
            setExecutionDetailsDialogOpen(true)
          }}
        />
      )}

      {/* Role view dialog */}
      <AgentRoleViewDialog
        open={roleViewOpen}
        roleId={agentType?.role_id ?? null}
        onClose={() => setRoleViewOpen(false)}
      />

      {/* Identity view dialog */}
      <AgentIdentityViewDialog
        open={identityViewOpen}
        identityId={agentType?.identity_id ?? null}
        onClose={() => setIdentityViewOpen(false)}
      />

      {/* Agent executions dialog */}
      <AgentExecutionsDialog
        open={executionsDialogOpen}
        onClose={() => setExecutionsDialogOpen(false)}
        agentTypeId={agentTypeId ?? undefined}
        agentTypeName={agentType?.name}
      />

      {/* Agent execution details dialog */}
      {selectedSessionId && (
        <AgentExecutionDetailsDialog
          open={executionDetailsDialogOpen}
          onClose={() => {
            setExecutionDetailsDialogOpen(false)
            setSelectedSessionId(null)
          }}
          sessionId={selectedSessionId}
        />
      )}
    </>
  )
}
