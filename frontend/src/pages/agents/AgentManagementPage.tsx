import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
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
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import VisibilityIcon from '@mui/icons-material/Visibility'
import { useAgentTypes } from '../../hooks/useAgentTypes'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import apiClient from '../../api/apiClient'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AgentTypeForm,
  defaultAgentTypeFormValues,
  type AgentTypeFormValues,
} from './AgentTypeForm'
import { AgentJobLaunchDialog } from './AgentJobLaunchDialog'
import PlanPreviewModal from '../../components/agents/PlanPreviewModal'
import { AgentTypeDetailsDialog } from '../../components/agents/AgentTypeDetailsDialog'
import type { AgentIdentity, AgentPlan, AgentRole, AgentType } from '../../types'

/**
 * Agent management page — agent type list, creation/editing, active instance table,
 * and session launch.
 */
export function AgentManagementPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { data: agentTypes, isLoading, error } = useAgentTypes()
  const queryClient = useQueryClient()

  // Role and identity name resolution for table columns
  const { data: allRoles } = useQuery<AgentRole[]>({
    queryKey: ['agents', 'roles'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentRole[]>('/agents/roles')
      return data
    },
  })
  const { data: allIdentities } = useQuery<AgentIdentity[]>({
    queryKey: ['agents', 'identities'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentIdentity[]>('/agents/identities')
      return data
    },
  })
  const roleMap = new Map((allRoles ?? []).map((r) => [r.id, r.name]))
  const identityMap = new Map((allIdentities ?? []).map((i) => [i.id, i.name]))
  const [detailsDialogTypeId, setDetailsDialogTypeId] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [editType, setEditType] = useState<AgentType | null>(null)
  const [form, setForm] = useState<AgentTypeFormValues>(defaultAgentTypeFormValues)
  const [launchType, setLaunchType] = useState<AgentType | null>(null)
  const [launchOpen, setLaunchOpen] = useState(false)
  const [planData, setPlanData] = useState<AgentPlan | null>(null)
  const [planModalOpen, setPlanModalOpen] = useState(false)
  const [planAgentTypeName, setPlanAgentTypeName] = useState('')
  const [previewLoading, setPreviewLoading] = useState<string | null>(null)

  const handleOpenCreate = () => {
    setEditType(null)
    setForm(defaultAgentTypeFormValues)
    setDialogError(null)
    setDialogOpen(true)
  }

  const handleOpenEdit = (at: AgentType) => {
    setEditType(at)
    setForm({
      name: at.name,
      description: at.description ?? '',
      identity_id: at.identity_id ?? '',
      role_id: at.role_id ?? '',
      model_id: at.model_id ?? '',
      system_instruction: at.system_instruction ?? '',
      input_type: at.input_type,
      input_schema: at.input_schema ? JSON.stringify(at.input_schema, null, 2) : '',
      output_type: at.output_type,
      output_schema: at.output_schema ? JSON.stringify(at.output_schema, null, 2) : '',
      primary_sop_id: at.primary_sop_id ?? '',
    })
    setDialogError(null)
    setDialogOpen(true)
  }

  const handleSave = async () => {
    try {
      setDialogError(null)
      if (form.input_type === 'none' && !form.primary_sop_id) {
        setDialogError(new Error(t('agents.types.form.primarySopRequired')))
        return
      }
      const body = {
        name: form.name,
        description: form.description || null,
        identity_id: form.identity_id || null,
        role_id: form.role_id || null,
        model_id: form.model_id || null,
        system_instruction: form.system_instruction || null,
        input_type: form.input_type,
        input_schema: form.input_schema ? JSON.parse(form.input_schema) : null,
        output_type: form.output_type,
        output_schema: form.output_schema ? JSON.parse(form.output_schema) : null,
        primary_sop_id: form.input_type === 'none' ? (form.primary_sop_id || null) : null,
      }
      let savedAgentType: AgentType
      if (editType) {
        const res = await apiClient.put<AgentType>(`/agents/types/${editType.id}`, body)
        savedAgentType = res.data
      } else {
        const res = await apiClient.post<AgentType>('/agents/types', body)
        savedAgentType = res.data
      }
      setDialogOpen(false)
      await queryClient.invalidateQueries({ queryKey: ['agents', 'types'] })
      // Show plan preview if a plan was generated
      if (savedAgentType.plan) {
        setPlanData(savedAgentType.plan)
        setPlanAgentTypeName(savedAgentType.name)
        setPlanModalOpen(true)
      }
    } catch (err) {
      setDialogError(err)
    }
  }

  const handleLaunch = (at: AgentType) => {
    setLaunchType(at)
    setLaunchOpen(true)
  }

  const handlePreviewPlan = async (at: AgentType) => {
    setPreviewLoading(at.id)
    try {
      const res = await apiClient.get<AgentType>(`/agents/types/${at.id}`)
      setPlanData(res.data.plan ?? null)
      setPlanAgentTypeName(res.data.name)
      setPlanModalOpen(true)
    } finally {
      setPreviewLoading(null)
    }
  }

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4" fontWeight={700}>{t('agents.title')}</Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={handleOpenCreate}>
          {t('agents.createType')}
        </Button>
      </Box>

      {isLoading && <CircularProgress />}
      {error && <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />}

      {!isLoading && !error && (
        <TableContainer component={Paper} sx={{ mb: 3 }}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>{t('app.name')}</TableCell>
                <TableCell>{t('agents.types.inputType')}</TableCell>
                <TableCell>{t('agents.types.outputType')}</TableCell>
                <TableCell>{t('agents.llmModel')}</TableCell>
                <TableCell>{t('app.status')}</TableCell>
                <TableCell>{t('agents.types.role')}</TableCell>
                <TableCell>{t('agents.types.identity')}</TableCell>
                <TableCell>{t('app.actions')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(agentTypes ?? []).map((at) => (
                <TableRow
                  key={at.id}
                  selected={detailsDialogTypeId === at.id}
                  onClick={() => setDetailsDialogTypeId(at.id)}
                  sx={{ cursor: 'pointer' }}
                >
                  <TableCell>{at.name}</TableCell>
                  <TableCell>
                    <Chip label={at.input_type} size="small" variant="outlined" />
                  </TableCell>
                  <TableCell>
                    <Chip label={at.output_type} size="small" variant="outlined" />
                  </TableCell>
                  <TableCell>{at.model_id ?? '—'}</TableCell>
                  <TableCell>
                    <Chip
                      label={at.is_active ? t('app.active') : t('app.inactive')}
                      color={at.is_active ? 'success' : 'default'}
                      size="small"
                    />
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">
                      {at.role_id ? (roleMap.get(at.role_id) ?? '—') : '—'}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">
                      {at.identity_id ? (identityMap.get(at.identity_id) ?? '—') : '—'}
                    </Typography>
                  </TableCell>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <Box display="flex" gap={0.5}>
                      <Tooltip title={t('agents.types.launch')}>
                        <IconButton
                          size="small"
                          color="primary"
                          aria-label={t('agents.types.launch')}
                          onClick={() => handleLaunch(at)}
                        >
                          <PlayArrowIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      {at.plan && (
                        <Tooltip title={t('agents.plan.previewButton')}>
                          <IconButton
                            size="small"
                            color="secondary"
                            aria-label={t('agents.plan.previewButton')}
                            onClick={() => void handlePreviewPlan(at)}
                            disabled={previewLoading === at.id}
                          >
                            {previewLoading === at.id
                              ? <CircularProgress size={16} color="inherit" />
                              : <VisibilityIcon fontSize="small" />}
                          </IconButton>
                        </Tooltip>
                      )}
                      <Tooltip title={t('app.edit')}>
                        <IconButton size="small" aria-label={t('app.edit')} onClick={() => handleOpenEdit(at)}>
                          <EditIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </Box>
                  </TableCell>
                </TableRow>
              ))}
              {(agentTypes ?? []).length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} align="center">{t('app.noData')}</TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Agent Type Details Dialog */}
      <AgentTypeDetailsDialog
        open={detailsDialogTypeId !== null}
        agentTypeId={detailsDialogTypeId}
        onClose={() => {
          setDetailsDialogTypeId(null)
          void queryClient.invalidateQueries({ queryKey: ['agents', 'types'] })
        }}
      />

      {/* Create / Edit Agent Type Dialog */}
      <Dialog
        open={dialogOpen}
        onClose={() => { setDialogOpen(false); setDialogError(null) }}
        maxWidth="lg"
        fullWidth
      >
        <DialogTitle>
          {editType ? t('agents.editType') : t('agents.createType')}
        </DialogTitle>
        <DialogContent dividers>
          {dialogError ? (
            <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
          ) : null}
          <Box pt={1}>
            <AgentTypeForm values={form} onChange={setForm} />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setDialogOpen(false); setDialogError(null) }}>
            {t('app.cancel')}
          </Button>
          <Button
            variant="contained"
            onClick={handleSave}
            disabled={!form.name.trim()}
          >
            {t('app.save')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Session Launch Dialog */}
      {launchType && (
        <AgentJobLaunchDialog
          open={launchOpen}
          agentType={launchType}
          onClose={() => { setLaunchOpen(false); setLaunchType(null) }}
          onLaunched={(sessionId) => {
            setLaunchOpen(false)
            setLaunchType(null)
            void navigate(`/agents/sessions/${sessionId}`)
          }}
        />
      )}

      <PlanPreviewModal
        open={planModalOpen}
        onClose={() => setPlanModalOpen(false)}
        plan={planData}
        agentTypeName={planAgentTypeName}
      />
    </Box>
  )
}
