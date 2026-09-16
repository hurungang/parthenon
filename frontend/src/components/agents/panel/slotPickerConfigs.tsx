import apiClient from '../../../api/apiClient'
import { dataTypeToInputSchema } from './EquipmentSlots'
import type { ResourcePickerItem } from './ResourcePickerDialog'
import type { UseAgentDraftCompositionResult } from '../../../hooks/useAgentDraftComposition'
import type {
  AgentDraftComposition,
  AgentEquipmentSlotId,
  AgentIdentity,
  AgentRole,
  CreateAndAssignResult,
  DataTypeListResponse,
  ModelConfig,
  PanelDialogRequest,
  Skill,
  Sop,
} from '../../../types'

/**
 * Draft mutations + current draft a picker selection is applied with.
 * Narrowed on purpose: the picker can only touch the slot draft setters.
 */
export type SlotDraftApi = Pick<
  UseAgentDraftCompositionResult,
  | 'draft'
  | 'setRole'
  | 'setIdentity'
  | 'assignSkill'
  | 'unassignSkill'
  | 'assignSop'
  | 'unassignSop'
  | 'setInputType'
  | 'setInputSchema'
  | 'setOutputType'
  | 'setOutputDataType'
  | 'setModel'
>

/**
 * Per-slot binding between an equipment slot and the generic
 * ResourcePickerDialog: which existing list endpoint feeds the picker, how
 * rows render, what is pre-selected from the draft, how the confirmed
 * selection is applied, and which create-new flow the footer button opens.
 */
export interface SlotPickerConfig {
  /** Equipment slot this config binds (ties labelKey + multi flag). */
  slotId: AgentEquipmentSlotId
  /** i18n key of the slot label — the dialog title is "Assign {{resource}}". */
  labelKey: string
  /**
   * react-query cache key — shared with the slot cards' list queries, so
   * invalidations from the shared module dialogs refresh the open picker.
   */
  queryKey: readonly unknown[]
  /**
   * Fetches the slot's existing list endpoint (full list; the picker
   * client-side filters and paginates — no new server endpoints).
   */
  queryFn: () => Promise<unknown>
  /** Maps the raw list payload to picker rows. */
  toItems: (data: unknown) => ResourcePickerItem[]
  /** Multi slots (skills, SOPs) toggle checkboxes and reconcile add/remove. */
  multi: boolean
  /** Currently equipped ids from the draft (pre-selection). */
  getSelectedIds: (draft: AgentDraftComposition, items: ResourcePickerItem[]) => string[]
  /** Applies the confirmed selection to the draft (draft-only, no API calls). */
  apply: (draftApi: SlotDraftApi, ids: string[], items: ResourcePickerItem[]) => void
  /** Create-new flow request routed to the shared dialog host. */
  createRequest: PanelDialogRequest
  /**
   * Pre-selection after an inline create (the model slot maps the created
   * config to its first enabled model, mirroring the card create flow).
   */
  createdSelectionIds: (result: CreateAndAssignResult) => string[]
}

/**
 * Type-safe config builder: each slot defines its config against its real
 * payload type; the builder narrows the registry's `unknown` boundary in one
 * place so the per-slot definitions stay fully typed.
 */
function defineSlotPickerConfig<TPayload>(config: {
  slotId: AgentEquipmentSlotId
  labelKey: string
  queryKey: readonly unknown[]
  queryFn: () => Promise<TPayload>
  toItems: (data: TPayload) => ResourcePickerItem[]
  multi: boolean
  getSelectedIds: (draft: AgentDraftComposition, items: ResourcePickerItem[]) => string[]
  apply: (draftApi: SlotDraftApi, ids: string[], items: ResourcePickerItem[]) => void
  createRequest: PanelDialogRequest
  createdSelectionIds: (result: CreateAndAssignResult) => string[]
}): SlotPickerConfig {
  return {
    ...config,
    queryFn: config.queryFn as () => Promise<unknown>,
    toItems: (data: unknown) => config.toItems(data as TPayload),
  }
}

/** Single-slot apply: replace the draft value with the picked id. */
function firstId(ids: string[]): string | null {
  return ids.length > 0 ? ids[0] : null
}

