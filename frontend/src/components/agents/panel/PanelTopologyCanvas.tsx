import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { Box, Chip, IconButton, Tooltip, Typography } from '@mui/material'
import FullscreenIcon from '@mui/icons-material/Fullscreen'
import FullscreenExitIcon from '@mui/icons-material/FullscreenExit'
import ZoomInIcon from '@mui/icons-material/ZoomIn'
import ZoomOutIcon from '@mui/icons-material/ZoomOut'
import FitScreenIcon from '@mui/icons-material/FitScreen'
import TopologyDiagramRenderer from '../TopologyDiagramRenderer'
import { dataTypeToInputSchema } from './EquipmentSlots'
import { useDataTypes } from '../../../hooks/useDataTypes'
import { useAvailableModels } from '../../../hooks/useAvailableModels'
import { useAllTools, useMcpServers } from '../../../hooks/useMcpServers'
import apiClient from '../../../api/apiClient'
import { useTokenHealth } from '../../../hooks/useTokenHealth'
import { TokenHealthState } from '../../../types/tokenHealth'
import { canonicalizeToolName } from '../../../utils/toolNaming'
import type {
  AgentDraftComposition,
  AgentIdentity,
  AgentRole,
  Skill,
  Sop,
  SopDetail,
  TopologyEdge,
  TopologyNode,
  TopologyZone,
} from '../../../types'

// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * Ids of the three zoned topology bands (① configuration ② capabilities
 * ③ tools). The Communication Hub renders as a vertical bar BETWEEN the
 * capabilities band and the tools band (runtime-monitor "firewall" pattern),
 * not as a node inside a band.
 */
export type PanelTopologyZoneId = 'config' | 'capabilities' | 'tools'

/** Result of the panel topology composition: nodes, edges and the zone bands. */
export interface PanelTopologyGraph {
  nodes: TopologyNode[]
  edges: TopologyEdge[]
  zones: TopologyZone[]
}

export interface PanelTopologyNames {
  roleNames: Record<string, string>
  identityNames: Record<string, string>
  skillNames: Record<string, string>
  sopNames: Record<string, string>
  dataTypeNames: Record<string, string>
  modelLabels: Record<string, string>
  /** Display name of the registry data type matching the draft input schema, if any. */
  inputDataTypeName: string | null
  /** MCP tool display name by tool id (tools zone). */
  toolNames: Record<string, string>
  /** MCP server slug by tool id (tools zone grouping). */
  toolServerSlugs: Record<string, string>
  /** MCP server slug → group accent colour (tools zone grouping). */
  toolServerColors: Record<string, string>
  /** MCP tool ids per skill id (tools zone resolution). */
  skillToolIds: Record<string, string[]>
  /**
   * Token health badge state per agent identity id (token-expiry-alerting):
   * 'expiring' / 'expired' — derived from the bound identity's and MCP
   * sessions' persisted health states. Healthy/unknown identities are absent.
   */
  identityTokenHealth: Record<string, 'expiring' | 'expired'>
  /**
   * Composed skill ids per SOP id (from the SOP detail's `skill_invocation`
   * steps — SOP → skill composition chain in the capabilities zone).
   */
  sopComposedSkillIds: Record<string, string[]>
}

export interface PanelTopologyLabels {
  /** Label of the Communication Hub vertical bar (between ② and ③). */
  hub: string
  empty: Record<string, string>
  inputSchemaLabel: string
  /** Label of the deliberately-set "no input" state (input type none). */
  inputNone: string
  /** Label of the conversational input type (matches the editor dialog). */
  inputConversation: string
  /** Label of the locked output slot (conversational agents). */
  outputLocked: string
  /** Label of the auto/unset output type (matches the editor dialog). */
  outputAuto: string
  /** Agent boundary caption for typed-output agents. */
  boundaryTyped: string
  /** Agent boundary caption for conversational agents. */
  boundaryConversational: string
  sections: {
    contract: string
    signsInAs: string
    assumesAs: string
    sops: string
    skills: string
  }
  edges: {
    equippedWith: string
    grants: string
    /** Label of the SOP → composed skill composition edge. */
    composed: string
  }
  zones: {
    config: { title: string; subtitle: string }
    capabilities: { title: string; subtitle: string }
    tools: { title: string; subtitle: string }
  }
  /** Placeholder label when no MCP tools resolve from the equipped skills. */
  noTools: string
  /**
   * Loading label rendered in place of any bound-but-unresolved entity (its
   * reference request is still in flight) — never a raw id mid-load.
   */
  loading: string
}

/**
 * Per-entity pending (in-flight) flags for the panel topology. A flag says the
 * list/detail request that resolves that entity kind has not completed yet;
 * the composer then renders a loading placeholder for bound entities whose
 * name is not already cached, instead of falling back to the raw id. Flags are
 * supplied by the canvas from its react-query states — the composer stays
 * pure. A bound entity whose kind resolved (flag `false`) but whose id is
 * absent keeps the historical raw-id fallback (genuinely missing).
 */
export interface PanelTopologyPending {
  /** Agent identities list in flight. */
  identity: boolean
  /** Agent roles list in flight. */
  role: boolean
  /** Model configurations (available models) in flight. */
  model: boolean
  /** Agent data types list in flight (input/output contract slots). */
  dataTypes: boolean
  /** Skills list in flight (labels + bound tool ids). */
  skills: boolean
  /** SOPs list in flight (SOP labels). */
  sops: boolean
  /** Bound SOP details in flight (composition chain unknown). */
  sopDetails: boolean
  /** MCP tools / servers in flight (tools zone resolution). */
  tools: boolean
}

