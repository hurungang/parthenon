import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
    CircularProgress,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
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
import type {
  AgentRole,
  AgentType,
  Skill,
  SopDetail,
  SopStep,
  SopStepType,
  SopWorkflowGenerateResponse,
  SopWorkflowPreviewResponse,
} from '../../types'

interface SopEditorProps {
  open: boolean
  sop: SopDetail | null
  mode?: 'create' | 'edit' | 'view'
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

export function SopEditor({ open, sop, mode = 'create', onClose, onSaved }: SopEditorProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const isViewMode = mode === 'view'

  const [form, setForm] = useState({ name: '', description: '', instructions: '', is_active: true })
  const [steps, setSteps] = useState<StepDraft[]>([])
  const [selectedRoleIds, setSelectedRoleIds] = useState<string[]>([])
  const [editorError, setEditorError] = useState<unknown>(null)
  const [saving, setSaving] = useState(false)
  const [working, setWorking] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewContent, setPreviewContent] = useState('')
  const [previewModelId, setPreviewModelId] = useState<string | null>(null)

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

  const nameError = form.name
    ? !/^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$/.test(form.name)
      ? t('sops.editor.nameInvalid')
      : null
    : null

  const handleSave = async () => {
    if (isViewMode) return
    if (nameError) return
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

  const stepsForWorkflow = steps.map((s, i) => ({
    order: i,
    step_type: s.step_type,
    skill_id: s.skill_id || null,
    target_agent_type_id: s.target_agent_type_id || null,
    name: s.name || null,
    description: s.description || null,
  }))

  const handleGenerateWorkflow = async () => {
    try {
      setGenerating(true)
      setEditorError(null)
      const { data } = await apiClient.post<SopWorkflowGenerateResponse>('/sops/workflow/generate', {
        description: form.description,
        steps: stepsForWorkflow,
      })
      setForm((f) => ({ ...f, instructions: data.workflow }))
    } catch (err) {
      setEditorError(err)
    } finally {
      setGenerating(false)
    }
  }

  const handlePreviewWorkflow = async () => {
    try {
      setWorking(true)
      setEditorError(null)
      const { data } = await apiClient.post<SopWorkflowPreviewResponse>('/sops/workflow/preview', {
        workflow: form.instructions,
        description: form.description,
        steps: stepsForWorkflow,
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

  return (
    <>
      <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth>
        <DialogTitle>
          <Box display="flex" justifyContent="space-between" alignItems="center">
            <Typography variant="h6">
              {mode === 'view' ? t('sops.viewSop') : sop ? t('sops.editSop') : t('sops.createSop')}
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
                    helperText={nameError ?? t('sops.editor.nameHint')}
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
                    label={t('sops.workflow')}
                    value={form.instructions}
                    onChange={(e) => setForm((f) => ({ ...f, instructions: e.target.value }))}
                    disabled={isViewMode}
                    fullWidth
                    multiline
                    rows={8}
                    size="small"
                    helperText={t('sops.workflowHint')}
                  />
                  <Stack direction="row" spacing={1}>
                    <Button
                      variant="outlined"
                      onClick={() => void handleGenerateWorkflow()}
                      disabled={generating || working}
                      startIcon={generating ? <CircularProgress size={16} color="inherit" /> : undefined}
                    >
                      {generating ? t('app.loading') : t('sops.editor.generateWorkflow')}
                    </Button>
                    <Button variant="outlined" onClick={() => void handlePreviewWorkflow()} disabled={working}>
                      {t('sops.editor.previewWorkflow')}
                    </Button>
                  </Stack>
                </Stack>
              </CardContent>
            </Card>

        {/* Steps */}
        <Card variant="outlined">
          <CardContent>
            <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
              <Typography variant="subtitle2">{t('sops.editor.steps')}</Typography>
              <Button size="small" startIcon={<AddIcon />} onClick={addStep} disabled={isViewMode}>
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
                      <IconButton size="small" onClick={() => moveStep(step.localId, -1)} disabled={isViewMode || idx === 0}>
                        <ArrowUpwardIcon fontSize="small" />
                      </IconButton>
                      <IconButton size="small" onClick={() => moveStep(step.localId, 1)} disabled={isViewMode || idx === steps.length - 1}>
                        <ArrowDownwardIcon fontSize="small" />
                      </IconButton>
                    </Box>
                    <Box flex={1}>
                      <Stack spacing={1}>
                        <FormControl size="small" fullWidth>
                          <InputLabel>{t('sops.editor.stepType')}</InputLabel>
                          <Select
                            value={step.step_type}
                            disabled={isViewMode}
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
                              disabled={isViewMode}
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
                              disabled={isViewMode}
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
                          disabled={isViewMode}
                          size="small"
                          fullWidth
                        />
                      </Stack>
                    </Box>
                    <IconButton size="small" color="error" onClick={() => removeStep(step.localId)} disabled={isViewMode}>
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
                  disabled={isViewMode}
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
      </Dialog>

      <Dialog open={previewOpen} onClose={() => setPreviewOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>{t('sops.editor.workflowPreviewTitle', { model: previewModelId ?? '-' })}</DialogTitle>
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
    </>
  )
}

