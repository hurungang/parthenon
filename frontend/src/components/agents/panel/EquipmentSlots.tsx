import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Chip,
  Divider,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward'
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward'
import CloseIcon from '@mui/icons-material/Close'
import LockIcon from '@mui/icons-material/Lock'
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline'
import PersonAddAltIcon from '@mui/icons-material/PersonAddAlt'
import { useQuery } from '@tanstack/react-query'
import apiClient from '../../../api/apiClient'
import { useDataTypes } from '../../../hooks/useDataTypes'
import { useAvailableModels } from '../../../hooks/useAvailableModels'
import type { UseAgentDraftCompositionResult } from '../../../hooks/useAgentDraftComposition'
import type { SxProps, Theme } from '@mui/material'
import type {
  AgentDataType,
  AgentDraftComposition,
  AgentEquipmentSlotId,
  AgentIdentity,
  AgentInputType,
  AgentRole,
  EquipmentSlotDefinition,
  PanelDialogRequest,
  Skill,
  Sop,
} from '../../../types'

/**
 * Chip sizing for equipped slot values: the chip fills (but never exceeds) its
 * container and is allowed to shrink below its content width (minWidth: 0),
 * so the MuiChip-label ellipsis truncates long resource names instead of
 * forcing the property bar column to scroll horizontally. Pair every chip
 * using this with a <Tooltip> so the full name stays readable on hover.
 */
