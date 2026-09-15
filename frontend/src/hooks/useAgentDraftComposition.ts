import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import type {
  AgentDraftComposition,
  AgentDraftGuardrails,
  AgentEquipmentSlotId,
  AgentInputType,
  AgentOutputType,
  AgentType,
  SkillBindingInput,
  SopBindingInput,
} from '../types'

/** Slug pattern shared with AgentTypeForm (name is the agent's slug). */
const SLUG_PATTERN = /^[a-z0-9-]+$/

/** Raw-token multiplier: the form edits the budget in k-tokens. */
const TOKEN_BUDGET_UNIT = 1000

/** AgentTypeForm fallbacks for optional guardrail columns. */
const DEFAULT_GUARDRAILS: AgentDraftGuardrails = {
  maxIterations: 10,
  maxDelegationDepth: 3,
  maxDelegatedSteps: 20,
  executionTimeoutSeconds: 300,
  tokenBudget: null,
  tokenEnforcementMode: 'observe',
  tokenFallbackMode: 'observe_and_log',
  conversationalTokenVisibilityMode: 'enabled',
  conversationalContinuationPolicy: 'allow',
}

/**
 * Derives the initial draft composition from a fetched AgentType: base
 * properties (name, description, system instruction, guardrails) plus
 * equipment fields.
 */
function draftFromAgent(agent: AgentType): AgentDraftComposition {
  return {
    name: agent.name,
    description: agent.description ?? '',
    systemInstruction: agent.system_instruction ?? '',
    guardrails: {
      ...DEFAULT_GUARDRAILS,
      maxIterations: agent.guardrail_max_iterations ?? DEFAULT_GUARDRAILS.maxIterations,
      maxDelegationDepth:
        agent.guardrail_max_delegation_depth ?? DEFAULT_GUARDRAILS.maxDelegationDepth,
      maxDelegatedSteps: agent.guardrail_max_delegated_steps ?? DEFAULT_GUARDRAILS.maxDelegatedSteps,
      executionTimeoutSeconds:
        agent.guardrail_execution_timeout_seconds ?? DEFAULT_GUARDRAILS.executionTimeoutSeconds,
      tokenBudget: agent.guardrail_token_budget ?? null,
      tokenEnforcementMode: agent.guardrail_token_enforcement_mode ?? 'observe',
      tokenFallbackMode: agent.guardrail_token_fallback_mode ?? 'observe_and_log',
      conversationalTokenVisibilityMode:
        agent.guardrail_conversational_token_visibility_mode ?? 'enabled',
      conversationalContinuationPolicy:
        agent.guardrail_conversational_continuation_policy ?? 'allow',
    },
    identityId: agent.identity_id ?? null,
    roleId: agent.role_id ?? null,
    skillBindings: (agent.skill_bindings ?? []).map((b) => ({
      skill_id: b.skill_id,
      order: b.order,
    })),
    sopBindings: (agent.sop_bindings ?? []).map((b) => ({
      sop_id: b.sop_id,
      order: b.order,
    })),
    inputType: agent.input_type,
    inputSchema: agent.input_schema ? { ...agent.input_schema } : null,
    outputType: agent.output_type,
    outputSchema: agent.output_schema ? { ...agent.output_schema } : null,
    outputDataTypeId: agent.output_data_type_id ?? null,
    modelId: agent.model_id ?? null,
  }
}

/** Empty draft for a brand-new agent (nothing equipped). */
export function emptyDraft(): AgentDraftComposition {
  return {
    name: '',
    description: '',
    systemInstruction: '',
    guardrails: { ...DEFAULT_GUARDRAILS, tokenBudget: 1000 * TOKEN_BUDGET_UNIT },
    identityId: null,
    roleId: null,
    skillBindings: [],
    sopBindings: [],
    inputType: 'none',
    inputSchema: null,
    outputType: 'auto',
    outputSchema: null,
    outputDataTypeId: null,
    modelId: null,
  }
}

function renumber<T extends { order: number }>(items: T[]): T[] {
  return items.map((item, index) => ({ ...item, order: index + 1 }))
}