/** No in-flight requests — resolved-or-missing semantics only. */
export const NO_PENDING: PanelTopologyPending = {
  identity: false,
  role: false,
  model: false,
  dataTypes: false,
  skills: false,
  sops: false,
  sopDetails: false,
  tools: false,
}

// ── Constants ─────────────────────────────────────────────────────────────────

/**
 * Worst-of token health merge (token-expiry-alerting): expired dominates
 * expiring. Returns undefined when neither side carries a badge state.
 */
export function worstTokenHealth(
  a: 'expiring' | 'expired' | undefined,
  b: 'expiring' | 'expired' | undefined,
): 'expiring' | 'expired' | undefined {
  if (a === 'expired' || b === 'expired') return 'expired'
  if (a === 'expiring' || b === 'expiring') return 'expiring'
  return undefined
}

/** Badge state for a draft identity id (undefined = healthy/unknown/unset). */
function identityTokenHealthOf(
  identityId: string | null | undefined,
  names: PanelTopologyNames,
): 'expiring' | 'expired' | undefined {
  if (identityId == null) return undefined
  return names.identityTokenHealth[identityId]
}

/**
 * Fullscreen zoom clamps + per-click step (~20%). zoom = 1 is the auto-fit
 * view; the renderer scales the viewBox inversely (view = world / zoom) so
 * viewBox-unit text fitting stays valid at every level.
 */
const TOPOLOGY_MIN_ZOOM = 0.5
const TOPOLOGY_MAX_ZOOM = 3
const TOPOLOGY_ZOOM_STEP = 1.2
/**
 * Font-scale cap (as a zoom level): once the fullscreen zoom passes this
 * value, the drawn font sizes shrink proportionally (cap / zoom) in the
 * renderer, so on-screen glyphs stop growing. Zooming in then reveals MORE
 * WORLD (width-fitted labels gain room, so fewer labels are ellipsized)
 * instead of magnifying text.
 */
export const TOPOLOGY_MAX_FONT_SCALE = 1.6

/** Clamp a zoom scalar into the [TOPOLOGY_MIN_ZOOM, TOPOLOGY_MAX_ZOOM] range. */
function clampZoom(value: number): number {
  return Math.min(TOPOLOGY_MAX_ZOOM, Math.max(TOPOLOGY_MIN_ZOOM, value))
}

/** Accent colour of the capabilities-zone section group boxes. */
const SECTION_GROUP_COLOR = '#7c3aed'

/** Small distinct-hue palette for MCP server group boxes (prototype MCP palette). */
const MCP_GROUP_PALETTE = ['#15803d', '#0e7490', '#b45309', '#1d4ed8', '#a21caf', '#4d7c0f', '#b91c1c'] as const

/**
 * Distinct-hue palette for per-capability node borders + route connectors —
 * mirrors the runtime monitor's per-agent route colours so the panel and the
 * map read consistently.
 */
const CAPABILITY_COLOR_PALETTE = [
  '#E53935',
  '#8E24AA',
  '#3949AB',
  '#1E88E5',
  '#00897B',
  '#43A047',
  '#F4511E',
  '#6D4C41',
  '#546E7A',
  '#5E35B1',
  '#00ACC1',
  '#FB8C00',
] as const

/** Deterministic palette colour for an MCP server slug (stable across renders). */
export function mcpGroupColor(slug: string): string {
  let hash = 0
  for (let i = 0; i < slug.length; i++) {
    hash = (hash * 31 + slug.charCodeAt(i)) >>> 0
  }
  return MCP_GROUP_PALETTE[hash % MCP_GROUP_PALETTE.length]
}

/**
 * Deterministic distinct border colour for a capability node (skill/SOP).
 * The SAME colour is used for the node's border and for its route
 * connector(s) to its tool(s), mirroring the runtime monitor's per-route
 * colour approach.
 */
export function capabilityColor(nodeId: string): string {
  let hash = 0
  for (let i = 0; i < nodeId.length; i++) {
    hash = (hash * 31 + nodeId.charCodeAt(i)) >>> 0
  }
  return CAPABILITY_COLOR_PALETTE[hash % CAPABILITY_COLOR_PALETTE.length]
}

// ── Reference resolution (pending vs. genuinely missing) ─────────────────────

/** Resolution outcome for a bound entity id. */
interface ResolvedRef {
  /** Display name when the reference is resolved, else undefined. */
  label: string | undefined
  /** The reference request is in flight and the name is not cached yet. */
  pending: boolean
}

/**
 * Resolves a bound entity id through its name map:
 * - name found → resolved (never pending — cached names must not flicker);
 * - name absent + that entity kind's request in flight → pending;
 * - name absent + request completed → genuinely missing (raw-id fallback).
 */
function resolveRef(
  id: string | null | undefined,
  namesById: Record<string, string> | undefined,
  loading: boolean,
): ResolvedRef {
  if (!id) return { label: undefined, pending: false }
  const name = namesById?.[id]
  if (name != null) return { label: name, pending: false }
  return { label: undefined, pending: loading }
}

/** Label for a bound entity: resolved name → loading label → raw id (missing). */
function refLabel(ref: ResolvedRef, id: string, loadingLabel: string): string {
  return ref.label ?? (ref.pending ? loadingLabel : id)
}

// ── Composition ───────────────────────────────────────────────────────────────