const EQUIPPED_CHIP_SX: SxProps<Theme> = {
  maxWidth: '100%',
  minWidth: 0,
  '& .MuiChip-label': {
    display: 'block',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
}

/** The seven panel slots with their gating resource types (existing manifest entries). */
export const EQUIPMENT_SLOT_DEFINITIONS: EquipmentSlotDefinition[] = [
  {
    id: 'role',
    resourceType: 'agent::roles',
    labelKey: 'agents.panel.slots.role.label',
    hintKey: 'agents.panel.slots.role.hint',
    multi: false,
  },
  {
    id: 'identity',
    resourceType: 'agent::identities',
    labelKey: 'agents.panel.slots.identity.label',
    hintKey: 'agents.panel.slots.identity.hint',
    multi: false,
  },
  {
    id: 'skills',
    resourceType: 'agent::skills',
    labelKey: 'agents.panel.slots.skills.label',
    hintKey: 'agents.panel.slots.skills.hint',
    multi: true,
  },
  {
    id: 'sops',
    resourceType: 'agent::sops',
    labelKey: 'agents.panel.slots.sops.label',
    hintKey: 'agents.panel.slots.sops.hint',
    multi: true,
  },
  {
    id: 'input_data_type',
    resourceType: 'agent::data_types',
    labelKey: 'agents.panel.slots.input_data_type.label',
    hintKey: 'agents.panel.slots.input_data_type.hint',
    multi: false,
  },
  {
    id: 'output_data_type',
    resourceType: 'agent::data_types',
    labelKey: 'agents.panel.slots.output_data_type.label',
    hintKey: 'agents.panel.slots.output_data_type.hint',
    multi: false,
  },
  {
    id: 'model',
    resourceType: 'agent::model_configs',
    labelKey: 'agents.panel.slots.model.label',
    hintKey: 'agents.panel.slots.model.hint',
    multi: false,
  },
]

/** Maps an Agent Data Type registry entry to a JSON-Schema object for typed input. */
export function dataTypeToInputSchema(dataType: AgentDataType): Record<string, unknown> {
  const properties: Record<string, unknown> = {}
  const required: string[] = []
  for (const field of dataType.fields) {
    const propertyType =
      field.type === 'number'
        ? 'number'
        : field.type === 'boolean'
          ? 'boolean'
          : 'string'
    const property: Record<string, unknown> = { type: propertyType }
    if (field.type === 'enum' && field.enum_values) {
      property.enum = field.enum_values
    }
    if (field.description) {
      property.description = field.description
    }
    properties[field.name] = property
    if (field.required) {
      required.push(field.name)
    }
  }
  const schema: Record<string, unknown> = { type: 'object', properties }
  if (required.length > 0) {
    schema.required = required
  }
  return schema
}

interface EquipmentSlotsProps {
  draftApi: UseAgentDraftCompositionResult
  /** Opens one of the shared module dialogs (create-new flows). */
  onOpenDialog: (request: PanelDialogRequest) => void
}

/**
 * The seven permission-gated equipment slots of the Agent Management Panel.
 * Each slot renders the current draft value(s), assign-existing / create-new
 * actions, dashed placeholders for empty slots, the locked output slot for
 * conversational agents, and disabled-with-explanation actions when the slot's
 * backing list query is denied (403 graceful degradation).
 */
export function EquipmentSlots({ draftApi, onOpenDialog }: EquipmentSlotsProps) {
  const { draft } = draftApi

  // Backing list queries — same endpoints/cache keys as the source module pages.
  const { data: roles, error: rolesError } = useQuery<AgentRole[]>({
    queryKey: ['agents', 'roles'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentRole[]>('/agents/roles')
      return data
    },
  })
  const { data: identities, error: identitiesError } = useQuery<AgentIdentity[]>({
    queryKey: ['agents', 'identities'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentIdentity[]>('/agents/identities')
      return data
    },
  })
  const { data: skills, error: skillsError } = useQuery<Skill[]>({
    queryKey: ['skills'],
    queryFn: async () => {
      const { data } = await apiClient.get<Skill[]>('/skills')
      return data
    },
  })
  const { data: sops, error: sopsError } = useQuery<Sop[]>({
    queryKey: ['sops'],
    queryFn: async () => {
      const { data } = await apiClient.get<Sop[]>('/sops')
      return data
    },
  })
  const { data: dataTypesPage, error: dataTypesError } = useDataTypes({ page: 1, page_size: 100 })
  const dataTypes = dataTypesPage?.items ?? []
  const { data: availableModels, error: modelsError } = useAvailableModels()

  const slotErrors: Record<AgentEquipmentSlotId, unknown> = {
    role: rolesError,
    identity: identitiesError,
    skills: skillsError,
    sops: sopsError,
    input_data_type: dataTypesError,
    output_data_type: dataTypesError,
    model: modelsError,
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
      {EQUIPMENT_SLOT_DEFINITIONS.map((slot) => (
        <SlotCard
          key={slot.id}
          slot={slot}
          error={slotErrors[slot.id]}
          draft={draft}
          onOpenDialog={onOpenDialog}
          draftApi={draftApi}
          roles={roles ?? []}
          identities={identities ?? []}
          skills={skills ?? []}
          sops={sops ?? []}
          dataTypes={dataTypes}
          availableModels={availableModels ?? []}
        />
      ))}
    </Box>
  )
}

// ── Slot card ─────────────────────────────────────────────────────────────────

interface SlotCardProps {
  slot: EquipmentSlotDefinition
  error: unknown
  draft: AgentDraftComposition
  draftApi: UseAgentDraftCompositionResult
  onOpenDialog: (request: PanelDialogRequest) => void
  roles: AgentRole[]
  identities: AgentIdentity[]
  skills: Skill[]
  sops: Sop[]
  dataTypes: AgentDataType[]
  availableModels: { model_id: string; config_display_name: string }[]
}

function SlotCard({
  slot,
  error,
  draft,
  draftApi,
  onOpenDialog,
  roles,
  identities,
  skills,
  sops,
  dataTypes,
  availableModels,
}: SlotCardProps) {
  const { t } = useTranslation()
  const [assigning, setAssigning] = useState(false)
  const denied = error != null

  // Conversational lock: conversational agents do not support typed outputs.
  const locked = slot.id === 'output_data_type' && draft.inputType === 'conversation'

  const createRequest: PanelDialogRequest | null =
    slot.id === 'role'
      ? { kind: 'role' }
      : slot.id === 'identity'
        ? { kind: 'identity' }
        : slot.id === 'skills'
          ? { kind: 'skill' }
          : slot.id === 'sops'
            ? { kind: 'sop' }
            : slot.id === 'input_data_type'
              ? { kind: 'input_data_type' }
              : slot.id === 'output_data_type'
                ? { kind: 'output_data_type' }
                : slot.id === 'model'
                  ? { kind: 'model_config' }
                  : null

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.5,
        borderStyle: 'dashed',
        borderColor: denied ? 'warning.main' : 'divider',
      }}
    >
      <Box display="flex" alignItems="center" justifyContent="space-between" gap={1}>
        <Tooltip title={t(slot.hintKey)}>
          <Typography variant="subtitle2" fontWeight={600}>
            {t(slot.labelKey)}
          </Typography>
        </Tooltip>
        {locked && <LockIcon fontSize="small" color="disabled" />}
      </Box>

      {/* Slot body — current draft value(s) or empty placeholder */}
      <Box sx={{ mt: 1, minHeight: 36 }}>
        {denied ? (
          <Typography variant="caption" color="text.secondary" sx={{ fontStyle: 'italic' }}>
            {t('agents.panel.permissionNote', { resourceType: slot.resourceType })}
          </Typography>
        ) : locked ? (
          <Typography variant="caption" color="text.secondary" sx={{ fontStyle: 'italic' }}>
            {t('agents.panel.lockedOutputNote')}
          </Typography>
        ) : (
          <SlotBody
            slot={slot}
            draft={draft}
            draftApi={draftApi}
            roles={roles}
            identities={identities}
            skills={skills}
            sops={sops}
            dataTypes={dataTypes}
            availableModels={availableModels}
          />
        )}
      </Box>

      {/* Slot actions */}
      {!denied && !locked && createRequest && (
        <>
          <Divider sx={{ my: 1 }} />
          <Box display="flex" gap={1} flexWrap="wrap">
            {!assigning ? (
              <Button
                size="small"
                startIcon={<PersonAddAltIcon />}
                onClick={() => setAssigning(true)}
                disabled={denied}
              >
                {t('agents.panel.assignExisting')}
              </Button>
            ) : (
              <Button size="small" onClick={() => setAssigning(false)}>
                {t('app.cancel')}
              </Button>
            )}
            <Button
              size="small"
              startIcon={<AddIcon />}
              onClick={() => onOpenDialog(createRequest)}
              disabled={denied}
            >
              {t('agents.panel.createNew')}
            </Button>
          </Box>
          {assigning && (
            <Box sx={{ mt: 1 }}>
              <AssignExistingPicker
                slot={slot}
                draft={draft}
                draftApi={draftApi}
                roles={roles}
                identities={identities}
                skills={skills}
                sops={sops}
                dataTypes={dataTypes}
                availableModels={availableModels}
                onDone={() => setAssigning(false)}
              />
            </Box>
          )}
        </>
      )}
    </Paper>
  )
}

