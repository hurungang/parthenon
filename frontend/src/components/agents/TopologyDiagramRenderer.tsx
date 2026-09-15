import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Box, Chip, ClickAwayListener, Tooltip, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { TopologyEdge, TopologyNode, TopologyZone } from '../../types'
import { TopologyNodeIcon } from './topologyNodeIcons'
import { fitTextToWidth } from './topologyTextFit'

// ── Layout constants (generic layered mode) ───────────────────────────────────

const NODE_WIDTH = 140
const NODE_HEIGHT = 40
const NODE_RADIUS = 6
const H_GAP = 60  // horizontal gap between columns
const V_GAP = 20  // vertical gap between nodes in the same column
const UNUSED_SKILL_GAP = 40  // extra gap separating used from unused skills

// Column order for the layered layout
const COLUMN_ORDER: Record<string, number> = {
  agent: 0,
  identity: 0,  // same column as agent, will be positioned below
  communication_hub: 1,
  role: 2,
  sop: 3,
  skill: 4,
  agent_type: 5,
  tool: 6,
  input_data_type: 7,
  output_data_type: 8,
  model: 9,
}

// Hex color map per node type (used for both SVG and legend)
const COLOR_MAP: Record<string, string> = {
  agent: '#d32f2f',      // red
  identity: '#00acc1',   // bright cyan (more distinct from red)
  communication_hub: '#3730a3', // indigo (platform node)
  role: '#1976d2',       // blue
  sop: '#9c27b0',        // purple
  skill: '#ed6c02',      // orange
  agent_type: '#455a64', // blue gray
  tool: '#2e7d32',       // green
  input_data_type: '#15803d', // green (typed input)
  output_data_type: '#9d174d', // pink (typed output)
  model: '#c2410c',      // rust (LLM model)
}

// ── Layout constants (zoned panel mode — prototype zoned design) ─────────────

const ZONE_PAD_X = 16        // horizontal inner padding of a zone band
const ZONE_TITLE_H = 52      // title + subtitle strip at the top of a zone band
const ZONE_PAD_BOTTOM = 14   // bottom inner padding of a zone band
const ZONE_GAP = 18          // gap between zone bands
const Z_NODE_W = 148         // zoned node width
const Z_NODE_H = 34          // zoned node height
const Z_NODE_GAP = 14        // vertical gap between zoned stack items
const CAPTION_H = 13         // caption strip above a node (e.g. "signs in as")
const BOUNDARY_HEADER_H = 46 // agent name + caption header inside the boundary
const BOUNDARY_PAD = 12      // inner padding of the agent boundary
const GROUP_LABEL_H = 18     // label strip of a group box
const GROUP_PAD = 8          // inner padding of a group box
/**
 * Horizontal indent of tree-child nodes beneath their parent inside a group
 * box (zoned mode — composed skills under their SOP): the child is narrower
 * by exactly this offset, so the group box width and the tool-route gutter
 * are unaffected. Composition edges trunk down the middle of this gutter.
 */
const GROUP_CHILD_INDENT = 24

/** Zoned agent boundary colour (thick blue — identity & role are part of it). */
const BOUNDARY_COLOR = '#1d4ed8'
const BOUNDARY_FILL = '#dbeafe'

/**
 * Communication Hub vertical "firewall" bar (zoned mode, mirroring the
 * runtime monitor): rendered between the Capabilities zone and the Tools
 * zone, spanning the SAME height as the zone bands. Route connectors
 * cross straight through it.
 */
const HUB_BAR_W = 44

/** Default accent colour of the hub bar (indigo platform tone). */
const HUB_BAR_COLOR = '#3730a3'

// ── Fullscreen view transform (zoom + pan via viewBox manipulation) ──────────

/**
 * Fullscreen view-zoom clamps. Zoom scales the viewBox INVERSELY (view
 * width = world width / zoom), so text fitting (viewBox-unit based) and
 * hit-targets stay valid at every zoom level.
 */
const VIEW_MIN_ZOOM = 0.5
const VIEW_MAX_ZOOM = 3
/** Screen-distance threshold (px) that turns a pointer drag into a pan. */
const PAN_DRAG_THRESHOLD_PX = 4
/** Round viewBox coordinates to 3 decimals (keeps the DOM attribute tidy). */
const r3 = (n: number): number => Math.round(n * 1000) / 1000

/**
 * Clamp a view coordinate into [min, max]. When the view is LARGER than the
 * world (zoom < 1) min > max — centre the view instead so the world stays
 * centred in the viewport.
 */
function clampView(value: number, min: number, max: number): number {
  if (min > max) return (min + max) / 2
  return Math.min(max, Math.max(min, value))
}

/** Edge semantics → colour + dash pattern (zoned mode; documented in the legend). */
const ZONED_EDGE_STYLES: Record<string, { color: string; dasharray?: string }> = {
  solid: { color: '#64748b' },                // equipped with
  dotted: { color: '#2563eb', dasharray: '2 4' }, // role grants permission
  dashed: { color: '#7c3aed', dasharray: '6 4' }, // call path via the Hub
}

/** Declares the Communication Hub vertical bar in zoned mode. */
export interface TopologyHubBar {
  /** Label rendered vertically on the bar (e.g. "Communication Hub"). */
  label: string
  /**
   * The bar is inserted AFTER the zone band with this id (between that band
   * and the next one) and spans the bands' full shared height.
   */
  afterZone: string
  /** Accent colour of the bar (defaults to the platform indigo). */
  color?: string
}

// ── Node text geometry (dense icon gutter + width-fitted labels) ─────────────

/**
 * Dense icon gutter: the entity-type icon sits at `NODE_ICON_X` with
 * `NODE_ICON_SIZE` units, then `ICON_LABEL_GAP` units before the label.
 * Labels are LEFT-ALIGNED at `NODE_LABEL_X` (never centred) so they always
 * start right of the icon and never overlap it.
 */
const NODE_ICON_SIZE = 10
const NODE_ICON_X = 7
const ICON_LABEL_GAP = 4
const NODE_TEXT_PAD_RIGHT = 6
/** x of the left-aligned node label = icon right edge + gap. */
export const NODE_LABEL_X = NODE_ICON_X + NODE_ICON_SIZE + ICON_LABEL_GAP

const NODE_LABEL_FONT = 11
const NODE_BADGE_FONT = 8
/** 0.05em letter-spacing of the uppercase type badge at 8px. */
const BADGE_LETTER_SPACING = 0.4
/** Caption strip above a node (e.g. "signs in as"). */
const CAPTION_STRIP_X = 8
const CAPTION_STRIP_FONT = 8
/** Boundary header icon + text (proportionally small like the node icons). */
const BOUNDARY_ICON_SIZE = 11
const BOUNDARY_ICON_X = 10
const BOUNDARY_TEXT_X = BOUNDARY_ICON_X + BOUNDARY_ICON_SIZE + ICON_LABEL_GAP
const BOUNDARY_HEADER_FONT = 12
const BOUNDARY_CAPTION_FONT = 9
/** Reserved width of the "🔒 " prefix on locked slots (em units at font size). */
const LOCK_PREFIX_EM = 1.6

