import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Badge,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import RemoveIcon from '@mui/icons-material/Remove'
import ZoomOutMapIcon from '@mui/icons-material/ZoomOutMap'
import FullscreenIcon from '@mui/icons-material/Fullscreen'
import FullscreenExitIcon from '@mui/icons-material/FullscreenExit'
import FilterListIcon from '@mui/icons-material/FilterList'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import MemoryIcon from '@mui/icons-material/Memory'
import ForumIcon from '@mui/icons-material/Forum'
import ExtensionIcon from '@mui/icons-material/Extension'
import HubIcon from '@mui/icons-material/Hub'
import DnsIcon from '@mui/icons-material/Dns'
import BuildIcon from '@mui/icons-material/Build'
import { useTranslation } from 'react-i18next'
import type { RuntimeTopologyNode, RuntimeTopologyProjection, ToolCallRoute } from '../../types'
import { isNodeVisibleByDefault } from '../../hooks/useRuntimeTopology'
import { AgentDetailBubble } from './AgentDetailBubble'
import { kindLabelKey, nodeKind, statusDotColor, statusLabelKey } from './runtimeNodeMeta'

interface AgentRuntimeMapCanvasProps {
  topology: RuntimeTopologyProjection | undefined
  selectedSessionId: string | null
  onSelectSession: (sessionId: string | null) => void
  onOpenIntervention: (node: RuntimeTopologyNode) => void
  onTerminateNode: (node: RuntimeTopologyNode) => void
  isFullscreen: boolean
  onToggleFullscreen: () => void
  /** Invoked after a state-changing action so the page can refresh data. */
  onChanged?: () => Promise<void> | void
  /** Whether recently-completed (terminal) agents are included (default on). */
  recentEnabled?: boolean
  /** Width of the recent-completed window in minutes (backend `recent_minutes`). */
  recentMinutes?: number
  /** Toggles the recently-completed restriction (page owns the fetch state). */
  onRecentEnabledChange?: (enabled: boolean) => void
  /** Commits a new recent-completed window in minutes (page debounces refetch). */
  onRecentMinutesChange?: (minutes: number) => void
}

// ── Layout constants ──
// Team containers (left region): one delegation tree per container, stacked
// vertically.  Inside a container, column X = delegation depth from the root
// (col 0 = main agent, col 1 = 1st-level delegation, …).
const TILE_W = 158
const TILE_H = 92
/** Tile-free vertical gutter between two depth columns (routing channel). */
const COLUMN_GAP = 28
/** Vertical gap between tiles stacked inside the same depth column. */
const ROW_STACK_GAP = 14
const GROUP_PAD_TOP = 32
const GROUP_PAD_SIDE = 16
/** Reserved tile-free bottom channel inside each container (≥ 22px). */
const CONTAINER_BOTTOM_CHANNEL = 26
/** Vertical gap between stacked team containers. */
const ROW_GAP = 44
const WORLD_PAD = 26
/** Horizontal gap between the container region and the Communication Hub. */
const INTER_REGION_GAP = 90
// Communication Hub: a vertical "firewall" bar spanning the FULL height of
// the world (at least stage-sized), pinned near the stage's right edge, so
// every bottom-channel route meets it horizontally — a fixed fixture even
// when the map is filtered empty.
const HUB_W = 46
/** Right-edge inset the hub keeps from the stage border when pinned. */
const HUB_EDGE_INSET = 24
// MCP server column (right of the hub) + tool chips column (right of MCPs).
const MCP_W = 130
const MCP_H = 48
const MCP_GAP_X = 40
const TOOL_GAP_X = 40
const TOOL_CHIP_W = 116
const TOOL_CHIP_H = 24
const TOOL_CHIP_GAP = 8
/** Horizontal stub length for the orthogonal MCP → tool-chip elbow. */
const TOOL_ELBOW_X = 14
const MIN_ZOOM = 0.25
const MAX_ZOOM = 2.5
const BUBBLE_W = 288
const BUBBLE_H = 320
// Per-agent route colours (latest-call / selected-history highlight).
const AGENT_ROUTE_COLORS = [
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
]
const ROUTE_GRAY = '#C7D0D8'
/** Delay before the filter panel auto-folds after the pointer leaves it (ms). */
const FILTER_FOLD_DELAY_MS = 1200

interface Rect {
  x: number
  y: number
  w: number
  h: number
}

interface PositionedNode {
  node: RuntimeTopologyNode
  /** Delegation depth from the tree root (== column index inside the container). */
  depth: number
  x: number
  y: number
  w: number
  h: number
}

/** One delegation tree = one team container = one horizontal row. */
interface TeamContainer {
  rootId: string
  nodes: PositionedNode[]
  x: number
  y: number
  bw: number
  bh: number
  /** Y of the tile-free bottom routing channel inside the container. */
  bottomChannelY: number
}

/** A small chip naming one distinct bare tool used via an MCP server. */
interface ToolChipDef {
  key: string
  label: string
  rect: Rect
}

/** One MCP server node (or the synthetic System Tools node) + its tool chips. */
interface McpNodeDef {
  key: string
  isSystem: boolean
  rect: Rect
  chips: ToolChipDef[]
}

/** One tool-call route: agent → (gutter → bottom channel) → hub → MCP → chip. */
interface ToolRouteDef {
  id: string
  sessionId: string
  color: string
  isLatest: boolean
  /** Orthogonal path from the agent tile to the hub's left edge. */
  inboundD: string
  /** Orthogonal path from the hub's right edge to the MCP (+ tool chip). */
  outboundD: string | null
  mcpKey: string | null
}

