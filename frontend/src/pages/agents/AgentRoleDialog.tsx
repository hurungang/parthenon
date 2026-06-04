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
  FormControlLabel,
  IconButton,
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
import CloudQueueIcon from '@mui/icons-material/CloudQueue'
import RemoveCircleOutlineIcon from '@mui/icons-material/RemoveCircleOutline'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import { useAllTools } from '../../hooks/useMcpServers'
import { canonicalizeToolName } from '../../utils/toolNaming'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { AssignIdentitiesToRoleDialog } from './AssignIdentitiesToRoleDialog'
import { AssignMcpSessionsToRoleDialog } from './AssignMcpSessionsToRoleDialog'
import type { AgentIdentity, AgentRole, McpTool, Skill, Sop } from '../../types'

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
 * Create / edit dialog for AgentRole.
 * Includes SOP multi-select, Skill multi-select, real-time MCP tool preview panel,
 * and assigned identities table with Assign/Remove actions.
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
  const [assignMcpDialogOpen, setAssignMcpDialogOpen] = useState(false)
  const [toolRefOpen, setToolRefOpen] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const { data: allTools } = useAllTools()

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

  const { data: assignedMcpSessions, refetch: refetchMcpSessions } = useQuery<McpSessionInfo[]>({
    queryKey: ['agents', 'roles', editRole?.id, 'mcp-sessions'],
    queryFn: async () => {
      const { data } = await apiClient.get<McpSessionInfo[]>(`/agents/roles/${editRole!.id}/mcp-sessions`)
      return data
    },
    enabled: open && !!editRole?.id,
  })

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

  const handleRemoveMcpSession = async (sessionId: string) => {
    if (!editRole?.id) return
    try {
      await apiClient.delete(`/agents/roles/${editRole.id}/mcp-sessions/${sessionId}`)
      await refetchMcpSessions()
    } catch (err) {
      setDialogError(err)
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
        await apiClient.put(`/agents/roles/${editRole.id}`, body)
      } else {
        await apiClient.post('/agents/roles', body)
      }
      await onSaved()
    } catch (err) {
      setDialogError(err)
    }
  }

  const isEditing = !!editRole

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

            {/* Assigned MCP Sessions table (edit/view mode) */}
            {(isEditing || isViewMode) && (
              <Box>
                <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
                  <Typography variant="subtitle2">{t('agents.roles.assignedMcpSessions')}</Typography>
                  {!isViewMode && (
                    <Button
                      size="small"
                      startIcon={<CloudQueueIcon />}
                      onClick={() => setAssignMcpDialogOpen(true)}
                    >
                      {t('agents.roles.assignMcpSessions')}
                    </Button>
                  )}
                </Box>
                {(assignedMcpSessions ?? []).length === 0 ? (
                  <Typography variant="body2" color="text.secondary">
                    {t('agents.roles.noAssignedMcpSessions')}
                  </Typography>
                ) : (
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>{t('mcp.sessions.title')}</TableCell>
                        <TableCell>{t('mcp.servers')}</TableCell>
                        {!isViewMode && <TableCell padding="checkbox" />}
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {(assignedMcpSessions ?? []).map((session) => (
                        <TableRow key={session.id}>
                          <TableCell>{session.name}</TableCell>
                          <TableCell>
                            <Typography variant="body2" color="text.secondary">
                              {session.server_name} ({session.server_slug})
                            </Typography>
                          </TableCell>
                          {!isViewMode && (
                            <TableCell padding="checkbox">
                              <Tooltip title={t('agents.roles.removeMcpSession')}>
                                <IconButton
                                  size="small"
                                  color="error"
                                  onClick={() => handleRemoveMcpSession(session.id)}
                                >
                                  <RemoveCircleOutlineIcon fontSize="small" />
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
              <Button variant="contained" onClick={handleSave} disabled={!name.trim()}>
                {t('app.save')}
              </Button>
            </>
          )}
        </DialogActions>
      </Dialog>

      {editRole && (
        <>
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
          <AssignMcpSessionsToRoleDialog
            open={assignMcpDialogOpen}
            role={editRole}
            onClose={() => setAssignMcpDialogOpen(false)}
            onSaved={async () => {
              setAssignMcpDialogOpen(false)
              await refetchMcpSessions()
              await queryClient.invalidateQueries({ queryKey: ['agents', 'roles', editRole.id, 'mcp-sessions'] })
            }}
          />
        </>
      )}
    </>
  )
}
