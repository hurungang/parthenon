import { useState } from 'react'
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import VpnKeyIcon from '@mui/icons-material/VpnKey'
import { useTranslation } from 'react-i18next'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import type { ModelConfig } from '../../types'
import { ModelConfigDialog } from './ModelConfigDialog'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'

export function ModelConfigListPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingConfig, setEditingConfig] = useState<ModelConfig | null>(null)
  const [deleteError, setDeleteError] = useState<unknown>(null)

  const {
    data: configs,
    isLoading,
    error,
  } = useQuery<ModelConfig[]>({
    queryKey: ['agents', 'model-configs'],
    queryFn: async () => {
      const { data } = await apiClient.get<ModelConfig[]>('/agents/model-configs')
      return data
    },
  })

  const handleCreate = () => {
    setEditingConfig(null)
    setDialogOpen(true)
  }

  const handleEdit = (config: ModelConfig) => {
    setEditingConfig(config)
    setDialogOpen(true)
  }

  const handleDelete = async (config: ModelConfig) => {
    if (!window.confirm(t('agents.modelConfigs.deleteConfirm', { name: config.display_name }))) return
    try {
      setDeleteError(null)
      await apiClient.delete(`/agents/model-configs/${config.id}`)
      void queryClient.invalidateQueries({ queryKey: ['agents', 'model-configs'] })
    } catch (err) {
      setDeleteError(err)
    }
  }

  const providerColor = (pt: string): 'default' | 'primary' | 'secondary' | 'info' | 'warning' => {
    if (pt === 'openai') return 'primary'
    if (pt === 'anthropic') return 'secondary'
    if (pt === 'litellm_proxy') return 'info'
    if (pt === 'azure_openai') return 'warning'
    return 'default'
  }

  if (isLoading) {
    return (
      <Box display="flex" justifyContent="center" pt={8}>
        <CircularProgress />
      </Box>
    )
  }

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="flex-start" mb={3}>
        <Box>
          <Typography variant="h4" fontWeight={700} mb={0.5}>
            {t('agents.modelConfigs.title')}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t('agents.modelConfigs.subtitle')}
          </Typography>
        </Box>
        <Button variant="contained" startIcon={<AddIcon />} onClick={handleCreate}>
          {t('agents.modelConfigs.create')}
        </Button>
      </Box>

      {error != null && <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />}
      {deleteError != null && <PermissionDeniedAlert error={deleteError} fallbackMessage={t('app.error')} />}

      {configs && configs.length === 0 ? (
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography color="text.secondary">{t('agents.modelConfigs.empty')}</Typography>
        </Paper>
      ) : (
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>{t('app.name')}</TableCell>
                <TableCell>{t('agents.modelConfigs.provider')}</TableCell>
                <TableCell>{t('agents.modelConfigs.apiBaseUrl')}</TableCell>
                <TableCell>{t('agents.modelConfigs.credentials')}</TableCell>
                <TableCell align="right">{t('app.actions')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(configs ?? []).map((config) => (
                <TableRow key={config.id} hover>
                  <TableCell>
                    <Typography fontWeight={500}>{config.display_name}</Typography>
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={config.provider_type}
                      color={providerColor(config.provider_type)}
                      size="small"
                    />
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" color="text.secondary" fontFamily="monospace">
                      {config.api_base_url ?? '—'}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    {config.has_credentials ? (
                      <Chip
                        icon={<VpnKeyIcon />}
                        label={t('agents.modelConfigs.credentialsSet')}
                        color="success"
                        size="small"
                        variant="outlined"
                      />
                    ) : (
                      <Chip
                        label={t('agents.modelConfigs.noCredentials')}
                        color="default"
                        size="small"
                        variant="outlined"
                      />
                    )}
                  </TableCell>
                  <TableCell align="right">
                    <IconButton size="small" onClick={() => handleEdit(config)} title={t('app.edit')}>
                      <EditIcon fontSize="small" />
                    </IconButton>
                    <IconButton size="small" onClick={() => handleDelete(config)} title={t('app.delete')}>
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <ModelConfigDialog
        open={dialogOpen}
        config={editingConfig}
        onClose={() => setDialogOpen(false)}
        onSaved={() => {
          setDialogOpen(false)
          void queryClient.invalidateQueries({ queryKey: ['agents', 'model-configs'] })
        }}
      />
    </Box>
  )
}
