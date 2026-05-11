import React, { useMemo, useState } from 'react'
import { Box, Chip, ClickAwayListener, FormControlLabel, Switch, Tooltip, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { TopologyEdge, TopologyNode } from '../../types'

// ── Layout constants ──────────────────────────────────────────────────────────

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
  role: 2,
  sop: 3,
  skill: 4,
  tool: 5,
}

// Hex color map per node type (used for both SVG and legend)
const COLOR_MAP: Record<string, string> = {
  agent: '#d32f2f',      // red
  identity: '#00acc1',   // bright cyan (more distinct from red)
  role: '#1976d2',       // blue
  sop: '#9c27b0',        // purple
  skill: '#ed6c02',      // orange
  tool: '#2e7d32',       // green
}

interface NodeLayout {
  node: TopologyNode
  x: number
  y: number
}

interface Props {
  nodes: TopologyNode[]
  edges: TopologyEdge[]
}

// ── Helpers ───────────────────────────────────────────────────────────────────

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
        layouts.push({ node, x: xPos, y: currentY })
        currentY += NODE_HEIGHT + V_GAP
      })
      if (unused.length > 0 && used.length > 0) {
        currentY += UNUSED_SKILL_GAP - V_GAP  // extra separator (UNUSED_SKILL_GAP total after last used)
      }
      unused.forEach((node) => {
        layouts.push({ node, x: xPos, y: currentY })
        currentY += NODE_HEIGHT + V_GAP
      })
    } else {
      colNodes.forEach((node, nodeIdx) => {
        layouts.push({
          node,
          x: xPos,
          y: yStart + nodeIdx * (NODE_HEIGHT + V_GAP),
        })
      })
    }
  })

  const svgWidth = sortedCols.length * (NODE_WIDTH + H_GAP) - H_GAP + 20
  const svgHeight = maxColHeight + 20

  return { layouts, svgWidth, svgHeight }
}

// ── Component ─────────────────────────────────────────────────────────────────

