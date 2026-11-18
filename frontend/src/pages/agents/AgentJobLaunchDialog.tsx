import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  Typography,
  IconButton,
  Tooltip,
} from '@mui/material'
import CodeIcon from '@mui/icons-material/Code'
import EditIcon from '@mui/icons-material/Edit'
import { useQuery } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import QuotaBlockedAlert from '../../components/tenant/QuotaBlockedAlert'
import { DynamicSchemaForm } from '../../components/DynamicSchemaForm'
import type { AgentJob, AgentRole, AgentType, Skill, Sop } from '../../types'
import type { OptimizedPlanView } from '../../components/agents/AgentOptimizedPlanTab'

interface AgentJobLaunchDialogProps {
  open: boolean
  agentType: AgentType
  onClose: () => void
  onLaunched: (sessionId: string) => void
}

/**
 * Dialog for launching a new agent session.
 * Renders the appropriate input form based on the agent type's input_type:
 *   - "none"         → confirm only
 *   - "typed"        → JSON text input based on input_schema
 *   - "conversation" → initial message text area
 *
 * Run is execution-only: it always uses the agent's own system/skill
 * instructions. Optimization is a separate, gated action (see
 * `AgentOptimizeAction`, plus the Optimized Plan tab's chat/help) and
 * implementation-plan generation is explicit-only, offered from the Plan
 * Preview tab — never from this dialog or as a side effect of saving an agent.
 *
 * Follows the Dialog Error Handling Standard.
 */
