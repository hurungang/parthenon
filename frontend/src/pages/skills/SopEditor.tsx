import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  FormControl,
  FormControlLabel,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward'
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import { useSopRoles } from '../../hooks/useSops'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import type { AgentRole, AgentType, Skill, SopDetail, SopStep, SopStepType } from '../../types'

interface SopEditorProps {
  sop: SopDetail | null
  onClose: () => void
  onSaved: () => void
}

interface StepDraft {
  localId: string
  order: number
  step_type: SopStepType
  skill_id: string | null
  target_agent_type_id: string | null
  name: string
  description: string
}

let _draftCounter = 0
const newDraftId = () => `draft-${++_draftCounter}`

const stepFromExisting = (step: SopStep): StepDraft => ({
  localId: newDraftId(),
  order: step.order,
  step_type: step.step_type,
  skill_id: step.skill_id,
  target_agent_type_id: step.target_agent_type_id,
  name: step.name ?? '',
  description: step.description ?? '',
})

export function SopEditor({ sop, onClose, onSaved }: SopEditorProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const [form, setForm] = useState({ name: '', description: '', instructions: '', is_active: true })
  const [steps, setSteps] = useState<StepDraft[]>([])
  const [selectedRoleIds, setSelectedRoleIds] = useState<string[]>([])
  const [editorError, setEditorError] = useState<unknown>(null)
  const [saving, setSaving] = useState(false)

  const { data: currentRoleIds } = useSopRoles(sop?.id ?? '')

  const { data: allSkills } = useQuery<Skill[]>({
    queryKey: ['skills'],
    queryFn: async () => {
      const { data } = await apiClient.get<Skill[]>('/skills')
      return data
    },
  })

  const { data: allAgentTypes } = useQuery<AgentType[]>({
    queryKey: ['agents', 'types'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentType[]>('/agents/types')
      return data
    },
  })

  const { data: allRoles } = useQuery<AgentRole[]>({
    queryKey: ['agents', 'roles'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentRole[]>('/agents/roles')
      return data
    },
  })

  useEffect(() => {
    if (sop) {
      setForm({
        name: sop.name,
        description: sop.description ?? '',
        instructions: sop.instructions ?? '',
        is_active: sop.is_active,
      })
      setSteps((sop.steps ?? []).map(stepFromExisting))
    } else {
      setForm({ name: '', description: '', instructions: '', is_active: true })
      setSteps([])
    }
    setEditorError(null)
  }, [sop])

  useEffect(() => {
    if (currentRoleIds) setSelectedRoleIds(currentRoleIds)
  }, [currentRoleIds])

  const addStep = () => {
    setSteps((prev) => [
      ...prev,
      {
        localId: newDraftId(),
        order: prev.length,
        step_type: 'skill_invocation',
        skill_id: null,
        target_agent_type_id: null,
        name: '',
        description: '',
      },
    ])
  }

  const removeStep = (localId: string) => {
    setSteps((prev) => prev.filter((s) => s.localId !== localId).map((s, i) => ({ ...s, order: i })))
  }

  const moveStep = (localId: string, dir: -1 | 1) => {
    setSteps((prev) => {
      const idx = prev.findIndex((s) => s.localId === localId)
      if (idx + dir < 0 || idx + dir >= prev.length) return prev
      const next = [...prev]
      ;[next[idx], next[idx + dir]] = [next[idx + dir], next[idx]]
      return next.map((s, i) => ({ ...s, order: i }))
    })
  }

  const updateStep = (localId: string, patch: Partial<StepDraft>) => {
    setSteps((prev) => prev.map((s) => (s.localId === localId ? { ...s, ...patch } : s)))
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
      const sopPayload = {
        name: form.name,
        description: form.description || null,
        instructions: form.instructions || null,
        is_active: form.is_active,
      }
      let sopId: string
      if (sop) {
        await apiClient.put(`/sops/${sop.id}`, sopPayload)
        sopId = sop.id
      } else {
        const { data } = await apiClient.post<SopDetail>('/sops', sopPayload)
        sopId = data.id
      }
      // Replace steps
      const stepsPayload = steps.map((s, i) => ({
        order: i,
        step_type: s.step_type,
        skill_id: s.skill_id || null,
        target_agent_type_id: s.target_agent_type_id || null,
        name: s.name || null,
        description: s.description || null,
      }))
      await apiClient.put(`/sops/${sopId}/steps`, stepsPayload)
      // Save role assignments
      await apiClient.put(`/sops/${sopId}/roles`, { role_ids: selectedRoleIds })
      await queryClient.invalidateQueries({ queryKey: ['sops'] })
      onSaved()
    } catch (err) {
      setEditorError(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Box sx={{ borderLeft: 1, borderColor: 'divider', pl: 3, minWidth: 520 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h6">
          {sop ? t('sops.editSop') : t('sops.createSop')}
        </Typography>
        <IconButton size="small" onClick={onClose}><CloseIcon /></IconButton>
      </Box>

      {editorError != null && <PermissionDeniedAlert error={editorError} fallbackMessage={t('app.error')} />}

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
                label={t('sops.instructions')}
                value={form.instructions}
                onChange={(e) => setForm((f) => ({ ...f, instructions: e.target.value }))}
                fullWidth
                multiline
                rows={4}
                size="small"
                helperText={t('sops.instructionsHint')}
              />
            </Stack>
          </CardContent>
        </Card>

        {/* Steps */}
        <Card variant="outlined">
          <CardContent>
            <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
              <Typography variant="subtitle2">{t('sops.editor.steps')}</Typography>
              <Button size="small" startIcon={<AddIcon />} onClick={addStep}>
                {t('sops.editor.addStep')}
              </Button>
            </Box>
            <Stack spacing={1}>
              {steps.map((step, idx) => (
                <Card key={step.localId} variant="outlined" sx={{ p: 1 }}>
                  <Box display="flex" alignItems="flex-start" gap={1}>
                    <Box display="flex" flexDirection="column" alignItems="center">
                      <Typography variant="caption" color="text.secondary" fontWeight={600}>
                        {idx + 1}
                      </Typography>
                      <IconButton size="small" onClick={() => moveStep(step.localId, -1)} disabled={idx === 0}>
                        <ArrowUpwardIcon fontSize="small" />
                      </IconButton>
                      <IconButton size="small" onClick={() => moveStep(step.localId, 1)} disabled={idx === steps.length - 1}>
                        <ArrowDownwardIcon fontSize="small" />
                      </IconButton>
                    </Box>
                    <Box flex={1}>
                      <Stack spacing={1}>
                        <FormControl size="small" fullWidth>
                          <InputLabel>{t('sops.editor.stepType')}</InputLabel>
                          <Select
                            value={step.step_type}
                            label={t('sops.editor.stepType')}
                            onChange={(e) =>
                              updateStep(step.localId, {
                                step_type: e.target.value as SopStepType,
                                skill_id: null,
                                target_agent_type_id: null,
                              })
                            }
                          >
                            <MenuItem value="skill_invocation">{t('sops.stepType.skillInvocation')}</MenuItem>
                            <MenuItem value="agent_delegation">{t('sops.stepType.agentDelegation')}</MenuItem>
                          </Select>
                        </FormControl>
                        {step.step_type === 'skill_invocation' && (
                          <FormControl size="small" fullWidth>
                            <InputLabel>{t('skills.title')}</InputLabel>
                            <Select
                              value={step.skill_id ?? ''}
                              label={t('skills.title')}
                              onChange={(e) => updateStep(step.localId, { skill_id: e.target.value || null })}
                            >
                              <MenuItem value="">{t('app.noData')}</MenuItem>
                              {(allSkills ?? []).map((s) => (
                                <MenuItem key={s.id} value={s.id}>{s.name}</MenuItem>
                              ))}
                            </Select>
                          </FormControl>
                        )}
                        {step.step_type === 'agent_delegation' && (
                          <FormControl size="small" fullWidth>
                            <InputLabel>{t('sops.editor.agentType')}</InputLabel>
                            <Select
                              value={step.target_agent_type_id ?? ''}
                              label={t('sops.editor.agentType')}
                              onChange={(e) => updateStep(step.localId, { target_agent_type_id: e.target.value || null })}
                            >
                              <MenuItem value="">{t('app.noData')}</MenuItem>
                              {(allAgentTypes ?? []).map((at) => (
                                <MenuItem key={at.id} value={at.id}>{at.name}</MenuItem>
                              ))}
                            </Select>
                          </FormControl>
                        )}
                        <TextField
                          label={t('app.name')}
                          value={step.name}
                          onChange={(e) => updateStep(step.localId, { name: e.target.value })}
                          size="small"
                          fullWidth
                        />
                      </Stack>
                    </Box>
                    <IconButton size="small" color="error" onClick={() => removeStep(step.localId)}>
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </Box>
                </Card>
              ))}
              {steps.length === 0 && (
                <Typography variant="caption" color="text.secondary">{t('app.noData')}</Typography>
              )}
            </Stack>
          </CardContent>
        </Card>

        {/* SOP Details */}
        <Card variant="outlined">
          <CardContent>
            <Typography variant="subtitle2" mb={1}>{t('app.status')}</Typography>
            <FormControlLabel
              control={
                <Switch
                  checked={form.is_active}
                  onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
                />
              }
              label={form.is_active ? t('app.active') : t('app.inactive')}
            />
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

