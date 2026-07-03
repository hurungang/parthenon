import { useState } from 'react'
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  FormControl,
  FormHelperText,
  IconButton,
  InputAdornment,
  InputLabel,
  MenuItem,
  Select,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward'
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward'
import CloseIcon from '@mui/icons-material/Close'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import type { AgentDataType, AgentIdentity, AgentInputType, AgentOutputType, AgentRole, ModelConfig, Skill, Sop, SopBindingInput, SkillBindingInput } from '../../types'
import { JsonSchemaBuilder } from '../../components/JsonSchemaBuilder'

const SLUG_PATTERN = /^[a-z0-9-]+$/

export interface AgentTypeFormValues {
  name: string
  description: string
  identity_id: string
  role_id: string
  model_id: string
  system_instruction: string
  input_type: AgentInputType
  input_schema: string
  output_type: AgentOutputType
  output_schema: string
  output_data_type_id: string
  sop_bindings: SopBindingInput[]
  skill_bindings: SkillBindingInput[]
  guardrail_max_iterations: number
  guardrail_max_delegation_depth: number
  guardrail_max_delegated_steps: number
  guardrail_execution_timeout_seconds: number
  guardrail_token_budget: string
  guardrail_token_enforcement_mode: 'observe' | 'enforce'
  guardrail_token_fallback_mode: 'observe_and_log' | 'stop_on_next_hard_guardrail'
  guardrail_conversational_token_visibility_mode: 'enabled' | 'disabled'
  guardrail_conversational_continuation_policy: 'allow'
}

export const defaultAgentTypeFormValues: AgentTypeFormValues = {
  name: '',
  description: '',
  identity_id: '',
  role_id: '',
  model_id: '',
  system_instruction: '',
  input_type: 'none',
  input_schema: '',
  output_type: 'auto',
  output_schema: '',
  output_data_type_id: '',
  sop_bindings: [],
  skill_bindings: [],
  guardrail_max_iterations: 10,
  guardrail_max_delegation_depth: 3,
  guardrail_max_delegated_steps: 20,
  guardrail_execution_timeout_seconds: 300,
  guardrail_token_budget: '1000',
  guardrail_token_enforcement_mode: 'observe',
  guardrail_token_fallback_mode: 'observe_and_log',
  guardrail_conversational_token_visibility_mode: 'enabled',
  guardrail_conversational_continuation_policy: 'allow',
}

interface AgentTypeFormProps {
  values: AgentTypeFormValues
  onChange: (values: AgentTypeFormValues) => void
}

/**
 * Reusable form for creating / editing an AgentType.
 * Covers all fields in the rearchitected AgentType schema.
 * Identity is selected first; the role dropdown is then filtered by the
 * identity's type via GET /agents/roles?allowed_for_identity_type=<type>.
 */
