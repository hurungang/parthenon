import { useEffect, useState } from 'react'
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
  Tooltip,
  Typography,
} from '@mui/material'
import DeleteIcon from '@mui/icons-material/Delete'
import { useQueryClient } from '@tanstack/react-query'
import { useAgentType, useAgentTypes, useDeleteAgentType } from '../../hooks/useAgentTypes'
import { useAgentDraftComposition } from '../../hooks/useAgentDraftComposition'
import { useUnsavedChangesDialog } from '../../hooks/useUnsavedChangesDialog'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { ConfirmDialog } from '../../components/common/ConfirmDialog'
import { AgentListSidebar } from '../../components/agents/panel/AgentListSidebar'
import { EquipmentSlots, dataTypeToInputSchema } from '../../components/agents/panel/EquipmentSlots'
import { AgentPropertiesSection } from '../../components/agents/panel/AgentPropertiesSection'
import { SharedDialogHost } from '../../components/agents/panel/SharedDialogHost'
import { PendingChangesTray } from '../../components/agents/panel/PendingChangesTray'
import { PanelTopologyCanvas } from '../../components/agents/panel/PanelTopologyCanvas'
import {
  AgentTypeForm,
  defaultAgentTypeFormValues,
  type AgentTypeFormValues,
} from './AgentTypeForm'
import type {
  AgentDataType,
  AgentEquipmentSlotId,
  AgentType,
  CreateAndAssignResult,
  PanelDialogRequest,
} from '../../types'

const SLUG_PATTERN = /^[a-z0-9-]+$/
const TOKEN_BUDGET_UNIT = 1000

function tokenBudgetKToRaw(value: string): number {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return 1000 * TOKEN_BUDGET_UNIT
  }
  return Math.round(parsed * TOKEN_BUDGET_UNIT)
}

/**
 * Agent Management Panel — unified three-region layout (agent list / live
 * topology / property bar) where an administrator configures an agent from
 * one place. Creation goes through the shared AgentTypeForm dialog; ALL
 * editing (base properties and equipment) happens in the right property bar
 * through the draft composition state, persisted by a single agent-type PUT.
 */
