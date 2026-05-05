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
  FormControlLabel,
  IconButton,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import { useAllTools, useMcpServers } from '../../hooks/useMcpServers'
import { useSkillRoles } from '../../hooks/useSkills'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import type { AgentRole, McpTool, Skill } from '../../types'

interface SkillEditorProps {
  skill: Skill | null
  onClose: () => void
  onSaved: () => void
}

export function SkillEditor({ skill, onClose, onSaved }: SkillEditorProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const [form, setForm] = useState({ name: '', description: '', instructions: '' })
  const [selectedToolIds, setSelectedToolIds] = useState<string[]>([])
  const [selectedRoleIds, setSelectedRoleIds] = useState<string[]>([])
  const [editorError, setEditorError] = useState<unknown>(null)
  const [saving, setSaving] = useState(false)

  const { data: allTools } = useAllTools()
  const { data: servers } = useMcpServers()
  const { data: currentRoleIds } = useSkillRoles(skill?.id ?? '')

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
  }, [skill])

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

  const toggleTool = (toolId: string) => {
    setSelectedToolIds((prev) =>
      prev.includes(toolId) ? prev.filter((id) => id !== toolId) : [...prev, toolId],
    )
  }

  const toggleRole = (roleId: string) => {
    setSelectedRoleIds((prev) =>
      prev.includes(roleId) ? prev.filter((id) => id !== roleId) : [...prev, roleId],
    )
  }

  const handleSave = async () => {
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

  return (
    <Box sx={{ borderLeft: 1, borderColor: 'divider', pl: 3, minWidth: 480 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h6">
          {skill ? t('skills.editSkill') : t('skills.createSkill')}
        </Typography>
        <IconButton size="small" onClick={onClose}><CloseIcon /></IconButton>
      </Box>

      {editorError && <PermissionDeniedAlert error={editorError} fallbackMessage={t('app.error')} />}

      <Stack spacing={2}>
        {/* Basic Info */}
        <Card variant="outlined">
          <CardContent>
            <Typography variant="subtitle2" mb={1}>{t('skills.editor.basicInfo')}</Typography>
            <Stack spacing={2}>
              <TextField
                label={t('app.name')}
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                fullWidth
                required
                size="small"
              />
              <TextField
                label={t('app.description')}
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                fullWidth
                multiline
                rows={2}
                size="small"
              />
              <TextField
                label={t('skills.editor.instructions')}
                value={form.instructions}
                onChange={(e) => setForm((f) => ({ ...f, instructions: e.target.value }))}
                fullWidth
                multiline
                rows={3}
                size="small"
                helperText={t('skills.editor.instructionsHint')}
              />
            </Stack>
          </CardContent>
        </Card>

        {/* MCP Tools */}
        <Card variant="outlined">
          <CardContent>
            <Typography variant="subtitle2" mb={1}>{t('skills.editor.mcpTools')}</Typography>
            {!allTools ? (
              <CircularProgress size={20} />
            ) : (
              Object.entries(toolsByServer).map(([slug, tools]) => (
                <Box key={slug} mb={1}>
                  <Typography variant="caption" color="primary" fontWeight={600}>
                    <Chip label={slug} size="small" color="primary" variant="outlined" sx={{ mb: 0.5 }} />
                  </Typography>
                  {tools.map((tool) => (
                    <FormControlLabel
                      key={tool.id}
                      control={
                        <Checkbox
                          size="small"
                          checked={selectedToolIds.includes(tool.id)}
                          onChange={() => toggleTool(tool.id)}
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
              ))
            )}
          </CardContent>
        </Card>

        {/* Assign to Roles */}
        <Card variant="outlined">
          <CardContent>
            <Typography variant="subtitle2" mb={1}>{t('skills.editor.assignToRoles')}</Typography>
            {(allRoles ?? []).map((role) => (
              <FormControlLabel
                key={role.id}
                control={
                  <Checkbox
                    size="small"
                    checked={selectedRoleIds.includes(role.id)}
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
          </CardContent>
        </Card>

        <Box display="flex" justifyContent="flex-end" gap={1}>
          <Button onClick={onClose} disabled={saving}>{t('app.cancel')}</Button>
          <Button variant="contained" onClick={handleSave} disabled={saving || !form.name}>
            {saving ? t('app.loading') : t('app.save')}
          </Button>
        </Box>
      </Stack>
    </Box>
  )
}

