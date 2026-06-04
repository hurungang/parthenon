import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  Link,
  List,
  ListItem,
  ListItemText,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  Tooltip,
  Typography,
} from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'
import CloseIcon from '@mui/icons-material/Close'
import EditIcon from '@mui/icons-material/Edit'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAgentType, useAgentTypes } from '../../hooks/useAgentTypes'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import AgentPlanContent from './AgentPlanContent'
import TopologyDiagramRenderer from './TopologyDiagramRenderer'
import { AgentJobLaunchDialog } from '../../pages/agents/AgentJobLaunchDialog'
import { AgentExecutionsDialog } from './AgentExecutionsDialog'
import { AgentExecutionDetailsDialog } from './AgentExecutionDetailsDialog'
import { ConversationSessionsTab } from './ConversationSessionsTab'
import { ConversationDialog } from './ConversationDialog'
import { SopEditor } from '../../pages/skills/SopEditor'
import { SkillEditor } from '../../pages/skills/SkillEditor'
import { AgentRoleDialog } from '../../pages/agents/AgentRoleDialog'
import { AgentIdentityViewDialog } from './AgentIdentityViewDialog'
import apiClient from '../../api/apiClient'
import { canonicalizeToolName } from '../../utils/toolNaming'
import type { AgentIdentity, AgentJob, AgentJobStatus, AgentRole, McpTool, Skill, Sop, SopDetail, TopologyNode, TopologyEdge } from '../../types'

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
  /** Which tab to select when the dialog opens. Defaults to 0 (Details). */
  initialTab?: number
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
  initialTab = 0,
}: AgentTypeDetailsDialogProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState(0)
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [launchOpen, setLaunchOpen] = useState(false)
  const [conversationDialogOpen, setConversationDialogOpen] = useState(false)
  const [roleViewOpen, setRoleViewOpen] = useState(false)
  const [identityViewOpen, setIdentityViewOpen] = useState(false)
  const [executionsDialogOpen, setExecutionsDialogOpen] = useState(false)
  const [executionDetailsDialogOpen, setExecutionDetailsDialogOpen] = useState(false)
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const [sopViewOpen, setSopViewOpen] = useState(false)
  const [sopViewSop, setSopViewSop] = useState<SopDetail | null>(null)
  const [skillViewOpen, setSkillViewOpen] = useState(false)
  const [skillViewSkill, setSkillViewSkill] = useState<Skill | null>(null)
  const [agentTypeViewOpen, setAgentTypeViewOpen] = useState(false)
  const [agentTypeViewId, setAgentTypeViewId] = useState<string | null>(null)

  // Reset tab and error when dialog opens
  useEffect(() => {
    if (open) {
      setActiveTab(initialTab)
      setDialogError(null)
    }
  }, [open, initialTab])

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

  // Agent Preview: SOPs and Skills — only fetched for conversation agents on tab 1
  const isConversation = agentType?.input_type === 'conversation'

  // All agent types — for resolving delegation target names in preview/topology
  const { data: allAgentTypes } = useAgentTypes()

  const { data: allSops } = useQuery<Sop[]>({
    queryKey: ['sops'],
    queryFn: async () => {
      const { data } = await apiClient.get<Sop[]>('/sops')
      return data
    },
    enabled: open && isConversation && activeTab === 1,
  })

  const { data: allSkills } = useQuery<Skill[]>({
    queryKey: ['skills'],
    queryFn: async () => {
      const { data } = await apiClient.get<Skill[]>('/skills')
      return data
    },
    enabled: open && isConversation && activeTab === 1,
  })

  // Fetch SOP details (with steps) to derive SOP→Skill relationships
  const currentRole = allRoles?.find((r) => r.id === agentType?.role_id)
  const roleSopIds = (allSops ?? [])
    .filter((s) => currentRole?.sop_ids.includes(s.id))
    .map((s) => s.id)

  const { data: sopDetails } = useQuery<SopDetail[]>({
    queryKey: ['sops', 'details', roleSopIds],
    queryFn: async () => {
      const results = await Promise.all(
        roleSopIds.map((id) => apiClient.get<SopDetail>(`/sops/${id}`).then((r) => r.data)),
      )
      return results
    },
    enabled: open && isConversation && activeTab === 1 && roleSopIds.length > 0,
  })

  // Fetch all MCP tools to resolve tool names from skill.tool_ids
  const { data: allMcpTools } = useQuery<McpTool[]>({
    queryKey: ['mcp', 'tools'],
    queryFn: async () => {
      const { data } = await apiClient.get<McpTool[]>('/mcp/tools')
      return data
    },
    enabled: open && isConversation && activeTab === 1,
  })
  const roleSops = (allSops ?? []).filter((s) => currentRole?.sop_ids.includes(s.id))
  const roleSkills = (allSkills ?? []).filter((s) => currentRole?.skill_ids.includes(s.id))

  // When binding lists exist, filter to only show bound SOPs and skills
  const hasBindings = (agentType?.sop_bindings && agentType.sop_bindings.length > 0) ||
    (agentType?.skill_bindings && agentType.skill_bindings.length > 0)
  const boundSopIds = new Set((agentType?.sop_bindings ?? []).map((b) => b.sop_id))
  const boundSkillIds = new Set((agentType?.skill_bindings ?? []).map((b) => b.skill_id))
  const displaySops = hasBindings ? roleSops.filter((s) => boundSopIds.has(s.id)) : roleSops
  const displaySkills = hasBindings ? roleSkills.filter((s) => boundSkillIds.has(s.id)) : roleSkills

  const planGeneratedAt = agentType?.plan?.generated_at ? new Date(agentType.plan.generated_at) : null

  const latestPreviewDefinitionUpdate = useMemo(() => {
    const timestamps = [
      currentRole?.updated_at,
      ...roleSops.map((sop) => sop.updated_at),
      ...roleSkills.map((skill) => skill.updated_at),
    ]
      .filter((value): value is string => !!value)
      .map((value) => new Date(value).getTime())
      .filter((value) => !Number.isNaN(value))

    if (timestamps.length === 0) {
      return null
    }

    return new Date(Math.max(...timestamps))
  }, [currentRole?.updated_at, roleSops, roleSkills])

  const staleDefinitionLabels = useMemo(() => {
    if (!planGeneratedAt) {
      return [] as string[]
    }

    const labels: string[] = []

    if (currentRole?.updated_at && new Date(currentRole.updated_at) > planGeneratedAt) {
      labels.push('role')
    }

    if (roleSops.some((sop) => new Date(sop.updated_at) > planGeneratedAt)) {
      labels.push('SOPs')
    }

    if (roleSkills.some((skill) => new Date(skill.updated_at) > planGeneratedAt)) {
      labels.push('skills')
    }

    return labels
  }, [currentRole?.updated_at, planGeneratedAt, roleSops, roleSkills])

  const staleDefinitionsMessage = useMemo(() => {
    if (staleDefinitionLabels.length === 0) {
      return null
    }

    if (staleDefinitionLabels.length === 1) {
      return `This plan is older than the current ${staleDefinitionLabels[0]} definition.`
    }

    const lastLabel = staleDefinitionLabels[staleDefinitionLabels.length - 1]
    const leadingLabels = staleDefinitionLabels.slice(0, -1).join(', ')
    return `This plan is older than the current ${leadingLabels}, and ${lastLabel} definitions.`
  }, [staleDefinitionLabels])

  const planIsStale = !!planGeneratedAt && !!latestPreviewDefinitionUpdate && latestPreviewDefinitionUpdate > planGeneratedAt

  const regeneratePlanMutation = useMutation({
    mutationFn: async () => {
      if (!agentTypeId) {
        throw new Error('Agent type not selected')
      }
      const { data } = await apiClient.post(`/agents/types/${agentTypeId}/regenerate-plan`)
      return data
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['agents', 'types', agentTypeId] })
      await queryClient.invalidateQueries({ queryKey: ['agents', 'types'] })
    },
    onError: (error) => {
      setDialogError(error)
    },
  })

  const roleName = agentType?.role_id
    ? (allRoles?.find((r) => r.id === agentType.role_id)?.name ?? agentType.role_id)
    : null

  const identityName = agentType?.identity_id
    ? (allIdentities?.find((i) => i.id === agentType.identity_id)?.name ?? agentType.identity_id)
    : null

  // Build topology nodes/edges for conversation agents (no plan required)
  const { convTopologyNodes, convTopologyEdges } = useMemo<{
    convTopologyNodes: TopologyNode[]
    convTopologyEdges: TopologyEdge[]
  }>(() => {
    if (!agentType || !isConversation) return { convTopologyNodes: [], convTopologyEdges: [] }

    const nodes: TopologyNode[] = []
    const edges: TopologyEdge[] = []
    const addedSkillIds = new Set<string>()
    const addedToolIds = new Set<string>()
    const addedDelegatedAgentTypeIds = new Set<string>()

    nodes.push({ id: 'agent', type: 'agent', label: agentType.name })

    if (agentType.identity_id && identityName) {
      nodes.push({ id: 'identity', type: 'identity', label: identityName })
      edges.push({ source: 'agent', target: 'identity' })
    }

    if (agentType.role_id && roleName) {
      nodes.push({ id: 'role', type: 'role', label: roleName })
      edges.push({ source: 'agent', target: 'role' })

      // Helper: add skill node + its tool nodes, then return the skill node id
      const addSkillWithTools = (skill: Skill): string => {
        const skillNodeId = `skill_${skill.id}`
        if (!addedSkillIds.has(skill.id)) {
          addedSkillIds.add(skill.id)
          nodes.push({ id: skillNodeId, type: 'skill', label: skill.name })
          skill.tool_ids.forEach((toolId) => {
            if (!addedToolIds.has(toolId)) {
              addedToolIds.add(toolId)
              const tool = (allMcpTools ?? []).find((t) => t.id === toolId)
              if (tool) {
                nodes.push({ id: `tool_${toolId}`, type: 'tool', label: canonicalizeToolName(tool.name) })
              }
            }
            if (addedToolIds.has(toolId)) {
              edges.push({ source: skillNodeId, target: `tool_${toolId}` })
            }
          })
        }
        return skillNodeId
      }

      // Track which skills are reached via SOP steps (to avoid duplicate role->skill edges)
      const sopSkillIds = new Set<string>()

      displaySops.forEach((sop) => {
        const sopNodeId = `sop_${sop.id}`
        nodes.push({ id: sopNodeId, type: 'sop', label: sop.name })
        edges.push({ source: 'role', target: sopNodeId })

        const detail = (sopDetails ?? []).find((d) => d.id === sop.id)
        if (detail) {
          detail.steps
            .filter((step) => step.step_type === 'agent_delegation' && step.target_agent_type_id)
            .forEach((step) => {
              const targetAgentTypeId = step.target_agent_type_id!
              const delegatedNodeId = `agent_type_${targetAgentTypeId}`
              if (!addedDelegatedAgentTypeIds.has(targetAgentTypeId)) {
                addedDelegatedAgentTypeIds.add(targetAgentTypeId)
                const delegatedAgentTypeName = (allAgentTypes ?? []).find((at) => at.id === targetAgentTypeId)?.name ?? targetAgentTypeId
                nodes.push({
                  id: delegatedNodeId,
                  type: 'agent_type',
                  label: delegatedAgentTypeName,
                })
              }
              edges.push({ source: sopNodeId, target: delegatedNodeId, label: 'delegates' })
            })

          detail.steps
            .filter((step) => step.step_type === 'skill_invocation' && step.skill_id)
            .forEach((step) => {
              const skillId = step.skill_id!
              sopSkillIds.add(skillId)
              const skill = (allSkills ?? []).find((s) => s.id === skillId)
              if (skill) {
                const skillNodeId = addSkillWithTools(skill)
                edges.push({ source: sopNodeId, target: skillNodeId })
              }
            })
        }
      })

      // Skills directly on role but not reachable via any SOP step → connect to role
      displaySkills
        .filter((skill) => !sopSkillIds.has(skill.id))
        .forEach((skill) => {
          const skillNodeId = addSkillWithTools(skill)
          edges.push({ source: 'role', target: skillNodeId })
        })
    }

    return { convTopologyNodes: nodes, convTopologyEdges: edges }
  }, [agentType, isConversation, identityName, roleName, displaySops, displaySkills, sopDetails, allSkills, allMcpTools, allAgentTypes])

  const handleClose = () => {
    setDialogError(null)
    onClose()
  }

  const handleEdit = () => {
    if (agentType) {
      // Navigate to agents page with state to open edit dialog
      navigate('/agents', { 
        state: { 
          editAgentType: agentType
        } 
      })
      onClose()
    }
  }

  const handleNodeClick = useCallback((node: TopologyNode) => {
    const colonIdx = node.id.indexOf(':')
    const type = colonIdx >= 0 ? node.id.slice(0, colonIdx) : node.type
    const entityId = colonIdx >= 0 ? node.id.slice(colonIdx + 1) : node.id

    if (type === 'role') {
      setRoleViewOpen(true)
      return
    }
    if (type === 'identity') {
      setIdentityViewOpen(true)
      return
    }
    if (type === 'agent') {
      return
    }
    if (type === 'sop') {
      const detail = (sopDetails ?? []).find((d) => d.id === entityId)
      if (detail) {
        setSopViewSop(detail)
        setSopViewOpen(true)
      } else {
        apiClient.get<SopDetail>(`/sops/${entityId}`).then(({ data }) => {
          setSopViewSop(data)
          setSopViewOpen(true)
        })
      }
      return
    }
    if (type === 'skill') {
      apiClient.get<Skill>(`/skills/${entityId}`).then(({ data }) => {
        setSkillViewSkill(data)
        setSkillViewOpen(true)
      })
      return
    }
    if (type === 'agent_type') {
      setAgentTypeViewId(entityId)
      setAgentTypeViewOpen(true)
    }
  }, [sopDetails])

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
          <Box display="flex" alignItems="center" gap={1}>
            {agentType && (
              <Tooltip title={t('app.edit')}>
                <IconButton size="small" onClick={handleEdit} aria-label={t('app.edit')}>
                  <EditIcon />
                </IconButton>
              </Tooltip>
            )}
            <Tooltip title={t('app.close')}>
              <IconButton size="small" onClick={handleClose} aria-label={t('app.close')}>
                <CloseIcon />
              </IconButton>
            </Tooltip>
          </Box>
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
                    label={t('agents.types.agentPreviewTab')}
                    id="agent-details-tab-1"
                    aria-controls="agent-details-tabpanel-1"
                  />
                  <Tab
                    label={t('agents.types.executionLogsTab')}
                    id="agent-details-tab-2"
                    aria-controls="agent-details-tabpanel-2"
                  />
                  {agentType.input_type === 'conversation' && (
                    <Tab
                      label={t('conversations.sessions.tabLabel')}
                      id="agent-details-tab-3"
                      aria-controls="agent-details-tabpanel-3"
                    />
                  )}
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

                </TabPanel>

                {/* ── Tab 1: Plan Preview OR Agent Preview ──────────────── */}
                <TabPanel value={activeTab} index={1}>
                  {planIsStale && (
                    <Box display="flex" gap={1} alignItems="stretch" sx={{ mb: 2 }}>
                      <Alert severity="warning" sx={{ flex: 1, alignItems: 'center' }}>
                        {staleDefinitionsMessage}
                      </Alert>
                      <Button
                        variant="outlined"
                        size="small"
                        startIcon={<RefreshIcon />}
                        onClick={() => void regeneratePlanMutation.mutateAsync()}
                        disabled={regeneratePlanMutation.isPending}
                      >
                        Regenerate plan
                      </Button>
                    </Box>
                  )}

                  {!planIsStale && (
                    <Box display="flex" justifyContent="flex-end" sx={{ mb: 2 }}>
                      <Button
                        variant="outlined"
                        size="small"
                        startIcon={<RefreshIcon />}
                        onClick={() => void regeneratePlanMutation.mutateAsync()}
                        disabled={regeneratePlanMutation.isPending}
                      >
                        Regenerate plan
                      </Button>
                    </Box>
                  )}

                  {isConversation ? (
                    <Box>
                      <Typography variant="subtitle2" gutterBottom>
                        {t('agents.plan.topology')}
                      </Typography>
                      <TopologyDiagramRenderer
                        nodes={convTopologyNodes}
                        edges={convTopologyEdges}
                        onNodeClick={handleNodeClick}
                      />

                      <Divider sx={{ my: 2 }} />

                      <Typography variant="subtitle2" gutterBottom>
                        {t('agents.types.agentSops')}
                      </Typography>
                      {displaySops.length === 0 ? (
                        <Typography variant="body2" color="text.secondary" mb={2}>
                          {hasBindings ? t('agents.types.noSopsBound') : t('agents.types.noSopsAssigned')}
                        </Typography>
                      ) : (
                        <List dense disablePadding sx={{ mb: 2 }}>
                          {displaySops.map((sop) => (
                            <ListItem key={sop.id} disableGutters secondaryAction={
                              boundSopIds.has(sop.id) ? (
                                <Chip label={t('agents.types.bindings.bound')} size="small" color="primary" variant="outlined" />
                              ) : null
                            }>
                              <ListItemText
                                primary={sop.name}
                                secondary={sop.description ?? undefined}
                              />
                            </ListItem>
                          ))}
                        </List>
                      )}

                      {displaySops.length > 0 && (
                        <>
                          <Divider sx={{ my: 1.5 }} />
                          <Typography variant="subtitle2" gutterBottom>
                            {t('agents.plan.steps')}
                          </Typography>
                          <List dense disablePadding sx={{ mb: 2 }}>
                            {(sopDetails ?? []).flatMap((detail) =>
                              [...detail.steps]
                                .sort((a, b) => a.order - b.order)
                                .map((step) => {
                                  const delegatedName = step.step_type === 'agent_delegation' && step.target_agent_type_id
                                    ? ((allAgentTypes ?? []).find((at) => at.id === step.target_agent_type_id)?.name ?? step.target_agent_type_id)
                                    : null
                                  const stepLabel =
                                    step.step_type === 'agent_delegation'
                                      ? `${step.name ?? 'Agent delegation'} → ${delegatedName ?? 'unknown'}`
                                      : step.name ?? 'Skill invocation'
                                  return (
                                    <ListItem key={step.id} disableGutters>
                                      <ListItemText
                                        primary={stepLabel}
                                        secondary={t(`agents.plan.stepTypes.${step.step_type}`)}
                                      />
                                    </ListItem>
                                  )
                                }),
                            )}
                          </List>
                        </>
                      )}

                      <Divider sx={{ my: 1.5 }} />

                      <Typography variant="subtitle2" gutterBottom>
                        {t('agents.types.agentSkills')}
                      </Typography>
                      {displaySkills.length === 0 ? (
                        <Typography variant="body2" color="text.secondary">
                          {hasBindings ? t('agents.types.noSkillsBound') : t('agents.types.noSkillsAssigned')}
                        </Typography>
                      ) : (
                        <List dense disablePadding>
                          {displaySkills.map((skill) => (
                            <ListItem key={skill.id} disableGutters secondaryAction={
                              boundSkillIds.has(skill.id) ? (
                                <Chip label={t('agents.types.bindings.bound')} size="small" color="secondary" variant="outlined" />
                              ) : null
                            }>
                              <ListItemText
                                primary={skill.name}
                                secondary={skill.description ?? undefined}
                              />
                            </ListItem>
                          ))}
                        </List>
                      )}
                    </Box>
                  ) : (
                    <AgentPlanContent
                      plan={agentType.plan}
                      noPlanMessage={t('agents.types.noPlan')}
                      onNodeClick={handleNodeClick}
                    />
                  )}
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

                {/* ── Tab 3: Sessions (conversation agents only) ───────────── */}
                {agentType.input_type === 'conversation' && agentTypeId && (
                  <TabPanel value={activeTab} index={3}>
                    <ConversationSessionsTab agentTypeId={agentTypeId} onClose={onClose} />
                  </TabPanel>
                )}
              </Box>
            </>
          )}
        </DialogContent>

        {agentType && (
          <DialogActions sx={{ px: 3, py: 2, borderTop: 1, borderColor: 'divider' }}>
            {isConversation ? (
              <Button
                variant="contained"
                onClick={() => setConversationDialogOpen(true)}
              >
                {t('agents.types.startChat')}
              </Button>
            ) : (
              <Button
                variant="contained"
                onClick={() => setLaunchOpen(true)}
              >
                {t('agents.types.runAgent')}
              </Button>
            )}
          </DialogActions>
        )}
      </Dialog>

      {/* Launch dialog — mounted inside so it shares the agent type context */}
      {agentType && launchOpen && (
        <AgentJobLaunchDialog
          open={true}
          agentType={agentType}
          onClose={() => setLaunchOpen(false)}
          onLaunched={(sessionId) => {
            setLaunchOpen(false)
            setSelectedSessionId(sessionId)
            setExecutionDetailsDialogOpen(true)
          }}
        />
      )}

      {/* Role view dialog — reuse AgentRoleDialog in view mode */}
      {roleViewOpen && (
        <AgentRoleDialog
          open={true}
          editRole={currentRole ?? null}
          mode="view"
          onClose={() => setRoleViewOpen(false)}
          onSaved={async () => {}}
        />
      )}

      {/* Identity view dialog */}
      {identityViewOpen && (
        <AgentIdentityViewDialog
          open={true}
          identityId={agentType?.identity_id ?? null}
          onClose={() => setIdentityViewOpen(false)}
        />
      )}

      {/* Agent executions dialog */}
      {executionsDialogOpen && (
        <AgentExecutionsDialog
          open={true}
          onClose={() => setExecutionsDialogOpen(false)}
          agentTypeId={agentTypeId ?? undefined}
          agentTypeName={agentType?.name}
        />
      )}

      {/* Agent execution details dialog */}
      {selectedSessionId && executionDetailsDialogOpen && (
        <AgentExecutionDetailsDialog
          open={true}
          onClose={() => {
            setExecutionDetailsDialogOpen(false)
            setSelectedSessionId(null)
          }}
          sessionId={selectedSessionId}
        />
      )}

      {/* Conversation dialog */}
      {conversationDialogOpen && (
        <ConversationDialog
          open={true}
          sessionId={null}
          agentTypeId={agentTypeId ?? ''}
          agentTypeName={agentType?.name ?? 'Agent'}
          onClose={() => setConversationDialogOpen(false)}
        />
      )}

      {/* SOP view — reuse SopEditor in view mode */}
      {sopViewSop && (
        <SopEditor
          open={sopViewOpen}
          sop={sopViewSop}
          mode="view"
          onClose={() => setSopViewOpen(false)}
          onSaved={() => setSopViewOpen(false)}
        />
      )}

      {/* Skill view — reuse SkillEditor in view mode */}
      {skillViewSkill && (
        <SkillEditor
          open={skillViewOpen}
          skill={skillViewSkill}
          mode="view"
          onClose={() => setSkillViewOpen(false)}
          onSaved={() => setSkillViewOpen(false)}
        />
      )}

      {/* Delegated Agent Type dialog — reuse AgentTypeDetailsDialog */}
      {agentTypeViewOpen && (
        <AgentTypeDetailsDialog
          open={agentTypeViewOpen}
          agentTypeId={agentTypeViewId}
          onClose={() => {
            setAgentTypeViewOpen(false)
            setAgentTypeViewId(null)
          }}
        />
      )}
    </>
  )
}