export function AgentManagementPanelPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: agentTypes, isLoading: listLoading, error: listError } = useAgentTypes()

  // ── Agent selection ───────────────────────────────────────────────────────
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null)
  const {
    data: selectedAgent,
    isLoading: detailLoading,
  } = useAgentType(selectedAgentId ?? '')

  // ── Create dialog state (AgentTypeForm host) ──────────────────────────────
  const [createOpen, setCreateOpen] = useState(false)
  const [form, setForm] = useState<AgentTypeFormValues>(defaultAgentTypeFormValues)
  const [saving, setSaving] = useState(false)
  const [dialogError, setDialogError] = useState<unknown>(null)
  const invalidAgentName = !!form.name && !SLUG_PATTERN.test(form.name)

  // ── Delete state ──────────────────────────────────────────────────────────
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false)
  const deleteMutation = useDeleteAgentType()

  // ── Shared dialog host state (one dialog at a time) ───────────────────────
  const [dialogRequest, setDialogRequest] = useState<PanelDialogRequest | null>(null)

  // ── Draft save tray state ─────────────────────────────────────────────────
  const [draftSaving, setDraftSaving] = useState(false)
  const [draftSaveError, setDraftSaveError] = useState<unknown>(null)

  // ── Unsaved-changes guard (draft-driven) ──────────────────────────────────
  const unsaved = useUnsavedChangesDialog()
  const { markUnsaved, markSaved } = unsaved
  const draftApi = useAgentDraftComposition(selectedAgent)

  useEffect(() => {
    if (draftApi.isDirty) {
      markUnsaved()
    } else {
      markSaved()
    }
  }, [draftApi.isDirty, markUnsaved, markSaved])

  const handleSelectAgent = (agentTypeId: string) => {
    // Guarded agent switch — prompt before discarding unsaved draft changes.
    unsaved.handleClose(() => setSelectedAgentId(agentTypeId))
  }

  const handleOpenCreate = () => {
    setForm(defaultAgentTypeFormValues)
    setDialogError(null)
    setCreateOpen(true)
  }

  const handleSaveCreate = async () => {
    setSaving(true)
    try {
      setDialogError(null)
      if (!SLUG_PATTERN.test(form.name)) {
        setDialogError(new Error(t('agents.types.slugNameValidationError')))
        return
      }
      if (form.sop_bindings.length === 0 && form.skill_bindings.length === 0) {
        setDialogError(new Error(t('agents.types.bindings.validationRequired')))
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
        output_data_type_id: form.output_data_type_id || null,
        sop_bindings: form.sop_bindings,
        skill_bindings: form.skill_bindings,
        guardrail_max_iterations: form.guardrail_max_iterations,
        guardrail_max_delegation_depth: form.guardrail_max_delegation_depth,
        guardrail_max_delegated_steps: form.guardrail_max_delegated_steps,
        guardrail_execution_timeout_seconds: form.guardrail_execution_timeout_seconds,
        guardrail_token_budget: tokenBudgetKToRaw(form.guardrail_token_budget),
        guardrail_token_enforcement_mode: form.guardrail_token_enforcement_mode,
        guardrail_token_fallback_mode: form.guardrail_token_fallback_mode,
        guardrail_conversational_token_visibility_mode:
          form.guardrail_conversational_token_visibility_mode,
        guardrail_conversational_continuation_policy:
          form.guardrail_conversational_continuation_policy,
      }
      const res = await apiClient.post<AgentType>('/agents/types', body)
      const savedAgentType = res.data
      setCreateOpen(false)
      setDialogError(null)
      await queryClient.invalidateQueries({ queryKey: ['agents', 'types'] })
      // Surface the saved agent in the sidebar immediately.
      setSelectedAgentId(savedAgentType.id)
    } catch (err) {
      setDialogError(err)
    } finally {
      setSaving(false)
    }
  }

  const handleCloseCreate = () => {
    setCreateOpen(false)
    setDialogError(null)
  }

  const handleConfirmDelete = async () => {
    if (!selectedAgent) return
    try {
      const deletedId = selectedAgent.id
      await deleteMutation.mutateAsync(deletedId)
      setConfirmDeleteOpen(false)
      // True deletion: drop the selection so the same name can be recreated.
      setSelectedAgentId((current) => (current === deletedId ? null : current))
      await queryClient.invalidateQueries({ queryKey: ['agents', 'types'] })
    } catch {
      // Deletion errors surface via the delete mutation's error state below.
    }
  }

  // ── Create-and-assign: route created resources into the draft ─────────────
  const assignCreatedResource = (slotId: AgentEquipmentSlotId, result: CreateAndAssignResult) => {
    switch (slotId) {
      case 'role':
        draftApi.setRole(result.id)
        break
      case 'identity':
        draftApi.setIdentity(result.id)
        break
      case 'skills':
        draftApi.assignSkill(result.id)
        break
      case 'sops':
        draftApi.assignSop(result.id)
        break
      case 'input_data_type':
        void (async () => {
          // Compose the typed input schema from the freshly created data type.
          try {
            const { data: created } = await apiClient.get<AgentDataType>(`/data-types/${result.id}`)
            draftApi.setInputType('typed')
            draftApi.setInputSchema(dataTypeToInputSchema(created))
          } catch {
            draftApi.setInputType('typed')
          }
        })()
        break
      case 'output_data_type':
        draftApi.setOutputType('typed')
        draftApi.setOutputDataType(result.id)
        break
      case 'model':
        // Assign the first enabled model of the newly created config, if any.
        if (result.enabledModelIds && result.enabledModelIds.length > 0) {
          draftApi.setModel(result.enabledModelIds[0])
        }
        break
      default:
        break
    }
  }

  const handleDraftSave = async () => {
    setDraftSaving(true)
    try {
      setDraftSaveError(null)
      await draftApi.save()
    } catch (err) {
      setDraftSaveError(err)
    } finally {
      setDraftSaving(false)
    }
  }

  const handleDraftDiscard = () => {
    setDraftSaveError(null)
    draftApi.discard()
  }

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Box>
        <Typography variant="h4" fontWeight={700}>
          {t('agents.panel.title')}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {t('agents.panel.subtitle')}
        </Typography>
      </Box>

      <Box
        sx={{
          flex: 1,
          minHeight: 0,
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', md: '280px 1fr 360px' },
          gap: 2,
          alignItems: 'stretch',
        }}
      >
        {/* ── Region 1: agent list sidebar ─────────────────────────────── */}
        <Paper sx={{ p: 2, minHeight: 0, display: 'flex' }} elevation={1}>
          <AgentListSidebar
            agents={agentTypes ?? []}
            loading={listLoading}
            error={listError}
            selectedId={selectedAgentId}
            onSelect={handleSelectAgent}
            onCreate={handleOpenCreate}
          />
        </Paper>

        {/* ── Region 2: header card + live topology ────────────────────── */}
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, minHeight: 0 }}>
          <Paper sx={{ p: 2 }} elevation={1}>
            {detailLoading && selectedAgentId && <CircularProgress size={24} />}
            {!selectedAgentId && (
              <Typography variant="body2" color="text.secondary">
                {t('agents.panel.selectAgentPrompt')}
              </Typography>
            )}
            {selectedAgent && (
              <Box display="flex" alignItems="flex-start" justifyContent="space-between" gap={2}>
                <Box minWidth={0}>
                  <Typography variant="h6" fontWeight={600} noWrap>
                    {selectedAgent.name}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {selectedAgent.description ?? t('agents.panel.headerDescription')}
                  </Typography>
                  <Box mt={1} display="flex" gap={1} flexWrap="wrap">
                    <Chip
                      label={selectedAgent.input_type}
                      size="small"
                      variant="outlined"
                    />
                    {selectedAgent.model_id && (
                      <Chip label={selectedAgent.model_id} size="small" variant="outlined" />
                    )}
                  </Box>
                </Box>
                <Box display="flex" gap={0.5} flexShrink={0}>
                  <Tooltip title={t('app.delete')}>
                    <IconButton
                      size="small"
                      aria-label={t('app.delete')}
                      onClick={() => setConfirmDeleteOpen(true)}
                    >
                      <DeleteIcon fontSize="small" color="error" />
                    </IconButton>
                  </Tooltip>
                </Box>
              </Box>
            )}
          </Paper>

          <Paper sx={{ p: 2, flex: 1, minHeight: 0, overflowY: 'auto' }} elevation={1}>
            {selectedAgent ? (
              <PanelTopologyCanvas
                agentName={selectedAgent.name}
                draft={draftApi.draft}
                isDirty={draftApi.isDirty}
              />
            ) : (
              <>
                <Typography variant="subtitle1" fontWeight={600}>
                  {t('agents.panel.topology')}
                </Typography>
                <Typography variant="body2" color="text.secondary" py={4} textAlign="center">
                  {t('agents.panel.selectAgentPrompt')}
                </Typography>
              </>
            )}
          </Paper>
        </Box>

        {/* ── Region 3: property bar (properties + slots + tray) ────────── */}
        <Paper
          sx={{
            p: 2,
            minHeight: 0,
            display: 'flex',
            flexDirection: 'column',
            // Fixed column width: never grow with content, never scroll
            // horizontally (long names truncate with ellipsis instead).
            minWidth: 0,
            overflowX: 'hidden',
          }}
          elevation={1}
        >
          <Box sx={{ flex: 1, minHeight: 0, overflowY: 'auto', overflowX: 'hidden', pr: 0.5 }}>
            <AgentPropertiesSection draftApi={draftApi} />
            <Typography variant="subtitle1" fontWeight={600} gutterBottom sx={{ mt: 2 }}>
              {t('agents.panel.equipment')}
            </Typography>
            <EquipmentSlots draftApi={draftApi} onOpenDialog={setDialogRequest} />
          </Box>
          <PendingChangesTray
            dirty={draftApi.isDirty}
            changedSlotIds={draftApi.changedSlotIds}
            propertiesChanged={draftApi.propertiesChanged}
            saving={draftSaving}
            saveDisabled={draftApi.isNameInvalid}
            saveError={draftSaveError}
            onSave={() => void handleDraftSave()}
            onDiscard={handleDraftDiscard}
          />
        </Paper>
      </Box>

      {/* Shared module dialogs (inline create-and-assign) */}
      <SharedDialogHost
        request={dialogRequest}
        onClose={() => setDialogRequest(null)}
        onCreateAndAssign={assignCreatedResource}
      />

      {/* Create agent dialog — hosts the shared AgentTypeForm (editing
          happens exclusively in the right property bar, not here) */}
      <Dialog
        open={createOpen}
        onClose={handleCloseCreate}
        maxWidth="lg"
        fullWidth
      >
        <DialogTitle>{t('agents.createType')}</DialogTitle>
        <DialogContent dividers>
          {dialogError ? (
            <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
          ) : null}
          {saving ? (
            <Box display="flex" flexDirection="column" alignItems="center" py={4}>
              <CircularProgress />
            </Box>
          ) : (
            <Box pt={1}>
              <AgentTypeForm values={form} onChange={setForm} />
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseCreate} disabled={saving}>
            {t('app.cancel')}
          </Button>
          <Button
            variant="contained"
            onClick={() => void handleSaveCreate()}
            disabled={
              !form.name.trim() ||
              invalidAgentName ||
              saving ||
              (form.sop_bindings.length === 0 && form.skill_bindings.length === 0)
            }
          >
            {t('app.save')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete confirmation */}
      <ConfirmDialog
        open={confirmDeleteOpen}
        title={t('app.delete')}
        message={t('agents.panel.deleteConfirm', { name: selectedAgent?.name ?? '' })}
        confirmText={t('app.delete')}
        confirmColor="error"
        onConfirm={() => void handleConfirmDelete()}
        onCancel={() => setConfirmDeleteOpen(false)}
      />

      {/* Unsaved-changes confirmation for guarded actions (agent switch) */}
      <unsaved.ConfirmationDialog />
    </Box>
  )
}
