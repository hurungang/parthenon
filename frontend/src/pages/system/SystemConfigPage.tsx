import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Snackbar,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import type { AssistantModelConfig, WorkflowGenerationModelConfig } from '../../types'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import {
  OPTIMIZER_MODEL_INHERIT_VALUE,
  isOptimizerSelectionUnavailable,
  useOptimizerModelConfig,
  useSetOptimizerModel,
} from '../../hooks/useOptimizerModelConfig'

export function SystemConfigPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const [saveError, setSaveError] = useState<unknown>(null)
  const [selectedWorkflowModelId, setSelectedWorkflowModelId] = useState<string>('')
  const [selectedAssistantModelId, setSelectedAssistantModelId] = useState<string>('')
  // `null` = untouched: the Select mirrors the saved value until the operator
  // changes it. The inherit value is an explicit sentinel so "clear back to
  // inherit" stays selectable even when a model is stored.
  const [optimizerSelection, setOptimizerSelection] = useState<string | null>(null)
  const [saveSuccessOpen, setSaveSuccessOpen] = useState(false)

  // Workspace optimizer model: powers the optimization-mode conversation, not
  // the agent's runtime. Unset inherits the plan authoring model.
  const { data: optimizerConfig, isLoading: isLoadingOptimizer } = useOptimizerModelConfig()
  const setOptimizerModel = useSetOptimizerModel()

  const { data: workflowConfig, isLoading } = useQuery<WorkflowGenerationModelConfig>({
    queryKey: ['agents', 'model-configs', 'workflow-generation'],
    queryFn: async () => {
      const { data } = await apiClient.get<WorkflowGenerationModelConfig>(
        '/agents/model-configs/workflow-generation',
      )
      return data
    },
  })

  // The assistant model is tenant-scoped: the backend resolves options and
  // the stored selection from the current session's tenant context.
  const { data: assistantConfig, isLoading: isLoadingAssistant } = useQuery<AssistantModelConfig>({
    queryKey: ['agents', 'model-configs', 'assistant-model'],
    queryFn: async () => {
      const { data } = await apiClient.get<AssistantModelConfig>(
        '/agents/model-configs/assistant-model',
      )
      return data
    },
  })

  const workflowOptions = workflowConfig?.options ?? []
  const effectiveSelectedWorkflowModelId =
    selectedWorkflowModelId || workflowConfig?.selected_model_id || ''
  const workflowSelectionIsValid =
    effectiveSelectedWorkflowModelId !== '' &&
    workflowOptions.some((option) => option.model_id === effectiveSelectedWorkflowModelId)
  // "Not configured" and "no longer available" both block plan/workflow
  // authoring in this workspace — the reminder stays until a valid model is saved.
  const showWorkflowReminder = !isLoading && !workflowSelectionIsValid
  const workflowSelectionUnavailable =
    !isLoading && effectiveSelectedWorkflowModelId !== '' && !workflowSelectionIsValid

  const assistantOptions = assistantConfig?.options ?? []
  const effectiveSelectedAssistantModelId =
    selectedAssistantModelId || assistantConfig?.selected_model_id || ''

  // ── Optimizer model (workspace-scoped, inherits the authoring model) ──────
  const optimizerOptions = optimizerConfig?.options ?? []
  const storedOptimizerModelId = optimizerConfig?.selected_model_id ?? null
  const effectiveOptimizerSelection =
    optimizerSelection ?? storedOptimizerModelId ?? OPTIMIZER_MODEL_INHERIT_VALUE
  const optimizerSelectionIsStale = isOptimizerSelectionUnavailable(optimizerConfig)
    ? // The STORED value is stale; a fresh local pick supersedes it.
      effectiveOptimizerSelection === storedOptimizerModelId
    : effectiveOptimizerSelection !== OPTIMIZER_MODEL_INHERIT_VALUE &&
      !optimizerOptions.some((option) => option.model_id === effectiveOptimizerSelection)
  const optimizerInherits = effectiveOptimizerSelection === OPTIMIZER_MODEL_INHERIT_VALUE
  const optimizerResolvedModelId = optimizerInherits
    ? optimizerConfig?.source === 'authoring'
      ? (optimizerConfig?.effective_model_id ?? null)
      : null
    : effectiveOptimizerSelection
  const optimizerHasUsableModel = Boolean(optimizerResolvedModelId) && !optimizerSelectionIsStale
  // An unsaved "inherit" pick is not a blocked state: the authoring model is
  // resolved at save time, so the current derived state can't be judged yet.
  const optimizerInheritPending = optimizerInherits && optimizerSelection !== null
  const showOptimizerReminder =
    !isLoadingOptimizer &&
    (optimizerSelectionIsStale || (!optimizerHasUsableModel && !optimizerInheritPending))

  const handleSave = async () => {
    try {
      setSaveError(null)
      const desiredModelId =
        selectedWorkflowModelId || workflowConfig?.selected_model_id || ''
      // Only an enabled model from THIS workspace's catalogue can be saved
      // (`null` clears the selection); a stale/unknown id is never re-submitted.
      const modelId = workflowOptions.some((option) => option.model_id === desiredModelId)
        ? desiredModelId
        : null
      await apiClient.put('/agents/model-configs/workflow-generation', {
        model_id: modelId,
      })
      void queryClient.invalidateQueries({
        queryKey: ['agents', 'model-configs', 'workflow-generation'],
      })
      setSaveSuccessOpen(true)
    } catch (err) {
      setSaveError(err)
    }
  }

  const handleSaveAssistant = async () => {
    try {
      setSaveError(null)
      const modelId =
        selectedAssistantModelId || assistantConfig?.selected_model_id || null
      await apiClient.put('/agents/model-configs/assistant-model', {
        model_id: modelId,
      })
      void queryClient.invalidateQueries({
        queryKey: ['agents', 'model-configs', 'assistant-model'],
      })
      setSaveSuccessOpen(true)
    } catch (err) {
      setSaveError(err)
    }
  }

  /**
   * Saves the workspace optimizer model. The inherit sentinel clears the
   * setting (`model_id: null`) so optimization falls back to the plan authoring
   * model without writing a second value. A stale/unknown id is never
   * re-submitted — Save stays blocked until the operator re-selects.
   */
  const handleSaveOptimizer = async () => {
    try {
      setSaveError(null)
      const modelId =
        effectiveOptimizerSelection === OPTIMIZER_MODEL_INHERIT_VALUE
          ? null
          : effectiveOptimizerSelection
      await setOptimizerModel.mutateAsync({ model_id: modelId })
      setOptimizerSelection(null)
      setSaveSuccessOpen(true)
    } catch (err) {
      setSaveError(err)
    }
  }

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>
        {t('systemConfig.title')}
      </Typography>

      {saveError != null && (
        <PermissionDeniedAlert error={saveError} fallbackMessage={t('app.error')} />
      )}

      {/* ── Optimizer Model (optimization-mode conversation) ─────────────── */}
      <Paper sx={{ p: 3, mb: 2 }} data-testid="optimizer-model-section">
        <Box display="flex" alignItems="center" gap={1} flexWrap="wrap" mb={0.5}>
          <Typography variant="h6">{t('systemConfig.optimizerSection')}</Typography>
          <Chip
            size="small"
            label={t('systemConfig.optimizerScope')}
            data-testid="optimizer-model-scope"
          />
        </Box>
        <Typography variant="body2" color="text.secondary" mb={1.5}>
          {t('systemConfig.optimizerHint')}
        </Typography>

        <Typography variant="body2" fontWeight={600}>
          {t('systemConfig.optimizerUsesTitle')}
        </Typography>
        <Box component="ul" sx={{ mt: 0.5, mb: 1.5, pl: 3 }}>
          <Typography component="li" variant="body2" color="text.secondary">
            {t('systemConfig.optimizerUseConversation')}
          </Typography>
          <Typography component="li" variant="body2" color="text.secondary">
            {t('systemConfig.optimizerUseInherit')}
          </Typography>
          <Typography component="li" variant="body2" color="text.secondary">
            {t('systemConfig.optimizerUseScope')}
          </Typography>
        </Box>

        {showOptimizerReminder && (
          <Alert
            severity="warning"
            sx={{ mb: 2 }}
            data-testid="optimizer-model-reminder"
          >
            {optimizerSelectionIsStale
              ? t('systemConfig.optimizerReminderUnavailable', {
                  modelId: effectiveOptimizerSelection,
                })
              : t('systemConfig.optimizerReminderUnset')}
          </Alert>
        )}

        {isLoadingOptimizer ? (
          <CircularProgress size={24} />
        ) : optimizerOptions.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {t('systemConfig.optimizerNoOptions')}
          </Typography>
        ) : (
          <Box display="flex" gap={1.5} alignItems="center" flexWrap="wrap">
            <FormControl size="small" sx={{ minWidth: 360 }}>
              <InputLabel>{t('systemConfig.optimizerModel')}</InputLabel>
              <Select
                label={t('systemConfig.optimizerModel')}
                value={effectiveOptimizerSelection}
                onChange={(e) => setOptimizerSelection(e.target.value)}
                inputProps={{ 'data-testid': 'optimizer-model-select' }}
              >
                <MenuItem value={OPTIMIZER_MODEL_INHERIT_VALUE}>
                  {t('systemConfig.optimizerInheritOption')}
                </MenuItem>
                {optimizerSelectionIsStale && (
                  // Render the stale value so the Select shows what was saved;
                  // it is not selectable — the operator must re-select.
                  <MenuItem value={effectiveOptimizerSelection} disabled>
                    {t('systemConfig.optimizerUnavailableOption', {
                      modelId: effectiveOptimizerSelection,
                    })}
                  </MenuItem>
                )}
                {optimizerOptions.map((option) => (
                  <MenuItem
                    key={`${option.config_id}:${option.model_id}`}
                    value={option.model_id}
                  >
                    {`${option.model_id} (${option.config_display_name})`}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button
              variant="contained"
              onClick={() => void handleSaveOptimizer()}
              disabled={optimizerSelectionIsStale || setOptimizerModel.isPending}
              data-testid="optimizer-model-save"
            >
              {t('app.save')}
            </Button>
          </Box>
        )}

        <Typography
          variant="caption"
          color="text.secondary"
          display="block"
          mt={1}
          data-testid="optimizer-model-state"
        >
          {optimizerSelectionIsStale
            ? ''
            : optimizerInheritPending
              ? t('systemConfig.optimizerStatePendingInherit')
              : optimizerHasUsableModel
                ? optimizerInherits
                  ? t('systemConfig.optimizerStateInherited', {
                      modelId: optimizerResolvedModelId,
                    })
                  : t('systemConfig.optimizerStateSelected', {
                      modelId: optimizerResolvedModelId,
                    })
                : t('systemConfig.optimizerStateBlocked')}
        </Typography>

        <Typography variant="caption" color="text.secondary" display="block" mt={0.5}>
          {t('systemConfig.optimizerCatalogueHint')}
        </Typography>
        <Typography
          variant="caption"
          color="text.secondary"
          display="block"
          mt={1}
          data-testid="optimizer-model-no-substitution"
        >
          {t('systemConfig.optimizerNoSubstitution')}
        </Typography>

        <Alert severity="info" sx={{ mt: 2 }} data-testid="optimizer-model-unchanged">
          {t('systemConfig.optimizerUnchanged')}
        </Alert>
      </Paper>

      <Paper sx={{ p: 3, mb: 2 }} data-testid="authoring-model-section">
        <Typography variant="h6" mb={0.5}>
          {t('systemConfig.workflowSection')}
        </Typography>
        <Typography variant="body2" color="text.secondary" mb={1}>
          {t('systemConfig.workflowHint')}
        </Typography>

        {/* What the model is used for — three consumers, one setting. */}
        <Typography variant="body2" fontWeight={600} mt={1.5}>
          {t('systemConfig.workflowUsesTitle')}
        </Typography>
        <Box component="ul" sx={{ mt: 0.5, mb: 1.5, pl: 3 }}>
          <Typography component="li" variant="body2" color="text.secondary">
            {t('systemConfig.workflowUseSkills')}
          </Typography>
          <Typography component="li" variant="body2" color="text.secondary">
            {t('systemConfig.workflowUseImplementationPlans')}
          </Typography>
          <Typography component="li" variant="body2" color="text.secondary">
            {t('systemConfig.workflowUseOptimizationPlans')}
          </Typography>
        </Box>

        <Alert
          severity="info"
          sx={{ mb: 1.5 }}
          data-testid="authoring-model-recommendation"
        >
          {t('systemConfig.workflowRecommendation')}
        </Alert>

        <Typography
          variant="caption"
          color="text.secondary"
          display="block"
          mb={2}
          data-testid="authoring-model-workspace-note"
        >
          {t('systemConfig.workflowOptionsScopeNote')}
        </Typography>

        {showWorkflowReminder && (
          <Alert
            severity="warning"
            sx={{ mb: 2 }}
            data-testid="authoring-model-reminder"
          >
            {workflowSelectionUnavailable
              ? t('systemConfig.workflowReminderUnavailable', {
                  modelId: effectiveSelectedWorkflowModelId,
                })
              : t('systemConfig.workflowReminderUnset')}
          </Alert>
        )}

        {isLoading ? (
          <CircularProgress size={24} />
        ) : workflowOptions.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {t('systemConfig.workflowNoOptions')}
          </Typography>
        ) : (
          <Box display="flex" gap={1.5} alignItems="center">
            <FormControl size="small" sx={{ minWidth: 360 }}>
              <InputLabel>{t('systemConfig.workflowModel')}</InputLabel>
              <Select
                label={t('systemConfig.workflowModel')}
                value={effectiveSelectedWorkflowModelId}
                onChange={(e) => setSelectedWorkflowModelId(e.target.value)}
                inputProps={{ 'data-testid': 'authoring-model-select' }}
              >
                <MenuItem value="">{t('systemConfig.workflowNotConfigured')}</MenuItem>
                {workflowSelectionUnavailable && (
                  // Render the stale value so the Select shows what was saved;
                  // it is not selectable — the operator must re-select.
                  <MenuItem value={effectiveSelectedWorkflowModelId} disabled>
                    {t('systemConfig.workflowUnavailableOption', {
                      modelId: effectiveSelectedWorkflowModelId,
                    })}
                  </MenuItem>
                )}
                {workflowOptions.map((option) => (
                  <MenuItem
                    key={`${option.config_id}:${option.model_id}`}
                    value={option.model_id}
                  >
                    {`${option.model_id} (${option.config_display_name})`}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button
              variant="contained"
              onClick={() => void handleSave()}
              disabled={workflowSelectionUnavailable}
            >
              {t('app.save')}
            </Button>
          </Box>
        )}
      </Paper>

      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" mb={0.5}>
          {t('systemConfig.assistantSection')}
        </Typography>
        <Typography variant="body2" color="text.secondary" mb={2}>
          {t('systemConfig.assistantHint')}
        </Typography>

        {isLoadingAssistant ? (
          <CircularProgress size={24} />
        ) : assistantOptions.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {t('systemConfig.assistantNoOptions')}
          </Typography>
        ) : (
          <Box display="flex" gap={1.5} alignItems="center">
            <FormControl size="small" sx={{ minWidth: 360 }}>
              <InputLabel>{t('systemConfig.assistantModel')}</InputLabel>
              <Select
                label={t('systemConfig.assistantModel')}
                value={effectiveSelectedAssistantModelId}
                onChange={(e) => setSelectedAssistantModelId(e.target.value)}
              >
                <MenuItem value="">{t('systemConfig.assistantNotConfigured')}</MenuItem>
                {assistantOptions.map((option) => (
                  <MenuItem
                    key={`${option.config_id}:${option.model_id}`}
                    value={option.model_id}
                  >
                    {`${option.model_id} (${option.config_display_name})`}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button variant="contained" onClick={() => void handleSaveAssistant()}>
              {t('app.save')}
            </Button>
          </Box>
        )}
      </Paper>

      <Snackbar
        open={saveSuccessOpen}
        autoHideDuration={3000}
        onClose={() => setSaveSuccessOpen(false)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert
          onClose={() => setSaveSuccessOpen(false)}
          severity="success"
          variant="filled"
          sx={{ width: '100%' }}
        >
          {t('systemConfig.saveSuccess')}
        </Alert>
      </Snackbar>
    </Box>
  )
}
