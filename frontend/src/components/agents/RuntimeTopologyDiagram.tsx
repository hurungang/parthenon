import {
  Box,
  Checkbox,
  FormControlLabel,
  Paper,
  Stack,
  Typography,
} from '@mui/material'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import type { RuntimeTopologyNode, RuntimeTopologyProjection } from '../../types'

interface RuntimeTopologyDiagramProps {
  topology: RuntimeTopologyProjection | undefined
  selectedSessionId: string | null
  onSelectSession: (sessionId: string) => void
  // Phase 3.16: status filter.  When provided, only nodes
  // whose (kind, status) is in the visible set are rendered
  // and shown in the legend as ticked.  When undefined, all
  // statuses are visible.
  visibleKeys?: Set<string>
  onToggleKey?: (key: string) => void
}

// Layout constants.  All nodes at the same depth are placed in a
// single horizontal row (one next to another); the wrapping
// container provides a horizontal scrollbar so users can pan
// through dozens of agents at the same depth without stacking
// them on top of each other.
const NODE_WIDTH = 200
const NODE_HEIGHT = 56
const NODE_X_STEP = 240
const COL_X_BASE = 24
const ROW_GAP = 90
const ROOT_Y = 24
const SVG_PADDING_X = 24
const SVG_PADDING_Y = 24
const MAX_TEXT_WIDTH = NODE_WIDTH - 20 // leave 10px padding on each side
const TRIM_CHARS = 22

function statusFill(status: string, kind: string): string {
  // Phase 3.16: instance nodes use a purple palette to make
  // them visually distinct from agent runs (blue) and
  // conversation sessions (teal/grey).
  if (kind === 'instance') {
    if (status === 'active') return '#D1C4E9' // light purple
    if (status === 'created') return '#E1BEE7' // very light purple
    if (status === 'closed') return '#C5CAE9' // light indigo
    if (status === 'error') return '#FFCDD2'  // light red
    return '#FFFFFF'
  }
  // Phase 3.14: conversation nodes use a teal palette to make
  // them visually distinct from agent runs.
  if (kind === 'conversation') {
    if (status === 'active') return '#B2DFDB' // teal — live agent driving
    if (status === 'sleep') return '#ECEFF1'  // cool grey — no live agent
    if (status === 'closed' || status === 'archived') return '#DCEDC8' // light green
    if (status === 'error') return '#FFCDD2'  // light red
    return '#FFFFFF'
  }
  if (status === 'running') return '#BBDEFB' // blue
  if (status === 'completed') return '#C8E6C9' // green
  if (status === 'failed') return '#FFCDD2' // red
  if (status === 'terminated') return '#FFE0B2' // amber
  if (status === 'queued') return '#FFF9C4' // yellow
  return '#FFFFFF'
}

function statusStroke(status: string, kind: string): string {
  if (kind === 'instance') {
    if (status === 'active') return '#4527A0' // dark purple
    if (status === 'created') return '#6A1B9A' // darker purple
    if (status === 'closed') return '#283593' // dark indigo
    if (status === 'error') return '#B71C1C'
    return '#90A4AE'
  }
  if (kind === 'conversation') {
    if (status === 'active') return '#00695C' // dark teal
    if (status === 'sleep') return '#546E7A'  // blue-grey
    if (status === 'closed' || status === 'archived') return '#33691E'
    if (status === 'error') return '#B71C1C'
    return '#90A4AE'
  }
  if (status === 'running') return '#1565C0'
  if (status === 'completed') return '#2E7D32'
  if (status === 'failed') return '#C62828'
  if (status === 'terminated') return '#E65100'
  if (status === 'queued') return '#F57F17'
  return '#B0BEC5'
}

function trimText(text: string, maxChars: number): string {
  if (text.length <= maxChars) return text
  return `${text.slice(0, maxChars - 1)}…`
}

// Phase 3.16: a stable string key for a (kind, status) pair,
// used as the filter toggle identity.  The dashboard page
// persists the set of visible keys across re-renders.
function statusKey(kind: string, status: string): string {
  return `${kind}:${status}`
}

interface PositionedNode {
  node: RuntimeTopologyNode
  x: number
  y: number
  col: number
  row: number
}