/** Max width of a node's fitted label right of the icon gutter (viewBox units). */
export function nodeTextMaxWidth(nodeWidth: number): number {
  return nodeWidth - NODE_LABEL_X - NODE_TEXT_PAD_RIGHT
}

/** Max width of the agent boundary header/caption text (viewBox units). */
function boundaryTextMaxWidth(boundaryWidth: number): number {
  return boundaryWidth - BOUNDARY_TEXT_X - 8
}

// ── Layout types ──────────────────────────────────────────────────────────────

interface NodeLayout {
  node: TopologyNode
  x: number
  y: number
  w: number
  h: number
  /** Height of the caption strip rendered above the node rect (0 = none). */
  capH: number
  /** Node renders as a containment boundary container (agent boundary). */
  boundary?: boolean
}

interface ZoneBandLayout {
  zone: TopologyZone
  x: number
  y: number
  w: number
  h: number
}

interface GroupLayout {
  key: string
  /** Group box label; `null` renders an unlabeled box (per-root tree boxes). */
  label: string | null
  color: string
  x: number
  y: number
  w: number
  h: number
}

interface Props {
  nodes: TopologyNode[]
  edges: TopologyEdge[]
  onNodeClick?: (node: TopologyNode) => void
  /**
   * Zoned layout mode (agent panel): tinted, labeled zone bands rendered
   * left → right, containment boundaries and grouped nodes. When omitted the
   * generic layered layout is used (backwards compatible).
   */
  zones?: TopologyZone[]
  /**
   * Zoned mode only: renders the Communication Hub as a vertical "firewall"
   * bar between the zone declared by `afterZone` and the next zone — route
   * connectors cross straight through it (runtime-monitor pattern).
   */
  hubBar?: TopologyHubBar
  /**
   * Stretch the responsive SVG to the full height of its container
   * (fullscreen panel topology) instead of keeping the intrinsic
   * aspect-driven height. In this mode the svg element becomes a bounded
   * flex item (width AND height constrained by the available viewport box)
   * with `preserveAspectRatio="xMidYMid meet"`, so the ENTIRE graph always
   * fits and centres — never clipped by the header or the legend.
   */
  fillHeight?: boolean
  /**
   * Fullscreen-only zoom scalar for the viewBox-based view transform
   * (1 = auto-fit the whole graph; clamped to 0.5–3). Only meaningful
   * together with `fillHeight`. The viewBox is scaled around the pan
   * centre (view width = world width / zoom) so viewBox-unit text fitting
   * stays valid at every zoom level. Drag-to-pan (mouse + touch) and wheel
   * panning are handled internally while zoomed in and are inert at zoom 1.
   */
  viewZoom?: number
}

// ── Generic layered layout ────────────────────────────────────────────────────

function computeLayout(nodes: TopologyNode[]): { layouts: NodeLayout[]; svgWidth: number; svgHeight: number } {
  // Group nodes by column (type)
  const columns: Map<number, TopologyNode[]> = new Map()
  for (const node of nodes) {
    const col = COLUMN_ORDER[node.type] ?? Object.keys(COLUMN_ORDER).length
    if (!columns.has(col)) columns.set(col, [])
    columns.get(col)!.push(node)
  }

  const sortedCols = [...columns.keys()].sort((a, b) => a - b)
  const layouts: NodeLayout[] = []

  // Calculate each column's height (skill column accounts for used/unused gap)
  function getColHeight(col: number, colNodes: TopologyNode[]): number {
    if (col === COLUMN_ORDER['skill']) {
      const used = colNodes.filter(n => n.usage !== 'unused')
      const unused = colNodes.filter(n => n.usage === 'unused')
      let h = used.length > 0 ? used.length * (NODE_HEIGHT + V_GAP) - V_GAP : 0
      if (unused.length > 0) {
        if (used.length > 0) h += UNUSED_SKILL_GAP
        h += unused.length * (NODE_HEIGHT + V_GAP) - V_GAP
      }
      return Math.max(h, 0)
    }
    return colNodes.length > 0 ? colNodes.length * (NODE_HEIGHT + V_GAP) - V_GAP : 0
  }

  let maxColHeight = 0
  sortedCols.forEach((col) => {
    const h = getColHeight(col, columns.get(col)!)
    if (h > maxColHeight) maxColHeight = h
  })

  sortedCols.forEach((col, colIdx) => {
    const colNodes = columns.get(col)!
    const colHeight = getColHeight(col, colNodes)
    const yStart = (maxColHeight - colHeight) / 2
    const xPos = colIdx * (NODE_WIDTH + H_GAP)

    if (col === COLUMN_ORDER['skill']) {
      // Used skills first, then extra gap, then unused skills
      const used = colNodes.filter(n => n.usage !== 'unused')
      const unused = colNodes.filter(n => n.usage === 'unused')
      let currentY = yStart
      used.forEach((node) => {
        layouts.push({ node, x: xPos, y: currentY, w: NODE_WIDTH, h: NODE_HEIGHT, capH: 0 })
        currentY += NODE_HEIGHT + V_GAP
      })
      if (unused.length > 0 && used.length > 0) {
        currentY += UNUSED_SKILL_GAP - V_GAP  // extra separator (UNUSED_SKILL_GAP total after last used)
      }
      unused.forEach((node) => {
        layouts.push({ node, x: xPos, y: currentY, w: NODE_WIDTH, h: NODE_HEIGHT, capH: 0 })
        currentY += NODE_HEIGHT + V_GAP
      })
    } else {
      colNodes.forEach((node, nodeIdx) => {
        layouts.push({
          node,
          x: xPos,
          y: yStart + nodeIdx * (NODE_HEIGHT + V_GAP),
          w: NODE_WIDTH,
          h: NODE_HEIGHT,
          capH: 0,
        })
      })
    }
  })

  const svgWidth = sortedCols.length * (NODE_WIDTH + H_GAP) - H_GAP + 20
  const svgHeight = maxColHeight + 20

  return { layouts, svgWidth, svgHeight }
}

// ── Zoned layout (agent panel prototype design) ──────────────────────────────

interface ZonedLayout {
  layouts: NodeLayout[]
  bands: ZoneBandLayout[]
  groups: GroupLayout[]
  /** Communication Hub vertical bar rect (zoned mode with `hubBar`), or null. */
  hubBarRect: { x: number; y: number; w: number; h: number } | null
  svgWidth: number
  svgHeight: number
}