interface ViewportTransform {
  zoom: number
  panX: number
  panY: number
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

/**
 * Classification key of a tool-call slug for the MCP column.
 *
 * System tools (reserved ``system`` slug or an empty slug) collapse into ONE
 * synthetic "System Tools" node.  The ``unknown`` fallback slug (backend
 * degrade path for unparseable names) and the ``agent`` pseudo-slug (A2A
 * delegation "tools" — delegation is rendered as delegation edges instead)
 * are skipped entirely so neither is ever rendered as an MCP node.  Returns
 * null for skipped calls.
 */
function classifyMcpKey(mcpSlug: string | undefined): string | null {
  if (!mcpSlug || mcpSlug === 'system') return SYSTEM_MCP_KEY
  if (mcpSlug === 'unknown' || mcpSlug === 'agent') return null
  return mcpSlug
}

const SYSTEM_MCP_KEY = '__system__'

/**
 * Bare tool name: the part after the canonical ``server____`` namespace
 * (4-underscore separator), or — for older recorder rows storing the
 * OpenAI-sanitised ``server__tool`` form — after the FIRST double
 * underscore.  Names with no separator at all (legacy bare system tools)
 * are returned unchanged so chip labels stay stable across both forms.
 */
function bareToolName(toolName: string): string {
  const idx4 = toolName.indexOf('____')
  if (idx4 >= 0) return toolName.slice(idx4 + 4)
  const idx2 = toolName.indexOf('__')
  if (idx2 > 0) return toolName.slice(idx2 + 2)
  return toolName
}

/** Kind-agnostic status → i18n key for the legend chips. */
const GENERIC_STATUS_LABEL: Record<string, string> = {
  queued: 'agents.sessions.statusQueued',
  running: 'agents.sessions.statusRunning',
  completed: 'agents.sessions.statusCompleted',
  failed: 'agents.sessions.statusFailed',
  terminated: 'agents.sessions.statusTerminated',
  waiting_for_human: 'agents.sessions.statusWaiting_for_human',
  active: 'agents.sessions.runtimeStatusActive',
  sleep: 'agents.sessions.runtimeStatusSleep',
  closed: 'agents.sessions.runtimeStatusClosed',
  archived: 'agents.sessions.runtimeStatusArchived',
  error: 'agents.sessions.runtimeStatusError',
  created: 'agents.sessions.statusCreated',
}

function genericStatusDotColor(status: string): string {
  if (status === 'active') return '#00695C'
  if (status === 'sleep') return '#F57F17'
  if (status === 'closed' || status === 'archived') return '#33691E'
  if (status === 'error') return '#B71C1C'
  if (status === 'created') return '#6A1B9A'
  if (status === 'running') return '#1565C0'
  if (status === 'completed') return '#2E7D32'
  if (status === 'failed') return '#C62828'
  if (status === 'terminated') return '#E65100'
  if (status === 'queued') return '#F57F17'
  return '#B0BEC5'
}

function kindIcon(kind: 'agent' | 'conversation' | 'instance') {
  if (kind === 'conversation') return <ForumIcon fontSize="inherit" />
  if (kind === 'instance') return <ExtensionIcon fontSize="inherit" />
  return <MemoryIcon fontSize="inherit" />
}

/**
 * Auto-layout: every visible node belongs to exactly one delegation tree.
 * Trees are built from the topology edges among the visible nodes (edges =
 * parent → child); a node whose parent is filtered out is promoted to its
 * own root.  Each tree renders as ONE team container occupying ONE row,
 * stacked vertically (ordered by root created_at desc).  Inside a container
 * the column index equals the BFS depth from the root: col 0 = main agent,
 * col 1 = 1st-level delegation, and so on; nodes in a column stack
 * vertically.  A tile-free bottom channel is reserved inside every
 * container for the orthogonal tool-call routing.
 *
 * Returns the positioned containers plus the container-region world size.
 */
function layoutTrees(
  nodes: RuntimeTopologyNode[],
  edges: { parent_session_id: string; child_session_id: string }[],
): {
  containers: TeamContainer[]
  worldW: number
  worldH: number
} {
  const nodeMap = new Map(nodes.map((n) => [n.session_id, n]))

  // Delegation maps from visible edges only.
  const childrenOf = new Map<string, string[]>()
  const parentOf = new Map<string, string>()
  for (const edge of edges) {
    if (!nodeMap.has(edge.parent_session_id) || !nodeMap.has(edge.child_session_id)) continue
    const list = childrenOf.get(edge.parent_session_id) ?? []
    list.push(edge.child_session_id)
    childrenOf.set(edge.parent_session_id, list)
    parentOf.set(edge.child_session_id, edge.parent_session_id)
  }

  // Roots: visible nodes with no visible parent edge (a filtered-out parent
  // promotes the child to its own root).  Newest first, stable by id.
  const roots = nodes
    .filter((n) => !parentOf.has(n.session_id))
    .sort((a, b) => {
      if (a.created_at !== b.created_at) return a.created_at < b.created_at ? 1 : -1
      if (a.session_id !== b.session_id) return a.session_id < b.session_id ? -1 : 1
      return 0
    })

  const containers: TeamContainer[] = []
  let y = WORLD_PAD
  let maxRight = 0
  let stackBottom = WORLD_PAD

  for (const root of roots) {
    // BFS depth assignment within the tree (cycle-guarded by depthOf).
    const depthOf = new Map<string, number>([[root.session_id, 0]])
    const queue: string[] = [root.session_id]
    while (queue.length > 0) {
      const id = queue.shift() as string
      const d = depthOf.get(id) ?? 0
      for (const kid of childrenOf.get(id) ?? []) {
        if (depthOf.has(kid)) continue
        depthOf.set(kid, d + 1)
        queue.push(kid)
      }
    }

    // Column = delegation depth; nodes in a column stack vertically.
    const members = [...depthOf.keys()]
      .map((id) => nodeMap.get(id))
      .filter((n): n is RuntimeTopologyNode => n !== undefined)
    const maxDepth = members.reduce((mx, n) => Math.max(mx, depthOf.get(n.session_id) ?? 0), 0)
    const columns: RuntimeTopologyNode[][] = Array.from({ length: maxDepth + 1 }, () => [])
    for (const m of members) columns[depthOf.get(m.session_id) ?? 0].push(m)

    const contentH = columns.reduce((mx, col) => {
      if (col.length === 0) return mx
      return Math.max(mx, col.length * TILE_H + (col.length - 1) * ROW_STACK_GAP)
    }, 0)
    const bw = GROUP_PAD_SIDE * 2 + (maxDepth + 1) * TILE_W + maxDepth * COLUMN_GAP
    const bh = GROUP_PAD_TOP + contentH + CONTAINER_BOTTOM_CHANNEL

    const positioned: PositionedNode[] = []
    columns.forEach((col, depth) => {
      let ty = y + GROUP_PAD_TOP
      for (const node of col) {
        positioned.push({
          node,
          depth,
          x: WORLD_PAD + GROUP_PAD_SIDE + depth * (TILE_W + COLUMN_GAP),
          y: ty,
          w: TILE_W,
          h: TILE_H,
        })
        ty += TILE_H + ROW_STACK_GAP
      }
    })

    containers.push({
      rootId: root.session_id,
      nodes: positioned,
      x: WORLD_PAD,
      y,
      bw,
      bh,
      bottomChannelY: y + GROUP_PAD_TOP + contentH + CONTAINER_BOTTOM_CHANNEL / 2,
    })
    maxRight = Math.max(maxRight, WORLD_PAD + bw)
    y += bh + ROW_GAP
    stackBottom = y - ROW_GAP
  }

  const worldW = Math.max(maxRight + WORLD_PAD, 420)
  const worldH = Math.max(stackBottom + WORLD_PAD, 200)
  return { containers, worldW, worldH }
}

export function AgentRuntimeMapCanvas({
  topology,
  selectedSessionId,
  onSelectSession,
  onOpenIntervention,
  onTerminateNode,
  isFullscreen,
  onToggleFullscreen,
  onChanged,
  recentEnabled = true,
  recentMinutes = 30,
  onRecentEnabledChange,
  onRecentMinutesChange,
}: AgentRuntimeMapCanvasProps) {
  const { t } = useTranslation()
  const viewportRef = useRef<HTMLDivElement | null>(null)

  const [transform, setTransform] = useState<ViewportTransform>({ zoom: 1, panX: 0, panY: 0 })
  const [viewportSize, setViewportSize] = useState({ width: 0, height: 0 })
  const [panning, setPanning] = useState(false)
  const [filterOpen, setFilterOpen] = useState(false)
  const [hiddenStatuses, setHiddenStatuses] = useState<Set<string>>(new Set())
  const [hiddenKinds, setHiddenKinds] = useState<Set<string>>(new Set())

  const panningRef = useRef(false)
  const lastPointerRef = useRef({ x: 0, y: 0 })

  // ── Filter popover open/fold behaviour ──
  const filterAnchorRef = useRef<HTMLDivElement | null>(null)
  const foldTimerRef = useRef<number | null>(null)

  const clearFoldTimer = useCallback(() => {
    if (foldTimerRef.current !== null) {
      window.clearTimeout(foldTimerRef.current)
      foldTimerRef.current = null
    }
  }, [])

  const scheduleFold = useCallback(() => {
    clearFoldTimer()
    foldTimerRef.current = window.setTimeout(() => setFilterOpen(false), FILTER_FOLD_DELAY_MS)
  }, [clearFoldTimer])

  const openFilter = useCallback(() => {
    clearFoldTimer()
    setFilterOpen(true)
  }, [clearFoldTimer])

  const toggleFilter = useCallback(() => {
    clearFoldTimer()
    setFilterOpen((v) => !v)
  }, [clearFoldTimer])

  // While expanded: fold immediately on click outside (document-level) or
  // Escape; the 1.2s pointer-leave fold is scheduled by onMouseLeave above.
  useEffect(() => {
    if (!filterOpen) return
    const onDocMouseDown = (e: MouseEvent) => {
      const root = filterAnchorRef.current
      if (root && !root.contains(e.target as Node)) setFilterOpen(false)
    }
    const onDocKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setFilterOpen(false)
    }
    document.addEventListener('mousedown', onDocMouseDown)
    document.addEventListener('keydown', onDocKeyDown)
    return () => {
      document.removeEventListener('mousedown', onDocMouseDown)
      document.removeEventListener('keydown', onDocKeyDown)
    }
  }, [filterOpen])