/**
 * Maps a draft composition to the zoned panel topology (approved prototype
 * design): Zone ① Configuration — the agent rendered as a large containment
 * boundary with identity ("signs in as"), role ("assumes as") and the
 * input/output/model contract chips INSIDE it; Zone ② Capabilities — SOPs and
 * Skills sections with solid "equipped-with" edges from the agent boundary
 * and dotted "grants" edges from the role; the Communication Hub — a vertical
 * bar rendered BETWEEN ② and ③ (declared separately by the component, not a
 * node); Zone ③ Tools — MCP-server-grouped tool nodes reached by dashed
 * per-capability route connectors that CROSS the hub bar directly (each
 * skill → its tools, in the skill's own colour). Each bound SOP's COMPOSED
 * skills (from its loaded detail) render as indented tree children beneath
 * it — each SOP wrapped in its own group box — connected by SOP-accent-
 * coloured tree elbow composition edges, and their tools route like any
 * other skill's. Empty slots render as dashed placeholders — except
 * the Skills section, which is omitted entirely when no skill is directly
 * equipped — and the conversational output lock is preserved. Purely
 * client-side composition.
 *
 * Pending states (FIX-20261102-100704): `pending` flags say which reference
 * lists/details are still in flight. Any BOUND entity whose name is not cached
 * then renders with `pending: true` and the `loading` label — never its raw id.
 * Cached names are never marked pending, and a resolved-but-absent reference
 * keeps the historical raw-id fallback (genuinely missing). Deliberately-set
 * None/Conversation/Auto slots and dashed unfilled placeholders are unaffected.
 */