/** Multi-slot reconcile: unassign removed ids, then append added ids at the end. */
function reconcileMulti(
  draftApi: SlotDraftApi,
  ids: string[],
  getBoundIds: (draft: AgentDraftComposition) => string[],
  unassign: (id: string) => void,
  assign: (id: string) => void,
): void {
  const target = new Set(ids)
  for (const bound of getBoundIds(draftApi.draft)) {
    if (!target.has(bound)) unassign(bound)
  }
  const bound = new Set(getBoundIds(draftApi.draft))
  for (const id of ids) {
    if (!bound.has(id)) assign(id)
  }
}

/** Resolves the applied input data type by comparing composed JSON schemas. */
function resolveAppliedInputDataType(
  draft: AgentDraftComposition,
  items: ResourcePickerItem[],
): string | null {
  if (draft.inputType !== 'typed' || draft.inputSchema == null) return null
  const serialized = JSON.stringify(draft.inputSchema)
  const applied = items.find(
    (item) =>
      item.dataType != null &&
      JSON.stringify(dataTypeToInputSchema(item.dataType)) === serialized,
  )
  return applied ? applied.id : null
}

/**
 * The seven slot → picker bindings. Query keys mirror the slot cards' list
 * queries exactly (['agents','roles'], ['skills'], ['data-types', …], …) so
 * the picker shares their cache and refreshes with the same invalidations.
 */