  // Clear any pending fold timer on unmount.
  useEffect(() => clearFoldTimer, [clearFoldTimer])

  // ── Recently-completed window control (numeric input + unit select) ──
  const [windowUnit, setWindowUnit] = useState<'minutes' | 'hours'>('minutes')
  const [minutesDraft, setMinutesDraft] = useState<string>(() =>
    String(recentMinutes),
  )
  // Keep the draft in sync with the committed value / selected unit.
  useEffect(() => {
    setMinutesDraft(
      String(windowUnit === 'minutes' ? recentMinutes : Math.round(recentMinutes / 60)),
    )
  }, [recentMinutes, windowUnit])

  const commitMinutesDraft = useCallback(
    (raw: string) => {
      const parsed = parseInt(raw, 10)
      if (Number.isNaN(parsed)) return
      const minutes = windowUnit === 'hours' ? parsed * 60 : parsed
      // Clamp ≥ 1 minute — a 0/negative window would disable the fetch.
      onRecentMinutesChange?.(Math.max(1, minutes))
    },
    [onRecentMinutesChange, windowUnit],
  )

  const allNodes = topology?.nodes ?? []

  // Default-visibility predicate + legend (status/kind) filter.
  const visibleNodes = useMemo(
    () =>
      allNodes.filter((node) => {
        if (!isNodeVisibleByDefault(node)) return false
        if (hiddenStatuses.has(node.status)) return false
        if (hiddenKinds.has(nodeKind(node))) return false
        return true
      }),
    [allNodes, hiddenStatuses, hiddenKinds],
  )

  const layout = useMemo(
    () =>
      layoutTrees(
        visibleNodes,
        (topology?.edges ?? []) as { parent_session_id: string; child_session_id: string }[],
      ),
    [visibleNodes, topology?.edges],
  )

  const positionedMap = useMemo(() => {
    const m = new Map<string, PositionedNode>()
    for (const container of layout.containers) {
      for (const p of container.nodes) m.set(p.node.session_id, p)
    }
    return m
  }, [layout.containers])

  // Per-agent route colour (deterministic by visible order).
  const agentColor = useMemo(() => {
    const m = new Map<string, string>()
    visibleNodes.forEach((n, i) => m.set(n.session_id, AGENT_ROUTE_COLORS[i % AGENT_ROUTE_COLORS.length]))
    return m
  }, [visibleNodes])

  // Communication Hub "firewall" + evenly distributed MCP nodes + tool chips
  // + orthogonal per-call tool routes.  The world is at least stage-sized so
  // the hub pins to the stage's right edge as a full-height fixture.
  const { hub, mcpNodes, routes, worldW, worldH } = useMemo(() => {
    const containers = layout.containers
    // Right edge of the container region — the hub never sits left of it.
    const containersRight = containers.reduce((mx, c) => Math.max(mx, c.x + c.bw), WORLD_PAD)

    // Collect the MCP slugs actually used by visible agents (plus the
    // synthetic System Tools bucket) and the distinct bare tool names per
    // slug.  Skipped calls (classifyMcpKey → null, A2A delegation rows)
    // render nothing at all.
    const slugOrder: string[] = []
    const toolsBySlug = new Map<string, Set<string>>()
    for (const node of visibleNodes) {
      for (const call of node.tool_calls ?? []) {
        if (call.route_type === 'a2a') continue
        const key = classifyMcpKey(call.mcp_slug)
        if (key === null) continue
        let tools = toolsBySlug.get(key)
        if (!tools) {
          tools = new Set()
          toolsBySlug.set(key, tools)
          slugOrder.push(key)
        }
        tools.add(bareToolName(call.tool_name))
      }
    }
    slugOrder.sort((a, b) => {
      if (a === SYSTEM_MCP_KEY) return -1
      if (b === SYSTEM_MCP_KEY) return 1
      return a < b ? -1 : a > b ? 1 : 0
    })

    // The world is at least as large as the visible stage so the hub can
    // pin to the stage's right edge as a full-height fixture — including
    // the filtered-empty state (no containers, no MCP/tool columns).
    const worldW = Math.max(layout.worldW, viewportSize.width)
    const worldH = Math.max(layout.worldH, viewportSize.height)

    // Communication Hub: full-height (spans the whole world) and pinned
    // near the right edge of the stage, never left of the containers.
    const hub: Rect = {
      x: Math.max(containersRight + INTER_REGION_GAP, viewportSize.width - HUB_W - HUB_EDGE_INSET),
      y: 0,
      w: HUB_W,
      h: worldH,
    }

    // Container lookup for the bottom-channel routing.
    const containerBySession = new Map<string, TeamContainer>()
    for (const c of containers) {
      for (const pn of c.nodes) containerBySession.set(pn.node.session_id, c)
    }

    // Distribute the MCP nodes evenly along the hub's height.
    const mcpX = hub.x + hub.w + MCP_GAP_X
    const count = slugOrder.length
    const mcpByKey = new Map<string, McpNodeDef>()
    const mcpNodes: McpNodeDef[] = slugOrder.map((key, i) => {
      const centerY = hub.y + hub.h * ((i + 1) / (count + 1))
      const rect: Rect = { x: mcpX, y: centerY - MCP_H / 2, w: MCP_W, h: MCP_H }
      const names = [...(toolsBySlug.get(key) ?? [])].sort()
      const chipsTotal = names.length * TOOL_CHIP_H + Math.max(0, names.length - 1) * TOOL_CHIP_GAP
      const chipsStartY = centerY - chipsTotal / 2
      const chips: ToolChipDef[] = names.map((name, j) => ({
        key: `${key}::${name}`,
        label: name,
        rect: {
          x: rect.x + MCP_W + TOOL_GAP_X,
          y: chipsStartY + j * (TOOL_CHIP_H + TOOL_CHIP_GAP),
          w: TOOL_CHIP_W,
          h: TOOL_CHIP_H,
        },
      }))
      const def: McpNodeDef = { key, isSystem: key === SYSTEM_MCP_KEY, rect, chips }
      mcpByKey.set(key, def)
      return def
    })

    // Orthogonal tool-call routes, one per call:
    //   agent right edge → gutter → container bottom channel → hub left edge
    //   hub right edge → MCP left edge (→ elbow → tool chip)
    // A2A rows are delegations (rendered as delegation edges) — skipped.
    const routes: ToolRouteDef[] = []
    for (const node of visibleNodes) {
      const pos = positionedMap.get(node.session_id)
      const container = containerBySession.get(node.session_id)
      if (!pos || !container) continue
      let drawn = 0
      ;(node.tool_calls ?? []).forEach((call: ToolCallRoute) => {
        // A2A rows are delegations (rendered as delegation edges) — skipped.
        if (call.route_type === 'a2a') return
        const key = classifyMcpKey(call.mcp_slug)
        const isLatest = drawn === 0
        drawn += 1
        const isSelected = selectedSessionId === node.session_id
        const color =
          isLatest || isSelected
            ? (agentColor.get(node.session_id) ?? '#3949AB')
            : ROUTE_GRAY

        // Segment 1+2: out of the tile into the tile-free column gutter,
        // then down to the container's tile-free bottom channel.
        const ax = pos.x + pos.w
        const ay = pos.y + pos.h / 2
        const gutterX = Math.min(ax + COLUMN_GAP / 2, container.x + container.bw - 6)
        const channelY = container.bottomChannelY
        // Segment 3: horizontal run along the bottom channel to the hub.
        const inboundD = `M ${ax} ${ay} L ${gutterX} ${ay} L ${gutterX} ${channelY} L ${hub.x} ${channelY}`

        // Segments 4+5: through the hub (visually joined by the hub node) to
        // the MCP and on to the tool chip — all horizontal at the MCP's Y.
        const mcp = key === null ? null : (mcpByKey.get(key) ?? null)
        let outboundD: string | null = null
        if (mcp) {
          const mcy = mcp.rect.y + MCP_H / 2
          let d = `M ${hub.x + hub.w} ${mcy} L ${mcp.rect.x} ${mcy}`
          const bare = bareToolName(call.tool_name)
          const chip = mcp.chips.find((ch) => ch.label === bare)
          if (chip) {
            const chipY = chip.rect.y + TOOL_CHIP_H / 2
            const elbowX = mcp.rect.x + MCP_W + TOOL_ELBOW_X
            d += ` M ${mcp.rect.x + MCP_W} ${mcy} L ${elbowX} ${mcy} L ${elbowX} ${chipY} L ${chip.rect.x} ${chipY}`
          }
          outboundD = d
        }

        routes.push({
          id: `${node.session_id}#${drawn - 1}`,
          sessionId: node.session_id,
          color,
          isLatest,
          inboundD,
          outboundD,
          mcpKey: key,
        })
      })
    }

    const maxMcpRight =
      mcpNodes.length > 0 ? Math.max(...mcpNodes.map((m) => m.rect.x + m.rect.w)) : hub.x + hub.w
    const maxChipRight = mcpNodes.reduce(
      (mx, m) => Math.max(mx, ...m.chips.map((ch) => ch.rect.x + ch.rect.w), 0),
      0,
    )
    const finalWorldW = Math.max(
      worldW,
      (maxChipRight > 0 ? maxChipRight : maxMcpRight) + WORLD_PAD,
    )
    return { hub, mcpNodes, routes, worldW: finalWorldW, worldH }
  }, [layout, visibleNodes, positionedMap, agentColor, selectedSessionId, viewportSize])

