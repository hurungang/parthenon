import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Divider,
  FormControl,
  InputAdornment,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  TextField,
  Typography,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import type { UseAgentDraftCompositionResult } from '../../../hooks/useAgentDraftComposition'

/** k-token ↔ raw conversion (raw = k × 1000), mirroring AgentTypeForm. */
const TOKEN_BUDGET_UNIT = 1000

function rawTokenBudgetToK(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) {
    return '1000'
  }
  return String(Math.max(1, Math.round(value / TOKEN_BUDGET_UNIT)))
}

function tokenBudgetKToRaw(value: string): number {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return 1000 * TOKEN_BUDGET_UNIT
  }
  return Math.round(parsed * TOKEN_BUDGET_UNIT)
}

interface AgentPropertiesSectionProps {
  draftApi: UseAgentDraftCompositionResult
}

/**
 * "Properties" section at the top of the panel's right property bar: editable
 * fields for every base agent property — name, description, system
 * instruction, and the execution-guardrail set — exactly mirroring the shared
 * AgentTypeForm (labels, validation, conditional conversational controls).
 * All edits mutate the draft composition only; the pending-changes tray owns
 * saving, so no local save action exists here.
 */
export function AgentPropertiesSection({ draftApi }: AgentPropertiesSectionProps) {
  const { t } = useTranslation()
  const { draft, setGuardrails } = draftApi
  const { guardrails } = draft

  const invalidAgentName = !!draft.name && !/^[a-z0-9-]+$/.test(draft.name)

  // Token budget is edited in k-tokens; keep a local string that only
  // re-syncs from the draft when it no longer round-trips (discard / save).
  const [tokenBudgetK, setTokenBudgetK] = useState(() => rawTokenBudgetToK(guardrails.tokenBudget))
  useEffect(() => {
    setTokenBudgetK((current) =>
      tokenBudgetKToRaw(current) === (guardrails.tokenBudget ?? null)
        ? current
        : rawTokenBudgetToK(guardrails.tokenBudget),
    )
  }, [guardrails.tokenBudget])

  const isConversation = draft.inputType === 'conversation'

  const tokenBudgetHelperText = isConversation
    ? t('agents.types.guardrails.tokenBudgetConversationHint', {
        value: '1000',
        defaultValue: 'Visible current-session usage threshold. Default: {{value}}k tokens.',
      })
    : t('agents.types.guardrails.tokenBudgetNonConversationHint', {
        value: '1000',
        defaultValue: 'Budget for non-conversational enforcement. Default: {{value}}k tokens.',
      })

  return (
    <Paper variant="outlined" sx={{ p: 1.5 }}>
      <Box display="flex" alignItems="center" gap={1}>
        <Typography variant="subtitle2" fontWeight={600}>
          {t('agents.panel.properties.label')}
        </Typography>
      </Box>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.25 }}>
        {t('agents.panel.properties.hint')}
      </Typography>

      <Box sx={{ mt: 1, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
        <TextField
          label={t('app.name')}
          value={draft.name}
          onChange={(e) => draftApi.setName(e.target.value)}
          size="small"
          fullWidth
          required
          error={invalidAgentName}
          helperText={
            invalidAgentName ? t('agents.types.slugNameHelper') : t('agents.types.slugNameHint')
          }
        />
        <TextField
          label={t('app.description')}
          value={draft.description}
          onChange={(e) => draftApi.setDescription(e.target.value)}
          size="small"
          fullWidth
          multiline
          rows={2}
        />
        <TextField
          label={t('agents.types.systemInstruction')}
          value={draft.systemInstruction}
          onChange={(e) => draftApi.setSystemInstruction(e.target.value)}
          size="small"
          fullWidth
          multiline
          rows={3}
        />

        {/* ── Execution Guardrails (mirrors AgentTypeForm's accordion) ───── */}
        <Accordion variant="outlined" defaultExpanded={false} disableGutters>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography variant="subtitle2" fontWeight={600}>
              {t('agents.types.guardrails.title')}
            </Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Box display="flex" flexDirection="column" gap={2}>
              <Box display="grid" gridTemplateColumns="1fr 1fr" gap={2}>
                <TextField
                  type="number"
                  size="small"
                  label={t('agents.types.guardrails.maxIterations')}
                  value={guardrails.maxIterations}
                  onChange={(e) => setGuardrails({ maxIterations: Number(e.target.value || 0) })}
                  inputProps={{ min: 1, max: 1000 }}
                  fullWidth
                />
                <TextField
                  type="number"
                  size="small"
                  label={t('agents.types.guardrails.timeoutSeconds')}
                  value={guardrails.executionTimeoutSeconds}
                  onChange={(e) => setGuardrails({ executionTimeoutSeconds: Number(e.target.value || 0) })}
                  inputProps={{ min: 1, max: 86400 }}
                  fullWidth
                />
                <TextField
                  type="number"
                  size="small"
                  label={t('agents.types.guardrails.maxDelegationDepth')}
                  value={guardrails.maxDelegationDepth}
                  onChange={(e) => setGuardrails({ maxDelegationDepth: Number(e.target.value || 0) })}
                  inputProps={{ min: 0, max: 32 }}
                  fullWidth
                />
                <TextField
                  type="number"
                  size="small"
                  label={t('agents.types.guardrails.maxDelegatedSteps')}
                  value={guardrails.maxDelegatedSteps}
                  onChange={(e) => setGuardrails({ maxDelegatedSteps: Number(e.target.value || 0) })}
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
                <Box display="flex" flexDirection="column" gap={2}>
                  <TextField
                    type="number"
                    size="small"
                    label={t('agents.types.guardrails.tokenBudget')}
                    value={tokenBudgetK}
                    onChange={(e) => {
                      setTokenBudgetK(e.target.value)
                      setGuardrails({ tokenBudget: tokenBudgetKToRaw(e.target.value) })
                    }}
                    inputProps={{ min: 1 }}
                    InputProps={{
                      endAdornment: (
                        <InputAdornment position="end">
                          {t('agents.types.guardrails.tokenBudgetUnit')}
                        </InputAdornment>
                      ),
                    }}
                    fullWidth
                    helperText={tokenBudgetHelperText}
                  />

                  {!isConversation ? (
                    <>
                      <FormControl fullWidth size="small">
                        <InputLabel>{t('agents.types.guardrails.tokenEnforcementMode')}</InputLabel>
                        <Select
                          value={guardrails.tokenEnforcementMode}
                          label={t('agents.types.guardrails.tokenEnforcementMode')}
                          onChange={(e) =>
                            setGuardrails({
                              tokenEnforcementMode: e.target.value as 'observe' | 'enforce',
                            })
                          }
                        >
                          <MenuItem value="observe">
                            {t('agents.types.guardrails.observeMode')}
                          </MenuItem>
                          <MenuItem value="enforce">
                            {t('agents.types.guardrails.enforceMode')}
                          </MenuItem>
                        </Select>
                      </FormControl>
                      <FormControl fullWidth size="small">
                        <InputLabel>{t('agents.types.guardrails.tokenFallbackMode')}</InputLabel>
                        <Select
                          value={guardrails.tokenFallbackMode}
                          label={t('agents.types.guardrails.tokenFallbackMode')}
                          onChange={(e) =>
                            setGuardrails({
                              tokenFallbackMode: e.target.value as
                                | 'observe_and_log'
                                | 'stop_on_next_hard_guardrail',
                            })
                          }
                        >
                          <MenuItem value="observe_and_log">
                            {t('agents.types.guardrails.observeAndLog')}
                          </MenuItem>
                          <MenuItem value="stop_on_next_hard_guardrail">
                            {t('agents.types.guardrails.stopOnNextHardGuardrail')}
                          </MenuItem>
                        </Select>
                      </FormControl>
                    </>
                  ) : (
                    <>
                      <FormControl fullWidth size="small">
                        <InputLabel>
                          {t('agents.types.guardrails.conversationalVisibilityMode')}
                        </InputLabel>
                        <Select
                          value={guardrails.conversationalTokenVisibilityMode}
                          label={t('agents.types.guardrails.conversationalVisibilityMode')}
                          onChange={(e) =>
                            setGuardrails({
                              conversationalTokenVisibilityMode: e.target.value as
                                | 'enabled'
                                | 'disabled',
                            })
                          }
                        >
                          <MenuItem value="enabled">
                            {t('agents.types.guardrails.visibilityEnabled')}
                          </MenuItem>
                          <MenuItem value="disabled">
                            {t('agents.types.guardrails.visibilityDisabled')}
                          </MenuItem>
                        </Select>
                      </FormControl>
                      <FormControl fullWidth size="small">
                        <InputLabel>
                          {t('agents.types.guardrails.conversationalContinuationPolicy')}
                        </InputLabel>
                        <Select
                          value={guardrails.conversationalContinuationPolicy}
                          label={t('agents.types.guardrails.conversationalContinuationPolicy')}
                          onChange={(e) =>
                            setGuardrails({
                              conversationalContinuationPolicy: e.target.value as 'allow',
                            })
                          }
                        >
                          <MenuItem value="allow">
                            {t('agents.types.guardrails.continueAllowed')}
                          </MenuItem>
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
    </Paper>
  )
}