export function AgentTypeForm({ values, onChange }: AgentTypeFormProps) {
  const { t } = useTranslation()
  const invalidAgentName = !!values.name && !SLUG_PATTERN.test(values.name)

  const set = <K extends keyof AgentTypeFormValues>(key: K, value: AgentTypeFormValues[K]) =>
    onChange({ ...values, [key]: value })

  const { data: identities } = useQuery<AgentIdentity[]>({
    queryKey: ['agents', 'identities'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentIdentity[]>('/agents/identities')
      return data
    },
  })

  const { data: roles } = useQuery<AgentRole[]>({
    queryKey: ['agents', 'roles'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentRole[]>('/agents/roles')
      return data
    },
  })

  // Fetch roles assigned to the selected identity for validation
  const { data: identityRoles } = useQuery<AgentRole[]>({
    queryKey: ['agents', 'identities', values.identity_id, 'roles'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentRole[]>(`/agents/identities/${values.identity_id}/roles`)
      return data
    },
    enabled: !!values.identity_id,
  })

  // Warn if the selected role is not assigned to the selected identity
  const selectedRoleIsAssigned =
    !values.identity_id ||
    !values.role_id ||
    (identityRoles ?? []).some((r) => r.id === values.role_id)

  const { data: modelConfigs } = useQuery<ModelConfig[]>({
    queryKey: ['agents', 'model-configs'],
    queryFn: async () => {
      const { data } = await apiClient.get<ModelConfig[]>('/agents/model-configs')
      return data
    },
  })

  const { data: sops } = useQuery<Sop[]>({
    queryKey: ['sops'],
    queryFn: async () => {
      const { data } = await apiClient.get<Sop[]>('/sops')
      return data
    },
  })

  const { data: skills } = useQuery<Skill[]>({
    queryKey: ['skills'],
    queryFn: async () => {
      const { data } = await apiClient.get<Skill[]>('/skills')
      return data
    },
  })

  const { data: dataTypes } = useQuery<AgentDataType[]>({
    queryKey: ['data-types', 'list'],
    queryFn: async () => {
      const { data } = await apiClient.get<{ items: AgentDataType[] }>('/data-types?page_size=100')
      return data.items
    },
  })

  // Build a flat list of { modelId, label } from all configs' enabled_models
  const flatModels: { modelId: string; label: string }[] = (modelConfigs ?? []).flatMap((mc) =>
    (mc.enabled_models ?? []).map((m) => ({
      modelId: m,
      label: `${m} (${mc.display_name})`,
    }))
  )

  const selectedRole = (roles ?? []).find((r) => r.id === values.role_id)
  const roleSops = (sops ?? []).filter((s) => (selectedRole?.sop_ids ?? []).includes(s.id))
  const roleSkills = (skills ?? []).filter((s) => (selectedRole?.skill_ids ?? []).includes(s.id))
  const isConversation = values.input_type === 'conversation'

  // Detect orphaned bindings — bound SOPs/Skills no longer in the selected role
  const roleSopIdSet = new Set(selectedRole?.sop_ids ?? [])
  const roleSkillIdSet = new Set(selectedRole?.skill_ids ?? [])
  const orphanSops = values.sop_bindings.filter((b) => !roleSopIdSet.has(b.sop_id))
  const orphanSkills = values.skill_bindings.filter((b) => !roleSkillIdSet.has(b.skill_id))
  const hasOrphans = orphanSops.length > 0 || orphanSkills.length > 0
  const orphanSopNames = orphanSops
    .map((b) => (sops ?? []).find((s) => s.id === b.sop_id)?.name ?? b.sop_id)
    .join(', ')
  const orphanSkillNames = orphanSkills
    .map((b) => (skills ?? []).find((s) => s.id === b.skill_id)?.name ?? b.skill_id)
    .join(', ')

  const handleRemoveOrphans = () => {
    const validSops = values.sop_bindings.filter((b) => roleSopIdSet.has(b.sop_id))
    const validSkills = values.skill_bindings.filter((b) => roleSkillIdSet.has(b.skill_id))
    onChange({ ...values, sop_bindings: validSops, skill_bindings: validSkills })
  }

  // ── Binding management helpers ─────────────────────────────────────────
  const [showAddBinding, setShowAddBinding] = useState(false)
  const [addBindingType, setAddBindingType] = useState<'sop' | 'skill'>('sop')
  const [addBindingId, setAddBindingId] = useState('')

  const boundSopIds = new Set(values.sop_bindings.map((b) => b.sop_id))
  const boundSkillIds = new Set(values.skill_bindings.map((b) => b.skill_id))

  const handleAddBinding = () => {
    if (!addBindingId) return
    if (addBindingType === 'sop') {
      const maxOrder = values.sop_bindings.reduce((max, b) => Math.max(max, b.order), 0)
      onChange({
        ...values,
        sop_bindings: [...values.sop_bindings, { sop_id: addBindingId, order: maxOrder + 1 }],
      })
    } else {
      const maxOrder = values.skill_bindings.reduce((max, b) => Math.max(max, b.order), 0)
      onChange({
        ...values,
        skill_bindings: [...values.skill_bindings, { skill_id: addBindingId, order: maxOrder + 1 }],
      })
    }
    setAddBindingId('')
    setShowAddBinding(false)
  }

  const handleRemoveBinding = (type: 'sop' | 'skill', index: number) => {
    if (type === 'sop') {
      const updated = values.sop_bindings.filter((_, i) => i !== index)
      onChange({ ...values, sop_bindings: updated })
    } else {
      const updated = values.skill_bindings.filter((_, i) => i !== index)
      onChange({ ...values, skill_bindings: updated })
    }
  }

  const handleMoveBinding = (type: 'sop' | 'skill', index: number, direction: 'up' | 'down') => {
    if (type === 'sop') {
      const list = [...values.sop_bindings]
      const targetIndex = direction === 'up' ? index - 1 : index + 1
      if (targetIndex < 0 || targetIndex >= list.length) return
      const tempOrder = list[index].order
      list[index] = { ...list[index], order: list[targetIndex].order }
      list[targetIndex] = { ...list[targetIndex], order: tempOrder }
      onChange({ ...values, sop_bindings: list })
    } else {
      const list = [...values.skill_bindings]
      const targetIndex = direction === 'up' ? index - 1 : index + 1
      if (targetIndex < 0 || targetIndex >= list.length) return
      const tempOrder = list[index].order
      list[index] = { ...list[index], order: list[targetIndex].order }
      list[targetIndex] = { ...list[targetIndex], order: tempOrder }
      onChange({ ...values, skill_bindings: list })
    }
  }

  const tokenBudgetHelperText = isConversation
    ? t('agents.types.guardrails.tokenBudgetConversationHint', {
        value: '1000',
        defaultValue: 'Visible current-session usage threshold. Default: {{value}}k tokens.',
      })
    : t('agents.types.guardrails.tokenBudgetNonConversationHint', {
        value: '1000',
        defaultValue: 'Budget for non-conversational enforcement. Default: {{value}}k tokens.',
      })

  // When identity changes: keep role if still valid, just update identity_id
  const handleIdentityChange = (newIdentityId: string) => {
    onChange({ ...values, identity_id: newIdentityId })
  }

  return (
    <Box display="flex" flexDirection="column" gap={2}>
      <TextField
        label={t('app.name')}
        value={values.name}
        onChange={(e) => set('name', e.target.value)}
        fullWidth
        required
        error={invalidAgentName}
        helperText={invalidAgentName ? t('agents.types.slugNameHelper') : t('agents.types.slugNameHint')}
      />
      <TextField
        label={t('app.description')}
        value={values.description}
        onChange={(e) => set('description', e.target.value)}
        fullWidth
        multiline
        rows={2}
      />

      {/* Identity selector */}
      <FormControl fullWidth>
        <InputLabel>{t('agents.types.identity')}</InputLabel>
        <Select
          value={values.identity_id}
          label={t('agents.types.identity')}
          onChange={(e) => handleIdentityChange(e.target.value)}
        >
          <MenuItem value=""><em>{t('agents.types.noIdentity')}</em></MenuItem>
          {(identities ?? []).map((i) => (
            <MenuItem key={i.id} value={i.id}>{i.name}</MenuItem>
          ))}
        </Select>
      </FormControl>

      <FormControl fullWidth error={!selectedRoleIsAssigned}>
        <InputLabel>{t('agents.types.role')}</InputLabel>
        <Select
          value={values.role_id}
          label={t('agents.types.role')}
          onChange={(e) => set('role_id', e.target.value)}
        >
          <MenuItem value=""><em>{t('agents.types.noRole')}</em></MenuItem>
          {(roles ?? []).map((r) => (
            <MenuItem key={r.id} value={r.id}>{r.name}</MenuItem>
          ))}
        </Select>
        {!selectedRoleIsAssigned && (
          <FormHelperText>{t('agents.types.roleNotAssignedToIdentity')}</FormHelperText>
        )}
      </FormControl>

      <FormControl fullWidth>
        <InputLabel>{t('agents.types.modelId')}</InputLabel>
        <Select
          value={values.model_id}
          label={t('agents.types.modelId')}
          onChange={(e) => set('model_id', e.target.value)}
        >
          <MenuItem value=""><em>{t('agents.types.noModel')}</em></MenuItem>
          {flatModels.map((m) => (
            <MenuItem key={m.modelId} value={m.modelId}>{m.label}</MenuItem>
          ))}
        </Select>
      </FormControl>

      {/* ── Workflow Configuration ────────────────────────────────────── */}
      <Divider sx={{ my: 1 }} />
      <Typography variant="subtitle1" fontWeight={600}>
        {t('agents.types.workflowConfig')}
      </Typography>

      <TextField
        label={t('agents.types.systemInstruction')}
        value={values.system_instruction}
        onChange={(e) => set('system_instruction', e.target.value)}
        fullWidth
        multiline
        rows={3}
      />

      {/* ── SOP / Skill Bindings Section ──────────────────────────────── */}
      <Box>
        <Typography variant="subtitle1" fontWeight={600} gutterBottom>
          {t('agents.types.bindings.title')}
        </Typography>
        <Typography variant="body2" color="text.secondary" mb={1}>
          {t('agents.types.bindings.sectionHint')}
        </Typography>

        {values.sop_bindings.length === 0 && values.skill_bindings.length === 0 && (
          <Typography variant="body2" color="error" sx={{ fontStyle: 'italic', mb: 1 }}>
            {t('agents.types.bindings.validationRequired')}
          </Typography>
        )}

        {hasOrphans && (
          <Alert severity="warning" sx={{ mb: 1.5 }} action={
            <Button size="small" color="inherit" onClick={handleRemoveOrphans}>
              {t('agents.types.bindings.removeOrphans')}
            </Button>
          }>
            <Typography variant="body2">
              {t('agents.types.bindings.orphanWarning')}
            </Typography>
            {orphanSopNames && (
              <Typography variant="body2" component="div" sx={{ mt: 0.5 }}>
                <strong>SOP:</strong> {orphanSopNames}
              </Typography>
            )}
            {orphanSkillNames && (
              <Typography variant="body2" component="div">
                <strong>{t('agents.types.bindings.typeSkill')}:</strong> {orphanSkillNames}
              </Typography>
            )}
          </Alert>
        )}

        {/* Render sorted merged bindings */}
        {[...values.sop_bindings.map((b) => ({ ...b, type: 'sop' as const })),
          ...values.skill_bindings.map((b) => ({ ...b, type: 'skill' as const }))]
          .sort((a, b) => a.order - b.order)
          .map((binding) => {
            const isSop = binding.type === 'sop'
            const item = isSop
              ? (sops ?? []).find((s) => s.id === (binding as typeof binding & { sop_id: string }).sop_id)
              : (skills ?? []).find((s) => s.id === (binding as typeof binding & { skill_id: string }).skill_id)
            const listIndex = isSop
              ? values.sop_bindings.findIndex((b) => b.sop_id === (binding as typeof binding & { sop_id: string }).sop_id)
              : values.skill_bindings.findIndex((b) => b.skill_id === (binding as typeof binding & { skill_id: string }).skill_id)
            const list = isSop ? values.sop_bindings : values.skill_bindings
            const isFirst = listIndex === 0
            const isLast = listIndex === list.length - 1
            const isOrphan = isSop
              ? !roleSopIdSet.has((binding as typeof binding & { sop_id: string }).sop_id)
              : !roleSkillIdSet.has((binding as typeof binding & { skill_id: string }).skill_id)
            return (
              <Box key={`${isSop ? 'sop' : 'skill'}-${isSop ? (binding as typeof binding & { sop_id: string }).sop_id : (binding as typeof binding & { skill_id: string }).skill_id}`}
                display="flex" alignItems="center" gap={1} mb={0.5}
                sx={isOrphan ? { border: 1, borderColor: 'warning.main', borderRadius: 1, p: 0.5, bgcolor: 'warning.50' } : undefined}>
                <Typography variant="body2" color="text.secondary" sx={{ minWidth: 28 }}>
                  #{binding.order}
                </Typography>
                <Chip
                  label={isSop ? t('agents.types.bindings.typeSop') : t('agents.types.bindings.typeSkill')}
                  color={isSop ? 'primary' : 'secondary'}
                  size="small"
                  variant="outlined"
                />
                <Typography variant="body2" sx={{ flex: 1 }}>
                  {item?.name ?? t('agents.types.bindings.brokenReference')}
                </Typography>
                <IconButton
                  size="small"
                  onClick={() => handleMoveBinding(isSop ? 'sop' : 'skill', listIndex, 'up')}
                  disabled={isFirst}
                  aria-label={t('agents.types.bindings.moveUp')}
                >
                  <ArrowUpwardIcon fontSize="small" />
                </IconButton>
                <IconButton
                  size="small"
                  onClick={() => handleMoveBinding(isSop ? 'sop' : 'skill', listIndex, 'down')}
                  disabled={isLast}
                  aria-label={t('agents.types.bindings.moveDown')}
                >
                  <ArrowDownwardIcon fontSize="small" />
                </IconButton>
                <IconButton
                  size="small"
                  color="error"
                  onClick={() => handleRemoveBinding(isSop ? 'sop' : 'skill', listIndex)}
                  aria-label={t('agents.types.bindings.remove')}
                >
                  <CloseIcon fontSize="small" />
                </IconButton>
              </Box>
            )
          })}

        {showAddBinding ? (
          <Box display="flex" alignItems="center" gap={1} mt={1}>
            <ToggleButtonGroup
              value={addBindingType}
              exclusive
              onChange={(_, v) => { if (v) { setAddBindingType(v); setAddBindingId('') } }}
              size="small"
            >
              <ToggleButton value="sop">{t('agents.types.bindings.typeSop')}</ToggleButton>
              <ToggleButton value="skill">{t('agents.types.bindings.typeSkill')}</ToggleButton>
            </ToggleButtonGroup>
            <FormControl size="small" sx={{ minWidth: 200 }}>
              <Select
                value={addBindingId}
                displayEmpty
                onChange={(e) => setAddBindingId(e.target.value)}
              >
                <MenuItem value="" disabled>
                  <em>{t('agents.types.bindings.selectPlaceholder')}</em>
                </MenuItem>
                {addBindingType === 'sop'
                  ? roleSops
                      .filter((s) => !boundSopIds.has(s.id))
                      .map((s) => (
                        <MenuItem key={s.id} value={s.id}>{s.name}</MenuItem>
                      ))
                  : roleSkills
                      .filter((s) => !boundSkillIds.has(s.id))
                      .map((s) => (
                        <MenuItem key={s.id} value={s.id}>{s.name}</MenuItem>
                      ))
                }
              </Select>
            </FormControl>
            <Button
              size="small"
              variant="contained"
              onClick={handleAddBinding}
              disabled={!addBindingId}
            >
              {t('app.add')}
            </Button>
            <Button
              size="small"
              onClick={() => { setShowAddBinding(false); setAddBindingId('') }}
            >
              {t('app.cancel')}
            </Button>
          </Box>
        ) : (
          <Box mt={1}>
            <Button
              size="small"
              startIcon={<AddIcon />}
              onClick={() => setShowAddBinding(true)}
              disabled={!values.role_id}
            >
              {t('agents.types.bindings.addBinding')}
            </Button>
          </Box>
        )}
      </Box>

      {/* ── Input / Output ────────────────────────────────────────────── */}
      <Divider sx={{ my: 1 }} />
      <Typography variant="subtitle1" fontWeight={600}>
        {t('agents.types.inputOutput')}
      </Typography>

      <FormControl fullWidth>
        <InputLabel>{t('agents.types.inputType')}</InputLabel>
        <Select
          value={values.input_type}
          label={t('agents.types.inputType')}
          onChange={(e) => {
            const newType = e.target.value as AgentInputType
            onChange({ ...values, input_type: newType })
          }}
        >
          <MenuItem value="none">{t('agents.types.inputNone')}</MenuItem>
          <MenuItem value="typed">{t('agents.types.inputTyped')}</MenuItem>
          <MenuItem value="conversation">{t('agents.types.inputConversation')}</MenuItem>
        </Select>
      </FormControl>

      {values.input_type === 'typed' && (
        <JsonSchemaBuilder
          value={values.input_schema}
          onChange={(schema) => set('input_schema', schema)}
          label={t('agents.types.inputSchema')}
          helperText={t('agents.types.schemaBuilder.inputSchemaHelper')}
        />
      )}

      {values.input_type !== 'conversation' && (
        <>
          <FormControl fullWidth>
            <InputLabel>{t('agents.types.outputType')}</InputLabel>
            <Select
              value={values.output_type}
              label={t('agents.types.outputType')}
              onChange={(e) => {
                const newType = e.target.value as AgentOutputType
                const updated = { ...values, output_type: newType }
                if (newType !== 'typed') {
                  updated.output_data_type_id = ''
                }
                onChange(updated)
              }}
            >
              <MenuItem value="typed">{t('agents.types.outputTyped')}</MenuItem>
              <MenuItem value="auto">{t('agents.types.outputAuto', { defaultValue: 'Auto' })}</MenuItem>
            </Select>
          </FormControl>

          {values.output_type === 'typed' && (
            <FormControl fullWidth>
              <InputLabel>{t('agents.types.outputDataType')}</InputLabel>
              <Select
                value={dataTypes !== undefined ? values.output_data_type_id : ''}
                label={t('agents.types.outputDataType')}
                onChange={(e) => set('output_data_type_id', e.target.value)}
              >
                <MenuItem value="">
                  <em>{t('agents.types.noOutputDataType')}</em>
                </MenuItem>
                {(dataTypes ?? []).map((dt) => (
                  <MenuItem key={dt.id} value={dt.id}>
                    {dt.name}
                  </MenuItem>
                ))}
              </Select>
              <FormHelperText>{t('agents.types.outputDataTypeHint')}</FormHelperText>
            </FormControl>
          )}
        </>
      )}

      <Accordion variant="outlined" defaultExpanded={false}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Box>
            <Typography variant="subtitle1" fontWeight={600}>
              {t('agents.types.guardrails.title')}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {t('agents.types.guardrails.sectionHint')}
            </Typography>
          </Box>
        </AccordionSummary>
        <AccordionDetails>
          <Box display="flex" flexDirection="column" gap={2}>
            <Box display="grid" gridTemplateColumns={{ xs: '1fr', md: '1fr 1fr' }} gap={2}>
              <TextField
                type="number"
                label={t('agents.types.guardrails.maxIterations')}
                value={values.guardrail_max_iterations}
                onChange={(e) => set('guardrail_max_iterations', Number(e.target.value || 0))}
                inputProps={{ min: 1, max: 1000 }}
                fullWidth
              />
              <TextField
                type="number"
                label={t('agents.types.guardrails.timeoutSeconds')}
                value={values.guardrail_execution_timeout_seconds}
                onChange={(e) => set('guardrail_execution_timeout_seconds', Number(e.target.value || 0))}
                inputProps={{ min: 1, max: 86400 }}
                fullWidth
              />
              <TextField
                type="number"
                label={t('agents.types.guardrails.maxDelegationDepth')}
                value={values.guardrail_max_delegation_depth}
                onChange={(e) => set('guardrail_max_delegation_depth', Number(e.target.value || 0))}
                inputProps={{ min: 0, max: 32 }}
                fullWidth
              />
              <TextField
                type="number"
                label={t('agents.types.guardrails.maxDelegatedSteps')}
                value={values.guardrail_max_delegated_steps}
                onChange={(e) => set('guardrail_max_delegated_steps', Number(e.target.value || 0))}
                inputProps={{ min: 0, max: 5000 }}
                fullWidth
              />
            </Box>

            <Divider />

            <Box>
              <Typography variant="subtitle2" gutterBottom>
                {isConversation
                  ? t('agents.types.guardrails.conversationalSectionTitle')
                  : t('agents.types.guardrails.nonConversationalSectionTitle')}
              </Typography>
              <Box display="grid" gridTemplateColumns={{ xs: '1fr', md: '1fr 1fr' }} gap={2}>
                <TextField
                  type="number"
                  label={t('agents.types.guardrails.tokenBudget')}
                  value={values.guardrail_token_budget}
                  onChange={(e) => set('guardrail_token_budget', e.target.value)}
                  inputProps={{ min: 1 }}
                  InputProps={{
                    endAdornment: <InputAdornment position="end">{t('agents.types.guardrails.tokenBudgetUnit')}</InputAdornment>,
                  }}
                  fullWidth
                  helperText={tokenBudgetHelperText}
                />

                {!isConversation ? (
                  <>
                    <FormControl fullWidth>
                      <InputLabel>{t('agents.types.guardrails.tokenEnforcementMode')}</InputLabel>
                      <Select
                        value={values.guardrail_token_enforcement_mode}
                        label={t('agents.types.guardrails.tokenEnforcementMode')}
                        onChange={(e) => set('guardrail_token_enforcement_mode', e.target.value as 'observe' | 'enforce')}
                      >
                        <MenuItem value="observe">{t('agents.types.guardrails.observeMode')}</MenuItem>
                        <MenuItem value="enforce">{t('agents.types.guardrails.enforceMode')}</MenuItem>
                      </Select>
                    </FormControl>
                    <FormControl fullWidth>
                      <InputLabel>{t('agents.types.guardrails.tokenFallbackMode')}</InputLabel>
                      <Select
                        value={values.guardrail_token_fallback_mode}
                        label={t('agents.types.guardrails.tokenFallbackMode')}
                        onChange={(e) => set('guardrail_token_fallback_mode', e.target.value as 'observe_and_log' | 'stop_on_next_hard_guardrail')}
                      >
                        <MenuItem value="observe_and_log">{t('agents.types.guardrails.observeAndLog')}</MenuItem>
                        <MenuItem value="stop_on_next_hard_guardrail">{t('agents.types.guardrails.stopOnNextHardGuardrail')}</MenuItem>
                      </Select>
                    </FormControl>
                  </>
                ) : (
                  <>
                    <FormControl fullWidth>
                      <InputLabel>{t('agents.types.guardrails.conversationalVisibilityMode')}</InputLabel>
                      <Select
                        value={values.guardrail_conversational_token_visibility_mode}
                        label={t('agents.types.guardrails.conversationalVisibilityMode')}
                        onChange={(e) => set('guardrail_conversational_token_visibility_mode', e.target.value as 'enabled' | 'disabled')}
                      >
                        <MenuItem value="enabled">{t('agents.types.guardrails.visibilityEnabled')}</MenuItem>
                        <MenuItem value="disabled">{t('agents.types.guardrails.visibilityDisabled')}</MenuItem>
                      </Select>
                    </FormControl>
                    <FormControl fullWidth>
                      <InputLabel>{t('agents.types.guardrails.conversationalContinuationPolicy')}</InputLabel>
                      <Select
                        value={values.guardrail_conversational_continuation_policy}
                        label={t('agents.types.guardrails.conversationalContinuationPolicy')}
                        onChange={(e) => set('guardrail_conversational_continuation_policy', e.target.value as 'allow')}
                      >
                        <MenuItem value="allow">{t('agents.types.guardrails.continueAllowed')}</MenuItem>
                      </Select>
                    </FormControl>
                  </>
                )}
              </Box>
            </Box>
          </Box>
        </AccordionDetails>
      </Accordion>
    </Box>
  )
}

