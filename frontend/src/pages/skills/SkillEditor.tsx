import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  CircularProgress,
  Chip,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  IconButton,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import Autocomplete from '@mui/material/Autocomplete'
import CloseIcon from '@mui/icons-material/Close'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import BuildIcon from '@mui/icons-material/Build'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import { useAllTools, useMcpServers } from '../../hooks/useMcpServers'
import { useSkillRoles } from '../../hooks/useSkills'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import type {
  AgentRole,
  McpTool,
  Skill,
  SkillWorkflowGenerateResponse,
  SkillWorkflowPreviewResponse,
} from '../../types'

interface SkillEditorProps {
  open: boolean
  skill: Skill | null
  mode?: 'create' | 'edit' | 'view'
  onClose: () => void
  onSaved: () => void
}

export function extractGeneratedToolSection(instructionsWithTools?: string | null): string | null {
  if (!instructionsWithTools) return null

  // Generated tool reference is appended to the end by backend.
  // Use the last Tools header to avoid matching a user-authored "## Tools" section.
  const marker = '\n\n## Tools'
  const idx = instructionsWithTools.lastIndexOf(marker)
  if (idx !== -1) return instructionsWithTools.slice(idx + 2)

  // Backward compatibility for payloads that start directly with the marker.
  if (instructionsWithTools.startsWith('## Tools')) return instructionsWithTools
  return null
}

type ToolReferenceTool = Pick<McpTool, 'id' | 'name' | 'description' | 'input_schema'>

export function buildGeneratedToolSectionFromSelection(
  selectedToolIds: string[],
  allTools?: ToolReferenceTool[] | null,
): string | null {
  if (!allTools || selectedToolIds.length === 0) return null

  const toolById = new Map(allTools.map((tool) => [tool.id, tool]))
  const selectedTools = selectedToolIds
    .map((toolId) => toolById.get(toolId))
    .filter((tool): tool is ToolReferenceTool => tool != null)

  if (selectedTools.length === 0) return null

  const lines: string[] = ['## Tools']
  for (const tool of selectedTools) {
    lines.push(`\n### \`${tool.name}\``)
    if (tool.description) lines.push(tool.description)
    if (tool.input_schema) {
      lines.push('\n**Input Schema:**')
      lines.push('```json')
      lines.push(JSON.stringify(tool.input_schema, null, 2))
      lines.push('```')
    }
  }
  return lines.join('\n')
}