export function buildPanelTopology(
  agentName: string,
  draft: AgentDraftComposition,
  names: PanelTopologyNames,
  labels: PanelTopologyLabels,
  pending: PanelTopologyPending = NO_PENDING,
): PanelTopologyGraph {
  const nodes: TopologyNode[] = []
  const edges: TopologyEdge[] = []
  /** Spread helper: only unresolved nodes carry the flag (node shape stable). */
  const pendingFlag = (isPending: boolean): { pending?: true } => (isPending ? { pending: true } : {})

  // ── Zone ① CONFIGURATION — agent boundary with containment ────────────────
  nodes.push({
    id: 'agent',
    type: 'agent',
    label: agentName,
    zone: 'config',
    caption: draft.inputType === 'conversation' ? labels.boundaryConversational : labels.boundaryTyped,
    // Container badge: worst token health across the bound identity (and
    // any MCP sessions resolved into identityTokenHealth by the caller).
    ...(identityTokenHealthOf(draft.identityId, names)
      ? { tokenHealth: identityTokenHealthOf(draft.identityId, names) }
      : {}),
  })

  const identityRef = resolveRef(draft.identityId, names.identityNames, pending.identity)
  nodes.push({
    id: 'identity',
    type: 'identity',
    label: draft.identityId ? refLabel(identityRef, draft.identityId, labels.loading) : labels.empty.identity,
    zone: 'config',
    containedIn: 'agent',
    caption: labels.sections.signsInAs,
    usage: draft.identityId ? undefined : 'empty',
    ...pendingFlag(identityRef.pending),
    ...(identityTokenHealthOf(draft.identityId, names)
      ? { tokenHealth: identityTokenHealthOf(draft.identityId, names) }
      : {}),
  })

  const roleRef = resolveRef(draft.roleId, names.roleNames, pending.role)
  nodes.push({
    id: 'role',
    type: 'role',
    label: draft.roleId ? refLabel(roleRef, draft.roleId, labels.loading) : labels.empty.role,
    zone: 'config',
    containedIn: 'agent',
    caption: labels.sections.assumesAs,
    usage: draft.roleId ? undefined : 'empty',
    ...pendingFlag(roleRef.pending),
  })

  // Input slot: a typed slot without a schema is GENUINELY unfilled (empty
  // placeholder); `none` and `conversation` are deliberately-set input
  // types and render the SAME labels the editor dialog shows — solid nodes,
  // not dashed placeholders. A typed schema whose registry data type is still
  // being looked up (data-type list in flight) is a PENDING state: the
  // resolved name replaces the generic schema label once it arrives.
  const hasInputSchema = draft.inputType === 'typed' && draft.inputSchema != null
  const inputTypeLabel =
    draft.inputType === 'none'
      ? labels.inputNone
      : draft.inputType === 'conversation'
        ? labels.inputConversation
        : null
  const inputPending = hasInputSchema && names.inputDataTypeName == null && pending.dataTypes
  nodes.push({
    id: 'input_data_type',
    type: 'input_data_type',
    label: hasInputSchema
      ? (names.inputDataTypeName ?? (inputPending ? labels.loading : labels.inputSchemaLabel))
      : (inputTypeLabel ?? labels.empty.input_data_type),
    zone: 'config',
    containedIn: 'agent',
    caption: labels.sections.contract,
    usage: hasInputSchema || inputTypeLabel != null ? undefined : 'empty',
    ...pendingFlag(inputPending),
  })

  // Output slot: the conversational lock wins; a typed output without a
  // data type is unfilled (empty placeholder); `auto` / `markdown` / unset
  // output types are deliberately set and show the editor's "Auto" label.
  const outputLocked = draft.inputType === 'conversation'
  const outputUnfilled = !outputLocked && draft.outputType === 'typed' && draft.outputDataTypeId == null
  const outputRef = resolveRef(draft.outputDataTypeId, names.dataTypeNames, pending.dataTypes)
  nodes.push({
    id: 'output_data_type',
    type: 'output_data_type',
    label: outputLocked
      ? labels.outputLocked
      : draft.outputDataTypeId
        ? refLabel(outputRef, draft.outputDataTypeId, labels.loading)
        : outputUnfilled
          ? labels.empty.output_data_type
          : labels.outputAuto,
    zone: 'config',
    containedIn: 'agent',
    usage: outputLocked ? 'locked' : draft.outputDataTypeId ? undefined : outputUnfilled ? 'empty' : undefined,
    ...pendingFlag(outputRef.pending),
  })

  const modelRef = resolveRef(draft.modelId, names.modelLabels, pending.model)
  nodes.push({
    id: 'model',
    type: 'model',
    label: draft.modelId ? refLabel(modelRef, draft.modelId, labels.loading) : labels.empty.model,
    zone: 'config',
    containedIn: 'agent',
    usage: draft.modelId ? undefined : 'empty',
    ...pendingFlag(modelRef.pending),
  })

  // ── Zone ② CAPABILITIES — SOPs and Skills sections ────────────────────────
  // Every real capability node gets a deterministic distinct border colour;
  // its route connector(s) to its tool(s) reuse the SAME colour.
  const capabilityIds: string[] = []
  const grantTargets: string[] = []

  const sops = [...draft.sopBindings].sort((a, b) => a.order - b.order)
  if (sops.length === 0) {
    nodes.push({
      id: 'sop_empty',
      type: 'sop',
      label: labels.empty.sops,
      zone: 'capabilities',
      usage: 'empty',
      group: 'sops',
      groupLabel: labels.sections.sops,
      groupColor: SECTION_GROUP_COLOR,
    })
    capabilityIds.push('sop_empty')
  }
  /** Compositions per bound SOP: node id + accent colour + composed skill ids. */
  const sopCompositions: { sopNodeId: string; sopColor: string; skillIds: string[] }[] = []
  for (const binding of sops) {
    const nodeId = `sop_${binding.sop_id}`
    const sopColor = capabilityColor(nodeId)
    const sopRef = resolveRef(binding.sop_id, names.sopNames, pending.sops)
    nodes.push({
      id: nodeId,
      type: 'sop',
      label: refLabel(sopRef, binding.sop_id, labels.loading),
      zone: 'capabilities',
      accentColor: sopColor,
      group: 'sops',
      groupLabel: labels.sections.sops,
      groupColor: SECTION_GROUP_COLOR,
      ...pendingFlag(sopRef.pending),
    })
    capabilityIds.push(nodeId)
    grantTargets.push(nodeId)
    // Composed skills from the loaded SOP detail (skill_invocation steps).
    sopCompositions.push({
      sopNodeId: nodeId,
      sopColor,
      skillIds: names.sopComposedSkillIds?.[binding.sop_id] ?? [],
    })
    // Composition unknown while the SOP detail request is in flight: render a
    // pending tree child beneath the SOP (same indented row geometry a real
    // composed skill uses) so the loading state is visible and the graph does
    // not jump when the composed skills replace it.
    if (pending.sopDetails && names.sopComposedSkillIds?.[binding.sop_id] == null) {
      nodes.push({
        id: `sop_pending_${binding.sop_id}`,
        type: 'skill',
        label: labels.loading,
        zone: 'capabilities',
        group: 'sops',
        groupLabel: labels.sections.sops,
        groupColor: SECTION_GROUP_COLOR,
        childOf: nodeId,
        pending: true,
      })
    }
  }

  const skills = [...draft.skillBindings].sort((a, b) => a.order - b.order)
  // No directly equipped skills → the Skills section group is OMITTED
  // entirely: no empty placeholder node, no group frame, and no orphan
  // "equipped with"/"grants" edges pointing at one. Composed skills still
  // render beneath their SOPs in the SOPs section, which keeps its own
  // behaviour (including its empty placeholder — so the Capabilities zone
  // collapses gracefully to it when the draft has no capabilities at all).
  /** Skill node ids rendered in the capabilities zone (direct + composed). */
  const routedSkillNodeIds = new Set<string>()
  for (const binding of skills) {
    const nodeId = `skill_${binding.skill_id}`
    routedSkillNodeIds.add(nodeId)
    const skillRef = resolveRef(binding.skill_id, names.skillNames, pending.skills)
    nodes.push({
      id: nodeId,
      type: 'skill',
      label: refLabel(skillRef, binding.skill_id, labels.loading),
      zone: 'capabilities',
      accentColor: capabilityColor(nodeId),
      group: 'skills',
      groupLabel: labels.sections.skills,
      groupColor: SECTION_GROUP_COLOR,
      ...pendingFlag(skillRef.pending),
    })
    capabilityIds.push(nodeId)
    grantTargets.push(nodeId)
  }

  // ── SOP composition chain: SOP → composed skills ───────────────────────────
  // Composed skill nodes render as INDENTED TREE CHILDREN beneath their SOP
  // (node.childOf) — each SOP gets its own group box wrapping itself and its
  // child stack, and the composition edges route as tree elbow connectors
  // from the SOP's bottom into each child's left edge. A skill that is ALSO
  // directly bound (or already composed under an earlier SOP) REUSES the
  // existing node — only the composition edge is added, so no duplicates
  // appear. Until a SOP's detail is loaded its composition is simply absent
  // (the SOP node itself is already rendered).
  for (const composition of sopCompositions) {
    const composedNodeIds: string[] = []
    const seen = new Set<string>()
    for (const skillId of composition.skillIds) {
      const nodeId = `skill_${skillId}`
      composedNodeIds.push(nodeId)
      if (seen.has(nodeId)) continue
      seen.add(nodeId)
      if (routedSkillNodeIds.has(nodeId)) continue
      routedSkillNodeIds.add(nodeId)
      const composedRef = resolveRef(skillId, names.skillNames, pending.skills)
      nodes.push({
        id: nodeId,
        type: 'skill',
        label: refLabel(composedRef, skillId, labels.loading),
        zone: 'capabilities',
        accentColor: capabilityColor(nodeId),
        group: 'sops',
        groupLabel: labels.sections.sops,
        groupColor: SECTION_GROUP_COLOR,
        childOf: composition.sopNodeId,
        ...pendingFlag(composedRef.pending),
      })
    }
    // Composition edges: SOP → each composed skill, in the SOP's accent
    // colour (label on the first edge only, matching the other semantics).
    composedNodeIds.forEach((skillNodeId, index) => {
      edges.push({
        source: composition.sopNodeId,
        target: skillNodeId,
        style: 'solid',
        color: composition.sopColor,
        ...(index === 0 ? { label: labels.edges.composed } : {}),
      })
    })
  }

  // Solid "equipped with" edges: agent boundary → every capability (label once).
  capabilityIds.forEach((id, index) => {
    edges.push({
      source: 'agent',
      target: id,
      style: 'solid',
      ...(index === 0 ? { label: labels.edges.equippedWith } : {}),
    })
  })
  // Dotted "grants" edges: role → each equipped capability (label once; only
  // with a role assigned — permission flow originates from the role).
  if (draft.roleId) {
    grantTargets.forEach((id, index) => {
      edges.push({
        source: 'role',
        target: id,
        style: 'dotted',
        ...(index === 0 ? { label: labels.edges.grants } : {}),
      })
    })
  }

  // ── Zone ③ TOOLS — MCP-server-grouped tool nodes ──────────────────────────
  // Route connectors go DIRECTLY from each skill to its tools, CROSSING the
  // Communication Hub bar (rendered by the renderer between ② and ③) — the
  // runtime monitor's firewall routing, static. Each connector reuses its
  // source skill's accent colour. Skills COMPOSED under a SOP route exactly
  // like directly bound skills (SOP → skill → tool chain). (SOP delegation
  // flows are not resolvable client-side from the draft, so no SOP→tool
  // connectors exist.)
  const toolGroups = new Map<string, string[]>()
  for (const skillNodeId of routedSkillNodeIds) {
    const skillId = skillNodeId.replace(/^skill_/, '')
    for (const toolId of names.skillToolIds?.[skillId] ?? []) {
      const slug = names.toolServerSlugs[toolId]
      if (!slug) continue
      const list = toolGroups.get(slug) ?? []
      if (!list.includes(toolId)) list.push(toolId)
      toolGroups.set(slug, list)
    }
  }
  if (toolGroups.size === 0) {
    // Tools resolution is still in flight: skill tool bindings or the MCP
    // tool/server catalogue has not arrived yet. The "no tools" placeholder is
    // reserved for a RESOLVED graph where nothing resolves — showing it here
    // would wrongly assert the agent has no tools.
    const routedSkillIds = [...routedSkillNodeIds].map((nodeId) => nodeId.replace(/^skill_/, ''))
    const hasBoundToolIds = routedSkillIds.some((skillId) => (names.skillToolIds?.[skillId] ?? []).length > 0)
    const toolsPending =
      (routedSkillNodeIds.size > 0 && (pending.skills || (pending.tools && hasBoundToolIds))) ||
      // SOP composition unknown → composed skills (and therefore their tools)
      // may still appear; the tools zone must not assert "no tools" yet.
      (pending.sopDetails && sops.length > 0)
    nodes.push(
      toolsPending
        ? { id: 'tool_pending', type: 'tool', label: labels.loading, zone: 'tools', pending: true }
        : { id: 'tool_empty', type: 'tool', label: labels.noTools, zone: 'tools', usage: 'empty' },
    )
  }
  for (const [slug, toolIds] of toolGroups) {
    for (const toolId of toolIds) {
      nodes.push({
        id: `tool_${toolId}`,
        type: 'tool',
        label: names.toolNames[toolId] ?? toolId,
        zone: 'tools',
        group: slug,
        groupLabel: slug,
        groupColor: names.toolServerColors[slug] ?? '#64748b',
      })
    }
  }
  // Dashed per-capability route connectors: skill → its tools (colour-matched
  // to the skill node's border; no per-edge labels — the legend covers the
  // "call path via Hub" semantics). Composed skills route identically.
  for (const skillNodeId of routedSkillNodeIds) {
    const skillId = skillNodeId.replace(/^skill_/, '')
    const color = capabilityColor(skillNodeId)
    const seen = new Set<string>()
    for (const toolId of names.skillToolIds?.[skillId] ?? []) {
      if (seen.has(toolId) || !toolGroups.has(names.toolServerSlugs[toolId] ?? '')) continue
      seen.add(toolId)
      edges.push({
        source: skillNodeId,
        target: `tool_${toolId}`,
        style: 'dashed',
        color,
      })
    }
  }

  const zones: TopologyZone[] = [
    {
      id: 'config',
      title: labels.zones.config.title,
      subtitle: labels.zones.config.subtitle,
      tint: '#f0f6ff',
      border: '#1d4ed8',
    },
    {
      id: 'capabilities',
      title: labels.zones.capabilities.title,
      subtitle: labels.zones.capabilities.subtitle,
      tint: '#faf5ff',
      border: '#7c3aed',
    },
    {
      id: 'tools',
      title: labels.zones.tools.title,
      subtitle: labels.zones.tools.subtitle,
      tint: '#f8fafc',
      border: '#64748b',
      dashed: true,
    },
  ]

  return { nodes, edges, zones }
}

