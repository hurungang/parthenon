import {
  Box,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  TextField,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import type { AgentIdentity, AgentInputType, AgentOutputType, AgentRole } from '../../types'

export interface AgentTypeFormValues {
  name: string
  description: string
  identity_id: string
  role_id: string
  llm_provider: string
  llm_model: string
  llm_api_key: string
  system_instruction: string
  input_type: AgentInputType
  input_schema: string
  output_type: AgentOutputType
  output_schema: string
}

export const defaultAgentTypeFormValues: AgentTypeFormValues = {
  name: '',
  description: '',
  identity_id: '',
  role_id: '',
  llm_provider: 'openai',
  llm_model: 'gpt-4o',
  llm_api_key: '',
  system_instruction: '',
  input_type: 'none',
  input_schema: '',
  output_type: 'auto',
  output_schema: '',
}

interface AgentTypeFormProps {
  values: AgentTypeFormValues
  onChange: (values: AgentTypeFormValues) => void
}

/**
 * Reusable form for creating / editing an AgentType.
 * Covers all fields in the rearchitected AgentType schema.
 */
export function AgentTypeForm({ values, onChange }: AgentTypeFormProps) {
  const { t } = useTranslation()

  const set = <K extends keyof AgentTypeFormValues>(key: K, value: AgentTypeFormValues[K]) =>
    onChange({ ...values, [key]: value })

  const { data: roles } = useQuery<AgentRole[]>({
    queryKey: ['agents', 'roles'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentRole[]>('/agents/roles')
      return data
    },
  })

  const { data: identities } = useQuery<AgentIdentity[]>({
    queryKey: ['agents', 'identities'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentIdentity[]>('/agents/identities')
      return data
    },
  })

  return (
    <Box display="flex" flexDirection="column" gap={2}>
      <TextField
        label={t('app.name')}
        value={values.name}
        onChange={(e) => set('name', e.target.value)}
        fullWidth
        required
      />
      <TextField
        label={t('app.description')}
        value={values.description}
        onChange={(e) => set('description', e.target.value)}
        fullWidth
        multiline
        rows={2}
      />

      <FormControl fullWidth>
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
      </FormControl>

      <FormControl fullWidth>
        <InputLabel>{t('agents.types.identity')}</InputLabel>
        <Select
          value={values.identity_id}
          label={t('agents.types.identity')}
          onChange={(e) => set('identity_id', e.target.value)}
        >
          <MenuItem value=""><em>{t('agents.types.noIdentity')}</em></MenuItem>
          {(identities ?? []).map((i) => (
            <MenuItem key={i.id} value={i.id}>{i.name}</MenuItem>
          ))}
        </Select>
      </FormControl>

      <TextField
        label={t('agents.types.llmProvider')}
        value={values.llm_provider}
        onChange={(e) => set('llm_provider', e.target.value)}
        fullWidth
      />
      <TextField
        label={t('agents.types.llmModel')}
        value={values.llm_model}
        onChange={(e) => set('llm_model', e.target.value)}
        fullWidth
      />
      <TextField
        label={t('agents.types.apiKey')}
        type="password"
        value={values.llm_api_key}
        onChange={(e) => set('llm_api_key', e.target.value)}
        fullWidth
      />

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
          onChange={(e) => set('input_type', e.target.value as AgentInputType)}
        >
          <MenuItem value="none">{t('agents.types.inputNone')}</MenuItem>
          <MenuItem value="typed">{t('agents.types.inputTyped')}</MenuItem>
          <MenuItem value="conversation">{t('agents.types.inputConversation')}</MenuItem>
        </Select>
      </FormControl>

      {values.input_type === 'typed' && (
        <Box>
          <Typography variant="caption" color="text.secondary" display="block" mb={0.5}>
            {t('agents.types.inputSchema')}
          </Typography>
          <TextField
            value={values.input_schema}
            onChange={(e) => set('input_schema', e.target.value)}
            fullWidth
            multiline
            rows={4}
            placeholder='{"field": {"type": "string", "description": "..."}}'
            inputProps={{ style: { fontFamily: 'monospace', fontSize: 13 } }}
          />
        </Box>
      )}

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

      {values.output_type === 'typed' && (
        <Box>
          <Typography variant="caption" color="text.secondary" display="block" mb={0.5}>
            {t('agents.types.outputSchema')}
          </Typography>
          <TextField
            value={values.output_schema}
            onChange={(e) => set('output_schema', e.target.value)}
            fullWidth
            multiline
            rows={4}
            placeholder='{"result": {"type": "string"}}'
            inputProps={{ style: { fontFamily: 'monospace', fontSize: 13 } }}
          />
        </Box>
      )}
    </Box>
  )
}