const TopologyDiagramRenderer: React.FC<Props> = ({ nodes, edges }) => {
  const { t } = useTranslation()
  const [showUnusedSkills, setShowUnusedSkills] = useState(false)
  const [clickedNodeId, setClickedNodeId] = useState<string | null>(null)

  const hasUnusedSkills = useMemo(
    () => nodes.some(n => n.type === 'skill' && n.usage === 'unused'),
    [nodes],
  )

  // Filter nodes and edges based on the toggle
  const visibleNodes = useMemo(() => {
    if (showUnusedSkills) return nodes
    return nodes.filter(n => !(n.type === 'skill' && n.usage === 'unused'))
  }, [nodes, showUnusedSkills])

  const visibleNodeIds = useMemo(() => new Set(visibleNodes.map(n => n.id)), [visibleNodes])

  const visibleEdges = useMemo(() => {
    if (showUnusedSkills) return edges
    return edges.filter(e => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target))
  }, [edges, showUnusedSkills, visibleNodeIds])

  const { layouts, svgWidth, svgHeight } = useMemo(() => computeLayout(visibleNodes), [visibleNodes])

  // Build a lookup from node ID → layout position (center point)
  const layoutByNodeId = useMemo<Map<string, NodeLayout>>(() => {
    const map = new Map<string, NodeLayout>()
    for (const layout of layouts) {
      map.set(layout.node.id, layout)
    }
    return map
  }, [layouts])

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

  return (
    <Box sx={{ overflowX: 'auto', mt: 1 }}>
      {/* Unused skills toggle */}
      {hasUnusedSkills && (
        <FormControlLabel
          control={
            <Switch
              size="small"
              checked={showUnusedSkills}
              onChange={(e) => setShowUnusedSkills(e.target.checked)}
            />
          }
          label={
            <Typography variant="caption">{t('agents.plan.showUnusedSkills')}</Typography>
          }
          sx={{ mb: 1, ml: 2 }}
        />
      )}

      <svg
        width={svgWidth + 20}
        height={svgHeight + 20}
        style={{ display: 'block', minWidth: svgWidth + 20 }}
        aria-label={t('agents.plan.topology')}
      >
        {/* Edges — drawn first so nodes appear on top */}
        {visibleEdges.map((edge, idx) => {
          const src = layoutByNodeId.get(edge.source)
          const tgt = layoutByNodeId.get(edge.target)
          if (!src || !tgt) return null

          // Special handling for agent→identity edges (vertical line)
          const isAgentToIdentity = src.node.type === 'agent' && tgt.node.type === 'identity'
          
          let x1: number, y1: number, x2: number, y2: number, pathD: string
          
          if (isAgentToIdentity) {
            // Agent bottom center to identity top center (vertical line)
            x1 = src.x + NODE_WIDTH / 2 + 10
            y1 = src.y + NODE_HEIGHT + 10
            x2 = tgt.x + NODE_WIDTH / 2 + 10
            y2 = tgt.y + 10
            pathD = `M ${x1},${y1} L ${x2},${y2}`  // Straight vertical line
          } else {
            // Standard horizontal connection (right-center to left-center)
            x1 = src.x + NODE_WIDTH + 10
            y1 = src.y + NODE_HEIGHT / 2 + 10
            x2 = tgt.x + 10
            y2 = tgt.y + NODE_HEIGHT / 2 + 10
            // Cubic bezier for a smooth curve
            const cx1 = x1 + (x2 - x1) * 0.4
            const cx2 = x2 - (x2 - x1) * 0.4
            pathD = `M ${x1},${y1} C ${cx1},${y1} ${cx2},${y2} ${x2},${y2}`
          }

          const isDashed = edge.style === 'dashed'
          const strokeColor = isAgentToIdentity ? '#00acc1' : '#9e9e9e'  // Bright cyan for agent→identity, gray for others
          const markerEnd = isAgentToIdentity ? 'url(#arrow-identity)' : 'url(#arrow)'

          return (
            <g key={`edge-${idx}`}>
              <path
                d={pathD}
                fill="none"
                stroke={strokeColor}
                strokeWidth={isAgentToIdentity ? 2 : 1.5}
                strokeDasharray={isDashed ? '6 3' : undefined}
                markerEnd={markerEnd}
              />
              {edge.label && (
                <text
                  x={(x1 + x2) / 2}
                  y={(y1 + y2) / 2 - 4}
                  fontSize={9}
                  fill="#757575"
                  textAnchor="middle"
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
        </defs>

        {/* Nodes */}
        {layouts.map(({ node, x, y }) => {
          const fillColor = COLOR_MAP[node.type] ?? '#757575'
          const isLong = node.label.length > 20
          const displayLabel = isLong ? `${node.label.slice(0, 19)}…` : node.label
          const isUnused = node.type === 'skill' && node.usage === 'unused'
          const isClicked = clickedNodeId === node.id

          return (
            <ClickAwayListener
              key={node.id}
              onClickAway={() => {
                if (isClicked) setClickedNodeId(null)
              }}
            >
              <Tooltip
                title={isLong ? node.label : ''}
                arrow
                open={isClicked || undefined}
                disableHoverListener={isClicked}
              >
                <g
                  transform={`translate(${x + 10}, ${y + 10})`}
                  onClick={() => {
                    if (isLong) {
                      setClickedNodeId(isClicked ? null : node.id)
                    }
                  }}
                  style={{ cursor: isLong ? 'pointer' : 'default' }}
                >
                  <rect
                    width={NODE_WIDTH}
                    height={NODE_HEIGHT}
                    rx={NODE_RADIUS}
                    ry={NODE_RADIUS}
                    fill={`${fillColor}22`}
                    stroke={fillColor}
                    strokeWidth={1.5}
                    strokeDasharray={isUnused ? '4 2' : undefined}
                    opacity={isUnused ? 0.7 : 1}
                  />
                  {/* Node type badge */}
                  <text
                    x={6}
                    y={12}
                    fontSize={8}
                    fontWeight={600}
                    fill={fillColor}
                    style={{ textTransform: 'uppercase', letterSpacing: '0.05em' }}
                  >
                    {node.type}
                  </text>
                  {/* Node label */}
                  <text
                    x={NODE_WIDTH / 2}
                    y={26}
                    fontSize={11}
                    fill="#212121"
                    textAnchor="middle"
                    style={{ fontWeight: 500 }}
                  >
                    {displayLabel}
                  </text>
                </g>
              </Tooltip>
            </ClickAwayListener>
          )
        })}
      </svg>

      {/* Legend */}
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 1 }}>
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
    </Box>
  )
}

export default TopologyDiagramRenderer