  // When an agent is selected, outline its involved MCP + tool nodes in the
  // agent's colour and dim unrelated ones so the full path agent → hub →
  // MCP → tool is obvious.  Precision: only the (mcp_slug, bare_tool) pairs
  // the agent ACTUALLY called are highlighted — never the whole MCP's chip
  // list.  A2A rows are delegations, not tool calls, and are excluded.
  const selectedColor = selectedSessionId ? (agentColor.get(selectedSessionId) ?? null) : null
  const selectedCallPairs = useMemo(() => {
    const pairs = new Map<string, Set<string>>()
    if (!selectedSessionId) return pairs
    const agent = visibleNodes.find((n) => n.session_id === selectedSessionId)
    for (const call of agent?.tool_calls ?? []) {
      if (call.route_type === 'a2a') continue
      const key = classifyMcpKey(call.mcp_slug)
      if (key === null) continue
      let tools = pairs.get(key)
      if (!tools) {
        tools = new Set()
        pairs.set(key, tools)
      }
      tools.add(bareToolName(call.tool_name))
    }
    return pairs
  }, [selectedSessionId, visibleNodes])

  const availableStatuses = useMemo(() => {
    const set = new Set<string>()
    for (const node of allNodes) set.add(node.status)
    return [...set].sort()
  }, [allNodes])

  const availableKinds = useMemo(() => {
    const set = new Set<'agent' | 'conversation' | 'instance'>()
    for (const node of allNodes) set.add(nodeKind(node))
    return [...set].sort()
  }, [allNodes])

  const worldSizeRef = useRef({ w: worldW, h: worldH })
  useEffect(() => {
    worldSizeRef.current = { w: worldW, h: worldH }
  }, [worldW, worldH])

  const fitToScreen = useCallback(() => {
    const el = viewportRef.current
    const { w, h } = worldSizeRef.current
    if (!el || w <= 0 || h <= 0) return
    const vw = el.clientWidth
    const vh = el.clientHeight
    const m = 56
    const s = Math.min((vw - m * 2) / w, (vh - m * 2) / h)
    const zoom = clamp(s, MIN_ZOOM, MAX_ZOOM)
    const panX = (vw - w * zoom) / 2
    const panY = (vh - h * zoom) / 2
    setTransform({ zoom, panX, panY })
  }, [])

  // Initial fit once content is available.
  const hasFittedRef = useRef(false)
  useEffect(() => {
    if (worldW > 0 && worldH > 0 && !hasFittedRef.current) {
      fitToScreen()
      hasFittedRef.current = true
    }
  }, [worldW, worldH, fitToScreen])