export interface UseAgentDraftCompositionResult {
  /** Id of the agent the draft belongs to (null when nothing selected). */
  agentId: string | null
  /** Current in-memory draft — mutations touch this only, never the API. */
  draft: AgentDraftComposition
  /** True after any draft mutation until save or discard. */
  isDirty: boolean
  /** Slot ids whose draft value differs from the last saved snapshot. */
  changedSlotIds: AgentEquipmentSlotId[]
  /** True when a base property (name/description/instruction/guardrails) changed. */
  propertiesChanged: boolean
  /** True when the draft name is empty or violates the slug pattern. */
  isNameInvalid: boolean
  setName: (name: string) => void
  setDescription: (description: string) => void
  setSystemInstruction: (systemInstruction: string) => void
  /** Merges a partial guardrail patch into the draft guardrails. */
  setGuardrails: (patch: Partial<AgentDraftGuardrails>) => void
  setIdentity: (identityId: string | null) => void
  setRole: (roleId: string | null) => void
  assignSkill: (skillId: string) => void
  unassignSkill: (skillId: string) => void
  moveSkill: (skillId: string, direction: 'up' | 'down') => void
  assignSop: (sopId: string) => void
  unassignSop: (sopId: string) => void
  moveSop: (sopId: string, direction: 'up' | 'down') => void
  setInputType: (inputType: AgentInputType) => void
  setInputSchema: (schema: Record<string, unknown> | null) => void
  setOutputType: (outputType: AgentOutputType) => void
  setOutputDataType: (dataTypeId: string | null) => void
  setModel: (modelId: string | null) => void
  /** Reverts the draft to the last saved snapshot. */
  discard: () => void
  /**
   * Persists the draft with exactly one PUT /agents/types/{id}, mapping base
   * properties (name, description, system instruction, guardrails) and
   * equipment fields onto the update payload. Returns the saved agent, or
   * null when no agent is selected. Throws on validation failure (invalid
   * slug name) or API failure.
   */
  save: () => Promise<AgentType | null>
}

/**
 * Core state hook of the Agent Management Panel: a typed in-memory draft of the
 * selected agent — base properties plus equipment. Every assign/unassign/
 * inline-create/property-edit mutation only touches the draft and marks it
 * dirty — no API calls until save. Save maps the draft onto the existing
 * agent-type update payload (a single PUT); discard reverts to the last saved
 * snapshot.
 */