function layoutNodes(nodes: RuntimeTopologyNode[]): {
  positioned: PositionedNode[]
  widthInColumns: number
  heightInRows: number
} {
  // Sort by depth, then by session_id for stability.
  const sorted = [...nodes].sort((a, b) => {
    if (a.depth_from_root !== b.depth_from_root) return a.depth_from_root - b.depth_from_root
    return a.session_id.localeCompare(b.session_id)
  })
  // Group by depth so we can place all nodes at the same
  // depth in a single horizontal row.
  const byDepth = new Map<number, RuntimeTopologyNode[]>()
  for (const n of sorted) {
    const arr = byDepth.get(n.depth_from_root) ?? []
    arr.push(n)
    byDepth.set(n.depth_from_root, arr)
  }

  const positioned: PositionedNode[] = []
  const sortedDepths = [...byDepth.keys()].sort((a, b) => a - b)
  let maxNodesInRow = 0
  for (const depth of sortedDepths) {
    const group = byDepth.get(depth)!
    maxNodesInRow = Math.max(maxNodesInRow, group.length)
    group.forEach((node, idx) => {
      // All nodes at the same depth share the same Y (one row
      // per depth).  The X is the position within that row, so
      // many nodes at one depth flow horizontally and the
      // wrapping container scrolls.
      const x = COL_X_BASE + idx * NODE_X_STEP
      const y = ROOT_Y + depth * ROW_GAP
      positioned.push({ node, x, y, col: idx, row: depth })
    })
  }
  return {
    positioned,
    widthInColumns: maxNodesInRow,
    heightInRows: sortedDepths.length,
  }
}

function findNodePosition(
  positioned: PositionedNode[],
  sessionId: string,
): PositionedNode | undefined {
  return positioned.find((p) => p.node.session_id === sessionId)
}

function statusLabelKey(status: string, kind: string): string {
  if (kind === 'conversation') {
    // Phase 3.14: synthetic "active" / "sleep" / "closed" / "error"
    // for conversation runtime status.
    if (status === 'active') return 'agents.sessions.runtimeStatusActive'
    if (status === 'sleep') return 'agents.sessions.runtimeStatusSleep'
    if (status === 'closed') return 'agents.sessions.runtimeStatusClosed'
    if (status === 'archived') return 'agents.sessions.runtimeStatusArchived'
    if (status === 'error') return 'agents.sessions.runtimeStatusError'
  }
  if (kind === 'instance') {
    // Phase 3.16: instance statuses.
    if (status === 'active') return 'agents.sessions.runtimeStatusActive'
    if (status === 'created') return 'agents.sessions.statusCreated'
    if (status === 'closed') return 'agents.sessions.runtimeStatusClosed'
    if (status === 'error') return 'agents.sessions.runtimeStatusError'
  }
  return `agents.sessions.status${status.charAt(0).toUpperCase()}${status.slice(1)}`
}

