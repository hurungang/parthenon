import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Divider,
  FormControl,
  FormHelperText,
  InputAdornment,
  InputLabel,
  MenuItem,
  Select,
  TextField,
  Typography,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import type { AgentIdentity, AgentInputType, AgentOutputType, AgentRole, ModelConfig, Sop } from '../../types'
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
  primary_sop_id: string
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
  primary_sop_id: '',
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

  // Build a flat list of { modelId, label } from all configs' enabled_models
  const flatModels: { modelId: string; label: string }[] = (modelConfigs ?? []).flatMap((mc) =>
    (mc.enabled_models ?? []).map((m) => ({
      modelId: m,
      label: `${m} (${mc.display_name})`,
    }))
  )

  const selectedRole = (roles ?? []).find((r) => r.id === values.role_id)
  const roleSops = (sops ?? []).filter((s) => (selectedRole?.sop_ids ?? []).includes(s.id))
  const isConversation = values.input_type === 'conversation'

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

      <TextField
        label={t('agents.types.systemInstruction')}
        value={values.system_instruction}
        onChange={(e) => set('system_instruction', e.target.value)}
        fullWidth
        multiline
        rows={3}
      />

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

      {values.input_type === 'none' && (
        <FormControl fullWidth required>
          <InputLabel>{t('agents.types.form.defaultSop')}</InputLabel>
          <Select
            value={values.primary_sop_id}
            label={t('agents.types.form.defaultSop')}
            onChange={(e) => set('primary_sop_id', e.target.value)}
          >
            <MenuItem value=""><em>{t('agents.types.form.defaultSopPlaceholder')}</em></MenuItem>
            {roleSops.map((s) => (
              <MenuItem key={s.id} value={s.id}>{s.name}</MenuItem>
            ))}
          </Select>
          <FormHelperText>{t('agents.types.form.defaultSopHelper')}</FormHelperText>
        </FormControl>
      )}

      {values.input_type !== 'none' && (
        <FormControl fullWidth>
          <InputLabel>{t('agents.types.form.defaultSop')}</InputLabel>
          <Select
            value={values.primary_sop_id}
            label={t('agents.types.form.defaultSop')}
            onChange={(e) => set('primary_sop_id', e.target.value)}
          >
            <MenuItem value=""><em>{t('agents.types.form.defaultSopPlaceholder')}</em></MenuItem>
            {roleSops.map((s) => (
              <MenuItem key={s.id} value={s.id}>{s.name}</MenuItem>
            ))}
          </Select>
          <FormHelperText>{t('agents.types.form.defaultSopHelper')}</FormHelperText>
        </FormControl>
      )}

      {values.input_type === 'typed' && (
        <JsonSchemaBuilder
          value={values.input_schema}
          onChange={(schema) => set('input_schema', schema)}
          label={t('agents.types.inputSchema')}
          helperText={t('agents.types.schemaBuilder.inputSchemaHelper')}
        />
      )}

      {values.input_type !== 'conversation' && (
        <FormControl fullWidth>
          <InputLabel>{t('agents.types.outputType')}</InputLabel>
          <Select
            value={values.output_type}
            label={t('agents.types.outputType')}
            onChange={(e) => set('output_type', e.target.value as AgentOutputType)}
          >
            <MenuItem value="auto">{t('agents.types.outputAuto')}</MenuItem>
            <MenuItem value="typed">{t('agents.types.outputTyped')}</MenuItem>
            <MenuItem value="markdown">{t('agents.types.outputMarkdown')}</MenuItem>
          </Select>
        </FormControl>
      )}

      {values.input_type !== 'conversation' && values.output_type === 'typed' && (
        <JsonSchemaBuilder
          value={values.output_schema}
          onChange={(schema) => set('output_schema', schema)}
          label={t('agents.types.outputSchema')}
          helperText={t('agents.types.schemaBuilder.outputSchemaHelper')}
        />
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