export function AgentJobLaunchDialog({
  open,
  agentType,
  onClose,
  onLaunched,
}: AgentJobLaunchDialogProps) {
  const { t } = useTranslation()
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [submitting, setSubmitting] = useState(false)
  const [inputText, setInputText] = useState('')
  const [typedInputData, setTypedInputData] = useState<Record<string, any>>({})
  const [useRawJson, setUseRawJson] = useState(false)

  useEffect(() => {
    if (open) {
      setInputText('')
      setTypedInputData({})
      setUseRawJson(false)
      setDialogError(null)
    }
  }, [open])

  const { data: allRoles } = useQuery<AgentRole[]>({
    queryKey: ['agents', 'roles'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentRole[]>('/agents/roles')
      return data
    },
    enabled: open && !!agentType?.role_id,
  })

  const { data: allSops } = useQuery<Sop[]>({
    queryKey: ['sops'],
    queryFn: async () => {
      const { data } = await apiClient.get<Sop[]>('/sops')
      return data
    },
    enabled: open && !!agentType?.role_id,
  })

  const { data: allSkills } = useQuery<Skill[]>({
    queryKey: ['skills'],
    queryFn: async () => {
      const { data } = await apiClient.get<Skill[]>('/skills')
      return data
    },
    enabled: open && !!agentType?.role_id,
  })

  const currentRole = allRoles?.find((r) => r.id === agentType?.role_id)
  const roleSops = (allSops ?? []).filter((s) => currentRole?.sop_ids.includes(s.id))
  const roleSkills = (allSkills ?? []).filter((s) => currentRole?.skill_ids.includes(s.id))

  const planGeneratedAt = agentType?.plan?.generated_at ? new Date(agentType.plan.generated_at) : null

  const staleDefinitionLabels = useMemo(() => {
    if (!planGeneratedAt) {
      return [] as string[]
    }

    const labels: string[] = []

    if (currentRole?.updated_at && new Date(currentRole.updated_at) > planGeneratedAt) {
      labels.push('role')
    }

    if (roleSops.some((sop) => new Date(sop.updated_at) > planGeneratedAt)) {
      labels.push('SOPs')
    }

    if (roleSkills.some((skill) => new Date(skill.updated_at) > planGeneratedAt)) {
      labels.push('skills')
    }

    return labels
  }, [currentRole?.updated_at, planGeneratedAt, roleSops, roleSkills])

  const staleDefinitionsMessage = useMemo(() => {
    if (staleDefinitionLabels.length === 0) {
      return null
    }

    if (staleDefinitionLabels.length === 1) {
      return `This plan is older than the current ${staleDefinitionLabels[0]} definition.`
    }

    const last = staleDefinitionLabels.pop()
    return `This plan is older than the current ${staleDefinitionLabels.join(', ')} and ${last} definitions.`
  }, [staleDefinitionLabels])

  const planIsStale = !!planGeneratedAt && staleDefinitionLabels.length > 0

  // Optimized-plan existence check: a verified (`ready`) optimized plan means
  // the run uses it directly; otherwise the run proceeds on the model path.
  // 404 (no plan yet) is an expected state. This is informational only — a
  // normal run never optimizes.
  const { data: optimizedPlan } = useQuery<OptimizedPlanView>({
    queryKey: ['agents', 'types', agentType.id, 'optimized-plan'],
    queryFn: async () => {
      const { data } = await apiClient.get<OptimizedPlanView>(
        `/agents/types/${agentType.id}/optimized-plan`,
      )
      return data
    },
    enabled: open,
    retry: false,
  })
  const hasReadyOptimizedPlan = optimizedPlan?.status === 'ready'

  const handleLaunch = async () => {
    try {
      setDialogError(null)
      setSubmitting(true)

      let inputData: Record<string, unknown> | null = null

      if (agentType.input_type === 'typed') {
        if (useRawJson) {
          try {
            inputData = inputText.trim() ? (JSON.parse(inputText) as Record<string, unknown>) : null
          } catch {
            throw new Error(t('agents.sessions.invalidJson'))
          }
        } else {
          inputData = Object.keys(typedInputData).length > 0 ? typedInputData : null
        }
      } else if (agentType.input_type === 'conversation') {
        inputData = { message: inputText }
      }

      // Execution-only launch: no `optimize` field — the backend runs the
      // agent with its own instructions.
      const { data } = await apiClient.post<AgentJob>('/agents/sessions', {
        agent_type_id: agentType.id,
        input_data: inputData,
      })

      onLaunched(data.id)
    } catch (err) {
      setDialogError(err)
    } finally {
      setSubmitting(false)
    }
  }

  const schemaHint = agentType.input_schema
    ? JSON.stringify(agentType.input_schema, null, 2)
    : undefined
  const schemaForForm = agentType.input_schema ? JSON.stringify(agentType.input_schema) : ''

  return (
    <Dialog
      open={open}
      onClose={() => { onClose(); setDialogError(null) }}
      maxWidth="lg"
      fullWidth
    >
      <DialogTitle>
        {t('agents.sessions.launchTitle', { name: agentType.name })}
      </DialogTitle>

      <DialogContent dividers>
        {dialogError ? (
          <QuotaBlockedAlert error={dialogError} fallbackMessage={t('app.error')} />
        ) : null}

        {planIsStale && (
          <Alert severity="warning" sx={{ mb: 1 }} data-testid="stale-plan-note">
            {staleDefinitionsMessage} {t('agents.sessions.stalePlanHint')}
          </Alert>
        )}

        <Box display="flex" flexDirection="column" gap={2} pt={1}>
          {agentType.input_type !== 'conversation' && (
            <Alert severity="info" data-testid="run-execution-only-hint">
              {hasReadyOptimizedPlan
                ? t('agents.sessions.optimizedPlanPresent')
                : t('agents.sessions.modelPath')}
            </Alert>
          )}

          {agentType.input_type === 'none' && (
            <Alert severity="info">{t('agents.sessions.confirmLaunch')}</Alert>
          )}

          {agentType.input_type === 'typed' && (
            <Box>
              <Box display="flex" alignItems="center" justifyContent="space-between" mb={1}>
                <Typography variant="body2" color="text.secondary">
                  {useRawJson
                    ? t('agents.sessions.typedInputHintRaw')
                    : t('agents.sessions.typedInputHint')}
                </Typography>
                <Tooltip title={useRawJson ? t('agents.sessions.useFormInput') : t('agents.sessions.useRawJson')}>
                  <IconButton size="small" onClick={() => setUseRawJson(!useRawJson)}>
                    {useRawJson ? <EditIcon fontSize="small" /> : <CodeIcon fontSize="small" />}
                  </IconButton>
                </Tooltip>
              </Box>

              {useRawJson ? (
                <Box>
                  {schemaHint && (
                    <Box
                      component="pre"
                      sx={{
                        bgcolor: 'grey.50',
                        border: 1,
                        borderColor: 'divider',
                        borderRadius: 1,
                        p: 1,
                        fontSize: 12,
                        overflow: 'auto',
                        mb: 1,
                      }}
                    >
                      {schemaHint}
                    </Box>
                  )}
                  <TextField
                    label={t('agents.sessions.inputData')}
                    value={inputText}
                    onChange={(e) => setInputText(e.target.value)}
                    fullWidth
                    multiline
                    rows={5}
                    placeholder='{"key": "value"}'
                    inputProps={{ style: { fontFamily: 'monospace', fontSize: 13 } }}
                  />
                </Box>
              ) : (
                <DynamicSchemaForm
                  schema={schemaForForm}
                  value={typedInputData}
                  onChange={setTypedInputData}
                />
              )}
            </Box>
          )}

          {agentType.input_type === 'conversation' && (
            <TextField
              label={t('agents.sessions.initialMessage')}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              fullWidth
              multiline
              rows={4}
              placeholder={t('agents.sessions.initialMessagePlaceholder')}
            />
          )}
        </Box>
      </DialogContent>

      <DialogActions>
        <Button onClick={() => { onClose(); setDialogError(null) }} disabled={submitting}>
          {t('app.cancel')}
        </Button>
        <Button
          variant="contained"
          onClick={() => void handleLaunch()}
          disabled={
            submitting ||
            (agentType.input_type === 'conversation' && !inputText.trim())
          }
        >
          {submitting ? t('agents.sessions.launching') : t('agents.sessions.launch')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