export function RuntimeTopologyDiagram({
  topology,
  selectedSessionId,
  onSelectSession,
  visibleKeys,
  onToggleKey,
}: RuntimeTopologyDiagramProps) {
  const { t } = useTranslation()

  // Phase 3.16: filter the topology nodes by the (kind, status)
  // visibility set.  When ``visibleKeys`` is undefined, all
  // nodes are shown (no filter applied).
  const filteredNodes = useMemo(() => {
    if (!topology?.nodes) return []
    if (!visibleKeys) return topology.nodes
    return topology.nodes.filter((n) => visibleKeys.has(statusKey(n.kind ?? 'agent', n.status)))
  }, [topology, visibleKeys])

  const filteredTopology = useMemo(
    () =>
      topology
        ? { ...topology, nodes: filteredNodes, edges: topology.edges ?? [] }
        : undefined,
    [topology, filteredNodes],
  )

  const { positioned, widthInColumns, heightInRows } = useMemo(
    () => layoutNodes(filteredNodes),
    [filteredNodes],
  )

  if (!topology || topology.nodes.length === 0) {
    return (
      <Paper sx={{ p: 3, textAlign: 'center' }} variant="outlined">
        <Typography variant="body2" color="text.secondary">
          {t('agents.sessions.runtimeTopologyEmpty')}
        </Typography>
      </Paper>
    )
  }

  if (filteredNodes.length === 0) {
    return (
      <Box>
        <Paper sx={{ p: 3, textAlign: 'center' }} variant="outlined">
          <Typography variant="body2" color="text.secondary">
            {t('agents.sessions.runtimeTopologyFilteredEmpty')}
          </Typography>
        </Paper>
        {renderLegend(t, visibleKeys, onToggleKey)}
      </Box>
    )
  }

  // Dynamic SVG size: width is at least ~3 visible nodes wide so
  // the diagram is not awkwardly narrow when there are only a
  // few nodes, otherwise it expands to fit the widest row
  // horizontally.  Height is one row per depth level.  When
  // there are many nodes at the same depth, the wrapping Box
  // provides a horizontal scrollbar (overflowX: 'auto').
  const svgWidth = Math.max(
    3 * NODE_X_STEP + NODE_WIDTH + SVG_PADDING_X,
    COL_X_BASE + widthInColumns * NODE_X_STEP + SVG_PADDING_X,
  )
  const svgHeight = Math.max(
    2 * ROW_GAP + ROOT_Y,
    ROOT_Y + heightInRows * ROW_GAP + SVG_PADDING_Y,
  )

  return (
    <Box>
      <Box
        sx={{
          // Phase 3.15: scrollable container so the user can see
          // all nodes even when there are many.
          overflowX: 'auto',
          overflowY: 'hidden',
          maxHeight: 480,
          border: '1px solid',
          borderColor: 'divider',
          borderRadius: 1,
        }}
      >
        <svg
          data-testid="runtime-topology-svg"
          viewBox={`0 0 ${svgWidth} ${svgHeight}`}
          width={svgWidth}
          height={svgHeight}
          aria-label={t('agents.sessions.runtimeTopologyTitle')}
          style={{ display: 'block', minWidth: 600 }}
        >
          <defs>
            <marker
              id="runtime-topology-arrow"
              markerWidth="8"
              markerHeight="8"
              refX="7"
              refY="4"
              orient="auto"
              markerUnits="strokeWidth"
            >
              <path d="M0,0 L8,4 L0,8 z" fill="#90A4AE" />
            </marker>
          </defs>

          {/* Edges */}
          {(topology.edges ?? []).map((edge) => {
            const parent = findNodePosition(positioned, edge.parent_session_id)
            const child = findNodePosition(positioned, edge.child_session_id)
            if (!parent || !child) return null
            const startX = parent.x + NODE_WIDTH
            const startY = parent.y + NODE_HEIGHT / 2
            const endX = child.x
            const endY = child.y + NODE_HEIGHT / 2
            const midX = (startX + endX) / 2
            const path = `M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${endY}, ${endX} ${endY}`
            return (
              <path
                key={`${edge.parent_session_id}-${edge.child_session_id}`}
                d={path}
                fill="none"
                stroke="#90A4AE"
                strokeWidth={1.4}
                markerEnd="url(#runtime-topology-arrow)"
              />
            )
          })}

          {/* Nodes */}
          {positioned.map(({ node, x, y }) => {
            const isSelected = selectedSessionId === node.session_id
            const isRisk = node.status === 'failed'
            const kind = node.kind ?? 'agent'
            // Phase 3.15/3.16: distinct box shapes per kind:
            //   agent         → small corner radius, solid border
            //   conversation  → large corner radius, dashed border
            //   instance      → pointed tab on left (rounded
            //                   rectangle with a notch), solid
            //                   border
            const isConv = kind === 'conversation'
            const isInst = kind === 'instance'
            const labelText = trimText(
              node.agent_type_name ?? t('agents.sessions.runtimeUnknownAgent'),
              TRIM_CHARS,
            )
            const sessionText = `${node.session_id.slice(0, 8)}…`
            // Build the path for the node shape.
            // For instance, we use a "tabbed" shape: a small
            // triangular notch on the left edge so it stands out
            // at a glance from regular agent boxes.
            const stroke = isSelected
              ? '#1976D2'
              : isRisk
                ? '#EF6C00'
                : statusStroke(node.status, kind)
            const strokeWidth = isSelected ? 2.4 : isConv || isInst ? 1.6 : 1.2
            const fill = statusFill(node.status, kind)
            const shape = (() => {
              if (isInst) {
                // Tabbed rectangle: notch on the left edge.
                const notchDepth = 10
                const notchY1 = y + 18
                const notchY2 = y + NODE_HEIGHT - 18
                return `M ${x + notchDepth} ${y} L ${x + NODE_WIDTH} ${y} L ${x + NODE_WIDTH} ${y + NODE_HEIGHT} L ${x + notchDepth} ${y + NODE_HEIGHT} L ${x} ${notchY2} L ${x} ${notchY1} Z`
              }
              return undefined // use plain rect
            })()
            return (
              <g
                key={node.session_id}
                data-testid={`topology-node-${node.session_id}`}
                data-node-id={node.session_id}
                onClick={() => onSelectSession(node.session_id)}
                style={{ cursor: 'pointer' }}
              >
                {shape ? (
                  <path
                    d={shape}
                    fill={fill}
                    stroke={stroke}
                    strokeWidth={strokeWidth}
                    strokeDasharray={isConv ? '4 2' : undefined}
                  />
                ) : (
                  <rect
                    x={x}
                    y={y}
                    width={NODE_WIDTH}
                    height={NODE_HEIGHT}
                    rx={isConv ? 16 : 6}
                    ry={isConv ? 16 : 6}
                    fill={fill}
                    stroke={stroke}
                    strokeWidth={strokeWidth}
                    strokeDasharray={isConv ? '4 2' : undefined}
                  />
                )}
                {/* Title: agent type name for both kinds */}
                <text
                  x={x + (isInst ? 22 : 12)}
                  y={y + 22}
                  fontSize={12}
                  fontWeight={700}
                  fill="#263238"
                  textLength={Math.min(MAX_TEXT_WIDTH, labelText.length * 7)}
                  lengthAdjust="spacingAndGlyphs"
                >
                  {labelText}
                </text>
                {/* Second line: short session id */}
                <text
                  x={x + (isInst ? 22 : 12)}
                  y={y + 42}
                  fontSize={10}
                  fill="#607D8B"
                  fontWeight={500}
                >
                  {sessionText}
                </text>
                {/* Status indicator dot in top-right corner — color codes
                    the status, replaces the redundant text label. */}
                <circle
                  cx={x + NODE_WIDTH - 14}
                  cy={y + 14}
                  r={5}
                  fill={statusStroke(node.status, kind)}
                  stroke="#FFFFFF"
                  strokeWidth={1.4}
                />
                <title>
                  {`${labelText} (${sessionText}) — ${t(statusLabelKey(node.status, kind), node.status)}`}
                </title>
              </g>
            )
          })}
        </svg>
      </Box>

      {renderLegend(t, visibleKeys, onToggleKey)}
    </Box>
  )
}

