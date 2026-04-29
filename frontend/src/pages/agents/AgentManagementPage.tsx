import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import { useAgentTypes, useAgentInstances, useTerminateInstance } from '../../hooks/useAgentTypes'
import apiClient from '../../api/apiClient'
import { useQueryClient } from '@tanstack/react-query'
import type { AgentType } from '../../types'

/**
 * Agent management page — agent type list, creation, and active instance table.
 */
export function AgentManagementPage() {
  const { t } = useTranslation()
  const { data: agentTypes, isLoading } = useAgentTypes()
  const queryClient = useQueryClient()
  const terminateInstance = useTerminateInstance()
  const [selectedType, setSelectedType] = useState<AgentType | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [form, setForm] = useState({
    name: '',
    description: '',
    mode: 'skillful-agent' as 'sop-agent' | 'skillful-agent',
    llm_provider: 'openai',
    llm_model: 'gpt-4o',
    llm_api_key: '',
    max_instances: 5,
    system_prompt: '',
  })

  const { data: instances } = useAgentInstances(selectedType?.id ?? '')

  const handleSave = async () => {
    await apiClient.post('/agents/types', form)
    setDialogOpen(false)
    await queryClient.invalidateQueries({ queryKey: ['agents', 'types'] })
  }

  const handleTerminate = async (instanceId: string) => {
    if (confirm(t('agents.terminateConfirm'))) {
      await terminateInstance.mutateAsync(instanceId)
    }
  }

  const statusColor = (status: string) => {
    if (status === 'active') return 'success'
    if (status === 'error') return 'error'
    if (status === 'closed') return 'default'
    return 'warning'
  }

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4" fontWeight={700}>{t('agents.title')}</Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setDialogOpen(true)}>
          {t('agents.createType')}
        </Button>
      </Box>

      {isLoading ? (
        <CircularProgress />
      ) : (
        <TableContainer component={Paper} sx={{ mb: 3 }}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>{t('app.name')}</TableCell>
                <TableCell>{t('agents.mode')}</TableCell>
                <TableCell>{t('agents.llmModel')}</TableCell>
                <TableCell>{t('agents.maxInstances')}</TableCell>
                <TableCell>{t('app.status')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(agentTypes ?? []).map((at) => (
                <TableRow
                  key={at.id}
                  selected={selectedType?.id === at.id}
                  onClick={() => setSelectedType(at)}
                  sx={{ cursor: 'pointer' }}
                >
                  <TableCell>{at.name}</TableCell>
                  <TableCell>
                    <Chip
                      label={at.mode === 'sop-agent' ? t('agents.sopAgent') : t('agents.skillfulAgent')}
                      size="small"
                      color={at.mode === 'sop-agent' ? 'primary' : 'secondary'}
                    />
                  </TableCell>
                  <TableCell>{at.llm_provider} / {at.llm_model}</TableCell>
                  <TableCell>{at.max_instances}</TableCell>
                  <TableCell>
                    <Chip
                      label={at.is_active ? t('app.active') : t('app.inactive')}
                      color={at.is_active ? 'success' : 'default'}
                      size="small"
                    />
                  </TableCell>
                </TableRow>
              ))}
              {(agentTypes ?? []).length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} align="center">{t('app.noData')}</TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Active instances for selected agent type */}
      {selectedType && (
        <Box>
          <Typography variant="h6" mb={2}>
            {t('agents.instances')} — {selectedType.name}
          </Typography>
          <TableContainer component={Paper}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Instance ID</TableCell>
                  <TableCell>{t('app.status')}</TableCell>
                  <TableCell>{t('app.createdAt')}</TableCell>
                  <TableCell>{t('app.actions')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {(instances ?? []).map((inst) => (
                  <TableRow key={inst.id}>
                    <TableCell><code>{inst.id.substring(0, 8)}…</code></TableCell>
                    <TableCell>
                      <Chip
                        label={inst.status}
                        color={statusColor(inst.status) as 'success' | 'error' | 'default' | 'warning'}
                        size="small"
                      />
                    </TableCell>
                    <TableCell>{new Date(inst.created_at).toLocaleString()}</TableCell>
                    <TableCell>
                      <Tooltip title={t('agents.terminate')}>
                        <IconButton
                          size="small"
                          color="error"
                          onClick={() => handleTerminate(inst.id)}
                          disabled={inst.status === 'closed'}
                        >
                          <DeleteIcon />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
                {(instances ?? []).length === 0 && (
                  <TableRow>
                    <TableCell colSpan={4} align="center">{t('app.noData')}</TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </Box>
      )}

      {/* Create Agent Type Dialog */}
      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{t('agents.createType')}</DialogTitle>
        <DialogContent>
          <Box display="flex" flexDirection="column" gap={2} mt={1}>
            <TextField
              label={t('app.name')}
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              fullWidth
            />
            <FormControl fullWidth>
              <InputLabel>{t('agents.mode')}</InputLabel>
              <Select
                value={form.mode}
                label={t('agents.mode')}
                onChange={(e) => setForm((f) => ({ ...f, mode: e.target.value as typeof form.mode }))}
              >
                <MenuItem value="skillful-agent">{t('agents.skillfulAgent')}</MenuItem>
                <MenuItem value="sop-agent">{t('agents.sopAgent')}</MenuItem>
              </Select>
            </FormControl>
            <TextField
              label={t('agents.llmProvider')}
              value={form.llm_provider}
              onChange={(e) => setForm((f) => ({ ...f, llm_provider: e.target.value }))}
              fullWidth
            />
            <TextField
              label={t('agents.llmModel')}
              value={form.llm_model}
              onChange={(e) => setForm((f) => ({ ...f, llm_model: e.target.value }))}
              fullWidth
            />
            <TextField
              label={t('agents.apiKey')}
              type="password"
              value={form.llm_api_key}
              onChange={(e) => setForm((f) => ({ ...f, llm_api_key: e.target.value }))}
              fullWidth
            />
            <TextField
              label={t('agents.maxInstances')}
              type="number"
              value={form.max_instances}
              onChange={(e) => setForm((f) => ({ ...f, max_instances: parseInt(e.target.value) || 5 }))}
              fullWidth
              inputProps={{ min: 1, max: 100 }}
            />
            <TextField
              label={t('agents.systemPrompt')}
              value={form.system_prompt}
              onChange={(e) => setForm((f) => ({ ...f, system_prompt: e.target.value }))}
              fullWidth
              multiline
              rows={3}
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>{t('app.cancel')}</Button>
          <Button variant="contained" onClick={handleSave}>{t('app.save')}</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