export function useAgentDraftComposition(agent: AgentType | null | undefined): UseAgentDraftCompositionResult {
  const queryClient = useQueryClient()
  const [baseline, setBaseline] = useState<AgentType | null>(agent ?? null)
  const [draft, setDraft] = useState<AgentDraftComposition>(() =>
    agent ? draftFromAgent(agent) : emptyDraft(),
  )
  const [isDirty, setIsDirty] = useState(false)

  // Track which agent/version the draft was initialized from so agent switches
  // (and post-save refreshes) re-initialize it without wiping in-progress edits.
  const initRef = useRef<{ id: string | null; updatedAt: string | null }>(
    agent ? { id: agent.id, updatedAt: agent.updated_at } : { id: null, updatedAt: null },
  )
  const isDirtyRef = useRef(false)
  isDirtyRef.current = isDirty

  useEffect(() => {
    if (!agent) {
      initRef.current = { id: null, updatedAt: null }
      setBaseline(null)
      setDraft(emptyDraft())
      setIsDirty(false)
      return
    }
    const changedId = initRef.current.id !== agent.id
    const changedAt = initRef.current.updatedAt !== agent.updated_at
    if (changedId || (changedAt && !isDirtyRef.current)) {
      initRef.current = { id: agent.id, updatedAt: agent.updated_at }
      setBaseline(agent)
      setDraft(draftFromAgent(agent))
      setIsDirty(false)
    }
  }, [agent])

  const mutate = useCallback((updater: (prev: AgentDraftComposition) => AgentDraftComposition) => {
    setIsDirty(true)
    setDraft((prev) => updater(prev))
  }, [])

  // ── Base-property setters (property bar "Properties" section) ────────────

  const setName = useCallback(
    (name: string) => mutate((prev) => ({ ...prev, name })),
    [mutate],
  )

  const setDescription = useCallback(
    (description: string) => mutate((prev) => ({ ...prev, description })),
    [mutate],
  )

  const setSystemInstruction = useCallback(
    (systemInstruction: string) => mutate((prev) => ({ ...prev, systemInstruction })),
    [mutate],
  )

  const setGuardrails = useCallback(
    (patch: Partial<AgentDraftGuardrails>) =>
      mutate((prev) => ({ ...prev, guardrails: { ...prev.guardrails, ...patch } })),
    [mutate],
  )

  const setIdentity = useCallback(
    (identityId: string | null) => mutate((prev) => ({ ...prev, identityId })),
    [mutate],
  )

  const setRole = useCallback(
    (roleId: string | null) => mutate((prev) => ({ ...prev, roleId })),
    [mutate],
  )

  const assignSkill = useCallback(
    (skillId: string) =>
      mutate((prev) => {
        if (prev.skillBindings.some((b) => b.skill_id === skillId)) return prev
        const maxOrder = prev.skillBindings.reduce((max, b) => Math.max(max, b.order), 0)
        const binding: SkillBindingInput = { skill_id: skillId, order: maxOrder + 1 }
        return { ...prev, skillBindings: [...prev.skillBindings, binding] }
      }),
    [mutate],
  )

  const unassignSkill = useCallback(
    (skillId: string) =>
      mutate((prev) => ({
        ...prev,
        skillBindings: renumber(prev.skillBindings.filter((b) => b.skill_id !== skillId)),
      })),
    [mutate],
  )

  const moveSkill = useCallback(
    (skillId: string, direction: 'up' | 'down') =>
      mutate((prev) => {
        const sorted = [...prev.skillBindings].sort((a, b) => a.order - b.order)
        const index = sorted.findIndex((b) => b.skill_id === skillId)
        const target = direction === 'up' ? index - 1 : index + 1
        if (index < 0 || target < 0 || target >= sorted.length) return prev
        const reordered = [...sorted]
        const moved = reordered[index]
        reordered[index] = reordered[target]
        reordered[target] = moved
        return { ...prev, skillBindings: renumber(reordered) }
      }),
    [mutate],
  )

  const assignSop = useCallback(
    (sopId: string) =>
      mutate((prev) => {
        if (prev.sopBindings.some((b) => b.sop_id === sopId)) return prev
        const maxOrder = prev.sopBindings.reduce((max, b) => Math.max(max, b.order), 0)
        const binding: SopBindingInput = { sop_id: sopId, order: maxOrder + 1 }
        return { ...prev, sopBindings: [...prev.sopBindings, binding] }
      }),
    [mutate],
  )

  const unassignSop = useCallback(
    (sopId: string) =>
      mutate((prev) => ({
        ...prev,
        sopBindings: renumber(prev.sopBindings.filter((b) => b.sop_id !== sopId)),
      })),
    [mutate],
  )

  const moveSop = useCallback(
    (sopId: string, direction: 'up' | 'down') =>
      mutate((prev) => {
        const sorted = [...prev.sopBindings].sort((a, b) => a.order - b.order)
        const index = sorted.findIndex((b) => b.sop_id === sopId)
        const target = direction === 'up' ? index - 1 : index + 1
        if (index < 0 || target < 0 || target >= sorted.length) return prev
        const reordered = [...sorted]
        const moved = reordered[index]
        reordered[index] = reordered[target]
        reordered[target] = moved
        return { ...prev, sopBindings: renumber(reordered) }
      }),
    [mutate],
  )

  const setInputType = useCallback(
    (inputType: AgentInputType) =>
      mutate((prev) => {
        const next = { ...prev, inputType }
        // Conversational agents do not support typed outputs — clear on lock.
        if (inputType === 'conversation') {
          next.outputDataTypeId = null
          next.inputSchema = null
        }
        return next
      }),
    [mutate],
  )

  const setInputSchema = useCallback(
    (inputSchema: Record<string, unknown> | null) => mutate((prev) => ({ ...prev, inputSchema })),
    [mutate],
  )

  const setOutputType = useCallback(
    (outputType: AgentOutputType) =>
      mutate((prev) => {
        const next = { ...prev, outputType }
        if (outputType !== 'typed') next.outputDataTypeId = null
        return next
      }),
    [mutate],
  )

  const setOutputDataType = useCallback(
    (outputDataTypeId: string | null) =>
      mutate((prev) => {
        // Data-type rule: conversational agents are locked out of typed outputs.
        if (prev.inputType === 'conversation') return prev
        return { ...prev, outputDataTypeId }
      }),
    [mutate],
  )

  const setModel = useCallback(
    (modelId: string | null) => mutate((prev) => ({ ...prev, modelId })),
    [mutate],
  )

  const discard = useCallback(() => {
    if (!baseline) return
    setDraft(draftFromAgent(baseline))
    setIsDirty(false)
  }, [baseline])

  const changedSlotIds = useMemo<AgentEquipmentSlotId[]>(() => {
    if (!baseline) return []
    const saved = draftFromAgent(baseline)
    const changed: AgentEquipmentSlotId[] = []
    if (saved.roleId !== draft.roleId) changed.push('role')
    if (saved.identityId !== draft.identityId) changed.push('identity')
    if (
      saved.skillBindings.length !== draft.skillBindings.length ||
      [...saved.skillBindings]
        .sort((a, b) => a.order - b.order)
        .some((b, i) => b.skill_id !== [...draft.skillBindings].sort((a, b) => a.order - b.order)[i].skill_id)
    ) {
      changed.push('skills')
    }
    if (
      saved.sopBindings.length !== draft.sopBindings.length ||
      [...saved.sopBindings]
        .sort((a, b) => a.order - b.order)
        .some((b, i) => b.sop_id !== [...draft.sopBindings].sort((a, b) => a.order - b.order)[i].sop_id)
    ) {
      changed.push('sops')
    }
    if (saved.inputType !== draft.inputType) changed.push('input_data_type')
    if (
      saved.inputSchema === null !== (draft.inputSchema === null) ||
      (saved.inputSchema !== null &&
        draft.inputSchema !== null &&
        JSON.stringify(saved.inputSchema) !== JSON.stringify(draft.inputSchema))
    ) {
      changed.push('input_data_type')
    }
    if (
      saved.outputType !== draft.outputType ||
      saved.outputDataTypeId !== draft.outputDataTypeId
    ) {
      changed.push('output_data_type')
    }
    if (saved.modelId !== draft.modelId) changed.push('model')
    return changed
  }, [baseline, draft])

  /** True when any base property (name/description/instruction/guardrails) drifted. */
  const propertiesChanged = useMemo<boolean>(() => {
    if (!baseline) return false
    const saved = draftFromAgent(baseline)
    return (
      saved.name !== draft.name ||
      saved.description !== draft.description ||
      saved.systemInstruction !== draft.systemInstruction ||
      JSON.stringify(saved.guardrails) !== JSON.stringify(draft.guardrails)
    )
  }, [baseline, draft])

  const isNameInvalid = !draft.name.trim() || !SLUG_PATTERN.test(draft.name)

  const save = useCallback(async (): Promise<AgentType | null> => {
    if (!baseline) return null
    // Same validation rules as AgentTypeForm: required slug-pattern name.
    if (!draft.name.trim() || !SLUG_PATTERN.test(draft.name)) {
      throw new Error('slugNameValidationError')
    }
    const body = {
      name: draft.name,
      description: draft.description,
      identity_id: draft.identityId,
      role_id: draft.roleId,
      model_id: draft.modelId,
      system_instruction: draft.systemInstruction,
      input_type: draft.inputType,
      input_schema: draft.inputSchema,
      output_type: draft.outputType,
      output_schema: draft.outputSchema,
      output_data_type_id: draft.outputDataTypeId,
      sop_bindings: draft.sopBindings,
      skill_bindings: draft.skillBindings,
      guardrail_max_iterations: draft.guardrails.maxIterations,
      guardrail_max_delegation_depth: draft.guardrails.maxDelegationDepth,
      guardrail_max_delegated_steps: draft.guardrails.maxDelegatedSteps,
      guardrail_execution_timeout_seconds: draft.guardrails.executionTimeoutSeconds,
      guardrail_token_budget: draft.guardrails.tokenBudget,
      guardrail_token_enforcement_mode: draft.guardrails.tokenEnforcementMode,
      guardrail_token_fallback_mode: draft.guardrails.tokenFallbackMode,
      guardrail_conversational_token_visibility_mode:
        draft.guardrails.conversationalTokenVisibilityMode,
      guardrail_conversational_continuation_policy:
        draft.guardrails.conversationalContinuationPolicy,
    }
    const { data: saved } = await apiClient.put<AgentType>(`/agents/types/${baseline.id}`, body)
    // Single write done — adopt the server response as the new snapshot.
    initRef.current = { id: saved.id, updatedAt: saved.updated_at }
    setBaseline(saved)
    setDraft(draftFromAgent(saved))
    setIsDirty(false)
    void queryClient.invalidateQueries({ queryKey: ['agents', 'types'] })
    return saved
  }, [baseline, draft, queryClient])

  return {
    agentId: baseline?.id ?? null,
    draft,
    isDirty,
    changedSlotIds,
    propertiesChanged,
    isNameInvalid,
    setName,
    setDescription,
    setSystemInstruction,
    setGuardrails,
    setIdentity,
    setRole,
    assignSkill,
    unassignSkill,
    moveSkill,
    assignSop,
    unassignSop,
    moveSop,
    setInputType,
    setInputSchema,
    setOutputType,
    setOutputDataType,
    setModel,
    discard,
    save,
  }
}