  // Re-fit on resize (and fullscreen size changes) via ResizeObserver.
  useEffect(() => {
    const el = viewportRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => {
      setViewportSize({ width: el.clientWidth, height: el.clientHeight })
      fitToScreen()
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [fitToScreen])

  // Re-fit shortly after a fullscreen toggle (layout settles after style change).
  useEffect(() => {
    const id = window.setTimeout(() => fitToScreen(), 60)
    return () => window.clearTimeout(id)
  }, [isFullscreen, fitToScreen])

  const applyZoomAt = useCallback((clientX: number, clientY: number, factor: number) => {
    const el = viewportRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const mx = clientX - rect.left
    const my = clientY - rect.top
    setTransform((prev) => {
      const before = prev.zoom
      const zoom = clamp(prev.zoom * factor, MIN_ZOOM, MAX_ZOOM)
      const k = zoom / before
      const panX = mx - (mx - prev.panX) * k
      const panY = my - (my - prev.panY) * k
      return { zoom, panX, panY }
    })
  }, [])

  // Wheel zoom (non-passive to preventDefault).
  useEffect(() => {
    const el = viewportRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      applyZoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1.12 : 1 / 1.12)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [applyZoomAt])

  // Drag-to-pan (background only).
  const handleStageMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return
    const target = e.target as HTMLElement
    if (target.closest('[data-map-interactive="true"]')) return
    panningRef.current = true
    lastPointerRef.current = { x: e.clientX, y: e.clientY }
    setPanning(true)
    e.preventDefault()
  }

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!panningRef.current) return
      const dx = e.clientX - lastPointerRef.current.x
      const dy = e.clientY - lastPointerRef.current.y
      lastPointerRef.current = { x: e.clientX, y: e.clientY }
      setTransform((prev) => ({ ...prev, panX: prev.panX + dx, panY: prev.panY + dy }))
    }
    const onUp = () => {
      panningRef.current = false
      setPanning(false)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [])

  const toggleStatus = (status: string) => {
    setHiddenStatuses((prev) => {
      const next = new Set(prev)
      if (next.has(status)) next.delete(status)
      else next.add(status)
      return next
    })
  }

  const toggleKind = (kind: string) => {
    setHiddenKinds((prev) => {
      const next = new Set(prev)
      if (next.has(kind)) next.delete(kind)
      else next.add(kind)
      return next
    })
  }

  const resetFilters = () => {
    setHiddenStatuses(new Set())
    setHiddenKinds(new Set())
  }

  // Count of ACTIVE filter restrictions for the collapsed button badge:
  // hidden statuses + hidden kinds + the recently-completed restriction
  // (when toggled off, recently-finished terminal agents are hidden).
  const activeFilterCount =
    hiddenStatuses.size + hiddenKinds.size + (recentEnabled ? 0 : 1)
  // Chip-driven hiding decides whether the filtered-empty overlay offers a
  // "reset filters" recovery (the recent window is a server-side param the
  // overlay's reset cannot restore).
  const hasActiveFilters = hiddenStatuses.size > 0 || hiddenKinds.size > 0

  const selectedPositioned = selectedSessionId ? positionedMap.get(selectedSessionId) : undefined
  const selectedNode = selectedPositioned?.node

  const bubblePosition = useMemo(() => {
    if (!selectedPositioned) return null
    const a = selectedPositioned
    const tx = a.x * transform.zoom + transform.panX
    const ty = a.y * transform.zoom + transform.panY
    const vw = viewportSize.width
    const vh = viewportSize.height
    let bx = tx + a.w * transform.zoom + 12
    let by = ty - 6
    if (bx + BUBBLE_W > vw - 8) bx = tx - BUBBLE_W - 12
    if (bx < 8) bx = 8
    if (by + BUBBLE_H > vh - 8) by = vh - BUBBLE_H - 8
    if (by < 8) by = 8
    return { left: bx, top: by }
  }, [selectedPositioned, transform, viewportSize])

  if (topology === undefined) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" height={520}>
        <CircularProgress data-testid="runtime-monitor-loading" />
      </Box>
    )
  }

  // Truly empty population (no nodes at all) — a clean empty state with
  // no toolbar/legend, distinct from the filter-driven empty state.
  if (allNodes.length === 0) {
    return (
      <Box
        display="flex"
        justifyContent="center"
        alignItems="center"
        height={520}
        data-testid="runtime-monitor-empty"
      >
        <Typography variant="body2" color="text.secondary">
          {t('agents.sessions.runtimeMonitorEmpty')}
        </Typography>
      </Box>
    )
  }

  const zoomPct = Math.round(transform.zoom * 100)
  const filteredEmpty = visibleNodes.length === 0

  return (
    <Box
      ref={viewportRef}
      data-testid="agent-runtime-map-canvas"
      onMouseDown={handleStageMouseDown}
      sx={{
        position: isFullscreen ? 'fixed' : 'relative',
        inset: isFullscreen ? 0 : undefined,
        zIndex: isFullscreen ? 1300 : undefined,
        width: isFullscreen ? '100vw' : '100%',
        height: isFullscreen ? '100vh' : 'calc(100vh - 260px)',
        minHeight: isFullscreen ? undefined : 520,
        overflow: 'hidden',
        bgcolor: '#EFF3F7',
        border: isFullscreen ? 'none' : '1px solid',
        borderColor: 'divider',
        borderRadius: isFullscreen ? 0 : 1,
        cursor: panning ? 'grabbing' : 'grab',
      }}
    >
      {/* World (transformed) */}
      <Box
        sx={{
          position: 'absolute',
          left: 0,
          top: 0,
          width: worldW,
          height: worldH,
          transform: `translate(${transform.panX}px, ${transform.panY}px) scale(${transform.zoom})`,
          transformOrigin: '0 0',
          userSelect: 'none',
          backgroundColor: '#F4F7FA',
          backgroundImage: 'radial-gradient(#D7E0EA 1px, transparent 1px)',
          backgroundSize: '22px 22px',
        }}
      >
        {/* Team containers: one delegation tree per container, one row each */}
        {layout.containers.map((container) => (
          <Box
            key={container.rootId}
            data-testid={`team-container-${container.rootId}`}
            sx={{
              position: 'absolute',
              left: container.x,
              top: container.y,
              width: container.bw,
              height: container.bh,
              border: '1px dashed #B0BEC5',
              borderRadius: '12px',
              backgroundColor: 'rgba(255,255,255,0.55)',
              zIndex: 1,
            }}
          >
            <Box display="flex" alignItems="center" gap={0.75} sx={{ position: 'absolute', top: 7, left: 12 }}>
              <Typography variant="caption" fontWeight={700} color="#455A64" sx={{ letterSpacing: 0.2 }}>
                {container.nodes[0]?.node.agent_type_name ?? t('agents.sessions.runtimeUnknownAgent')}
              </Typography>
              {container.nodes.length > 1 && (
                <Chip
                  size="small"
                  label={container.nodes.length}
                  sx={{ height: 16, fontSize: 10, bgcolor: '#ECEFF3', color: '#607D8B' }}
                />
              )}
            </Box>
          </Box>
        ))}

        {/* Connectors + tool-call routes (orthogonal, multi-segment) */}
        <svg
          width={worldW}
          height={worldH}
          style={{ position: 'absolute', left: 0, top: 0, zIndex: 2, pointerEvents: 'none', overflow: 'visible' }}
        >
          <defs>
            <marker
              id="arm-connector-arrow"
              markerWidth="9"
              markerHeight="9"
              refX="7.5"
              refY="4.5"
              orient="auto"
              markerUnits="strokeWidth"
            >
              <path d="M0,0 L9,4.5 L0,9 z" fill="#90A4AE" />
            </marker>
          </defs>
          {/* Delegation connectors: parent right edge → gutter elbow → child left edge */}
          {(topology?.edges ?? []).map((edge) => {
            const from = positionedMap.get(edge.parent_session_id)
            const to = positionedMap.get(edge.child_session_id)
            if (!from || !to) return null
            const x1 = from.x + from.w
            const y1 = from.y + from.h / 2
            const x2 = to.x
            const y2 = to.y + to.h / 2
            let d: string
            if (x2 >= x1 + 8) {
              // Clean elbow through the tile-free gutter between the two columns.
              const gx = x1 + COLUMN_GAP / 2
              d = `M ${x1} ${y1} L ${gx} ${y1} L ${gx} ${y2} L ${x2} ${y2}`
            } else {
              // Degenerate same-column edge (cross edges): keep the old curve.
              const dx = (x2 - x1) * 0.55
              d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`
            }
            return (
              <path
                key={`${edge.parent_session_id}-${edge.child_session_id}`}
                d={d}
                fill="none"
                stroke="#90A4AE"
                strokeWidth={1.6}
                markerEnd="url(#arm-connector-arrow)"
              />
            )
          })}

          {/* Tool-call routes: agent → hub (inbound) and hub → MCP → tool (outbound).
              The hub node visually joins the two halves at its own Y. */}
          {routes.map((route) => {
            const highlighted = selectedSessionId === route.sessionId
            const dimmed = selectedSessionId !== null && !highlighted
            const isGray = route.color === ROUTE_GRAY
            const strokeWidth = highlighted ? 2.5 : isGray ? 1.2 : 2
            const strokeOpacity = dimmed ? 0.3 : highlighted ? 1 : isGray ? 0.5 : 0.9
            const renderPath = (d: string, kind: 'inbound' | 'outbound', idx: number) => (
              <path
                key={`${route.id}-${kind}-${idx}`}
                d={d}
                fill="none"
                stroke={route.color}
                strokeWidth={strokeWidth}
                strokeOpacity={strokeOpacity}
                data-route-kind="tool"
                data-route-session={route.sessionId}
                data-highlighted={highlighted ? 'true' : undefined}
                data-dimmed={dimmed ? 'true' : undefined}
              />
            )
            return (
              <Fragment key={route.id}>
                {renderPath(route.inboundD, 'inbound', 0)}
                {route.outboundD && renderPath(route.outboundD, 'outbound', 1)}
              </Fragment>
            )
          })}
        </svg>

        {/* Tiles (delegation-depth column + owning container exposed for tests) */}
        {layout.containers.map((container) =>
          container.nodes.map(({ node, depth, x, y, w, h }) => {
            const kind = nodeKind(node)
            const isSelected = selectedSessionId === node.session_id
            // Any node awaiting human intervention gets the alert treatment —
            // including agent jobs paused in `waiting_for_human`.
            const needsAlert = node.needs_intervention === true
            // First non-delegation call (A2A rows are not tool executions).
            const latestTool = node.tool_calls?.find((c) => c.route_type !== 'a2a')
            const triggerLabel =
              node.trigger_source_label ??
              t(
                node.trigger_source === 'delegated'
                  ? 'agents.sessions.runtimeTriggerSourceDelegated'
                  : node.trigger_source === 'schedule'
                    ? 'agents.sessions.runtimeTriggerSourceSchedule'
                    : node.trigger_source === 'user'
                      ? 'agents.sessions.runtimeTriggerSourceUser'
                      : 'agents.sessions.runtimeTriggerSourceUnknown',
              )
            return (
              <Box
                key={node.session_id}
                data-map-interactive="true"
                role="button"
                tabIndex={0}
                data-container={container.rootId}
                data-depth={depth}
                aria-label={`${node.agent_type_name ?? t('agents.sessions.runtimeUnknownAgent')} — ${t(statusLabelKey(node.status, kind), node.status)}`}
                onClick={() => onSelectSession(node.session_id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onSelectSession(node.session_id)
                  }
                }}
                sx={{
                  position: 'absolute',
                  left: x,
                  top: y,
                  width: w,
                  height: h,
                  zIndex: 3,
                  backgroundColor: needsAlert ? '#FFFBEB' : '#FFFFFF',
                  border: isSelected ? '2px solid #1976D2' : needsAlert ? '2px solid #FF9800' : '1px solid #CFD8DC',
                  borderColor: isSelected ? '#1976D2' : needsAlert ? '#FF9800' : '#CFD8DC',
                  borderRadius: '10px',
                  boxShadow: isSelected ? 2 : 1,
                  p: 1,
                  cursor: 'pointer',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 0.5,
                  '&:hover': { borderColor: needsAlert ? '#FB8C00' : '#90CAF9' },
                }}
              >
                <Box display="flex" alignItems="center" gap={0.75} minWidth={0}>
                  <Box
                    sx={{
                      width: 18,
                      height: 18,
                      borderRadius: '5px',
                      bgcolor: '#F1F5F9',
                      color: '#607D8B',
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 11,
                      flexShrink: 0,
                    }}
                  >
                    {kindIcon(kind)}
                  </Box>
                  <Typography
                    variant="caption"
                    fontWeight={600}
                    sx={{ flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                  >
                    {node.agent_type_name ?? t('agents.sessions.runtimeUnknownAgent')}
                  </Typography>
                  <Box
                    sx={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      bgcolor: statusDotColor(node.status, kind),
                      flexShrink: 0,
                      boxShadow: needsAlert ? '0 0 0 3px rgba(255,152,0,0.22)' : undefined,
                    }}
                    aria-hidden
                  />
                </Box>
                <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace', fontSize: 11, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {node.session_id}
                </Typography>
                <Box display="flex" alignItems="center" gap={0.75}>
                  <Typography variant="caption" color="text.secondary" sx={{ fontSize: 11 }}>
                    {t(statusLabelKey(node.status, kind), node.status)}
                  </Typography>
                </Box>

                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ fontSize: 10, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                  data-testid={`trigger-source-${node.session_id}`}
                >
                  {t('agents.sessions.runtimeTriggeredBy', { source: triggerLabel })}
                </Typography>

                {latestTool && (
                  <Tooltip
                    title={t('agents.sessions.runtimeMonitorLatestToolTitle', {
                      tool: latestTool.tool_name,
                      server: latestTool.mcp_slug,
                    })}
                  >
                    <Box
                      display="flex"
                      alignItems="center"
                      gap={0.5}
                      data-testid={`latest-tool-${node.session_id}`}
                      sx={{
                        mt: 'auto',
                        maxWidth: '100%',
                        bgcolor: '#F1F5F9',
                        borderRadius: '5px',
                        px: 0.5,
                        py: '1px',
                      }}
                    >
                      <BuildIcon sx={{ fontSize: 10, color: '#607D8B', flexShrink: 0 }} />
                      <Typography
                        variant="caption"
                        sx={{
                          fontSize: 10,
                          color: '#455A64',
                          fontFamily: 'monospace',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                        }}
                      >
                        {latestTool.tool_name}
                      </Typography>
                    </Box>
                  </Tooltip>
                )}

                {needsAlert && (
                  <Tooltip title={t('agents.sessions.runtimeMonitorRequiresIntervention')}>
                    <IconButton
                      size="small"
                      aria-label={t('agents.sessions.runtimeMonitorRequiresIntervention')}
                      data-testid={`intervention-alert-${node.session_id}`}
                      onClick={(e) => {
                        e.stopPropagation()
                        onOpenIntervention(node)
                      }}
                      sx={{
                        position: 'absolute',
                        top: -9,
                        right: -9,
                        width: 22,
                        height: 22,
                        bgcolor: '#FF9800',
                        color: '#fff',
                        border: '2px solid #fff',
                        zIndex: 4,
                        '&:hover': { bgcolor: '#FB8C00' },
                      }}
                    >
                      <WarningAmberIcon sx={{ fontSize: 13 }} />
                    </IconButton>
                  </Tooltip>
                )}
              </Box>
            )
          }),
        )}

        {/* Communication Hub — full-height firewall fixture pinned to the
            stage's right edge (spans the whole world, even when filtered empty) */}
        <Box
          data-testid="communication-hub-node"
          sx={{
            position: 'absolute',
            left: hub.x,
            top: hub.y,
            width: hub.w,
            height: hub.h,
            zIndex: 3,
            border: '1px solid #90A4AE',
            borderRadius: '12px',
            backgroundColor: '#FFFFFF',
            boxShadow: 1,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 0.75,
            py: 1,
          }}
        >
          <Box
            sx={{
              width: 22,
              height: 22,
              borderRadius: '6px',
              bgcolor: '#ECEFF3',
              color: '#37474F',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            <HubIcon sx={{ fontSize: 14 }} />
          </Box>
          <Typography
            variant="caption"
            fontWeight={700}
            color="#37474F"
            sx={{
              writingMode: 'vertical-rl',
              transform: 'rotate(180deg)',
              whiteSpace: 'nowrap',
              letterSpacing: 0.4,
            }}
          >
            {t('agents.sessions.runtimeCommunicationHub')}
          </Typography>
        </Box>

        {/* MCP server nodes — evenly distributed along the hub's height */}
        {mcpNodes.map((mcp) => {
          const involved = selectedSessionId !== null && selectedCallPairs.has(mcp.key)
          const dimmed = selectedSessionId !== null && !involved
          return (
            <Box
              key={mcp.key}
              data-testid={mcp.isSystem ? 'system-tools-node' : `mcp-server-node-${mcp.key}`}
              data-highlighted={involved ? 'true' : undefined}
              data-dimmed={dimmed ? 'true' : undefined}
              sx={{
                position: 'absolute',
                left: mcp.rect.x,
                top: mcp.rect.y,
                width: mcp.rect.w,
                height: mcp.rect.h,
                zIndex: 3,
                border: involved && selectedColor ? `2px solid ${selectedColor}` : '1px solid #CFD8DC',
                borderRadius: '10px',
                backgroundColor: '#FFFFFF',
                boxShadow: involved && selectedColor ? `0 0 0 3px ${selectedColor}22` : 1,
                opacity: dimmed ? 0.55 : 1,
                display: 'flex',
                alignItems: 'center',
                gap: 0.5,
                px: 1,
              }}
            >
              <Box
                sx={{
                  width: 18,
                  height: 18,
                  borderRadius: '5px',
                  bgcolor: '#F1F5F9',
                  color: '#607D8B',
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}
              >
                {mcp.isSystem ? <BuildIcon sx={{ fontSize: 11 }} /> : <DnsIcon sx={{ fontSize: 11 }} />}
              </Box>
              <Typography
                variant="caption"
                sx={{
                  color: '#455A64',
                  fontWeight: 600,
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {mcp.isSystem ? t('agents.sessions.runtimeMonitorSystemTools') : mcp.key}
              </Typography>
            </Box>
          )
        })}

        {/* Tool chips — distinct bare tool names per MCP, centred on the MCP node.
            Only chips matching the selected agent's ACTUAL calls are highlighted. */}
        {mcpNodes.flatMap((mcp) =>
          mcp.chips.map((chip) => {
            const usedTools = selectedSessionId !== null ? selectedCallPairs.get(mcp.key) : undefined
            const involved = usedTools !== undefined && usedTools.has(chip.label)
            const dimmed = selectedSessionId !== null && !involved
            return (
              <Tooltip key={chip.key} title={chip.label}>
                <Box
                  data-testid={`tool-chip-${mcp.key === SYSTEM_MCP_KEY ? 'system' : mcp.key}-${chip.label}`}
                  data-highlighted={involved ? 'true' : undefined}
                  data-dimmed={dimmed ? 'true' : undefined}
                  sx={{
                    position: 'absolute',
                    left: chip.rect.x,
                    top: chip.rect.y,
                    width: chip.rect.w,
                    height: chip.rect.h,
                    zIndex: 3,
                    border: involved && selectedColor ? `1.5px solid ${selectedColor}` : '1px solid #CFD8DC',
                    borderRadius: '6px',
                    backgroundColor: '#FFFFFF',
                    boxShadow: 1,
                    opacity: dimmed ? 0.55 : 1,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 0.5,
                    px: 0.75,
                    overflow: 'hidden',
                  }}
                >
                  <BuildIcon sx={{ fontSize: 10, color: '#607D8B', flexShrink: 0 }} />
                  <Typography
                    variant="caption"
                    sx={{
                      fontSize: 10,
                      color: '#455A64',
                      fontFamily: 'monospace',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    {chip.label}
                  </Typography>
                </Box>
              </Tooltip>
            )
          }),
        )}
      </Box>

      {/* Filter-driven empty state: overlay on the canvas, keeping the
          toolbar + legend visible and usable so the operator can always
          reset filters and restore the population. */}
      {filteredEmpty && (
        <Box
          data-testid="runtime-monitor-filtered-empty"
          sx={{
            position: 'absolute',
            inset: 0,
            zIndex: 15,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 1,
            pointerEvents: 'none',
          }}
        >
          <Typography variant="body2" color="text.secondary">
            {hasActiveFilters
              ? t('agents.sessions.runtimeMonitorFilteredEmpty')
              : t('agents.sessions.runtimeMonitorEmpty')}
          </Typography>
          {hasActiveFilters && (
            <Button
              data-testid="runtime-monitor-reset-filters"
              data-map-interactive="true"
              variant="outlined"
              size="small"
              onClick={resetFilters}
              sx={{ pointerEvents: 'auto' }}
            >
              {t('agents.sessions.runtimeMonitorResetFilters')}
            </Button>
          )}
        </Box>
      )}

      {/* Toolbar */}
      <Box
        data-map-interactive="true"
        sx={{
          position: 'absolute',
          right: 16,
          top: 16,
          zIndex: 20,
          bgcolor: '#fff',
          border: '1px solid',
          borderColor: 'divider',
          borderRadius: '10px',
          boxShadow: 2,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        <Tooltip title={t('agents.sessions.runtimeMonitorZoomIn')}>
          <IconButton
            aria-label={t('agents.sessions.runtimeMonitorZoomIn')}
            onClick={() => {
              const el = viewportRef.current
              if (!el) return
              const rect = el.getBoundingClientRect()
              applyZoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, 1.25)
            }}
            sx={{ width: 42, height: 40, borderRadius: 0 }}
          >
            <AddIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title={t('agents.sessions.runtimeMonitorZoomOut')}>
          <IconButton
            aria-label={t('agents.sessions.runtimeMonitorZoomOut')}
            onClick={() => {
              const el = viewportRef.current
              if (!el) return
              const rect = el.getBoundingClientRect()
              applyZoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, 0.8)
            }}
            sx={{ width: 42, height: 40, borderRadius: 0, borderTop: '1px solid', borderColor: 'divider' }}
          >
            <RemoveIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Box sx={{ textAlign: 'center', fontSize: 12, color: 'text.secondary', py: 0.75, borderTop: '1px solid', borderColor: 'divider' }}>
          {zoomPct}%
        </Box>
        <Tooltip title={t('agents.sessions.runtimeMonitorFitToScreen')}>
          <IconButton
            aria-label={t('agents.sessions.runtimeMonitorFitToScreen')}
            onClick={fitToScreen}
            sx={{ width: 42, height: 40, borderRadius: 0, borderTop: '1px solid', borderColor: 'divider' }}
          >
            <ZoomOutMapIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title={isFullscreen ? t('agents.sessions.runtimeMonitorExitFullscreen') : t('agents.sessions.runtimeMonitorMaximize')}>
          <IconButton
            aria-label={isFullscreen ? t('agents.sessions.runtimeMonitorExitFullscreen') : t('agents.sessions.runtimeMonitorMaximize')}
            onClick={onToggleFullscreen}
            data-testid="runtime-monitor-fullscreen"
            sx={{ width: 42, height: 40, borderRadius: 0, borderTop: '1px solid', borderColor: 'divider' }}
          >
            {isFullscreen ? <FullscreenExitIcon fontSize="small" /> : <FullscreenIcon fontSize="small" />}
          </IconButton>
        </Tooltip>
      </Box>

      {/* Filter popover — collapsed by default as a floating circular
          button at the right-bottom corner; expands (hover or click) into a
          compact panel with the status/kind chips plus the recently-completed
          controls.  Folds on pointer-leave (1.2s), click-outside, or Escape. */}
      <Box
        ref={filterAnchorRef}
        data-map-interactive="true"
        data-testid="runtime-monitor-filter-root"
        onMouseEnter={openFilter}
        onMouseLeave={scheduleFold}
        sx={{
          position: 'absolute',
          right: 20,
          bottom: 20,
          zIndex: 20,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-end',
          gap: 1,
        }}
      >
        {filterOpen && (
          <Box
            data-testid="runtime-monitor-filter-panel"
            data-map-interactive="true"
            role="group"
            aria-label={t('agents.sessions.runtimeMonitorFilterButton')}
            sx={{
              bgcolor: '#fff',
              border: '1px solid',
              borderColor: 'divider',
              borderRadius: '10px',
              boxShadow: 4,
              p: 1.25,
              display: 'flex',
              flexDirection: 'column',
              gap: 0.75,
              width: 480,
              maxWidth: 'calc(100vw - 48px)',
            }}
          >
            <Box display="flex" alignItems="center" gap={0.75} flexWrap="wrap">
              <Typography variant="caption" fontWeight={700} color="text.secondary" sx={{ textTransform: 'uppercase', letterSpacing: 0.4, whiteSpace: 'nowrap' }}>
                {t('agents.sessions.runtimeMonitorLegendStatus')}
              </Typography>
              {availableStatuses.map((status) => {
                const off = hiddenStatuses.has(status)
                const label = t(GENERIC_STATUS_LABEL[status] ?? status, status)
                return (
                  <Chip
                    key={status}
                    size="small"
                    label={label}
                    onClick={() => toggleStatus(status)}
                    aria-pressed={!off}
                    icon={
                      <Box
                        component="span"
                        sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: genericStatusDotColor(status), display: 'inline-block' }}
                      />
                    }
                    sx={{ opacity: off ? 0.42 : 1 }}
                  />
                )
              })}
            </Box>

            <Box display="flex" alignItems="center" gap={0.75} flexWrap="wrap">
              <Typography variant="caption" fontWeight={700} color="text.secondary" sx={{ textTransform: 'uppercase', letterSpacing: 0.4, whiteSpace: 'nowrap' }}>
                {t('agents.sessions.runtimeMonitorLegendKind')}
              </Typography>
              {availableKinds.map((kind) => {
                const off = hiddenKinds.has(kind)
                return (
                  <Chip
                    key={kind}
                    size="small"
                    label={t(kindLabelKey(kind))}
                    onClick={() => toggleKind(kind)}
                    aria-pressed={!off}
                    sx={{ opacity: off ? 0.42 : 1 }}
                  />
                )
              })}
            </Box>

            <Box sx={{ height: 1, bgcolor: 'divider' }} />

            {/* Recently-completed agents: visibility toggle + window control.
                The page owns the values (they drive the `recent_minutes`
                topology fetch); the numeric input commits clamped ≥ 1. */}
            <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
              <Switch
                size="small"
                checked={recentEnabled}
                onChange={(e) => onRecentEnabledChange?.(e.target.checked)}
                inputProps={{ 'aria-label': t('agents.sessions.runtimeMonitorRecentToggle') }}
                data-testid="runtime-monitor-recent-toggle"
              />
              <Typography variant="caption" sx={{ whiteSpace: 'nowrap' }}>
                {t('agents.sessions.runtimeMonitorRecentToggle')}
              </Typography>
              <Box sx={{ flex: 1 }} />
              <TextField
                data-testid="runtime-monitor-recent-minutes"
                size="small"
                type="number"
                label={t('agents.sessions.runtimeMonitorWindowLabel')}
                value={minutesDraft}
                disabled={!recentEnabled}
                onChange={(e) => {
                  const raw = e.target.value
                  setMinutesDraft(raw)
                  commitMinutesDraft(raw)
                }}
                onBlur={() => {
                  // Normalise an invalid/empty draft back to the committed value.
                  const parsed = parseInt(minutesDraft, 10)
                  if (Number.isNaN(parsed) || parsed < 1) {
                    setMinutesDraft(
                      String(windowUnit === 'minutes' ? recentMinutes : Math.round(recentMinutes / 60)),
                    )
                  }
                }}
                inputProps={{ min: 1, 'data-testid': 'runtime-monitor-recent-minutes-input' }}
                sx={{ width: 104 }}
              />
              {/* Native select keeps the unit chooser keyboard-accessible
                  and simple (minutes / hours presets around the numeric input). */}
              <Box
                component="select"
                data-testid="runtime-monitor-recent-unit"
                aria-label={t('agents.sessions.runtimeMonitorWindowLabel')}
                value={windowUnit}
                disabled={!recentEnabled}
                onChange={(e) => setWindowUnit(e.target.value as 'minutes' | 'hours')}
                sx={{
                  height: 40,
                  px: 0.75,
                  borderRadius: '6px',
                  border: '1px solid',
                  borderColor: 'divider',
                  bgcolor: '#fff',
                  color: '#455A64',
                  fontSize: 12,
                  outline: 'none',
                }}
              >
                <option value="minutes">{t('agents.sessions.runtimeMonitorWindowUnitMinutes')}</option>
                <option value="hours">{t('agents.sessions.runtimeMonitorWindowUnitHours')}</option>
              </Box>
            </Box>
          </Box>
        )}

        <Tooltip title={t('agents.sessions.runtimeMonitorFilterButton')}>
          <IconButton
            data-testid="runtime-monitor-filter-button"
            aria-label={t('agents.sessions.runtimeMonitorFilterButton')}
            aria-expanded={filterOpen}
            aria-haspopup="true"
            onClick={toggleFilter}
            sx={{
              width: 44,
              height: 44,
              borderRadius: '50%',
              bgcolor: 'primary.main',
              color: '#fff',
              boxShadow: 3,
              '&:hover': { bgcolor: 'primary.dark' },
            }}
          >
            <Badge
              badgeContent={activeFilterCount}
              color="secondary"
              invisible={activeFilterCount === 0}
              data-testid="runtime-monitor-filter-badge"
            >
              <FilterListIcon />
            </Badge>
          </IconButton>
        </Tooltip>
      </Box>

      {/* Detail bubble */}
      {selectedNode && bubblePosition && (
        <Box data-map-interactive="true">
          <AgentDetailBubble
            node={selectedNode}
            position={bubblePosition}
            onDismiss={() => onSelectSession(null)}
            onTerminate={onTerminateNode}
            onChanged={onChanged}
          />
        </Box>
      )}
    </Box>
  )
}