// Phase 3.16: each legend item is a checkbox that toggles
// visibility of that (kind, status) in the diagram.  When
// ``onToggleKey`` is undefined, the legend is rendered as a
// read-only display (no checkboxes).
function renderLegend(
  t: (k: string, d?: string) => string,
  visibleKeys: Set<string> | undefined,
  onToggleKey: ((key: string) => void) | undefined,
) {
  const items: Array<{ kind: string; status: string; label: string; dashed?: boolean }> = [
    { kind: 'agent', status: 'running', label: t('agents.sessions.statusRunning') },
    { kind: 'agent', status: 'queued', label: t('agents.sessions.statusQueued') },
    { kind: 'agent', status: 'completed', label: t('agents.sessions.statusCompleted') },
    { kind: 'agent', status: 'failed', label: t('agents.sessions.statusFailed') },
    { kind: 'agent', status: 'terminated', label: t('agents.sessions.statusTerminated') },
    {
      kind: 'conversation',
      status: 'active',
      label: t('agents.sessions.runtimeStatusActive'),
      dashed: true,
    },
    {
      kind: 'conversation',
      status: 'sleep',
      label: t('agents.sessions.runtimeStatusSleep'),
      dashed: true,
    },
    {
      kind: 'conversation',
      status: 'closed',
      label: t('agents.sessions.runtimeStatusClosed'),
      dashed: true,
    },
    {
      kind: 'conversation',
      status: 'error',
      label: t('agents.sessions.runtimeStatusError'),
      dashed: true,
    },
    {
      kind: 'instance',
      status: 'active',
      label: t('agents.sessions.runtimeStatusActive'),
    },
    {
      kind: 'instance',
      status: 'created',
      label: t('agents.sessions.statusCreated', t('agents.sessions.statusQueued')),
    },
    {
      kind: 'instance',
      status: 'error',
      label: t('agents.sessions.runtimeStatusError'),
    },
  ]
  return (
    <Stack
      direction="row"
      spacing={1.5}
      sx={{ mt: 1.5, px: 1, flexWrap: 'wrap', alignItems: 'center' }}
    >
      <Typography variant="caption" color="text.secondary" fontWeight={600}>
        {t('agents.sessions.runtimeTopologyLegend')}
      </Typography>
      {items.map((it) => {
        const key = statusKey(it.kind, it.status)
        const visible = !visibleKeys || visibleKeys.has(key)
        return (
          <FormControlLabel
            key={key}
            sx={{ m: 0 }}
            control={
              <Checkbox
                size="small"
                checked={visible}
                disabled={!onToggleKey}
                onChange={() => onToggleKey?.(key)}
                sx={{ p: 0.5 }}
              />
            }
            label={
              <Stack direction="row" alignItems="center" spacing={0.5}>
                <Box
                  sx={{
                    width: 14,
                    height: 14,
                    borderRadius: it.dashed ? '50%' : '3px',
                    backgroundColor: statusFill(it.status, it.kind),
                    border: `1.4px ${it.dashed ? 'dashed' : 'solid'} ${statusStroke(it.status, it.kind)}`,
                    opacity: visible ? 1 : 0.35,
                  }}
                />
                <Typography
                  variant="caption"
                  color={visible ? 'text.secondary' : 'text.disabled'}
                >
                  {it.label}
                </Typography>
              </Stack>
            }
          />
        )
      })}
    </Stack>
  )
}