export const SLOT_PICKER_CONFIGS: Record<AgentEquipmentSlotId, SlotPickerConfig> = {
  role: defineSlotPickerConfig<AgentRole[]>({
    slotId: 'role',
    labelKey: 'agents.panel.slots.role.label',
    queryKey: ['agents', 'roles'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentRole[]>('/agents/roles')
      return data
    },
    toItems: (roles) =>
      roles.map((role) => ({ id: role.id, label: role.name, sublabel: role.description })),
    multi: false,
    getSelectedIds: (draft) => (draft.roleId ? [draft.roleId] : []),
    apply: (draftApi, ids) => draftApi.setRole(firstId(ids)),
    createRequest: { kind: 'role' },
    createdSelectionIds: (result) => [result.id],
  }),

  identity: defineSlotPickerConfig<AgentIdentity[]>({
    slotId: 'identity',
    labelKey: 'agents.panel.slots.identity.label',
    queryKey: ['agents', 'identities'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentIdentity[]>('/agents/identities')
      return data
    },
    toItems: (identities) =>
      identities.map((identity) => ({
        id: identity.id,
        label: identity.name,
        sublabel: identity.realm_username ?? identity.realm_name,
      })),
    multi: false,
    getSelectedIds: (draft) => (draft.identityId ? [draft.identityId] : []),
    apply: (draftApi, ids) => draftApi.setIdentity(firstId(ids)),
    createRequest: { kind: 'identity' },
    createdSelectionIds: (result) => [result.id],
  }),

  skills: defineSlotPickerConfig<Skill[]>({
    slotId: 'skills',
    labelKey: 'agents.panel.slots.skills.label',
    queryKey: ['skills'],
    queryFn: async () => {
      const { data } = await apiClient.get<Skill[]>('/skills')
      return data
    },
    toItems: (skills) =>
      skills.map((skill) => ({ id: skill.id, label: skill.name, sublabel: skill.description })),
    multi: true,
    getSelectedIds: (draft) => draft.skillBindings.map((binding) => binding.skill_id),
    apply: (draftApi, ids) =>
      reconcileMulti(
        draftApi,
        ids,
        (draft) => draft.skillBindings.map((binding) => binding.skill_id),
        draftApi.unassignSkill,
        draftApi.assignSkill,
      ),
    createRequest: { kind: 'skill' },
    createdSelectionIds: (result) => [result.id],
  }),

  sops: defineSlotPickerConfig<Sop[]>({
    slotId: 'sops',
    labelKey: 'agents.panel.slots.sops.label',
    queryKey: ['sops'],
    queryFn: async () => {
      const { data } = await apiClient.get<Sop[]>('/sops')
      return data
    },
    toItems: (sops) =>
      sops.map((sop) => ({ id: sop.id, label: sop.name, sublabel: sop.description })),
    multi: true,
    getSelectedIds: (draft) => draft.sopBindings.map((binding) => binding.sop_id),
    apply: (draftApi, ids) =>
      reconcileMulti(
        draftApi,
        ids,
        (draft) => draft.sopBindings.map((binding) => binding.sop_id),
        draftApi.unassignSop,
        draftApi.assignSop,
      ),
    createRequest: { kind: 'sop' },
    createdSelectionIds: (result) => [result.id],
  }),

  input_data_type: defineSlotPickerConfig<DataTypeListResponse>({
    slotId: 'input_data_type',
    labelKey: 'agents.panel.slots.input_data_type.label',
    // Same key + request as the slot cards' useDataTypes({ page: 1, page_size: 100 }).
    queryKey: ['data-types', { page: 1, page_size: 100 }],
    queryFn: async () => {
      const { data } = await apiClient.get<DataTypeListResponse>('/data-types', {
        params: { page: 1, page_size: 100 },
      })
      return data
    },
    toItems: (page) =>
      page.items.map((dataType) => ({
        id: dataType.id,
        label: dataType.name,
        sublabel: dataType.description ?? dataType.slug,
        dataType,
      })),
    multi: false,
    getSelectedIds: (draft, items) => {
      const applied = resolveAppliedInputDataType(draft, items)
      return applied ? [applied] : []
    },
    apply: (draftApi, ids, items) => {
      const dataType = items.find((item) => item.id === firstId(ids))?.dataType
      if (!dataType) return
      draftApi.setInputType('typed')
      draftApi.setInputSchema(dataTypeToInputSchema(dataType))
    },
    createRequest: { kind: 'input_data_type' },
    createdSelectionIds: (result) => [result.id],
  }),

  output_data_type: defineSlotPickerConfig<DataTypeListResponse>({
    slotId: 'output_data_type',
    labelKey: 'agents.panel.slots.output_data_type.label',
    queryKey: ['data-types', { page: 1, page_size: 100 }],
    queryFn: async () => {
      const { data } = await apiClient.get<DataTypeListResponse>('/data-types', {
        params: { page: 1, page_size: 100 },
      })
      return data
    },
    toItems: (page) =>
      page.items.map((dataType) => ({
        id: dataType.id,
        label: dataType.name,
        sublabel: dataType.description ?? dataType.slug,
        dataType,
      })),
    multi: false,
    getSelectedIds: (draft) => (draft.outputDataTypeId ? [draft.outputDataTypeId] : []),
    apply: (draftApi, ids) => {
      const id = firstId(ids)
      if (!id) return
      draftApi.setOutputType('typed')
      draftApi.setOutputDataType(id)
    },
    createRequest: { kind: 'output_data_type' },
    createdSelectionIds: (result) => [result.id],
  }),

  model: defineSlotPickerConfig<ModelConfig[]>({
    slotId: 'model',
    labelKey: 'agents.panel.slots.model.label',
    queryKey: ['agents', 'model-configs'],
    queryFn: async () => {
      const { data } = await apiClient.get<ModelConfig[]>('/agents/model-configs')
      return data
    },
    toItems: (configs) =>
      configs.flatMap((config) =>
        config.enabled_models.map((modelId) => ({
          id: modelId,
          label: `${modelId} (${config.display_name})`,
          sublabel: config.provider_type,
        })),
      ),
    multi: false,
    getSelectedIds: (draft) => (draft.modelId ? [draft.modelId] : []),
    apply: (draftApi, ids) => draftApi.setModel(firstId(ids)),
    createRequest: { kind: 'model_config' },
    createdSelectionIds: (result) =>
      result.enabledModelIds && result.enabledModelIds.length > 0
        ? [result.enabledModelIds[0]]
        : [],
  }),
}

/** Resolves the picker binding for one slot. */
export function getSlotPickerConfig(slotId: AgentEquipmentSlotId): SlotPickerConfig {
  return SLOT_PICKER_CONFIGS[slotId]
}