export function SkillEditor({ open, skill, mode = 'create', onClose, onSaved }: SkillEditorProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const isViewMode = mode === 'view'

  const [form, setForm] = useState({ name: '', description: '', instructions: '' })
  const [selectedToolIds, setSelectedToolIds] = useState<string[]>([])
  const [selectedRoleIds, setSelectedRoleIds] = useState<string[]>([])
  const [editorError, setEditorError] = useState<unknown>(null)
  const [saving, setSaving] = useState(false)
  const [working, setWorking] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [rolesOpen, setRolesOpen] = useState(false)
  const [toolRefOpen, setToolRefOpen] = useState(false)
  const [filterServerSlugs, setFilterServerSlugs] = useState<string[]>([])
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewContent, setPreviewContent] = useState('')
  const [previewModelId, setPreviewModelId] = useState<string | null>(null)
  const [toolSelectorOpen, setToolSelectorOpen] = useState(false)
  const [pendingToolIds, setPendingToolIds] = useState<string[]>([])
  const [generateAfterSelect, setGenerateAfterSelect] = useState(false)

  const { data: allTools } = useAllTools()
  const { data: servers } = useMcpServers()
  const { data: currentRoleIds } = useSkillRoles(skill?.id ?? '')

  // Fetch full skill detail (includes instructions + instructions_with_tools) when editing
  const { data: skillDetail } = useQuery<Skill>({
    queryKey: ['skills', skill?.id],
    queryFn: async () => {
      const { data } = await apiClient.get<Skill>(`/skills/${skill!.id}`)
      return data
    },
    enabled: !!skill?.id,
  })

  const { data: allRoles } = useQuery<AgentRole[]>({
    queryKey: ['agents', 'roles'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentRole[]>('/agents/roles')
      return data
    },
  })

  // Initialize form when skill changes
  useEffect(() => {
    if (skill) {
      setForm({
        name: skill.name,
        description: skill.description ?? '',
        instructions: skill.instructions ?? '',
      })
      setSelectedToolIds(skill.tool_ids ?? [])
    } else {
      setForm({ name: '', description: '', instructions: '' })
      setSelectedToolIds([])
    }
    setEditorError(null)
    setToolRefOpen(false)
    setRolesOpen(false)
    setFilterServerSlugs([])
    setToolSelectorOpen(false)
    setPendingToolIds([])
    setGenerateAfterSelect(false)
  }, [skill])

  // Populate instructions from detail fetch (detail has the full instructions field)
  useEffect(() => {
    if (skillDetail) {
      setForm((f) => ({ ...f, instructions: skillDetail.instructions ?? '' }))
    }
  }, [skillDetail])

  // Load existing role memberships when editing
  useEffect(() => {
    if (currentRoleIds) {
      setSelectedRoleIds(currentRoleIds)
    }
  }, [currentRoleIds])

  const serverMap = useMemo(() => {
    const m: Record<string, string> = {}
    for (const s of servers ?? []) m[s.id] = s.slug
    return m
  }, [servers])

  // Group tools by server slug
  const toolsByServer = useMemo(() => {
    const groups: Record<string, McpTool[]> = {}
    for (const tool of allTools ?? []) {
      const slug = serverMap[tool.server_id] ?? tool.server_id
      if (!groups[slug]) groups[slug] = []
      groups[slug].push(tool)
    }
    return groups
  }, [allTools, serverMap])

  // Filter tool groups by selected server slugs
  const filteredToolsByServer = useMemo(() => {
    if (filterServerSlugs.length === 0) return toolsByServer
    return Object.fromEntries(
      Object.entries(toolsByServer).filter(([slug]) => filterServerSlugs.includes(slug)),
    )
  }, [toolsByServer, filterServerSlugs])

  const toggleRole = (roleId: string) => {
    setSelectedRoleIds((prev) =>
      prev.includes(roleId) ? prev.filter((id) => id !== roleId) : [...prev, roleId],
    )
  }

  const nameError = form.name
    ? !/^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$/.test(form.name)
      ? t('skills.editor.nameInvalid')
      : null
    : null

  const handleSave = async () => {
    if (isViewMode) return
    if (nameError) return
    try {
      setSaving(true)
      setEditorError(null)
      const payload = {
        name: form.name,
        description: form.description || null,
        instructions: form.instructions || null,
        tool_ids: selectedToolIds,
      }
      let skillId: string
      if (skill) {
        await apiClient.put(`/skills/${skill.id}`, payload)
        skillId = skill.id
      } else {
        const { data } = await apiClient.post<Skill>('/skills', payload)
        skillId = data.id
      }
      // Save role assignments
      await apiClient.put(`/skills/${skillId}/roles`, { role_ids: selectedRoleIds })
      await queryClient.invalidateQueries({ queryKey: ['skills'] })
      onSaved()
    } catch (err) {
      setEditorError(err)
    } finally {
      setSaving(false)
    }
  }

  const selectedToolsForWorkflow = useMemo(() => {
    if (!allTools || selectedToolIds.length === 0) return []
    const byId = new Map(allTools.map((tool) => [tool.id, tool]))
    return selectedToolIds
      .map((toolId) => byId.get(toolId))
      .filter((tool): tool is McpTool => tool != null)
      .map((tool) => ({
        id: tool.id,
        name: tool.name,
        description: tool.description,
        input_schema: tool.input_schema,
      }))
  }, [allTools, selectedToolIds])

  const handleGenerateWorkflow = async (toolsOverride?: typeof selectedToolsForWorkflow) => {
    try {
      setGenerating(true)
      setEditorError(null)
      const { data } = await apiClient.post<SkillWorkflowGenerateResponse>('/skills/workflow/generate', {
        description: form.description,
        selected_tools: toolsOverride ?? selectedToolsForWorkflow,
      })
      setForm((f) => ({ ...f, instructions: data.workflow }))
    } catch (err) {
      setEditorError(err)
    } finally {
      setGenerating(false)
    }
  }

  const handleGenerateClick = () => {
    if (selectedToolIds.length === 0) {
      setPendingToolIds([...selectedToolIds])
      setGenerateAfterSelect(true)
      setToolSelectorOpen(true)
    } else {
      void handleGenerateWorkflow()
    }
  }

  const handleOpenToolSelector = () => {
    setPendingToolIds([...selectedToolIds])
    setGenerateAfterSelect(false)
    setToolSelectorOpen(true)
  }

  const pendingToggleTool = (toolId: string) => {
    setPendingToolIds((prev) =>
      prev.includes(toolId) ? prev.filter((id) => id !== toolId) : [...prev, toolId],
    )
  }

  const handleToolSelectorConfirm = () => {
    setSelectedToolIds(pendingToolIds)
    setToolSelectorOpen(false)
    if (generateAfterSelect) {
      setGenerateAfterSelect(false)
      if (!allTools) return
      const byId = new Map(allTools.map((tool) => [tool.id, tool]))
      const toolsForGenerate = pendingToolIds
        .map((toolId) => byId.get(toolId))
        .filter((tool): tool is McpTool => tool != null)
        .map((tool) => ({
          id: tool.id,
          name: tool.name,
          description: tool.description,
          input_schema: tool.input_schema,
        }))
      void handleGenerateWorkflow(toolsForGenerate)
    }
  }

  const handleToolSelectorCancel = () => {
    setToolSelectorOpen(false)
    setGenerateAfterSelect(false)
  }

  const handlePreviewWorkflow = async () => {
    try {
      setWorking(true)
      setEditorError(null)
      const { data } = await apiClient.post<SkillWorkflowPreviewResponse>('/skills/workflow/preview', {
        workflow: form.instructions,
        description: form.description,
        selected_tools: selectedToolsForWorkflow,
      })
      setPreviewModelId(data.model_id)
      setPreviewContent(data.instruction_file)
      setPreviewOpen(true)
    } catch (err) {
      setEditorError(err)
    } finally {
      setWorking(false)
    }
  }

  // Extract just the ## Tools section from instructions_with_tools (if present)
  const persistedToolSection = useMemo(() => {
    return extractGeneratedToolSection(skillDetail?.instructions_with_tools)
  }, [skillDetail])

  // Live preview from current selections so the reference refreshes immediately
  // when tools are checked/unchecked, before saving.
  const liveToolSection = useMemo(
    () => buildGeneratedToolSectionFromSelection(selectedToolIds, allTools),
    [selectedToolIds, allTools],
  )

  const toolSection = liveToolSection ?? persistedToolSection

  return (
    <Dialog
      open={open}
      onClose={() => {
        onClose()
        setEditorError(null)
      }}
      maxWidth="lg"
      fullWidth
    >
      <DialogTitle>
        <Box display="flex" justifyContent="space-between" alignItems="center">
          <Typography variant="h6">
            {mode === 'view'
              ? t('skills.viewSkill')
              : skill
                ? t('skills.editSkill')
                : t('skills.createSkill')}
          </Typography>
          <IconButton size="small" onClick={onClose}><CloseIcon /></IconButton>
        </Box>
      </DialogTitle>
      <DialogContent dividers>
        {editorError != null && <PermissionDeniedAlert error={editorError} fallbackMessage={t('app.error')} />}

        <Stack spacing={2} sx={{ mt: 1 }}>
        {/* Basic Info */}
        <Card variant="outlined">
          <CardContent>
            <Typography variant="subtitle2" mb={1}>{t('skills.editor.basicInfo')}</Typography>
            <Stack spacing={2}>
              <TextField
                label={t('app.name')}
                value={form.name}
                onChange={(e) => {
                  const raw = e.target.value
                  setForm((f) => ({ ...f, name: raw.toLowerCase().replace(/[^a-z0-9-]/g, '') }))
                }}
                disabled={isViewMode}
                fullWidth
                required
                size="small"
                error={!!nameError}
                helperText={nameError ?? t('skills.editor.nameHint')}
              />
              <TextField
                label={t('app.description')}
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                disabled={isViewMode}
                fullWidth
                multiline
                rows={2}
                size="small"
              />
              <TextField
                label={t('skills.editor.workflow')}
                value={form.instructions}
                onChange={(e) => setForm((f) => ({ ...f, instructions: e.target.value }))}
                disabled={isViewMode}
                fullWidth
                multiline
                rows={8}
                size="small"
                helperText={t('skills.editor.workflowHint')}
              />
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                <Button
                  variant="outlined"
                  onClick={() => void handleGenerateClick()}
                  disabled={generating || working}
                  startIcon={generating ? <CircularProgress size={16} color="inherit" /> : undefined}
                >
                  {generating ? t('app.loading') : t('skills.editor.generateWorkflow')}
                </Button>
                <Button
                  variant="outlined"
                  onClick={() => void handlePreviewWorkflow()}
                  disabled={generating || working}
                >
                  {t('skills.editor.previewWorkflow')}
                </Button>
                <Button
                  variant="outlined"
                  startIcon={<BuildIcon />}
                  onClick={handleOpenToolSelector}
                  disabled={isViewMode}
                >
                  {t('skills.editor.selectTools')}
                </Button>
              </Stack>
              {/* Selected tools summary */}
              {selectedToolIds.length > 0 && allTools && (
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
                  {selectedToolIds.map((toolId) => {
                    const tool = allTools.find((t) => t.id === toolId)
                    return tool ? (
                      <Chip key={toolId} label={tool.name} size="small" variant="outlined" />
                    ) : null
                  })}
                </Box>
              )}

              {/* Generated Tool Reference (read-only, collapsible) */}
              {skill && (
                <Box>
                  <Box
                    display="flex"
                    alignItems="center"
                    sx={{ cursor: 'pointer', userSelect: 'none' }}
                    onClick={() => setToolRefOpen((o) => !o)}
                  >
                    <Typography variant="caption" color="text.secondary" fontWeight={600} sx={{ flexGrow: 1 }}>
                      {t('skills.editor.generatedToolReference')}
                    </Typography>
                    <IconButton size="small" tabIndex={-1}>
                      {toolRefOpen ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
                    </IconButton>
                  </Box>
                  <Collapse in={toolRefOpen}>
                    <Box
                      component="pre"
                      sx={{
                        mt: 1,
                        p: 1.5,
                        bgcolor: 'action.hover',
                        borderRadius: 1,
                        fontSize: '0.75rem',
                        fontFamily: 'monospace',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        color: 'text.secondary',
                        maxHeight: 320,
                        overflowY: 'auto',
                      }}
                    >
                      {toolSection
                        ? toolSection
                        : <Typography variant="caption" color="text.disabled" component="span">{t('skills.noTools')}</Typography>
                      }
                    </Box>
                    <Typography variant="caption" color="text.disabled">
                      {t('skills.editor.generatedToolReferenceHint')}
                    </Typography>
                  </Collapse>
                </Box>
              )}
            </Stack>
          </CardContent>
        </Card>

        {/* Assign to Roles */}
        <Card variant="outlined">
          <CardContent sx={{ pb: rolesOpen ? undefined : '12px !important' }}>
            <Box
              display="flex"
              alignItems="center"
              sx={{ cursor: 'pointer', userSelect: 'none' }}
              onClick={() => setRolesOpen((o) => !o)}
            >
              <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>{t('skills.editor.assignToRoles')}</Typography>
              <IconButton size="small" tabIndex={-1}>
                {rolesOpen ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
              </IconButton>
            </Box>
            <Collapse in={rolesOpen}>
              <Box sx={{ mt: 1 }}>
                {(allRoles ?? []).map((role) => (
                  <FormControlLabel
                    key={role.id}
                    control={
                      <Checkbox
                        size="small"
                        checked={selectedRoleIds.includes(role.id)}
                        disabled={isViewMode}
                        onChange={() => toggleRole(role.id)}
                      />
                    }
                    label={role.name}
                    sx={{ display: 'flex' }}
                  />
                ))}
                {(allRoles ?? []).length === 0 && (
                  <Typography variant="caption" color="text.secondary">{t('app.noData')}</Typography>
                )}
              </Box>
            </Collapse>
          </CardContent>
        </Card>

        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving}>{t('app.cancel')}</Button>
        {!isViewMode && (
          <Button variant="contained" onClick={handleSave} disabled={saving || !form.name || !!nameError}>
            {saving ? t('app.loading') : t('app.save')}
          </Button>
        )}
      </DialogActions>

      <Dialog
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>{t('skills.editor.workflowPreviewTitle', { model: previewModelId ?? '-' })}</DialogTitle>
        <DialogContent dividers>
          <Box
            component="pre"
            sx={{
              m: 0,
              p: 1.5,
              bgcolor: 'action.hover',
              borderRadius: 1,
              fontSize: '0.8rem',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {previewContent}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPreviewOpen(false)}>{t('app.close')}</Button>
        </DialogActions>
      </Dialog>

      {/* Tool Selector Dialog */}
      <Dialog
        open={toolSelectorOpen}
        onClose={handleToolSelectorCancel}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>{t('skills.editor.selectToolsDialogTitle')}</DialogTitle>
        <DialogContent dividers>
          {generateAfterSelect && (
            <Box
              sx={{
                mb: 2,
                p: 1.5,
                bgcolor: 'info.main',
                color: 'info.contrastText',
                borderRadius: 1,
              }}
            >
              <Typography variant="body2">{t('skills.editor.selectToolsHintForGenerate')}</Typography>
            </Box>
          )}
          {!allTools ? (
            <CircularProgress size={20} />
          ) : allTools.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              {t('skills.editor.noToolsAvailable')}
            </Typography>
          ) : (
            <>
              <Autocomplete
                multiple
                size="small"
                options={Object.keys(toolsByServer)}
                value={filterServerSlugs}
                onChange={(_, newValue) => setFilterServerSlugs(newValue)}
                renderInput={(params) => (
                  <TextField {...params} label={t('skills.editor.filterByServer')} size="small" />
                )}
                renderTags={(value, getTagProps) =>
                  value.map((option, index) => (
                    <Chip {...getTagProps({ index })} key={option} label={option} size="small" />
                  ))
                }
                sx={{ mb: 2 }}
              />
              {Object.entries(filteredToolsByServer).map(([slug, tools]) => (
                <Box key={slug} mb={1}>
                  <Chip label={slug} size="small" color="primary" variant="outlined" sx={{ mb: 0.5 }} />
                  {tools.map((tool) => (
                    <FormControlLabel
                      key={tool.id}
                      control={
                        <Checkbox
                          size="small"
                          checked={pendingToolIds.includes(tool.id)}
                          onChange={() => pendingToggleTool(tool.id)}
                        />
                      }
                      label={
                        <Box>
                          <Typography variant="body2" component="span">
                            <code>{tool.name}</code>
                          </Typography>
                          {tool.description && (
                            <Typography variant="caption" color="text.secondary" display="block">
                              {tool.description}
                            </Typography>
                          )}
                        </Box>
                      }
                      sx={{ display: 'flex', ml: 1 }}
                    />
                  ))}
                </Box>
              ))}
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleToolSelectorCancel}>{t('app.cancel')}</Button>
          <Button variant="contained" onClick={handleToolSelectorConfirm}>
            {t('skills.editor.confirmSelection')}
          </Button>
        </DialogActions>
      </Dialog>
    </Dialog>
  )
}