/**
 * Lays out nodes inside labeled zone bands (left → right), with containment
 * boundaries (node.containedIn) and labeled group boxes (node.group).
 * Mirrors the approved prototype: ① Configuration (agent boundary containing
 * identity/role/contract chips) → ② Capabilities (SOPs + Skills sections) →
 * the Communication Hub vertical bar → ③ Tools (MCP-server-grouped tool
 * nodes). Grouped nodes carrying `childOf` render as INDENTED tree children
 * beneath their parent, each parent wrapped in its own unlabeled group box
 * (composed skills under their SOP). When `hubBarAfterZone` is set, a
 * full-height hub bar column is reserved after that zone band.
 */
function computeZonedLayout(
  nodes: TopologyNode[],
  zones: TopologyZone[],
  hubBarAfterZone?: string,
): ZonedLayout {
  const layouts: NodeLayout[] = []
  const bands: ZoneBandLayout[] = []
  const groups: GroupLayout[] = []
  const laidOut = new Set<string>()

  let cursorX = 10
  let maxBottom = 0

  interface StackItem {
    w: number
    h: number
    place: (x: number, y: number) => void
  }

  const itemHeight = (n: TopologyNode): number => (n.caption ? CAPTION_H : 0) + Z_NODE_H

  // Pass 1 — build the stack items per zone and measure their content.
  const zonePlans: { zone: TopologyZone; items: StackItem[]; stackH: number; contentW: number }[] = []

  for (const zone of zones) {
    const zoneNodes = nodes.filter((n) => n.zone === zone.id)
    if (zoneNodes.length === 0) continue

    // Containment map: container id → contained nodes (in node order)
    const containedBy = new Map<string, TopologyNode[]>()
    for (const n of zoneNodes) {
      if (n.containedIn) {
        const list = containedBy.get(n.containedIn) ?? []
        list.push(n)
        containedBy.set(n.containedIn, list)
      }
    }

    const items: StackItem[] = []
    const visited = new Set<string>()

    for (const node of zoneNodes) {
      if (visited.has(node.id)) continue

      if (node.containedIn) {
        // Positioned by its container — skip here.
        visited.add(node.id)
        continue
      }

      if (containedBy.has(node.id)) {
        // Containment boundary container: wraps its contained nodes.
        const children = containedBy.get(node.id)!
        const w = Z_NODE_W + BOUNDARY_PAD * 2 + 4
        const innerH = children.reduce((acc, c) => acc + itemHeight(c) + Z_NODE_GAP, -Z_NODE_GAP)
        const h = BOUNDARY_HEADER_H + innerH + BOUNDARY_PAD
        items.push({
          w,
          h,
          place: (x, y) => {
            layouts.push({ node, x, y, w, h, capH: 0, boundary: true })
            let cy = y + BOUNDARY_HEADER_H
            for (const child of children) {
              const ch = itemHeight(child)
              layouts.push({ node: child, x: x + BOUNDARY_PAD, y: cy, w: Z_NODE_W, h: ch, capH: child.caption ? CAPTION_H : 0 })
              cy += ch + Z_NODE_GAP
              visited.add(child.id)
            }
          },
        })
        visited.add(node.id)
        continue
      }

      if (node.group) {
        // Group box(es): wrap every node in this zone sharing the group id.
        // Tree children (node.childOf → a member of the same group) render
        // INDENTED beneath their parent — each parent gets its own unlabeled
        // group box wrapping itself and its child stack (tree/folder look).
        // Flat groups keep the single shared labeled box.
        const groupId: string = node.group
        const members = zoneNodes.filter((m) => m.group === groupId && !m.containedIn)
        const memberIds = new Set(members.map((m) => m.id))
        const isTreeChild = (m: TopologyNode): boolean =>
          m.childOf != null && memberIds.has(m.childOf)
        const childrenByRoot = new Map<string, TopologyNode[]>()
        for (const m of members) {
          if (!isTreeChild(m)) continue
          const list = childrenByRoot.get(m.childOf!) ?? []
          list.push(m)
          childrenByRoot.set(m.childOf!, list)
        }
        const roots = members.filter((m) => !isTreeChild(m))
        const isTree = childrenByRoot.size > 0
        const w = Z_NODE_W + GROUP_PAD * 2

        if (isTree) {
          // One unlabeled box per root: parent node at full width on top,
          // its children indented below (narrower by the indent exactly, so
          // the box width — and the tool-route gutter right of it — stays
          // unchanged).
          for (const root of roots) {
            const children = childrenByRoot.get(root.id) ?? []
            const rows = 1 + children.length
            const h = GROUP_PAD + rows * (Z_NODE_H + Z_NODE_GAP) - Z_NODE_GAP + GROUP_PAD
            items.push({
              w,
              h,
              place: (x, y) => {
                groups.push({
                  key: `${zone.id}:${groupId}:${root.id}`,
                  label: null,
                  color: root.groupColor ?? node.groupColor ?? '#64748b',
                  x,
                  y,
                  w,
                  h,
                })
                let cy = y + GROUP_PAD
                layouts.push({ node: root, x: x + GROUP_PAD, y: cy, w: Z_NODE_W, h: Z_NODE_H, capH: 0 })
                cy += Z_NODE_H + Z_NODE_GAP
                for (const child of children) {
                  layouts.push({
                    node: child,
                    x: x + GROUP_PAD + GROUP_CHILD_INDENT,
                    y: cy,
                    w: Z_NODE_W - GROUP_CHILD_INDENT,
                    h: Z_NODE_H,
                    capH: 0,
                  })
                  cy += Z_NODE_H + Z_NODE_GAP
                }
              },
            })
          }
        } else {
          const h = GROUP_LABEL_H + members.length * (Z_NODE_H + Z_NODE_GAP) - Z_NODE_GAP + GROUP_PAD
          items.push({
            w,
            h,
            place: (x, y) => {
              groups.push({
                key: `${zone.id}:${groupId}`,
                label: node.groupLabel ?? groupId,
                color: node.groupColor ?? '#64748b',
                x,
                y,
                w,
                h,
              })
              let cy = y + GROUP_LABEL_H
              for (const member of members) {
                layouts.push({ node: member, x: x + GROUP_PAD, y: cy, w: Z_NODE_W, h: Z_NODE_H, capH: 0 })
                cy += Z_NODE_H + Z_NODE_GAP
                visited.add(member.id)
              }
            },
          })
        }
        for (const member of members) visited.add(member.id)
        continue
      }

      // Standalone node.
      items.push({
        w: Z_NODE_W,
        h: Z_NODE_H,
        place: (x, y) => {
          layouts.push({ node, x, y, w: Z_NODE_W, h: Z_NODE_H, capH: 0 })
        },
      })
      visited.add(node.id)
    }

    const stackH = items.reduce((acc, it) => acc + it.h + Z_NODE_GAP, -Z_NODE_GAP)
    const contentW = items.reduce((max, it) => Math.max(max, it.w), 0)
    zonePlans.push({ zone, items, stackH, contentW })
  }

  // Pass 2 — place zones left → right with equal-height bands (prototype look).
  const maxStackH = zonePlans.reduce((max, p) => Math.max(max, p.stackH), 0)
  const bandH = ZONE_TITLE_H + maxStackH + ZONE_PAD_BOTTOM
  let hubBarRect: ZonedLayout['hubBarRect'] = null
  for (const plan of zonePlans) {
    const zoneW = Math.max(plan.contentW + ZONE_PAD_X * 2, 210)
    const zoneH = bandH
    const zoneX = cursorX
    const zoneY = 10
    bands.push({ zone: plan.zone, x: zoneX, y: zoneY, w: zoneW, h: zoneH })

    let itemY = zoneY + ZONE_TITLE_H
    for (const item of plan.items) {
      item.place(zoneX + (zoneW - item.w) / 2, itemY)
      itemY += item.h + Z_NODE_GAP
    }

    for (const n of nodes.filter((x) => x.zone === plan.zone.id)) laidOut.add(n.id)
    cursorX = zoneX + zoneW + ZONE_GAP
    maxBottom = Math.max(maxBottom, zoneY + zoneH)

    // Reserve the Communication Hub bar column after the declared zone —
    // full band height, standing free in the gap before the next band.
    if (hubBarAfterZone && plan.zone.id === hubBarAfterZone) {
      hubBarRect = { x: cursorX, y: 10, w: HUB_BAR_W, h: bandH }
      cursorX += HUB_BAR_W + ZONE_GAP
    }
  }

  // Defensive fallback: any node whose zone is unknown still renders, in a
  // trailing column, so nothing silently disappears from the graph.
  const leftovers = nodes.filter((n) => !laidOut.has(n.id))
  if (leftovers.length > 0) {
    let y = 10
    for (const node of leftovers) {
      layouts.push({ node, x: cursorX, y, w: Z_NODE_W, h: Z_NODE_H, capH: 0 })
      y += Z_NODE_H + Z_NODE_GAP
    }
    cursorX += Z_NODE_W + ZONE_GAP
    maxBottom = Math.max(maxBottom, y - Z_NODE_GAP)
  }

  return {
    layouts,
    bands,
    groups,
    hubBarRect,
    svgWidth: cursorX - ZONE_GAP + 10,
    svgHeight: maxBottom + 10,
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

const TopologyDiagramRenderer: React.FC<Props> = ({ nodes, edges, onNodeClick, zones, hubBar, fillHeight, viewZoom }) => {
  const { t } = useTranslation()
  const [clickedNodeId, setClickedNodeId] = useState<string | null>(null)
  const isZoned = Array.isArray(zones) && zones.length > 0
  const hubBarAfterZone = hubBar?.afterZone

  // ── Fullscreen view transform state (fillHeight + viewZoom only) ──
  // The svg element ref (client box → screen-to-viewBox conversion for pan).
  const svgRef = useRef<SVGSVGElement | null>(null)
  // Pan state = the view CENTRE in world (viewBox) coordinates, so zooming
  // never needs to re-derive the pan offset (the same centre stays centred).
  // `null` means "world centre" — the auto-fit view.
  const [panCenter, setPanCenter] = useState<{ x: number; y: number } | null>(null)
  const [panning, setPanning] = useState(false)
  /** In-flight pointer drag (screen coords + whether the threshold was crossed). */
  const panDragRef = useRef<{
    pointerId: number
    startX: number
    startY: number
    lastX: number
    lastY: number
    moved: boolean
  } | null>(null)

  // Escape dismisses the click-shown full-label tooltip (same document-level
  // convention as dialogs / the fullscreen topology overlay).
  useEffect(() => {
    if (clickedNodeId == null) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setClickedNodeId(null)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [clickedNodeId])

  // Filter out unused skills — they should not appear in the topology
  const visibleNodes = useMemo(() => {
    return nodes.filter(n => !(n.type === 'skill' && n.usage === 'unused'))
  }, [nodes])

  const visibleNodeIds = useMemo(() => new Set(visibleNodes.map(n => n.id)), [visibleNodes])

  const visibleEdges = useMemo(() => {
    return edges.filter(e => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target))
  }, [edges, visibleNodeIds])

  const genericLayout = useMemo(
    () => (isZoned ? null : computeLayout(visibleNodes)),
    [isZoned, visibleNodes],
  )
  const zonedLayout = useMemo(
    () => (isZoned ? computeZonedLayout(visibleNodes, zones!, hubBarAfterZone) : null),
    [isZoned, visibleNodes, zones, hubBarAfterZone],
  )

  const layouts = isZoned ? zonedLayout!.layouts : genericLayout!.layouts
  const svgWidth = isZoned ? zonedLayout!.svgWidth : genericLayout!.svgWidth
  const svgHeight = isZoned ? zonedLayout!.svgHeight : genericLayout!.svgHeight

  // Build a lookup from node ID → layout position
  const layoutByNodeId = useMemo<Map<string, NodeLayout>>(() => {
    const map = new Map<string, NodeLayout>()
    for (const layout of layouts) {
      map.set(layout.node.id, layout)
    }
    return map
  }, [layouts])

  // ── Fullscreen view transform (viewBox manipulation) ──
  // zoom = 1 → the viewBox is the whole world → `preserveAspectRatio
  // "xMidYMid meet"` auto-fits and centres it in the bounded svg box.
  // zoom > 1 → the viewBox shrinks (view = world / zoom) around the pan
  // centre, magnifying the content; panning moves the centre within the
  // world so every area stays reachable.
  const worldW = svgWidth + 20
  const worldH = svgHeight + 20
  const zoomLevel = clampView(fillHeight && viewZoom != null ? viewZoom : 1, VIEW_MIN_ZOOM, VIEW_MAX_ZOOM)
  const panEnabled = fillHeight && zoomLevel > 1
  const viewW = worldW / zoomLevel
  const viewH = worldH / zoomLevel
  const halfW = viewW / 2
  const halfH = viewH / 2
  // Clamped pan centre (falls back to the world centre at zoom 1, which the
  // clamp enforces anyway — a stale pan can never un-fit a zoom-1 view).
  const panX = clampView(panCenter?.x ?? worldW / 2, halfW, worldW - halfW)
  const panY = clampView(panCenter?.y ?? worldH / 2, halfH, worldH - halfH)
  const viewBoxStr = `${r3(panX - halfW)} ${r3(panY - halfH)} ${r3(viewW)} ${r3(viewH)}`

  /** Convert a screen-space delta into a clamped viewBox-space pan. */
  const panByScreen = (dxScreen: number, dyScreen: number) => {
    const el = svgRef.current
    if (!el || el.clientWidth <= 0 || el.clientHeight <= 0) return
    const scale = viewW / el.clientWidth
    setPanCenter((prev) => {
      const base = prev ?? { x: worldW / 2, y: worldH / 2 }
      return {
        x: clampView(base.x - dxScreen * scale, halfW, worldW - halfW),
        y: clampView(base.y - dyScreen * scale, halfH, worldH - halfH),
      }
    })
  }

  // Wheel panning while zoomed in (native non-passive listener so the page
  // does not scroll; inert at zoom 1). Same approach as the runtime monitor.
  useEffect(() => {
    if (!panEnabled) return
    const el = svgRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      panByScreen(e.deltaX, e.deltaY)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  })
  // (No dep array — re-binds every render so the handler always closes over
  // the current viewBox geometry; the add/remove pair is cheap.)

  // ── Drag-to-pan (mouse + touch via pointer events) ──
  // Background-only: drags starting on a node group (data-topology-node)
  // never pan, so node click/tooltip interactions stay untouched (the
  // runtime-monitor pattern). Movement below the threshold is a click, not
  // a pan; at zoom 1 panning is inert entirely.
  const handleSvgPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!panEnabled) return
    if (e.pointerType === 'mouse' && e.button !== 0) return
    if ((e.target as Element).closest('[data-topology-node]')) return
    panDragRef.current = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      lastX: e.clientX,
      lastY: e.clientY,
      moved: false,
    }
    // Capture so the drag keeps tracking outside the svg (touch especially).
    try {
      e.currentTarget.setPointerCapture?.(e.pointerId)
    } catch {
      // Pointer capture is best-effort (unsupported in some environments).
    }
  }

  const handleSvgPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const drag = panDragRef.current
    if (!drag || drag.pointerId !== e.pointerId) return
    if (e.clientX === drag.lastX && e.clientY === drag.lastY) return
    const dx = e.clientX - drag.lastX
    const dy = e.clientY - drag.lastY
    drag.lastX = e.clientX
    drag.lastY = e.clientY
    // Distinguish drag from click by movement threshold.
    if (!drag.moved) {
      if (Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) < PAN_DRAG_THRESHOLD_PX) return
      drag.moved = true
      setPanning(true)
    }
    panByScreen(dx, dy)
  }

  const endSvgPan = (e: React.PointerEvent<SVGSVGElement>) => {
    if (panDragRef.current?.pointerId !== e.pointerId) return
    panDragRef.current = null
    setPanning(false)
    try {
      e.currentTarget.releasePointerCapture?.(e.pointerId)
    } catch {
      // Pointer capture is best-effort (unsupported in some environments).
    }
  }

  if (nodes.length === 0) {
    return (
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: 80,
          border: '1px dashed',
          borderColor: 'divider',
          borderRadius: 1,
        }}
      >
        <Typography variant="body2" color="text.secondary">
          {t('agents.plan.topology')} — {t('agents.plan.noSteps')}
        </Typography>
      </Box>
    )
  }

  /** Marker id for an explicit per-edge colour (per-capability route connectors). */
  const colorMarkerId = (color: string): string => `zoned-arrow-c-${color.replace(/[^a-zA-Z0-9-]/g, '')}`

  /** Appearance of one edge in the current mode. */
  const edgeAppearance = (edge: TopologyEdge): { color: string; dasharray?: string; marker: string; strokeWidth: number } => {
    if (isZoned) {
      const semantic = ZONED_EDGE_STYLES[edge.style ?? 'solid'] ?? ZONED_EDGE_STYLES.solid
      // Explicit edge colour (per-capability connector matching its source
      // node's border) overrides the style-semantics colour.
      const color = edge.color ?? semantic.color
      return {
        color,
        dasharray: semantic.dasharray,
        marker: edge.color
          ? `url(#${colorMarkerId(edge.color)})`
          : `url(#zoned-arrow-${edge.style === 'dotted' ? 'dotted' : edge.style === 'dashed' ? 'dashed' : 'solid'})`,
        strokeWidth: 1.8,
      }
    }
    // Generic mode: explicit edge colour is honoured the same way (no
    // producer sets it today — the default grey arrow is unchanged).
    return {
      color: edge.color ?? '#9e9e9e',
      dasharray: edge.style === 'dashed' ? '6 3' : undefined,
      marker: edge.color ? `url(#${colorMarkerId(edge.color)})` : 'url(#arrow)',
      strokeWidth: 1.5,
    }
  }

  // Distinct explicit edge colours — one arrow marker per colour (markers
  // cannot inherit stroke colour portably, so each gets its own def).
  // Plain derivation (kept below hooks — after the empty-state early return).
  const edgeColors = [...new Set(edges.filter((e) => e.color).map((e) => e.color as string))]

  const renderNode = (l: NodeLayout) => {
    const { node, x, y, w, h, capH } = l
    // Per-capability accent colour (zoned panel) overrides the type colour.
    const fillColor = node.accentColor ?? COLOR_MAP[node.type] ?? '#757575'
    // Empty-slot placeholders and the locked output slot render dashed.
    const isPlaceholder = node.usage === 'empty' || node.usage === 'locked'
    const isLocked = node.usage === 'locked'
    const isBoundary = l.boundary === true
    const isClicked = clickedNodeId === node.id

    // Width-aware label fitting (viewBox units — robust under responsive and
    // fillHeight scaling): the label is LEFT-ALIGNED after the icon gutter
    // and truncated with an ellipsis to the node's inner width, so it can
    // never overflow the node bounds or overlap the icon. The full text
    // stays available via the native <title> (hover) and the click tooltip.
    const labelFit = isBoundary
      ? fitTextToWidth(node.label, boundaryTextMaxWidth(w), BOUNDARY_HEADER_FONT, { bold: true })
      : fitTextToWidth(
          node.label,
          nodeTextMaxWidth(w) - (isLocked ? LOCK_PREFIX_EM * NODE_LABEL_FONT : 0),
          NODE_LABEL_FONT,
        )
    const displayLabel = labelFit.text
    const isTruncated = labelFit.truncated
    // Caption: the boundary caption sits right of the header icon; a regular
    // caption strip sits above the node box.
    const captionFit = node.caption
      ? isBoundary
        ? fitTextToWidth(node.caption, boundaryTextMaxWidth(w), BOUNDARY_CAPTION_FONT)
        : fitTextToWidth(node.caption, w - CAPTION_STRIP_X - NODE_TEXT_PAD_RIGHT, CAPTION_STRIP_FONT, { bold: true })
      : null
    // Type badge renders uppercase via CSS — estimate the uppercase width.
    const badgeFit = fitTextToWidth(node.type.toUpperCase(), nodeTextMaxWidth(w), NODE_BADGE_FONT, {
      letterSpacing: BADGE_LETTER_SPACING,
    })

    return (
      <ClickAwayListener
        key={node.id}
        onClickAway={() => {
          if (isClicked) setClickedNodeId(null)
        }}
      >
        <Tooltip
          title={isTruncated ? node.label : ''}
          arrow
          open={isClicked || undefined}
          disableHoverListener
        >
          <g
            data-topology-node={node.id}
            transform={`translate(${x + 10}, ${y + 10})`}
            onClick={() => {
              if (isTruncated) {
                setClickedNodeId(isClicked ? null : node.id)
              }
              onNodeClick?.(node)
            }}
            style={{ cursor: onNodeClick ? 'pointer' : isTruncated ? 'pointer' : 'default' }}
          >
            {/* Native browser tooltip with the FULL label (hover) — on the
                node group and on every truncated text element. */}
            {isTruncated && <title>{node.label}</title>}
            {/* Caption strip (containment context, e.g. "signs in as") */}
            {capH > 0 && captionFit && (
              <text
                x={CAPTION_STRIP_X}
                y={capH - 4}
                fontSize={CAPTION_STRIP_FONT}
                fontWeight={700}
                fill="#64748b"
                style={{ textTransform: 'uppercase', letterSpacing: '0.08em' }}
              >
                {captionFit.text}
                {captionFit.truncated && <title>{node.caption}</title>}
              </text>
            )}
            <rect
              y={capH}
              width={w}
              height={h - capH}
              rx={isBoundary ? 12 : NODE_RADIUS}
              ry={isBoundary ? 12 : NODE_RADIUS}
              fill={isBoundary ? BOUNDARY_FILL : `${fillColor}22`}
              fillOpacity={isBoundary ? 0.45 : 1}
              stroke={isBoundary ? BOUNDARY_COLOR : fillColor}
              strokeWidth={isBoundary ? 3 : 1.5}
              strokeDasharray={isPlaceholder ? '4 2' : undefined}
              opacity={isPlaceholder ? 0.85 : 1}
            />
            {isBoundary ? (
              <>
                {/* Entity-type icon (agent) in the boundary header — small
                    dense geometry, header text starts after the gutter */}
                <TopologyNodeIcon
                  type={node.type}
                  size={BOUNDARY_ICON_SIZE}
                  color={BOUNDARY_COLOR}
                  x={BOUNDARY_ICON_X}
                  y={capH + 7}
                  testId={node.type}
                />
                {/* Boundary header: agent name + caption — left-aligned after
                    the icon, width-fitted to the boundary box */}
                <text x={BOUNDARY_TEXT_X} y={capH + 17} fontSize={BOUNDARY_HEADER_FONT} fontWeight={700} fill="#1e3a8a">
                  {displayLabel}
                  {isTruncated && <title>{node.label}</title>}
                </text>
                {node.caption && captionFit && (
                  <text x={BOUNDARY_TEXT_X} y={capH + 31} fontSize={BOUNDARY_CAPTION_FONT} fill="#475569">
                    {captionFit.text}
                    {captionFit.truncated && <title>{node.caption}</title>}
                  </text>
                )}
              </>
            ) : (
              <>
                {/* Entity-type icon — dense 10px geometry inside the node
                    box; the left-aligned label starts 4 units right of the
                    icon and is vertically centred on it. Placeholders and
                    locked slots render the same icon. */}
                <TopologyNodeIcon
                  type={node.type}
                  size={NODE_ICON_SIZE}
                  color={fillColor}
                  x={NODE_ICON_X}
                  y={capH + (h - capH) / 2 - NODE_ICON_SIZE / 2}
                  testId={node.type}
                />
                {/* Node type badge (width-fitted, uppercase) */}
                <text
                  x={NODE_LABEL_X}
                  y={capH + 12}
                  fontSize={NODE_BADGE_FONT}
                  fontWeight={600}
                  fill={fillColor}
                  style={{ textTransform: 'uppercase', letterSpacing: '0.05em' }}
                >
                  {badgeFit.text}
                  {badgeFit.truncated && <title>{node.type}</title>}
                </text>
                {/* Node label — LEFT-ALIGNED next to the icon, vertically
                    centred on it, truncated to the node's inner width */}
                <text
                  x={NODE_LABEL_X}
                  y={capH + (h - capH) / 2 + 4}
                  fontSize={NODE_LABEL_FONT}
                  fill="#212121"
                  textAnchor="start"
                  style={{ fontWeight: 500 }}
                >
                  {isLocked ? `🔒 ${displayLabel}` : displayLabel}
                  {isTruncated && <title>{node.label}</title>}
                </text>
              </>
            )}
          </g>
        </Tooltip>
      </ClickAwayListener>
    )
  }

  return (
    <Box
      sx={{ mt: 1, maxWidth: '100%' }}
      // Fullscreen (fillHeight): a bounded flex column (inline style — pure
      // layout, not theme) — the svg gets the remaining height after the
      // legend, so the legend can never push the graph past the viewport
      // (the cutout fix).
      style={fillHeight ? { display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 } : undefined}
    >
      {/* Responsive SVG: viewBox scaling keeps the topology inside its
          container (no horizontal scrollbar); maxWidth keeps it from
          blowing up on very wide screens. `fillHeight` (fullscreen) instead
          makes the svg a bounded flex item (width AND height constrained by
          the available box) and `preserveAspectRatio="xMidYMid meet"` scales
          the ENTIRE graph to fit and centre it — no clipping at any window
          size/aspect ratio. `viewZoom` scales the viewBox inversely
          (view = world / zoom) so the viewBox-unit text fitting stays valid
          while zoomed; panning moves the viewBox origin within the world. */}
      <svg
        ref={svgRef}
        viewBox={viewBoxStr}
        preserveAspectRatio="xMidYMid meet"
        style={
          fillHeight
            ? {
                display: 'block',
                width: '100%',
                height: '100%',
                flex: '1 1 0',
                minWidth: 0,
                minHeight: 0,
                touchAction: 'none',
                cursor: panEnabled ? (panning ? 'grabbing' : 'grab') : 'default',
              }
            : { display: 'block', width: '100%', maxWidth: svgWidth + 20, height: 'auto' }
        }
        onPointerDown={handleSvgPointerDown}
        onPointerMove={handleSvgPointerMove}
        onPointerUp={endSvgPan}
        onPointerCancel={endSvgPan}
        aria-label={t('agents.plan.topology')}
        role="img"
      >
        {/* ── Zone bands (zoned mode) — drawn first, behind everything ── */}
        {isZoned &&
          zonedLayout!.bands.map(({ zone, x, y, w, h }) => {
            // Zone title/subtitle are width-fitted to the band so a long
            // localized string cannot spill past the band's border.
            const titleFit = fitTextToWidth(zone.title, w - 24 - 10, 11, { bold: true })
            const subtitleFit = zone.subtitle ? fitTextToWidth(zone.subtitle, w - 24 - 10, 9.5) : null
            return (
              <g key={`zone-${zone.id}`}>
                <rect
                  x={x + 10}
                  y={y + 10}
                  width={w}
                  height={h}
                  rx={14}
                  fill={zone.tint}
                  stroke={zone.border}
                  strokeWidth={1.4}
                  strokeDasharray={zone.dashed ? '7 5' : undefined}
                />
                <text
                  x={x + 24}
                  y={y + 32}
                  fontSize={11}
                  fontWeight={700}
                  fill={zone.border}
                  style={{ letterSpacing: '0.5px' }}
                >
                  {titleFit.text}
                  {titleFit.truncated && <title>{zone.title}</title>}
                </text>
                {zone.subtitle && subtitleFit && (
                  <text x={x + 24} y={y + 47} fontSize={9.5} fill="#64748b">
                    {subtitleFit.text}
                    {subtitleFit.truncated && <title>{zone.subtitle}</title>}
                  </text>
                )}
              </g>
            )
          })}

        {/* ── Group boxes (zoned mode) — behind their member nodes ── */}
        {isZoned &&
          zonedLayout!.groups.map((g) => {
            // Group label is width-fitted to the group box (long MCP server
            // slugs truncate; the full text stays on hover via <title>).
            const groupLabelFit = g.label != null ? fitTextToWidth(g.label, g.w - 30 - 8, 9.5, { bold: true }) : null
            return (
              <g key={`group-${g.key}`}>
                <rect
                  x={g.x + 10}
                  y={g.y + 10}
                  width={g.w}
                  height={g.h}
                  rx={10}
                  fill={g.color}
                  fillOpacity={0.08}
                  stroke={g.color}
                  strokeWidth={1.2}
                  strokeOpacity={0.55}
                />
                {g.label != null && groupLabelFit && (
                  <>
                    <circle cx={g.x + 22} cy={g.y + 10 + GROUP_LABEL_H / 2} r={3} fill={g.color} />
                    <text
                      x={g.x + 30}
                      y={g.y + 10 + GROUP_LABEL_H / 2 + 3.5}
                      fontSize={9.5}
                      fontWeight={700}
                      fill={g.color}
                    >
                      {groupLabelFit.text}
                      {groupLabelFit.truncated && <title>{g.label}</title>}
                    </text>
                  </>
                )}
              </g>
            )
          })}

        {/* ── Communication Hub vertical bar (zoned mode) — a full-band-height
              "firewall" between the Capabilities zone and the Tools zone,
              drawn before the edges so route connectors visibly cross it ── */}
        {isZoned && zonedLayout!.hubBarRect && hubBar && (
          <g data-testid="topology-hub-bar">
            {(() => {
              const bar = zonedLayout!.hubBarRect
              const barX = bar.x + 10
              const barY = bar.y + 10
              const barColor = hubBar.color ?? HUB_BAR_COLOR
              const centerX = barX + bar.w / 2
              const centerY = barY + bar.h / 2
              return (
                <>
                  <rect
                    x={barX}
                    y={barY}
                    width={bar.w}
                    height={bar.h}
                    rx={10}
                    ry={10}
                    fill={`${barColor}14`}
                    stroke={barColor}
                    strokeWidth={1.6}
                  />
                  {/* Hub icon badge (top of the bar) — proportionally small */}
                  <rect
                    x={centerX - 10}
                    y={barY + 8}
                    width={20}
                    height={20}
                    rx={6}
                    fill="#ffffff"
                    stroke={barColor}
                    strokeWidth={1}
                  />
                  <TopologyNodeIcon type="communication_hub" size={11} color={barColor} x={centerX - 5.5} y={barY + 12.5} />
                  {/* Vertical label — rotated so it reads bottom-up along the bar */}
                  <text
                    x={centerX}
                    y={centerY + 12}
                    transform={`rotate(-90 ${centerX} ${centerY + 12})`}
                    fontSize={10.5}
                    fontWeight={700}
                    fill={barColor}
                    textAnchor="middle"
                    style={{ letterSpacing: '0.6px', textTransform: 'uppercase' }}
                  >
                    {hubBar.label}
                  </text>
                </>
              )
            })()}
          </g>
        )}

        {/* Edges — drawn first so nodes appear on top */}
        {visibleEdges.map((edge, idx) => {
          const src = layoutByNodeId.get(edge.source)
          const tgt = layoutByNodeId.get(edge.target)
          if (!src || !tgt) return null

          // Special handling for agent→identity edges (vertical line, generic mode)
          const isAgentToIdentity = !isZoned && src.node.type === 'agent' && tgt.node.type === 'identity'

          let x1: number, y1: number, x2: number, y2: number, pathD: string
          // Label anchor (defaults to the straight-line midpoint).
          let labelX: number, labelY: number

          // Zoned mode: route connectors CROSS the Communication Hub bar —
          // an orthogonal run out of the capability, a vertical jog inside
          // the bar's column, then a horizontal entry into the tool node
          // (the runtime-monitor "firewall" routing, static).
          const bar = isZoned ? zonedLayout!.hubBarRect : null
          const crossesHubBar =
            bar !== null &&
            src.x + src.w + 10 <= bar.x &&
            tgt.x + 10 >= bar.x + bar.w

          if (isAgentToIdentity) {
            // Agent bottom center to identity top center (vertical line)
            x1 = src.x + src.w / 2 + 10
            y1 = src.y + src.h + 10
            x2 = tgt.x + tgt.w / 2 + 10
            y2 = tgt.y + 10
            pathD = `M ${x1},${y1} L ${x2},${y2}`  // Straight vertical line
            labelX = (x1 + x2) / 2
            labelY = (y1 + y2) / 2 - 4
          } else if (bar && crossesHubBar) {
            // Orthogonal route through the hub bar: capability right edge →
            // bar centre column → vertical jog → tool left edge.
            x1 = src.x + src.w + 10
            y1 = src.y + src.h / 2 + 10
            x2 = tgt.x + 10
            y2 = tgt.y + tgt.h / 2 + 10
            const midX = bar.x + bar.w / 2
            pathD = `M ${x1},${y1} L ${midX},${y1} L ${midX},${y2} L ${x2},${y2}`
            labelX = (midX + x2) / 2
            labelY = y2 - 5
          } else if (isZoned && tgt.node.childOf === src.node.id) {
            // Composition tree connector (SOP → its composed skills): a
            // vertical trunk drops from the parent's bottom edge into the
            // child-indent gutter (half-way into the indent), then elbows
            // horizontally into each child's left edge — classic tree/folder
            // branch lines. One shared trunk, branching elbows; per-edge
            // verticals overlap into a single line.
            x1 = src.x + GROUP_CHILD_INDENT / 2 + 10
            y1 = src.y + src.h + 10
            x2 = tgt.x + 10
            y2 = tgt.y + tgt.h / 2 + 10
            pathD = `M ${x1},${y1} L ${x1},${y2} L ${x2},${y2}`
            // Label sits in the gap between the parent and its first child,
            // just right of the shared trunk (only the first edge carries it).
            labelX = x1 + 32
            labelY = y1 + 9
          } else if (isZoned &&
                     Math.min(src.x + src.w, tgt.x + tgt.w) - Math.max(src.x, tgt.x) >
                       Math.min(src.w, tgt.w) / 2) {
            // Zoned same-column edge fallback (e.g. a SOP composing an
            // ALREADY directly-bound skill rendered in the Skills section —
            // both boxes share the zone column): a straight vertical drop
            // from the source bottom centre to the target top centre — the
            // default left↔right bezier would loop through both nodes.
            x1 = src.x + src.w / 2 + 10
            y1 = src.y + src.h + 10
            x2 = tgt.x + tgt.w / 2 + 10
            y2 = tgt.y + 10
            pathD = `M ${x1},${y1} L ${x2},${y2}`
            labelX = (x1 + x2) / 2
            labelY = (y1 + y2) / 2 - 4
          } else {
            // Standard horizontal connection (right-center to left-center)
            x1 = src.x + src.w + 10
            y1 = src.y + src.h / 2 + 10
            x2 = tgt.x + 10
            y2 = tgt.y + tgt.h / 2 + 10
            // Cubic bezier for a smooth curve
            const cx1 = x1 + (x2 - x1) * 0.4
            const cx2 = x2 - (x2 - x1) * 0.4
            pathD = `M ${x1},${y1} C ${cx1},${y1} ${cx2},${y2} ${x2},${y2}`
            labelX = (x1 + x2) / 2
            labelY = (y1 + y2) / 2 - 4
          }

          const appearance = edgeAppearance(edge)
          const isDashed = !isZoned && edge.style === 'dashed'
          // Generic mode keeps its historical agent→identity cyan styling.
          const strokeColor = !isZoned && isAgentToIdentity ? '#00acc1' : appearance.color
          const strokeWidth = !isZoned ? (isAgentToIdentity ? 2 : 1.5) : appearance.strokeWidth
          const markerEnd = isZoned
            ? appearance.marker
            : isAgentToIdentity
              ? 'url(#arrow-identity)'
              : 'url(#arrow)'

          return (
            <g key={`edge-${idx}`}>
              <path
                d={pathD}
                fill="none"
                stroke={strokeColor}
                strokeWidth={strokeWidth}
                strokeDasharray={isZoned ? appearance.dasharray : isDashed ? '6 3' : undefined}
                markerEnd={markerEnd}
              />
              {edge.label && (
                <text
                  x={labelX}
                  y={labelY}
                  fontSize={9}
                  fill={isZoned ? appearance.color : '#757575'}
                  textAnchor="middle"
                  style={isZoned ? { paintOrder: 'stroke', stroke: '#ffffff', strokeWidth: 3, fontWeight: 600 } : undefined}
                >
                  {edge.label}
                </text>
              )}
            </g>
          )
        })}

        {/* Arrow marker definitions */}
        <defs>
          <marker
            id="arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#9e9e9e" />
          </marker>
          <marker
            id="arrow-identity"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#00acc1" />
          </marker>
          {/* Zoned-mode semantic edge markers */}
          {Object.entries(ZONED_EDGE_STYLES).map(([style, appearance]) => (
            <marker
              key={`zoned-arrow-${style}`}
              id={`zoned-arrow-${style}`}
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill={appearance.color} />
            </marker>
          ))}
          {/* Zoned-mode per-capability route markers (explicit edge colours) */}
          {edgeColors.map((color) => (
            <marker
              key={colorMarkerId(color)}
              id={colorMarkerId(color)}
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill={color} />
            </marker>
          ))}
        </defs>

        {/* Nodes */}
        {layouts.map((l) => renderNode(l))}
      </svg>

      {/* Legend */}
      {isZoned ? (
        // Zoned edge-semantics legend (containment / equipped-with / grants / call path)
        <Box
          sx={{
            display: 'flex',
            gap: 1.5,
            flexWrap: 'wrap',
            mt: 1,
            alignItems: 'center',
            // Fullscreen: the legend keeps its natural height and the svg
            // gets the remaining viewport height (never pushed off-screen).
            ...(fillHeight ? { flexShrink: 0 } : {}),
          }}
        >
          <Typography
            variant="caption"
            sx={{ fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.4px', color: 'text.secondary' }}
          >
            {t('agents.plan.legend.title')}
          </Typography>
          <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
            <svg width="22" height="12" aria-hidden="true">
              <rect x="1" y="1" width="20" height="10" rx="3" fill="none" stroke={BOUNDARY_COLOR} strokeWidth="2.5" />
            </svg>
            <Typography variant="caption" color="text.secondary">
              {t('agents.plan.legend.boundary')}
            </Typography>
          </Box>
          <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
            <svg width="24" height="8" aria-hidden="true">
              <line x1="1" y1="4" x2="18" y2="4" stroke={ZONED_EDGE_STYLES.solid.color} strokeWidth="2" />
              <path d="M18 1l5 3-5 3z" fill={ZONED_EDGE_STYLES.solid.color} />
            </svg>
            <Typography variant="caption" color="text.secondary">
              {t('agents.plan.legend.equippedWith')}
            </Typography>
          </Box>
          <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
            <svg width="24" height="8" aria-hidden="true">
              <line
                x1="1"
                y1="4"
                x2="18"
                y2="4"
                stroke={ZONED_EDGE_STYLES.dotted.color}
                strokeWidth="2"
                strokeDasharray="2 3"
              />
              <path d="M18 1l5 3-5 3z" fill={ZONED_EDGE_STYLES.dotted.color} />
            </svg>
            <Typography variant="caption" color="text.secondary">
              {t('agents.plan.legend.grants')}
            </Typography>
          </Box>
          <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
            <svg width="24" height="8" aria-hidden="true">
              <line
                x1="1"
                y1="4"
                x2="18"
                y2="4"
                stroke={ZONED_EDGE_STYLES.dashed.color}
                strokeWidth="2"
                strokeDasharray="5 3"
              />
              <path d="M18 1l5 3-5 3z" fill={ZONED_EDGE_STYLES.dashed.color} />
            </svg>
            <Typography variant="caption" color="text.secondary">
              {t('agents.plan.legend.callPath')}
            </Typography>
          </Box>
        </Box>
      ) : (
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 1, ...(fillHeight ? { flexShrink: 0 } : {}) }}>
          {Object.entries(COLOR_MAP).map(([type, hexColor]) => (
            <Chip
              key={type}
              label={t(`agents.plan.nodeTypes.${type}`, { defaultValue: type })}
              size="small"
              variant="outlined"
              sx={{
                fontSize: 10,
                borderColor: hexColor,
                color: hexColor,
                '&:hover': {
                  borderColor: hexColor,
                  backgroundColor: `${hexColor}22`,
                }
              }}
            />
          ))}
        </Box>
      )}
    </Box>
  )
}

export default TopologyDiagramRenderer