// ── Slot body (current values) ────────────────────────────────────────────────

interface SlotBodyProps extends Omit<SlotCardProps, 'error' | 'onOpenDialog'> {}

function SlotBody({
  slot,
  draft,
  draftApi,
  roles,
  identities,
  skills,
  sops,
  dataTypes,
  availableModels,
}: SlotBodyProps) {
  const { t } = useTranslation()

  const emptyPlaceholder = (
    <Typography
      variant="caption"
      color="text.secondary"
      sx={{
        display: 'block',
        border: '1px dashed',
        borderColor: 'divider',
        borderRadius: 1,
        px: 1,
        py: 1,
        textAlign: 'center',
        fontStyle: 'italic',
      }}
    >
      {t('agents.panel.emptySlot')}
    </Typography>
  )

  if (slot.id === 'role') {
    const role = roles.find((r) => r.id === draft.roleId)
    return role ? (
      <Tooltip title={role.name}>
        <Chip
          label={role.name}
          size="small"
          onDelete={() => draftApi.setRole(null)}
          deleteIcon={<CloseIcon fontSize="small" aria-label={t('agents.panel.remove')} />}
          sx={EQUIPPED_CHIP_SX}
        />
      </Tooltip>
    ) : (
      emptyPlaceholder
    )
  }

  if (slot.id === 'identity') {
    const identity = identities.find((i) => i.id === draft.identityId)
    return identity ? (
      <Tooltip title={identity.name}>
        <Chip
          label={identity.name}
          size="small"
          color="warning"
          variant="outlined"
          onDelete={() => draftApi.setIdentity(null)}
          deleteIcon={<CloseIcon fontSize="small" aria-label={t('agents.panel.remove')} />}
          sx={EQUIPPED_CHIP_SX}
        />
      </Tooltip>
    ) : (
      emptyPlaceholder
    )
  }

  if (slot.id === 'skills') {
    if (draft.skillBindings.length === 0) return emptyPlaceholder
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
        {[...draft.skillBindings]
          .sort((a, b) => a.order - b.order)
          .map((binding) => {
            const skill = skills.find((s) => s.id === binding.skill_id)
            const skillLabel = skill?.name ?? binding.skill_id
            return (
              <Box
                key={binding.skill_id}
                display="flex"
                alignItems="center"
                gap={0.5}
                sx={{ minWidth: 0 }}
              >
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ minWidth: 20, flexShrink: 0 }}
                >
                  #{binding.order}
                </Typography>
                <Tooltip title={skillLabel}>
                  <Chip
                    label={skillLabel}
                    size="small"
                    color="secondary"
                    variant="outlined"
                    sx={EQUIPPED_CHIP_SX}
                  />
                </Tooltip>
                <IconButton
                  size="small"
                  sx={{ flexShrink: 0 }}
                  aria-label={t('agents.panel.bindingOrderUp')}
                  disabled={binding.order === 1}
                  onClick={() => draftApi.moveSkill(binding.skill_id, 'up')}
                >
                  <ArrowUpwardIcon sx={{ fontSize: 14 }} />
                </IconButton>
                <IconButton
                  size="small"
                  sx={{ flexShrink: 0 }}
                  aria-label={t('agents.panel.bindingOrderDown')}
                  disabled={binding.order === draft.skillBindings.length}
                  onClick={() => draftApi.moveSkill(binding.skill_id, 'down')}
                >
                  <ArrowDownwardIcon sx={{ fontSize: 14 }} />
                </IconButton>
                <IconButton
                  size="small"
                  sx={{ flexShrink: 0 }}
                  aria-label={t('agents.panel.remove')}
                  onClick={() => draftApi.unassignSkill(binding.skill_id)}
                >
                  <CloseIcon sx={{ fontSize: 14 }} />
                </IconButton>
              </Box>
            )
          })}
      </Box>
    )
  }

  if (slot.id === 'sops') {
    if (draft.sopBindings.length === 0) return emptyPlaceholder
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
        {[...draft.sopBindings]
          .sort((a, b) => a.order - b.order)
          .map((binding) => {
            const sop = sops.find((s) => s.id === binding.sop_id)
            const sopLabel = sop?.name ?? binding.sop_id
            return (
              <Box
                key={binding.sop_id}
                display="flex"
                alignItems="center"
                gap={0.5}
                sx={{ minWidth: 0 }}
              >
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ minWidth: 20, flexShrink: 0 }}
                >
                  #{binding.order}
                </Typography>
                <Tooltip title={sopLabel}>
                  <Chip
                    label={sopLabel}
                    size="small"
                    color="primary"
                    variant="outlined"
                    sx={EQUIPPED_CHIP_SX}
                  />
                </Tooltip>
                <IconButton
                  size="small"
                  sx={{ flexShrink: 0 }}
                  aria-label={t('agents.panel.bindingOrderUp')}
                  disabled={binding.order === 1}
                  onClick={() => draftApi.moveSop(binding.sop_id, 'up')}
                >
                  <ArrowUpwardIcon sx={{ fontSize: 14 }} />
                </IconButton>
                <IconButton
                  size="small"
                  sx={{ flexShrink: 0 }}
                  aria-label={t('agents.panel.bindingOrderDown')}
                  disabled={binding.order === draft.sopBindings.length}
                  onClick={() => draftApi.moveSop(binding.sop_id, 'down')}
                >
                  <ArrowDownwardIcon sx={{ fontSize: 14 }} />
                </IconButton>
                <IconButton
                  size="small"
                  sx={{ flexShrink: 0 }}
                  aria-label={t('agents.panel.remove')}
                  onClick={() => draftApi.unassignSop(binding.sop_id)}
                >
                  <CloseIcon sx={{ fontSize: 14 }} />
                </IconButton>
              </Box>
            )
          })}
      </Box>
    )
  }

  if (slot.id === 'input_data_type') {
    const inputTypeLabels: Record<AgentInputType, string> = {
      none: t('agents.panel.noInputType'),
      typed: t('agents.types.inputTyped'),
      conversation: t('agents.panel.inputTypeConversation'),
    }
    const appliedType = dataTypes.find(
      (dt) => JSON.stringify(dataTypeToInputSchema(dt)) === JSON.stringify(draft.inputSchema),
    )
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        <FormControl size="small" fullWidth>
          <InputLabel id="panel-input-type-label">{t('agents.types.inputType')}</InputLabel>
          <Select
            labelId="panel-input-type-label"
            value={draft.inputType}
            label={t('agents.types.inputType')}
            onChange={(e) => draftApi.setInputType(e.target.value as AgentInputType)}
          >
            <MenuItem value="none">{inputTypeLabels.none}</MenuItem>
            <MenuItem value="typed">{inputTypeLabels.typed}</MenuItem>
            <MenuItem value="conversation">{inputTypeLabels.conversation}</MenuItem>
          </Select>
        </FormControl>
        {draft.inputType === 'typed' &&
          (appliedType ? (
            <Tooltip title={appliedType.name}>
              <Chip
                label={appliedType.name}
                size="small"
                color="success"
                variant="outlined"
                onDelete={() => draftApi.setInputSchema(null)}
                deleteIcon={<CloseIcon fontSize="small" aria-label={t('agents.panel.remove')} />}
                sx={EQUIPPED_CHIP_SX}
              />
            </Tooltip>
          ) : draft.inputSchema ? (
            <Tooltip title={t('agents.types.inputSchema')}>
              <Chip
                label={t('agents.types.inputSchema')}
                size="small"
                variant="outlined"
                onDelete={() => draftApi.setInputSchema(null)}
                deleteIcon={<CloseIcon fontSize="small" aria-label={t('agents.panel.remove')} />}
                sx={EQUIPPED_CHIP_SX}
              />
            </Tooltip>
          ) : (
            emptyPlaceholder
          ))}
      </Box>
    )
  }

  if (slot.id === 'output_data_type') {
    const dataType = dataTypes.find((dt) => dt.id === draft.outputDataTypeId)
    return dataType ? (
      <Tooltip title={dataType.name}>
        <Chip
          label={dataType.name}
          size="small"
          color="info"
          variant="outlined"
          onDelete={() => draftApi.setOutputDataType(null)}
          deleteIcon={<CloseIcon fontSize="small" aria-label={t('agents.panel.remove')} />}
          sx={EQUIPPED_CHIP_SX}
        />
      </Tooltip>
    ) : (
      emptyPlaceholder
    )
  }

  if (slot.id === 'model') {
    const model = availableModels.find((m) => m.model_id === draft.modelId)
    const modelLabel = model ? `${model.model_id} (${model.config_display_name})` : draft.modelId
    return draft.modelId ? (
      <Tooltip title={modelLabel}>
        <Chip
          label={modelLabel}
          size="small"
          icon={<PlayCircleOutlineIcon />}
          onDelete={() => draftApi.setModel(null)}
          deleteIcon={<CloseIcon fontSize="small" aria-label={t('agents.panel.remove')} />}
          sx={EQUIPPED_CHIP_SX}
        />
      </Tooltip>
    ) : (
      emptyPlaceholder
    )
  }

  return null
}

