import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  FormControlLabel,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import PersonAddIcon from '@mui/icons-material/PersonAdd'
import PersonRemoveIcon from '@mui/icons-material/PersonRemove'
import RefreshIcon from '@mui/icons-material/Refresh'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import { useQuery, useQueries, useQueryClient } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import { useAllTools } from '../../hooks/useMcpServers'
import { canonicalizeToolName } from '../../utils/toolNaming'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { AssignIdentitiesToRoleDialog } from './AssignIdentitiesToRoleDialog'
import type { AgentIdentity, AgentRole, McpServer, McpSession, McpTool, Skill, Sop } from '../../types'

interface McpSessionInfo {
  id: string
  name: string
  server_id: string
  server_name: string
  server_slug: string
}

interface AgentRoleDialogProps {
  open: boolean
  editRole: AgentRole | null
  mode?: 'create' | 'edit' | 'view'
  onClose: () => void
  onSaved: () => Promise<void>
}

/**
 * Extracts the MCP server slug from a tool name using the canonical slug____tool format.
 * Returns null for system tools or names that cannot be parsed.
 */
function extractServerSlug(toolName: string): string | null {
  if (!toolName) return null
  const name = canonicalizeToolName(toolName)
  if (!name.includes('____')) {
    // Legacy slash-format fallback
    if (name.includes('/')) {
      const slug = name.split('/', 1)[0]
      return slug && slug !== 'system' ? slug : null
    }
    return null
  }
  const slug = name.split('____', 1)[0]
  return slug && slug !== 'system' ? slug : null
}

/**
 * Create / edit dialog for AgentRole.
 * Includes SOP multi-select, Skill multi-select, inline MCP session assignment,
 * real-time MCP tool preview panel, and assigned identities table.
 */
