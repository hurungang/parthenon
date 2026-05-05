import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  TextField,
  Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import type { AgentRole, Skill, Sop } from '../../types'

interface AgentRoleDialogProps {
  open: boolean
  editRole: AgentRole | null
  onClose: () => void
  onSaved: () => Promise<void>
}

/**
 * Create / edit dialog for AgentRole.
 * Includes SOP multi-select, Skill multi-select, and a real-time MCP tool preview panel.
 */
export function AgentRoleDialog({ open, editRole, onClose, onSaved }: AgentRoleDialogProps) {
  const { t } = useTranslation()
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [selectedSopIds, setSelectedSopIds] = useState<string[]>([])
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([])
  const [previewTools, setPreviewTools] = useState<string[]>([])
  const [previewLoading, setPreviewLoading] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

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

  // Populate form when editing
  useEffect(() => {
    if (open) {
      setName(editRole?.name ?? '')
      setDescription(editRole?.description ?? '')
      setSelectedSopIds(editRole?.sop_ids ?? [])
      setSelectedSkillIds(editRole?.skill_ids ?? [])
      setPreviewTools([])
      setDialogError(null)
    }
  }, [open, editRole])

  // Fetch MCP tool preview when in edit mode and selection changes
  useEffect(() => {
    if (!editRole?.id) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      try {
        setPreviewLoading(true)
        const { data } = await apiClient.get<string[]>(
          `/agents/roles/${editRole.id}/mcp-tools`,
        )
        setPreviewTools(data)
      } catch {
        setPreviewTools([])
      } finally {
        setPreviewLoading(false)
      }
    }, 300)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [editRole?.id, selectedSopIds, selectedSkillIds])

  const toggleSop = (id: string) => {
    setSelectedSopIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  const toggleSkill = (id: string) => {
    setSelectedSkillIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  const handleSave = async () => {
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
    <Dialog
      open={open}
      onClose={() => { onClose(); setDialogError(null) }}
      maxWidth="md"
      fullWidth
    >
      <DialogTitle>
        {isEditing ? t('agents.roles.editTitle') : t('agents.roles.createTitle')}
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
          />
          <TextField
            label={t('app.description')}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            fullWidth
            multiline
            rows={2}
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
                    <FormControlLabel
                      key={skill.id}
                      control={
                        <Checkbox
                          size="small"
                          checked={selectedSkillIds.includes(skill.id)}
                          onChange={() => toggleSkill(skill.id)}
                        />
                      }
                      label={skill.name}
                      sx={{ display: 'flex', mx: 0 }}
                    />
                  ))
                )}
              </Box>
            </Box>
          </Box>

          <Divider />

          {/* MCP Tool Preview */}
          <Box>
            <Typography variant="subtitle2" mb={1}>{t('agents.roles.mcpToolPreview')}</Typography>
            {!isEditing ? (
              <Alert severity="info">{t('agents.roles.mcpToolPreviewHint')}</Alert>
            ) : previewLoading ? (
              <CircularProgress size={20} />
            ) : previewTools.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                {t('agents.roles.noMcpTools')}
              </Typography>
            ) : (
              <Box
                sx={{
                  border: 1,
                  borderColor: 'divider',
                  borderRadius: 1,
                  maxHeight: 140,
                  overflow: 'auto',
                  p: 1,
                }}
              >
                {previewTools.map((tool) => (
                  <Typography key={tool} variant="body2" sx={{ fontFamily: 'monospace', py: 0.25 }}>
                    {tool}
                  </Typography>
                ))}
              </Box>
            )}
          </Box>
        </Box>
      </DialogContent>

      <DialogActions>
        <Button onClick={() => { onClose(); setDialogError(null) }}>{t('app.cancel')}</Button>
        <Button variant="contained" onClick={handleSave} disabled={!name.trim()}>
          {t('app.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