// ── Component ─────────────────────────────────────────────────────────────────

interface PanelTopologyCanvasProps {
  agentName: string
  draft: AgentDraftComposition
  isDirty: boolean
  /**
   * Optional node-click handler (e.g. the agent preview dialog's detail
   * navigation). The management panel omits it — default behaviour is
   * unchanged (nodes render non-clickable, exactly as before).
   */
  onNodeClick?: (node: TopologyNode) => void
}

/**
 * Live topology region of the Agent Management Panel: composes the zoned
 * topology from the draft state on every change — before saving — and renders
 * it through the shared renderer in zoned mode. Label resolution uses the
 * shared react-query caches (same keys as the equipment slots, so requests
 * are deduplicated). The Communication Hub renders as a vertical bar between
 * the Capabilities and Tools zones, and a fullscreen toggle expands the
 * topology over the whole viewport (Escape or the toggle exits).
 */
export function PanelTopologyCanvas({ agentName, draft, isDirty, onNodeClick }: PanelTopologyCanvasProps) {
  const { t } = useTranslation()
  const [fullscreen, setFullscreen] = useState(false)
  /** Fullscreen view zoom (1 = auto-fit; the renderer scales the viewBox). */
  const [zoom, setZoom] = useState(1)

  // Fullscreen enter/exit always reset the zoom so re-entering starts
  // fitted (auto-fit = zoom 1).
  const exitFullscreen = useCallback(() => {
    setZoom(1)
    setFullscreen(false)
  }, [])
  const enterFullscreen = useCallback(() => {
    setZoom(1)
    setFullscreen(true)
  }, [])

  // Escape exits fullscreen (document-level convention, same as dialogs).
  useEffect(() => {
    if (!fullscreen) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') exitFullscreen()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [fullscreen, exitFullscreen])

  // Zoom controls (stepped ~20% per click, clamped to the 0.5×–3× range).
  const zoomIn = useCallback(() => setZoom((z) => clampZoom(z * TOPOLOGY_ZOOM_STEP)), [])
  const zoomOut = useCallback(() => setZoom((z) => clampZoom(z / TOPOLOGY_ZOOM_STEP)), [])
  const zoomFit = useCallback(() => setZoom(1), [])

  // Same shared list queries/cache keys as the equipment slots, so requests
  // are deduplicated and label resolution stays consistent with the draft.
  // The `isLoading` flags drive the topology's pending (in-flight) states: an
  // unresolved bound entity renders a spinner + loading label instead of its
  // raw id until the request completes.
  const { data: roles, isLoading: rolesLoading } = useQuery<AgentRole[]>({
    queryKey: ['agents', 'roles'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentRole[]>('/agents/roles')
      return data
    },
  })
  const { data: identities, isLoading: identitiesLoading } = useQuery<AgentIdentity[]>({
    queryKey: ['agents', 'identities'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentIdentity[]>('/agents/identities')
      return data
    },
  })
  const { data: skills, isLoading: skillsLoading } = useQuery<Skill[]>({
    queryKey: ['skills'],
    queryFn: async () => {
      const { data } = await apiClient.get<Skill[]>('/skills')
      return data
    },
  })
  const { data: sops, isLoading: sopsLoading } = useQuery<Sop[]>({
    queryKey: ['sops'],
    queryFn: async () => {
      const { data } = await apiClient.get<Sop[]>('/sops')
      return data
    },
  })
  // SOP details for the bound SOPs — the composition chain source (each
  // detail carries the SOP's `skill_invocation` steps → composed skills).
  // Same react-query pattern/cache key shape as AgentTypeDetailsDialog, so
  // requests are deduplicated with the rest of the app. While details are
  // loading the SOP nodes render a pending composition placeholder child.
  const boundSopIds = useMemo(
    () => [...new Set(draft.sopBindings.map((binding) => binding.sop_id))].sort(),
    [draft.sopBindings],
  )
  const { data: sopDetails, isLoading: sopDetailsLoading } = useQuery<SopDetail[]>({
    queryKey: ['sops', 'details', boundSopIds],
    queryFn: async () => {
      const results = await Promise.all(
        boundSopIds.map((id) => apiClient.get<SopDetail>(`/sops/${id}`).then((r) => r.data)),
      )
      return results
    },
    enabled: boundSopIds.length > 0,
  })
  const { data: dataTypesPage, isLoading: dataTypesLoading } = useDataTypes({ page: 1, page_size: 100 })
  const { data: availableModels, isLoading: modelsLoading } = useAvailableModels()
  // Tools zone: MCP tools + servers for MCP-server tool grouping.
  const { data: mcpTools, isLoading: mcpToolsLoading } = useAllTools()
  const { data: mcpServers, isLoading: mcpServersLoading } = useMcpServers()
  // Token health (token-expiry-alerting): expired / expiring states for
  // identities and MCP sessions, from the dashboard token-health API.
  const { data: tokenHealth } = useTokenHealth()

  const graph = useMemo(() => {
    const roleNames: Record<string, string> = {}
    for (const role of roles ?? []) roleNames[role.id] = role.name
    const identityNames: Record<string, string> = {}
    for (const identity of identities ?? []) identityNames[identity.id] = identity.name
    const skillNames: Record<string, string> = {}
    const skillToolIds: Record<string, string[]> = {}
    for (const skill of skills ?? []) {
      skillNames[skill.id] = skill.name
      skillToolIds[skill.id] = skill.tool_ids
    }
    const sopNames: Record<string, string> = {}
    for (const sop of sops ?? []) sopNames[sop.id] = sop.name
    // SOP → composed skills, from each bound SOP's loaded detail
    // (skill_invocation steps, step order preserved, deduplicated).
    const sopComposedSkillIds: Record<string, string[]> = {}
    for (const detail of sopDetails ?? []) {
      if (!detail?.id) continue
      const composedIds = (detail.steps ?? [])
        .filter((step) => step.step_type === 'skill_invocation' && step.skill_id != null)
        .slice()
        .sort((a, b) => a.order - b.order)
        .map((step) => step.skill_id as string)
      sopComposedSkillIds[detail.id] = [...new Set(composedIds)]
    }
    const dataTypeNames: Record<string, string> = {}
    for (const dataType of dataTypesPage?.items ?? []) dataTypeNames[dataType.id] = dataType.name
    const modelLabels: Record<string, string> = {}
    for (const model of availableModels ?? []) {
      modelLabels[model.model_id] = `${model.model_id} (${model.config_display_name})`
    }

    // Tools zone: tool display names + MCP server slug grouping.
    const serverSlugById = new Map<string, string>()
    for (const server of mcpServers ?? []) serverSlugById.set(server.id, server.slug)
    const toolNames: Record<string, string> = {}
    const toolServerSlugs: Record<string, string> = {}
    for (const tool of mcpTools ?? []) {
      toolNames[tool.id] = canonicalizeToolName(tool.name)
      toolServerSlugs[tool.id] = serverSlugById.get(tool.server_id) ?? tool.server_id
    }
    const toolServerColors: Record<string, string> = {}
    for (const slug of new Set(Object.values(toolServerSlugs))) {
      toolServerColors[slug] = mcpGroupColor(slug)
    }

    // Token health map per identity id: worst of the identity's own state
    // and the states of any MCP sessions client-side resolvable to it.
    // (Sessions bind via role; only identity-keyed states are resolvable
    // here — session states still surface on the dashboard cards.)
    const identityTokenHealth: Record<string, 'expiring' | 'expired'> = {}
    const fold = (state: 'expiring' | 'expired', key: string) => {
      const merged = worstTokenHealth(identityTokenHealth[key], state)
      if (merged != null) identityTokenHealth[key] = merged
    }
    for (const item of tokenHealth?.identities?.items ?? []) {
      if (item.health_state === TokenHealthState.Expired) fold('expired', item.id)
      else if (item.health_state === TokenHealthState.Expiring) fold('expiring', item.id)
    }
    // MCP session states are NOT merged here: sessions bind via role, which
    // is not client-side resolvable to a specific identity — they surface
    // on the dashboard token-health cards instead.

    const emptyKeys = [
      'role',
      'identity',
      'skills',
      'sops',
      'input_data_type',
      'output_data_type',
      'model',
    ] as const
    const empty: Record<string, string> = {}
    for (const key of emptyKeys) {
      empty[key] = t(`agents.plan.nodeTypes.empty_${key}`)
    }

    // Resolve which registry data type (if any) produced the draft input schema.
    const draftInputSchemaJson = draft.inputSchema ? JSON.stringify(draft.inputSchema) : null
    const inputDataTypeName =
      (dataTypesPage?.items ?? []).find(
        (dataType) =>
          draftInputSchemaJson !== null &&
          JSON.stringify(dataTypeToInputSchema(dataType)) === draftInputSchemaJson,
      )?.name ?? null

    // In-flight request flags — the composer renders a loading placeholder for
    // every bound entity whose reference has not resolved yet (never a raw id
    // mid-load). `isLoading` is false for completed/disabled queries, so a
    // resolved-but-missing reference keeps its raw-id fallback.
    const pending: PanelTopologyPending = {
      identity: identitiesLoading,
      role: rolesLoading,
      model: modelsLoading,
      dataTypes: dataTypesLoading,
      skills: skillsLoading,
      sops: sopsLoading,
      sopDetails: sopDetailsLoading,
      tools: mcpToolsLoading || mcpServersLoading,
    }

    return buildPanelTopology(
      agentName,
      draft,
      {
        roleNames,
        identityNames,
        skillNames,
        sopNames,
        dataTypeNames,
        modelLabels,
        inputDataTypeName,
        toolNames,
        toolServerSlugs,
        toolServerColors,
        skillToolIds,
        identityTokenHealth,
        sopComposedSkillIds,
      },
      {
        hub: t('agents.plan.nodeTypes.communication_hub'),
        empty,
        inputSchemaLabel: t('agents.types.inputSchema'),
        inputNone: t('agents.panel.noInputType'),
        inputConversation: t('agents.panel.inputTypeConversation'),
        outputLocked: t('agents.panel.topologyOutputLocked'),
        outputAuto: t('agents.types.outputAuto', { defaultValue: 'Auto' }),
        boundaryTyped: t('agents.plan.boundaryTyped'),
        boundaryConversational: t('agents.plan.boundaryConversational'),
        sections: {
          contract: t('agents.plan.sectionContract'),
          signsInAs: t('agents.plan.signsInAs'),
          assumesAs: t('agents.plan.assumesAs'),
          sops: t('agents.plan.sectionSops'),
          skills: t('agents.plan.sectionSkills'),
        },
        edges: {
          equippedWith: t('agents.plan.edgeEquipped'),
          grants: t('agents.plan.edgeGrants'),
          composed: t('agents.plan.edgeComposed'),
        },
        zones: {
          config: {
            title: t('agents.plan.zoneConfigTitle'),
            subtitle: t('agents.plan.zoneConfigSubtitle'),
          },
          capabilities: {
            title: t('agents.plan.zoneCapabilitiesTitle'),
            subtitle: t('agents.plan.zoneCapabilitiesSubtitle'),
          },
          tools: {
            title: t('agents.plan.zoneToolsTitle'),
            subtitle: t('agents.plan.zoneToolsSubtitle'),
          },
        },
        noTools: t('agents.plan.noTools'),
        loading: t('agents.panel.topologyLoading'),
      },
      pending,
    )
  }, [agentName, draft, roles, identities, skills, sops, sopDetails, dataTypesPage, availableModels, mcpTools, mcpServers, tokenHealth, t,
      rolesLoading, identitiesLoading, skillsLoading, sopsLoading, sopDetailsLoading, dataTypesLoading, modelsLoading, mcpToolsLoading, mcpServersLoading])

  const hubLabel = t('agents.plan.nodeTypes.communication_hub')
  const fullscreenLabel = t('agents.panel.topologyFullscreen')
  const fullscreenExitLabel = t('agents.panel.topologyFullscreenExit')
  const zoomInLabel = t('agents.panel.topologyZoomIn')
  const zoomOutLabel = t('agents.panel.topologyZoomOut')
  const zoomFitLabel = t('agents.panel.topologyZoomFit')
  const zoomPct = Math.round(zoom * 100)

  /**
   * The zoned canvas — inline (aspect-scaled) or fullscreen (height-filling
   * with the viewBox zoom transform; `viewZoom` is omitted inline, which is
   * the plain responsive behaviour). The font-scale cap travels with the
   * zoom: past TOPOLOGY_MAX_FONT_SCALE the renderer stops magnifying glyphs
   * so zoom reveals more world (fewer ellipsized labels) instead.
   */
  const renderCanvas = (fillHeight: boolean, viewZoom?: number) => (
    <TopologyDiagramRenderer
      nodes={graph.nodes}
      edges={graph.edges}
      zones={graph.zones}
      hubBar={{ label: hubLabel, afterZone: 'capabilities' }}
      fillHeight={fillHeight}
      viewZoom={viewZoom}
      viewFontZoom={viewZoom != null ? TOPOLOGY_MAX_FONT_SCALE : undefined}
      onNodeClick={onNodeClick}
    />
  )

  const liveChip = (
    <Chip
      label={t('agents.panel.topologyLive')}
      size="small"
      color={isDirty ? 'warning' : 'default'}
      sx={{ fontSize: 10, height: 18 }}
    />
  )

  return (
    <Box>
      {!fullscreen && (
        <>
          <Box display="flex" alignItems="center" justifyContent="space-between" sx={{ mb: 0.5 }}>
            <Box display="flex" alignItems="center" gap={1}>
              <Typography variant="subtitle1" fontWeight={600}>
                {t('agents.panel.topology')}
              </Typography>
              {liveChip}
            </Box>
            <Box display="flex" alignItems="center" gap={0.5}>
              <Typography variant="caption" color="text.secondary">
                {t('agents.panel.topologyHint')}
              </Typography>
              <Tooltip title={fullscreenLabel}>
                <IconButton
                  size="small"
                  aria-label={fullscreenLabel}
                  data-testid="panel-topology-fullscreen"
                  onClick={enterFullscreen}
                >
                  <FullscreenIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Box>
          </Box>
          {/* Zoned canvas — tinted background echoes the prototype canvas strip. */}
          <Box
            sx={{
              bgcolor: '#fafbfd',
              border: '1px solid',
              borderColor: 'divider',
              borderRadius: 1,
              px: 1,
              pb: 1,
            }}
          >
            {renderCanvas(false)}
          </Box>
        </>
      )}
      {/* Fullscreen overlay — the topology at maximum size; ESC or the
          exit toggle returns to the panel. Zoom controls step the viewBox
          zoom (0.5×–3×) around the pan centre; Fit returns to auto-fit. */}
      {fullscreen && (
        <Box
          data-testid="panel-topology-fullscreen-overlay"
          sx={{
            position: 'fixed',
            inset: 0,
            zIndex: 1300,
            bgcolor: 'background.paper',
            display: 'flex',
            flexDirection: 'column',
            p: 2,
            gap: 1,
          }}
        >
          <Box display="flex" alignItems="center" justifyContent="space-between">
            <Box display="flex" alignItems="center" gap={1}>
              <Typography variant="h6" fontWeight={600}>
                {t('agents.panel.topology')}
              </Typography>
              {liveChip}
            </Box>
            <Box display="flex" alignItems="center" gap={0.5}>
              <Tooltip title={zoomOutLabel}>
                <span>
                  <IconButton
                    size="small"
                    aria-label={zoomOutLabel}
                    data-testid="panel-topology-zoom-out"
                    onClick={zoomOut}
                    disabled={zoom <= TOPOLOGY_MIN_ZOOM}
                  >
                    <ZoomOutIcon fontSize="small" />
                  </IconButton>
                </span>
              </Tooltip>
              <Typography
                variant="caption"
                color="text.secondary"
                data-testid="panel-topology-zoom-level"
                sx={{ minWidth: 38, textAlign: 'center', fontVariantNumeric: 'tabular-nums' }}
              >
                {zoomPct}%
              </Typography>
              <Tooltip title={zoomInLabel}>
                <span>
                  <IconButton
                    size="small"
                    aria-label={zoomInLabel}
                    data-testid="panel-topology-zoom-in"
                    onClick={zoomIn}
                    disabled={zoom >= TOPOLOGY_MAX_ZOOM}
                  >
                    <ZoomInIcon fontSize="small" />
                  </IconButton>
                </span>
              </Tooltip>
              <Tooltip title={zoomFitLabel}>
                <span>
                  <IconButton
                    size="small"
                    aria-label={zoomFitLabel}
                    data-testid="panel-topology-zoom-fit"
                    onClick={zoomFit}
                    disabled={zoom === 1}
                  >
                    <FitScreenIcon fontSize="small" />
                  </IconButton>
                </span>
              </Tooltip>
              <Tooltip title={fullscreenExitLabel}>
                <IconButton
                  aria-label={fullscreenExitLabel}
                  data-testid="panel-topology-fullscreen-exit"
                  onClick={exitFullscreen}
                >
                  <FullscreenExitIcon />
                </IconButton>
              </Tooltip>
            </Box>
          </Box>
          {/* Bounded flex column — the svg (flex item) gets the remaining
              height after the legend, so the graph always fits the screen. */}
          <Box sx={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
            {renderCanvas(true, zoom)}
          </Box>
        </Box>
      )}
    </Box>
  )
}