export function AgentRoleDialog({ open, editRole, mode: modeProp, onClose, onSaved }: AgentRoleDialogProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const mode = modeProp ?? 'edit'
  const isViewMode = mode === 'view'
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [selectedSopIds, setSelectedSopIds] = useState<string[]>([])
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([])
  // Skills that are auto-locked because a selected SOP requires them.
  // Locked skills are auto-checked and their checkboxes are disabled.
  const [lockedSkills, setLockedSkills] = useState<Set<string>>(new Set())
  const [previewTools, setPreviewTools] = useState<string[]>([])
  const [previewAgentTypes, setPreviewAgentTypes] = useState<string[]>([])
  const [previewLoading, setPreviewLoading] = useState(false)
  const [assignDialogOpen, setAssignDialogOpen] = useState(false)
  const [toolRefOpen, setToolRefOpen] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // MCP session assignment state
  const [selectedMcpSessions, setSelectedMcpSessions] = useState<Record<string, string>>({})
  const initialAssignedSessionIds = useRef<Set<string>>(new Set())

  const { data: allTools } = useAllTools()

  // Fetch all MCP servers for slug to id/name mapping
  const { data: mcpServers } = useQuery<McpServer[]>({
    queryKey: ['mcp', 'servers', 'all'],
    queryFn: async () => {
      const { data } = await apiClient.get<McpServer[]>('/mcp/servers')
      return data
    },
    enabled: open,
  })

  const { data: sops } = useQuery<Sop[]>({
    queryKey: ['sops'],
    queryFn: async () => {
      const { data } = await apiClient.get<Sop[]>('/sops')
      return data
    },
    enabled: open,
  })

  const { data: skills } = useQuery<Skill[]>({
    queryKey: ['skills'],
    queryFn: async () => {
      const { data } = await apiClient.get<Skill[]>('/skills')
      return data
    },
    enabled: open,
  })

  const { data: assignedIdentities, refetch: refetchIdentities } = useQuery<AgentIdentity[]>({
    queryKey: ['agents', 'roles', editRole?.id, 'identities'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentIdentity[]>(`/agents/roles/${editRole!.id}/identities`)
      return data
    },
    enabled: open && !!editRole?.id,
  })

  // Fetch currently assigned MCP sessions (edit mode pre-population)
  const { data: assignedSessions } = useQuery<McpSessionInfo[]>({
    queryKey: ['agents', 'roles', editRole?.id, 'mcp-sessions'],
    queryFn: async () => {
      const { data } = await apiClient.get<McpSessionInfo[]>(`/agents/roles/${editRole!.id}/mcp-sessions`)
      return data
    },
    enabled: open && !!editRole?.id,
  })

  // Build slug to serverId map
  const serverSlugToId = useMemo(() => {
    const map: Record<string, string> = {}
    ;(mcpServers ?? []).forEach((s) => { map[s.slug] = s.id })
    return map
  }, [mcpServers])

  // Compute required MCP server slugs from selected SOPs/Skills
  const requiredMcpServers = useMemo(() => {
    if (!skills || !allTools || !mcpServers) return [] as string[]

    // Collect all effective skill IDs (direct + locked from SOP requirements)
    const effectiveSkillIds = new Set<string>()
    selectedSkillIds.forEach((id) => effectiveSkillIds.add(id))
    lockedSkills.forEach((id) => effectiveSkillIds.add(id))

    // Build tool lookup by tool ID
    const toolsById = new Map<string, McpTool>()
    ;(allTools ?? []).forEach((tool) => toolsById.set(tool.id, tool))

    const serverSlugs = new Set<string>()

    for (const skillId of effectiveSkillIds) {
      const skill = skills.find((s) => s.id === skillId)
      if (!skill) continue
      for (const toolId of skill.tool_ids) {
        const tool = toolsById.get(toolId)
        if (!tool) continue
        const slug = extractServerSlug(tool.name)
        if (slug) serverSlugs.add(slug)
      }
    }

    return Array.from(serverSlugs).sort()
  }, [selectedSopIds, selectedSkillIds, skills, allTools, mcpServers, lockedSkills])

  // Batch fetch sessions per required server
  const serverSessionsQueries = useQueries({
    queries: requiredMcpServers.map((slug) => ({
      queryKey: ['mcp', 'servers', serverSlugToId[slug], 'sessions'] as const,
      queryFn: async () => {
        const serverId = serverSlugToId[slug]
        if (!serverId) return [] as McpSession[]
        const { data } = await apiClient.get<McpSession[]>(`/mcp/servers/${serverId}/sessions`)
        return data
      },
      enabled: open && !!serverSlugToId[slug],
    })),
  })

  // Map slug to available sessions
  const sessionsBySlug = useMemo(() => {
    const map: Record<string, McpSession[]> = {}
    requiredMcpServers.forEach((slug, i) => {
      const query = serverSessionsQueries[i]
      if (query?.data) map[slug] = query.data
    })
    return map
  }, [requiredMcpServers, serverSessionsQueries])

  // Pre-populate selectedMcpSessions on dialog open (edit mode)
  useEffect(() => {
    if (open && assignedSessions && editRole?.id) {
      const map: Record<string, string> = {}
      assignedSessions.forEach((s) => { map[s.server_slug] = s.id })
      setSelectedMcpSessions(map)
      initialAssignedSessionIds.current = new Set(assignedSessions.map((s) => s.id))
    } else if (open && !editRole?.id) {
      setSelectedMcpSessions({})
      initialAssignedSessionIds.current = new Set()
    }
  }, [open, assignedSessions, editRole?.id])

  // Clear stale selections when sessions data refreshes
  useEffect(() => {
    setSelectedMcpSessions((prev) => {
      const next = { ...prev }
      let changed = false
      for (const [slug, sessionId] of Object.entries(prev)) {
        const sessions = sessionsBySlug[slug]
        if (sessions && sessions.length > 0 && !sessions.some((s) => s.id === sessionId)) {
          delete next[slug]
          changed = true
        }
      }
      return changed ? next : prev
    })
  }, [sessionsBySlug])

  // Derived: is save disabled?
  const isSaveDisabled = useMemo(() => {
    if (!name.trim()) return true
    return requiredMcpServers.some((slug) => !selectedMcpSessions[slug])
  }, [name, requiredMcpServers, selectedMcpSessions])

  // Derived: missing server slugs for validation message
  const missingServers = useMemo(() => {
    return requiredMcpServers.filter((slug) => !selectedMcpSessions[slug])
  }, [requiredMcpServers, selectedMcpSessions])

  // Populate form when editing
  useEffect(() => {
    if (open) {
      setName(editRole?.name ?? '')
      setDescription(editRole?.description ?? '')
      setSelectedSopIds(editRole?.sop_ids ?? [])
      setSelectedSkillIds(editRole?.skill_ids ?? [])
      setLockedSkills(new Set())
      setPreviewTools([])
      setPreviewAgentTypes([])
      setDialogError(null)
    }
  }, [open, editRole])

  // Recompute locked skills (and auto-select/deselect them) whenever the
  // selected SOPs or the SOP data changes.
  useEffect(() => {
    const newLocked = new Set<string>()
    for (const sopId of selectedSopIds) {
      const sop = (sops ?? []).find((s) => s.id === sopId)
      if (sop?.required_skill_ids) {
        sop.required_skill_ids.forEach((skillId) => newLocked.add(skillId))
      }
    }
    // Use the functional form of setLockedSkills to access the previous locked
    // set so we can remove skills that are no longer required by any SOP.
    setLockedSkills((prevLocked) => {
      setSelectedSkillIds((prevSkills) => {
        const next = new Set(prevSkills)
        // Auto-select all newly locked skills
        newLocked.forEach((id) => next.add(id))
        // Remove skills that were locked before but are no longer needed
        prevLocked.forEach((id) => {
          if (!newLocked.has(id)) next.delete(id)
        })
        return Array.from(next)
      })
      return newLocked
    })
  }, [selectedSopIds, sops])

  // Fetch MCP tool preview when in edit mode and selection changes
  useEffect(() => {
    if (!editRole?.id) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      try {
        setPreviewLoading(true)
        // Pass current selections as query parameters for live preview
        const params = new URLSearchParams({
          skill_ids: selectedSkillIds.join(','),
          sop_ids: selectedSopIds.join(','),
        })
        const [toolsRes, agentTypesRes] = await Promise.all([
          apiClient.get<string[]>(`/agents/roles/${editRole.id}/mcp-tools?${params.toString()}`),
          apiClient.get<string[]>(`/agents/roles/${editRole.id}/allowed-agent-types?sop_ids=${selectedSopIds.join(',')}`),
        ])
        setPreviewTools(toolsRes.data)
        setPreviewAgentTypes(agentTypesRes.data)
      } catch {
        setPreviewTools([])
        setPreviewAgentTypes([])
      } finally {
        setPreviewLoading(false)
      }
    }, 300)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [editRole?.id, selectedSopIds, selectedSkillIds])

  // Build a schema-based tool reference text from previewTools + allTools metadata
  const toolReferenceText = useMemo(() => {
    if (!previewTools.length) return null
    const toolMap = new Map<string, McpTool>()
    ;(allTools ?? []).forEach((tool) => {
      toolMap.set(tool.name, tool)
      toolMap.set(canonicalizeToolName(tool.name), tool)
    })
    const lines: string[] = ['## Tools']
    for (const rawToolName of previewTools) {
      const toolName = canonicalizeToolName(rawToolName)
      const tool = toolMap.get(toolName)
      lines.push(`\n### \`${toolName}\``)
      if (tool?.description) lines.push(tool.description)
      if (tool?.input_schema) {
        lines.push('\n**Input Schema:**')
        lines.push('```json')
        lines.push(JSON.stringify(tool.input_schema, null, 2))
        lines.push('```')
      }
    }
    return lines.join('\n')
  }, [previewTools, allTools])

  const toggleSop = (id: string) => {
    setSelectedSopIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
    // Note: skill auto-selection is handled by the useEffect above that
    // watches selectedSopIds — no extra logic needed here.
  }

  const toggleSkill = (id: string) => {
    setSelectedSkillIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  const handleRemoveIdentity = async (identityId: string) => {
    if (!editRole?.id) return
    try {
      await apiClient.delete(`/agents/roles/${editRole.id}/identities/${identityId}`)
      await refetchIdentities()
    } catch (err) {
      setDialogError(err)
    }
  }

  const handleSessionSelectionChange = (serverSlug: string, sessionId: string) => {
    setSelectedMcpSessions((prev) => {
      if (sessionId) {
        return { ...prev, [serverSlug]: sessionId }
      } else {
        const next = { ...prev }
        delete next[serverSlug]
        return next
      }
    })
  }

  const handleRefreshSessions = (slug: string) => {
    const serverId = serverSlugToId[slug]
    if (serverId) {
      queryClient.invalidateQueries({ queryKey: ['mcp', 'servers', serverId, 'sessions'] })
    }
  }

  const handleSave = async () => {
    if (isViewMode) return
    try {
      setDialogError(null)
      const body = {
        name,
        description: description || null,
        sop_ids: selectedSopIds,
        skill_ids: selectedSkillIds,
      }

      if (editRole) {
        // Edit mode: update role, then diff-assign sessions
        await apiClient.put(`/agents/roles/${editRole.id}`, body)

        const prevIds = initialAssignedSessionIds.current
        const currentIds = new Set(Object.values(selectedMcpSessions).filter(Boolean))

        // Add new sessions
        for (const sessionId of currentIds) {
          if (!prevIds.has(sessionId)) {
            await apiClient.post(`/agents/roles/${editRole.id}/mcp-sessions`, {
              mcp_session_id: sessionId,
            })
          }
        }

        // Remove stale sessions
        for (const sessionId of prevIds) {
          if (!currentIds.has(sessionId)) {
            await apiClient.delete(`/agents/roles/${editRole.id}/mcp-sessions/${sessionId}`)
          }
        }
      } else {
        // Create mode: create role first, then assign sessions
        const { data: newRole } = await apiClient.post('/agents/roles', body)
        const newRoleId = newRole.id

        for (const sessionId of Object.values(selectedMcpSessions).filter(Boolean)) {
          await apiClient.post(`/agents/roles/${newRoleId}/mcp-sessions`, {
            mcp_session_id: sessionId,
          })
        }
      }

      await onSaved()
    } catch (err) {
      setDialogError(err)
    }
  }

  const isEditing = !!editRole

  // Helper: get server display name by slug
  const getServerDisplayName = (slug: string): string => {
    const server = (mcpServers ?? []).find((s) => s.slug === slug)
    return server?.name ?? slug
  }

  // Helper: check if any session for a server is passthrough
  const serverHasPassthrough = (slug: string): boolean => {
    const sessions = sessionsBySlug[slug]
    return sessions ? sessions.some((s) => s.auth_type === 'passthrough') : false
  }

  return (
    <>
      <Dialog
        open={open}
        onClose={() => { onClose(); setDialogError(null) }}
        maxWidth="lg"
        fullWidth
      >
        <DialogTitle>
          {isViewMode ? t('agents.roles.viewTitle') : isEditing ? t('agents.roles.editTitle') : t('agents.roles.createTitle')}
        </DialogTitle>

        <DialogContent dividers>
          {dialogError ? (
            <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
          ) : null}

          <Box display="flex" flexDirection="column" gap={2} pt={1}>
            {/* Name & Description */}
            <TextField
              label={t('app.name')}
              value={name}
              onChange={(e) => setName(e.target.value)}
              fullWidth
              required
              disabled={isViewMode}
            />
            <TextField
              label={t('app.description')}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              fullWidth
              multiline
              rows={2}
              disabled={isViewMode}
            />

            <Divider />

            <Box display="flex" gap={2}>
              {/* SOP multi-select */}
              <Box flex={1}>
                <Typography variant="subtitle2" mb={1}>{t('agents.roles.assignedSops')}</Typography>
                <Box
                  sx={{
                    border: 1,
                    borderColor: 'divider',
                    borderRadius: 1,
                    maxHeight: 180,
                    overflow: 'auto',
                    p: 1,
                  }}
                >
                  {(sops ?? []).length === 0 ? (
                    <Typography variant="body2" color="text.secondary">{t('app.noData')}</Typography>
                  ) : (
                    (sops ?? []).map((sop) => (
                      <FormControlLabel
                        key={sop.id}
                        control={
                        <Checkbox
                          size="small"
                          checked={selectedSopIds.includes(sop.id)}
                          onChange={() => toggleSop(sop.id)}
                          disabled={isViewMode}
                        />
                        }
                        label={sop.name}
                        sx={{ display: 'flex', mx: 0 }}
                      />
                    ))
                  )}
                </Box>
              </Box>

              {/* Skill multi-select */}
              <Box flex={1}>
                <Typography variant="subtitle2" mb={1}>{t('agents.roles.assignedSkills')}</Typography>
                <Box
                  sx={{
                    border: 1,
                    borderColor: 'divider',
                    borderRadius: 1,
                    maxHeight: 180,
                    overflow: 'auto',
                    p: 1,
                  }}
                >
                  {(skills ?? []).length === 0 ? (
                    <Typography variant="body2" color="text.secondary">{t('app.noData')}</Typography>
                  ) : (
                    (skills ?? []).map((skill) => (
                      <Tooltip
                        key={skill.id}
                        title={
                          !isViewMode && lockedSkills.has(skill.id)
                            ? t('agents.roles.skillLockedBySOPTooltip', { defaultValue: 'Required by a selected SOP' })
                            : ''
                        }
                        placement="right"
                      >
                        <FormControlLabel
                          control={
                            <Checkbox
                              size="small"
                              checked={selectedSkillIds.includes(skill.id)}
                              onChange={() => toggleSkill(skill.id)}
                              disabled={isViewMode || lockedSkills.has(skill.id)}
                            />
                          }
                          label={skill.name}
                          sx={{ display: 'flex', mx: 0 }}
                        />
                      </Tooltip>
                    ))
                  )}
                </Box>
              </Box>
            </Box>

            <Divider />

            {/* Assigned Identities table (edit/view mode) */}
            {(isEditing || isViewMode) && (
              <Box>
                <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
                  <Typography variant="subtitle2">{t('agents.roles.assignedIdentities')}</Typography>
                  {!isViewMode && (
                    <Button
                      size="small"
                      startIcon={<PersonAddIcon />}
                      onClick={() => setAssignDialogOpen(true)}
                    >
                      {t('agents.roles.assignIdentities')}
                    </Button>
                  )}
                </Box>
                {(assignedIdentities ?? []).length === 0 ? (
                  <Typography variant="body2" color="text.secondary">
                    {t('agents.roles.noAssignedIdentities')}
                  </Typography>
                ) : (
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>{t('app.name')}</TableCell>
                        <TableCell>{t('agents.identities.realmUsername')}</TableCell>
                        <TableCell>{t('app.status')}</TableCell>
                        {!isViewMode && <TableCell padding="checkbox" />}
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {(assignedIdentities ?? []).map((identity) => (
                        <TableRow key={identity.id}>
                          <TableCell>{identity.name}</TableCell>
                          <TableCell>
                            <Typography variant="body2" color="text.secondary">
                              {identity.realm_username ?? '—'}
                            </Typography>
                          </TableCell>
                          <TableCell>
                            <Chip
                              size="small"
                              label={identity.status}
                              color={identity.status === 'active' ? 'success' : 'default'}
                            />
                          </TableCell>
                          {!isViewMode && (
                            <TableCell padding="checkbox">
                              <Tooltip title={t('agents.roles.removeIdentity')}>
                                <IconButton
                                  size="small"
                                  color="error"
                                  onClick={() => handleRemoveIdentity(identity.id)}
                                >
                                  <PersonRemoveIcon fontSize="small" />
                                </IconButton>
                              </Tooltip>
                            </TableCell>
                          )}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </Box>
            )}

            <Divider />

            {/* Inline MCP Session Assignment */}
            <Box>
              <Typography variant="subtitle2" mb={1}>
                {t('agents.roles.mcpSessionAssignment')}
              </Typography>

              {requiredMcpServers.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  {t('agents.roles.mcpSessionAssignmentHint')}
                </Typography>
              ) : (
                <Box>
                  <Typography variant="body2" color="text.secondary" mb={1.5}>
                    {t('agents.roles.mcpSessionAssignmentHint')}
                  </Typography>

                  {requiredMcpServers.map((slug, idx) => {
                    const query = serverSessionsQueries[idx]
                    const isLoading = query?.isLoading ?? false
                    const isError = query?.isError ?? false
                    const sessions = sessionsBySlug[slug] ?? []
                    const selectedId = selectedMcpSessions[slug] ?? ''
                    const hasPassthrough = serverHasPassthrough(slug)

                    return (
                      <Box
                        key={slug}
                        sx={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 1.5,
                          mb: 1.5,
                          p: 1.5,
                          border: 1,
                          borderColor: !isViewMode && !selectedId ? 'warning.main' : 'divider',
                          borderRadius: 1,
                        }}
                      >
                        {/* Server label */}
                        <Box sx={{ minWidth: 160, display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <Typography variant="body2" fontWeight={500} noWrap>
                            {getServerDisplayName(slug)}
                          </Typography>
                          <Typography variant="caption" color="text.secondary" noWrap>
                            ({slug})
                          </Typography>
                          {hasPassthrough && (
                            <Chip
                              label={t('mcp.sessions.passthrough')}
                              size="small"
                              sx={{ height: 18, fontSize: '0.65rem', ml: 0.5 }}
                            />
                          )}
                        </Box>

                        {/* Session dropdown or loading/error state */}
                        {isLoading ? (
                          <Box display="flex" alignItems="center" gap={1} flex={1}>
                            <CircularProgress size={16} />
                            <Typography variant="caption" color="text.secondary">
                              {t('agents.roles.mcpSessionLoading')}
                            </Typography>
                          </Box>
                        ) : isError ? (
                          <Box display="flex" alignItems="center" gap={1} flex={1}>
                            <Typography variant="caption" color="error">
                              {t('agents.roles.mcpSessionLoadError')}
                            </Typography>
                            <Button
                              size="small"
                              variant="outlined"
                              onClick={() => query?.refetch?.()}
                            >
                              {t('agents.roles.mcpSessionRetry')}
                            </Button>
                          </Box>
                        ) : sessions.length === 0 ? (
                          <Typography variant="caption" color="text.secondary" flex={1}>
                            {t('agents.roles.mcpSessionNoSessions')}
                          </Typography>
                        ) : (
                          <FormControl size="small" sx={{ flex: 1, minWidth: 200 }} disabled={isViewMode}>
                            <InputLabel id={`mcp-session-label-${slug}`}>
                              {t('agents.roles.mcpSessionRequired')}
                            </InputLabel>
                            <Select
                              labelId={`mcp-session-label-${slug}`}
                              value={selectedId}
                              label={t('agents.roles.mcpSessionRequired')}
                              onChange={(e) => handleSessionSelectionChange(slug, e.target.value as string)}
                            >
                              <MenuItem value="">
                                <em>{t('agents.roles.mcpSessionRequired')}</em>
                              </MenuItem>
                              {sessions.map((session) => (
                                <MenuItem key={session.id} value={session.id}>
                                  <Box display="flex" alignItems="center" gap={1}>
                                    <Typography variant="body2">{session.name}</Typography>
                                    {session.auth_type === 'passthrough' && (
                                      <Chip
                                        label={t('mcp.sessions.passthrough')}
                                        size="small"
                                        sx={{ height: 18, fontSize: '0.65rem' }}
                                      />
                                    )}
                                  </Box>
                                </MenuItem>
                              ))}
                            </Select>
                          </FormControl>
                        )}

                        {/* Refresh button */}
                        {!isViewMode && (
                          <Tooltip title={t('agents.roles.mcpSessionRefresh')}>
                            <IconButton
                              size="small"
                              onClick={() => handleRefreshSessions(slug)}
                              disabled={isLoading}
                            >
                              <RefreshIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                        )}
                      </Box>
                    )
                  })}

                  {/* Missing session validation warning */}
                  {!isViewMode && missingServers.length > 0 && (
                    <Alert severity="warning" sx={{ mt: 1 }}>
                      {t('agents.roles.mcpSessionMissing')}{' '}
                      {missingServers.map((s) => getServerDisplayName(s)).join(', ')}
                    </Alert>
                  )}
                </Box>
              )}
            </Box>

            <Divider />

            {/* MCP Tool Preview */}
            <Box>
              <Box
                display="flex"
                alignItems="center"
                sx={{ mb: 1, cursor: !isViewMode && isEditing && previewTools.length > 0 ? 'pointer' : 'default', userSelect: 'none' }}
                onClick={() => !isViewMode && isEditing && previewTools.length > 0 && setToolRefOpen((o) => !o)}
              >
                <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>{t('agents.roles.mcpToolPreview')}</Typography>
                {!isViewMode && isEditing && previewTools.length > 0 && (
                  <IconButton size="small" tabIndex={-1}>
                    {toolRefOpen ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
                  </IconButton>
                )}
              </Box>
              {!isEditing && !isViewMode ? (
                <Alert severity="info">{t('agents.roles.mcpToolPreviewHint')}</Alert>
              ) : previewLoading ? (
                <CircularProgress size={20} />
              ) : previewTools.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  {t('agents.roles.noMcpTools')}
                </Typography>
              ) : (
                <>
                  {/* Summary chips */}
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mb: toolRefOpen ? 1 : 0 }}>
                    {previewTools.map((tool) => (
                      <Chip key={tool} label={tool} size="small" variant="outlined" sx={{ fontFamily: 'monospace', fontSize: '0.7rem' }} />
                    ))}
                  </Box>
                  {/* Schema reference (collapsible) */}
                  {toolRefOpen && toolReferenceText && (
                    <Box
                      component="pre"
                      sx={{
                        mt: 1,
                        p: 1.5,
                        bgcolor: 'action.hover',
                        borderRadius: 1,
                        fontSize: '0.72rem',
                        fontFamily: 'monospace',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        color: 'text.secondary',
                        maxHeight: 400,
                        overflowY: 'auto',
                      }}
                    >
                      {toolReferenceText}
                    </Box>
                  )}
                </>
              )}
            </Box>

            <Divider />

            {/* Allowed Agent Type Preview */}
            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                {t('agents.roles.allowedAgentTypePreview')}
              </Typography>
              {!isEditing && !isViewMode ? (
                <Alert severity="info">{t('agents.roles.allowedAgentTypePreviewHint')}</Alert>
              ) : previewLoading ? (
                <CircularProgress size={20} />
              ) : previewAgentTypes.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  {t('agents.roles.noAllowedAgentTypes')}
                </Typography>
              ) : (
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                  {previewAgentTypes.map((agentType) => (
                    <Chip
                      key={agentType}
                      label={agentType}
                      size="small"
                      variant="outlined"
                      sx={{ fontFamily: 'monospace', fontSize: '0.7rem' }}
                    />
                  ))}
                </Box>
              )}
            </Box>
          </Box>
        </DialogContent>

        <DialogActions>
          {isViewMode ? (
            <Button onClick={() => { onClose(); setDialogError(null) }}>{t('app.close')}</Button>
          ) : (
            <>
              <Button onClick={() => { onClose(); setDialogError(null) }}>{t('app.cancel')}</Button>
              <Button variant="contained" onClick={handleSave} disabled={isSaveDisabled}>
                {t('app.save')}
              </Button>
            </>
          )}
        </DialogActions>
      </Dialog>

      {editRole && (
        <AssignIdentitiesToRoleDialog
          open={assignDialogOpen}
          role={editRole}
          onClose={() => setAssignDialogOpen(false)}
          onSaved={async () => {
            setAssignDialogOpen(false)
            await refetchIdentities()
            await queryClient.invalidateQueries({ queryKey: ['agents', 'roles', editRole.id, 'identities'] })
          }}
        />
      )}
    </>
  )
}
