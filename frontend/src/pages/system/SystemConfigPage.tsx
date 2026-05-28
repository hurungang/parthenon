import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
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
import type { WorkflowGenerationModelConfig } from '../../types'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'

export function SystemConfigPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const [saveError, setSaveError] = useState<unknown>(null)
  const [selectedWorkflowModelId, setSelectedWorkflowModelId] = useState<string>('')
  const [saveSuccessOpen, setSaveSuccessOpen] = useState(false)

  const { data: workflowConfig, isLoading } = useQuery<WorkflowGenerationModelConfig>({
    queryKey: ['agents', 'model-configs', 'workflow-generation'],
    queryFn: async () => {
      const { data } = await apiClient.get<WorkflowGenerationModelConfig>(
        '/agents/model-configs/workflow-generation',
      )
      return data
    },
  })

  const workflowOptions = workflowConfig?.options ?? []
  const effectiveSelectedWorkflowModelId =
    selectedWorkflowModelId || workflowConfig?.selected_model_id || ''

  const handleSave = async () => {
    try {
      setSaveError(null)
      const modelId =
        selectedWorkflowModelId || workflowConfig?.selected_model_id || null
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

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>
        {t('systemConfig.title')}
      </Typography>

      {saveError != null && (
        <PermissionDeniedAlert error={saveError} fallbackMessage={t('app.error')} />
      )}

      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" mb={0.5}>
          {t('systemConfig.workflowSection')}
        </Typography>
        <Typography variant="body2" color="text.secondary" mb={2}>
          {t('systemConfig.workflowHint')}
        </Typography>

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
              >
                <MenuItem value="">{t('systemConfig.workflowNotConfigured')}</MenuItem>
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
            <Button variant="contained" onClick={() => void handleSave()}>
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