// ── Assign-existing picker ────────────────────────────────────────────────────

interface AssignExistingPickerProps {
  slot: EquipmentSlotDefinition
  draft: AgentDraftComposition
  draftApi: UseAgentDraftCompositionResult
  roles: AgentRole[]
  identities: AgentIdentity[]
  skills: Skill[]
  sops: Sop[]
  dataTypes: AgentDataType[]
  availableModels: { model_id: string; config_display_name: string }[]
  onDone: () => void
}

function AssignExistingPicker({
  slot,
  draft,
  draftApi,
  roles,
  identities,
  skills,
  sops,
  dataTypes,
  availableModels,
  onDone,
}: AssignExistingPickerProps) {
  const { t } = useTranslation()
  const [value, setValue] = useState('')

  const pick = (id: string) => {
    if (!id) return
    if (slot.id === 'role') draftApi.setRole(id)
    else if (slot.id === 'identity') draftApi.setIdentity(id)
    else if (slot.id === 'skills') draftApi.assignSkill(id)
    else if (slot.id === 'sops') draftApi.assignSop(id)
    else if (slot.id === 'input_data_type') {
      const dataType = dataTypes.find((dt) => dt.id === id)
      if (dataType) {
        draftApi.setInputType('typed')
        draftApi.setInputSchema(dataTypeToInputSchema(dataType))
      }
    } else if (slot.id === 'output_data_type') {
      draftApi.setOutputType('typed')
      draftApi.setOutputDataType(id)
    } else if (slot.id === 'model') {
      draftApi.setModel(id)
    }
    setValue('')
    onDone()
  }

  const options: { id: string; label: string }[] =
    slot.id === 'role'
      ? roles.map((r) => ({ id: r.id, label: r.name }))
      : slot.id === 'identity'
        ? identities.map((i) => ({ id: i.id, label: i.name }))
        : slot.id === 'skills'
          ? skills
              .filter((s) => !draft.skillBindings.some((b) => b.skill_id === s.id))
              .map((s) => ({ id: s.id, label: s.name }))
          : slot.id === 'sops'
            ? sops
                .filter((s) => !draft.sopBindings.some((b) => b.sop_id === s.id))
                .map((s) => ({ id: s.id, label: s.name }))
            : slot.id === 'input_data_type' || slot.id === 'output_data_type'
              ? dataTypes.map((dt) => ({ id: dt.id, label: dt.name }))
              : slot.id === 'model'
                ? availableModels.map((m) => ({
                    id: m.model_id,
                    label: `${m.model_id} (${m.config_display_name})`,
                  }))
                : []

  const label = t(slot.labelKey)

  return (
    <FormControl size="small" fullWidth>
      <InputLabel id={`panel-assign-${slot.id}-label`}>{label}</InputLabel>
      <Select
        labelId={`panel-assign-${slot.id}-label`}
        value={value}
        label={label}
        onChange={(e) => pick(e.target.value)}
        autoWidth
        MenuProps={{
          sx: { maxHeight: 360 },
          // Cap the dropdown at the property-bar column width so long
          // resource names truncate instead of widening past the panel.
          slotProps: { paper: { sx: { maxWidth: 360 } } },
        }}
      >
        <MenuItem value="" disabled>
          <em>{t('agents.types.bindings.selectPlaceholder')}</em>
        </MenuItem>
        {options.map((option) => (
          <MenuItem key={option.id} value={option.id}>
            <Tooltip title={option.label}>
              <Typography variant="body2" noWrap sx={{ minWidth: 0 }}>
                {option.label}
              </Typography>
            </Tooltip>
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  )
}
