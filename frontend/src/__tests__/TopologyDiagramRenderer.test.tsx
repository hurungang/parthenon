import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import type { TopologyEdge, TopologyNode, TopologyZone } from '../types'
import { estimateTextWidth } from '../components/agents/topologyTextFit'
import { NODE_LABEL_X, nodeTextMaxWidth } from '../components/agents/TopologyDiagramRenderer'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

// ── Test fixtures ──────────────────────────────────────────────────────────────

const ROLE_NODE: TopologyNode = { id: 'role:r1', type: 'role', label: 'My Role', meta: { description: 'Role desc' } }
const SOP_NODE: TopologyNode = { id: 'sop:s1', type: 'sop', label: 'My SOP' }
const SKILL_NODE: TopologyNode = { id: 'skill:sk1', type: 'skill', label: 'My Skill', meta: undefined }
const TOOL_NODE: TopologyNode = { id: 'tool:my_tool', type: 'tool', label: 'my_tool', meta: { description: 'Tool desc' } }
const AGENT_TYPE_NODE: TopologyNode = {
  id: 'agent_type:research-agent',
  type: 'agent_type',
  label: 'research-agent',
  meta: { description: 'Delegation target' },
}

const ALL_NODES: TopologyNode[] = [ROLE_NODE, SOP_NODE, SKILL_NODE, TOOL_NODE]
const ALL_EDGES: TopologyEdge[] = [
  { source: 'role:r1', target: 'sop:s1', label: 'uses SOP' },
  { source: 'sop:s1', target: 'skill:sk1', label: 'invokes' },
  { source: 'skill:sk1', target: 'tool:my_tool', label: 'calls' },
]
const DELEGATION_NODES: TopologyNode[] = [ROLE_NODE, SKILL_NODE, AGENT_TYPE_NODE]
const DELEGATION_EDGES: TopologyEdge[] = [
  { source: 'role:r1', target: 'agent_type:research-agent', label: 'delegates to' },
  { source: 'skill:sk1', target: 'agent_type:research-agent', label: 'requests review' },
]

/** Zoned zone-band fixture shared by layout/composition/icon tests. */
const ZONED_TEST_ZONES: TopologyZone[] = [
  { id: 'config', title: '① CONFIGURATION', tint: '#f0f6ff', border: '#1d4ed8' },
  { id: 'capabilities', title: '② CAPABILITIES', tint: '#faf5ff', border: '#7c3aed' },
  { id: 'tools', title: '③ TOOLS', tint: '#f8fafc', border: '#64748b', dashed: true },
]

// ── Tests ──────────────────────────────────────────────────────────────────────

describe('TopologyDiagramRenderer', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renders without throwing with a valid non-empty payload', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    expect(() =>
      render(<TopologyDiagramRenderer nodes={ALL_NODES} edges={ALL_EDGES} />),
    ).not.toThrow()
  })

  it('renders an SVG element when nodes are present', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    const { container } = render(
      <TopologyDiagramRenderer nodes={ALL_NODES} edges={ALL_EDGES} />,
    )
    const svg = container.querySelector('svg')
    expect(svg).not.toBeNull()
  })

  it('renders node labels for all four node types', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    render(<TopologyDiagramRenderer nodes={ALL_NODES} edges={ALL_EDGES} />)

    // Node labels should appear in the SVG text elements
    expect(screen.getByText('My Role')).toBeDefined()
    expect(screen.getByText('My SOP')).toBeDefined()
    expect(screen.getByText('My Skill')).toBeDefined()
    expect(screen.getByText('my_tool')).toBeDefined()
  })

  it('renders node type labels (type badges)', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    const { container } = render(
      <TopologyDiagramRenderer nodes={ALL_NODES} edges={ALL_EDGES} />,
    )
    // Type badges are lowercase SVG text elements
    const textEls = container.querySelectorAll('text')
    const typeTexts = Array.from(textEls).map((el) => el.textContent?.toLowerCase() ?? '')
    expect(typeTexts.some((t) => t.includes('role'))).toBe(true)
    expect(typeTexts.some((t) => t.includes('sop'))).toBe(true)
    expect(typeTexts.some((t) => t.includes('skill'))).toBe(true)
    expect(typeTexts.some((t) => t.includes('tool'))).toBe(true)
  })

  it('renders empty state when nodes array is empty', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    render(<TopologyDiagramRenderer nodes={[]} edges={[]} />)

    // Should not render an SVG, should show empty state text
    const svg = document.querySelector('svg')
    expect(svg).toBeNull()

    // The empty state message uses t() key agents.plan.topology
    expect(screen.getByText(/agents\.plan\.topology/i)).toBeDefined()
  })

  it('does not throw when nodes contain unexpected extra fields', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    const nodesWithExtras = [
      { id: 'role:r1', type: 'role', label: 'Role', extra_unknown_field: 'ignored' },
    ] as unknown as TopologyNode[]

    expect(() =>
      render(<TopologyDiagramRenderer nodes={nodesWithExtras} edges={[]} />),
    ).not.toThrow()
  })

  it('does not throw when edges contain unexpected extra fields', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    const edgesWithExtras = [
      { source: 'role:r1', target: 'sop:s1', label: 'uses SOP', extra: 'ignored' },
    ] as unknown as TopologyEdge[]

    expect(() =>
      render(
        <TopologyDiagramRenderer
          nodes={[ROLE_NODE, SOP_NODE]}
          edges={edgesWithExtras}
        />,
      ),
    ).not.toThrow()
  })

  it('renders edge lines in the SVG when edges are provided', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    const { container } = render(
      <TopologyDiagramRenderer nodes={[ROLE_NODE, SKILL_NODE]} edges={[ALL_EDGES[0]]} />,
    )
    const paths = container.querySelectorAll('path')
    // At least one path element should be rendered for the edge
    expect(paths.length).toBeGreaterThan(0)
  })

  it('renders role-only graph without throwing', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    expect(() =>
      render(<TopologyDiagramRenderer nodes={[ROLE_NODE]} edges={[]} />),
    ).not.toThrow()

    expect(screen.getByText('My Role')).toBeDefined()
  })

  it('renders agent type nodes for delegation relationships', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    render(<TopologyDiagramRenderer nodes={DELEGATION_NODES} edges={DELEGATION_EDGES} />)

    expect(screen.getByText('research-agent')).toBeDefined()
  })

  it('renders delegation edges connecting the graph to the target agent type', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    render(<TopologyDiagramRenderer nodes={DELEGATION_NODES} edges={DELEGATION_EDGES} />)

    expect(screen.getByText('delegates to')).toBeDefined()
    expect(screen.getByText('requests review')).toBeDefined()
  })

  it('renders delegation nodes with a distinct color from skills', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    render(<TopologyDiagramRenderer nodes={DELEGATION_NODES} edges={DELEGATION_EDGES} />)

    const skillRect = screen.getByText('My Skill').parentElement?.querySelector('rect')
    const agentTypeRect = screen.getByText('research-agent').parentElement?.querySelector('rect')

    expect(skillRect?.getAttribute('stroke')).not.toBe(agentTypeRect?.getAttribute('stroke'))
  })
})

// ── Communication Hub node type (Phase 4.1 / 5.3) ─────────────────────────────

describe('TopologyDiagramRenderer — communication_hub node type', () => {
  const HUB_NODE: TopologyNode = { id: 'communication_hub', type: 'communication_hub', label: 'Communication Hub' }
  const AGENT_NODE: TopologyNode = { id: 'agent', type: 'agent', label: 'My Agent' }
  const HUB_EDGE: TopologyEdge = { source: 'agent', target: 'communication_hub', style: 'dashed', label: 'agents.plan.hubEdgeLabel' }

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renders the hub node with its own label and type badge', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    render(<TopologyDiagramRenderer nodes={[AGENT_NODE, HUB_NODE]} edges={[HUB_EDGE]} />)

    // Node label (short fixture label) and the legend chip (t() key) both render.
    expect(screen.getByText('Communication Hub')).toBeDefined()
    expect(screen.getByText('agents.plan.nodeTypes.communication_hub')).toBeDefined()
    const textEls = Array.from(document.querySelectorAll('text')).map((el) => el.textContent ?? '')
    expect(textEls.some((t) => t.toLowerCase() === 'communication_hub')).toBe(true)
  })

  it('draws the hub edge with a dashed style', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    const { container } = render(
      <TopologyDiagramRenderer nodes={[AGENT_NODE, HUB_NODE]} edges={[HUB_EDGE]} />,
    )

    expect(container.querySelectorAll('[stroke-dasharray="6 3"]').length).toBeGreaterThan(0)
    expect(screen.getByText('agents.plan.hubEdgeLabel')).toBeDefined()
  })

  it('gives the hub node a distinct colour from the agent node', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    render(<TopologyDiagramRenderer nodes={[AGENT_NODE, HUB_NODE]} edges={[HUB_EDGE]} />)

    const agentRect = screen.getByText('My Agent').parentElement?.querySelector('rect')
    const hubRect = screen.getByText('Communication Hub').parentElement?.querySelector('rect')
    expect(agentRect?.getAttribute('stroke')).toBeTruthy()
    expect(hubRect?.getAttribute('stroke')).toBeTruthy()
    expect(agentRect?.getAttribute('stroke')).not.toBe(hubRect?.getAttribute('stroke'))
  })

  it('renders a localized legend chip for the hub type', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    render(<TopologyDiagramRenderer nodes={[AGENT_NODE, HUB_NODE]} edges={[HUB_EDGE]} />)

    // The legend chip renders the localized node-type label via t().
    expect(screen.getByText('agents.plan.nodeTypes.communication_hub')).toBeDefined()
  })

  it('backwards compatibility: graphs without hub nodes render exactly as before', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    render(<TopologyDiagramRenderer nodes={ALL_NODES} edges={ALL_EDGES} />)

    // No hub node is drawn (no such label/badge); existing nodes render unchanged.
    expect(screen.queryByText('Communication Hub')).toBeNull()
    const textEls = Array.from(document.querySelectorAll('text')).map((el) => el.textContent ?? '')
    expect(textEls.some((t) => t.toLowerCase() === 'communication_hub')).toBe(false)
    expect(screen.getByText('My Role')).toBeDefined()
    expect(screen.getByText('My SOP')).toBeDefined()
  })
})

// ── Zoned panel layout (agent panel prototype design) ─────────────────────────

describe('TopologyDiagramRenderer — zoned layout', () => {
  const ZONES: TopologyZone[] = [
    { id: 'config', title: '① CONFIGURATION', subtitle: 'who the agent IS', tint: '#f0f6ff', border: '#1d4ed8' },
    { id: 'capabilities', title: '② CAPABILITIES', subtitle: 'what it is equipped with', tint: '#faf5ff', border: '#7c3aed' },
    { id: 'tools', title: '③ TOOLS', subtitle: 'what it can call', tint: '#f8fafc', border: '#64748b', dashed: true },
  ]

  const SKILL_COLOR = '#E53935'

  const ZONED_NODES: TopologyNode[] = [
    { id: 'agent', type: 'agent', label: 'research-agent', zone: 'config', caption: 'Agent Type · typed output' },
    { id: 'identity', type: 'identity', label: 'svc-agent', zone: 'config', containedIn: 'agent', caption: 'signs in as' },
    { id: 'role', type: 'role', label: 'Researcher', zone: 'config', containedIn: 'agent', caption: 'assumes as' },
    {
      id: 'skill_1',
      type: 'skill',
      label: 'web-search',
      zone: 'capabilities',
      accentColor: SKILL_COLOR,
      group: 'skills',
      groupLabel: 'Skills',
      groupColor: '#7c3aed',
    },
    {
      id: 'tool_1',
      type: 'tool',
      label: 'web_search',
      zone: 'tools',
      group: 'mcp-github',
      groupLabel: 'mcp-github',
      groupColor: '#15803d',
    },
  ]

  const ZONED_EDGES: TopologyEdge[] = [
    { source: 'agent', target: 'skill_1', style: 'solid', label: 'equipped with' },
    { source: 'role', target: 'skill_1', style: 'dotted', label: 'grants' },
    { source: 'skill_1', target: 'tool_1', style: 'dashed', color: SKILL_COLOR },
  ]

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renders the three zone bands with titles and subtitles', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    render(<TopologyDiagramRenderer nodes={ZONED_NODES} edges={ZONED_EDGES} zones={ZONES} />)

    expect(screen.getByText('① CONFIGURATION')).toBeDefined()
    expect(screen.getByText('who the agent IS')).toBeDefined()
    expect(screen.getByText('② CAPABILITIES')).toBeDefined()
    expect(screen.getByText('③ TOOLS')).toBeDefined()
  })

  it('renders contained nodes inside the agent boundary (containment, not edges)', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    const { container } = render(
      <TopologyDiagramRenderer nodes={ZONED_NODES} edges={ZONED_EDGES} zones={ZONES} />,
    )

    // All node labels render, including the contained identity/role.
    expect(screen.getByText('research-agent')).toBeDefined()
    expect(screen.getByText('svc-agent')).toBeDefined()
    expect(screen.getByText('Researcher')).toBeDefined()

    // Containment captions render ("signs in as" / "assumes as").
    expect(screen.getByText('signs in as')).toBeDefined()
    expect(screen.getByText('assumes as')).toBeDefined()

    // No containment edges: only the three semantic edges exist.
    const edgePaths = container.querySelectorAll('path[marker-end]')
    expect(edgePaths.length).toBe(ZONED_EDGES.length)
  })

  it('draws the agent boundary with a thick stroke and larger rect', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    const { container } = render(
      <TopologyDiagramRenderer nodes={ZONED_NODES} edges={ZONED_EDGES} zones={ZONES} />,
    )

    const boundaryRect = screen.getByText('research-agent').parentElement?.querySelector('rect')
    const roleRect = screen.getByText('Researcher').parentElement?.querySelector('rect')
    expect(boundaryRect?.getAttribute('stroke-width')).toBe('3')
    expect(boundaryRect?.getAttribute('stroke')).toBe('#1d4ed8')
    expect(roleRect?.getAttribute('stroke-width')).toBe('1.5')
    expect(boundaryRect?.getAttribute('stroke')).not.toBe(roleRect?.getAttribute('stroke'))
    expect(container).toBeDefined()
  })

  it('renders the distinct edge styles (solid / dotted / colored dashed)', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    const { container } = render(
      <TopologyDiagramRenderer nodes={ZONED_NODES} edges={ZONED_EDGES} zones={ZONES} />,
    )

    // Dotted grants edges + dashed call-path edges use their semantic dash patterns.
    expect(container.querySelectorAll('[stroke-dasharray="2 4"]').length).toBeGreaterThan(0)
    expect(container.querySelectorAll('[stroke-dasharray="6 4"]').length).toBeGreaterThan(0)
    // Edge labels render.
    expect(screen.getByText('equipped with')).toBeDefined()
    expect(screen.getByText('grants')).toBeDefined()
  })

  it('renders group boxes with their labels (sections / MCP servers)', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    render(<TopologyDiagramRenderer nodes={ZONED_NODES} edges={ZONED_EDGES} zones={ZONES} />)

    expect(screen.getByText('Skills')).toBeDefined()
    expect(screen.getByText('mcp-github')).toBeDefined()
  })

  it('renders the edge-semantics legend (containment / equipped / grants / call path)', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    render(<TopologyDiagramRenderer nodes={ZONED_NODES} edges={ZONED_EDGES} zones={ZONES} />)

    expect(screen.getByText('agents.plan.legend.title')).toBeDefined()
    expect(screen.getByText('agents.plan.legend.boundary')).toBeDefined()
    expect(screen.getByText('agents.plan.legend.equippedWith')).toBeDefined()
    expect(screen.getByText('agents.plan.legend.grants')).toBeDefined()
    expect(screen.getByText('agents.plan.legend.callPath')).toBeDefined()
  })

  it('scales the SVG responsively (viewBox, 100% width) — no horizontal overflow', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    const { container } = render(
      <TopologyDiagramRenderer nodes={ZONED_NODES} edges={ZONED_EDGES} zones={ZONES} />,
    )

    const svg = container.querySelector('svg')
    expect(svg).not.toBeNull()
    expect(svg?.getAttribute('viewBox')).toMatch(/^0 0 \d+(\.\d+)? \d+(\.\d+)?$/)
    expect(svg?.getAttribute('width')).toBeNull()
    expect(svg?.style.width).toBe('100%')
    expect(svg?.style.minWidth).toBe('')
  })

  it('stretches the SVG to the container height when fillHeight is set (fullscreen)', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    const { container } = render(
      <TopologyDiagramRenderer nodes={ZONED_NODES} edges={ZONED_EDGES} zones={ZONES} fillHeight />,
    )

    const svg = container.querySelector('svg')
    expect(svg?.style.height).toBe('100%')
    expect(svg?.style.width).toBe('100%')
    // Auto-fit contract: the svg box is bounded in BOTH dimensions (a flex
    // item with min-height 0 inside the flex-column root) and `meet`
    // scaling keeps the ENTIRE graph visible and centred — never clipped.
    expect(svg?.getAttribute('preserveAspectRatio')).toBe('xMidYMid meet')
    expect(svg?.style.flex).toMatch(/^1 1 0(px)?$/)
    expect(svg?.style.minHeight).toMatch(/^0(px)?$/)
    expect(svg?.style.touchAction).toBe('none')
    // The renderer root is a bounded flex column (legend below, svg above).
    const root = svg?.parentElement as HTMLElement
    expect(root.style.display).toBe('flex')
    expect(root.style.flexDirection).toBe('column')
    expect(root.style.minHeight).toMatch(/^0(px)?$/)
  })

  it('keeps the responsive height:auto behaviour without fillHeight (no fullscreen layout)', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    const { container } = render(
      <TopologyDiagramRenderer nodes={ZONED_NODES} edges={ZONED_EDGES} zones={ZONES} />,
    )

    const svg = container.querySelector('svg')
    expect(svg?.style.height).toBe('auto')
    expect(svg?.style.width).toBe('100%')
    // No fullscreen flex layout / touch handling in the inline mode.
    expect(svg?.style.flex).toBe('')
    expect(svg?.style.minHeight).toBe('')
    expect(svg?.style.getPropertyValue('touch-action')).toBe('')
    expect((svg?.parentElement as HTMLElement).style.display).toBe('')
    // The explicit attribute matches the SVG default (no behaviour change).
    expect(svg?.getAttribute('preserveAspectRatio')).toBe('xMidYMid meet')
  })

  it('marks every node group with data-topology-node (drag-to-pan exclusion targets)', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    const { container } = render(
      <TopologyDiagramRenderer nodes={ZONED_NODES} edges={ZONED_EDGES} zones={ZONES} />,
    )

    const nodeGroups = container.querySelectorAll('g[data-topology-node]')
    expect(nodeGroups.length).toBe(ZONED_NODES.length)
    expect(container.querySelector('g[data-topology-node="agent"]')).not.toBeNull()
    expect(container.querySelector('g[data-topology-node="skill_1"]')).not.toBeNull()
  })

  it('keeps the generic layered layout when no zones are provided', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    render(<TopologyDiagramRenderer nodes={ALL_NODES} edges={ALL_EDGES} />)

    // No zone bands or edge legend in generic mode.
    expect(screen.queryByText('① CONFIGURATION')).toBeNull()
    expect(screen.queryByText('agents.plan.legend.title')).toBeNull()
    // Node-type chip legend still renders.
    expect(screen.getByText('agents.plan.nodeTypes.skill')).toBeDefined()
  })
})

// ── Fullscreen view transform (viewBox zoom + pan) ────────────────────────────

describe('TopologyDiagramRenderer — fullscreen view transform (zoom/pan)', () => {
  const NODES: TopologyNode[] = [
    { id: 'agent', type: 'agent', label: 'research-agent', zone: 'config' },
    {
      id: 'skill_1',
      type: 'skill',
      label: 'web-search',
      zone: 'capabilities',
      group: 'skills',
      groupLabel: 'Skills',
      groupColor: '#7c3aed',
    },
    { id: 'tool_1', type: 'tool', label: 'web_search', zone: 'tools' },
  ]
  const EDGES: TopologyEdge[] = [{ source: 'skill_1', target: 'tool_1', style: 'dashed' }]

  /** Parsed viewBox numbers of the rendered topology svg. */
  function viewBoxOf(svg: Element | null): { x: number; y: number; w: number; h: number } {
    expect(svg).not.toBeNull()
    const [x, y, w, h] = (svg!.getAttribute('viewBox') ?? '')
      .split(/\s+/)
      .map((n) => Number(n))
    return { x, y, w, h }
  }

  it('keeps the full-world viewBox at zoom 1 — identical to the plain responsive render', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    const plain = render(
      <TopologyDiagramRenderer nodes={NODES} edges={EDGES} zones={ZONED_TEST_ZONES} />,
    )
    const base = viewBoxOf(plain.container.querySelector('svg'))
    plain.unmount()

    const fitted = render(
      <TopologyDiagramRenderer nodes={NODES} edges={EDGES} zones={ZONED_TEST_ZONES} fillHeight viewZoom={1} />,
    )
    const fittedView = viewBoxOf(fitted.container.querySelector('svg'))
    // zoom 1 = auto-fit: the whole world, anchored at the origin.
    expect(fittedView.x).toBe(0)
    expect(fittedView.y).toBe(0)
    expect(fittedView.w).toBeCloseTo(base.w, 1)
    expect(fittedView.h).toBeCloseTo(base.h, 1)
  })

  it('scales the viewBox inversely to the zoom and centres it on the world', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    const plain = render(
      <TopologyDiagramRenderer nodes={NODES} edges={EDGES} zones={ZONED_TEST_ZONES} />,
    )
    const base = viewBoxOf(plain.container.querySelector('svg'))
    plain.unmount()

    const zoomed = render(
      <TopologyDiagramRenderer nodes={NODES} edges={EDGES} zones={ZONED_TEST_ZONES} fillHeight viewZoom={2} />,
    )
    const view = viewBoxOf(zoomed.container.querySelector('svg'))
    // view = world / zoom (2× magnification of the content).
    expect(view.w).toBeCloseTo(base.w / 2, 1)
    expect(view.h).toBeCloseTo(base.h / 2, 1)
    // The default pan centre is the world centre → the view origin moves
    // to the upper-left quadrant of the world (centred zoom).
    expect(view.x).toBeCloseTo(base.w / 4, 1)
    expect(view.y).toBeCloseTo(base.h / 4, 1)
  })

  it('clamps an out-of-range viewZoom to the supported range', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    const plain = render(
      <TopologyDiagramRenderer nodes={NODES} edges={EDGES} zones={ZONED_TEST_ZONES} />,
    )
    const base = viewBoxOf(plain.container.querySelector('svg'))
    plain.unmount()

    // zoom 10 clamps to 3 → view width = world / 3.
    const over = render(
      <TopologyDiagramRenderer nodes={NODES} edges={EDGES} zones={ZONED_TEST_ZONES} fillHeight viewZoom={10} />,
    )
    const overView = viewBoxOf(over.container.querySelector('svg'))
    expect(overView.w).toBeCloseTo(base.w / 3, 1)
    over.unmount()

    // zoom 0.1 clamps to 0.5 → view width = world / 0.5 (2× the world).
    const under = render(
      <TopologyDiagramRenderer nodes={NODES} edges={EDGES} zones={ZONED_TEST_ZONES} fillHeight viewZoom={0.1} />,
    )
    const underView = viewBoxOf(under.container.querySelector('svg'))
    expect(underView.w).toBeCloseTo(base.w * 2, 1)
  })
})

// ── Zoned Communication Hub vertical bar (runtime-monitor firewall pattern) ────

describe('TopologyDiagramRenderer — zoned Communication Hub bar', () => {
  const ZONES: TopologyZone[] = [
    { id: 'config', title: '① CONFIGURATION', tint: '#f0f6ff', border: '#1d4ed8' },
    { id: 'capabilities', title: '② CAPABILITIES', tint: '#faf5ff', border: '#7c3aed' },
    { id: 'tools', title: '③ TOOLS', tint: '#f8fafc', border: '#64748b', dashed: true },
  ]

  const NODES: TopologyNode[] = [
    { id: 'agent', type: 'agent', label: 'research-agent', zone: 'config' },
    {
      id: 'skill_1',
      type: 'skill',
      label: 'web-search',
      zone: 'capabilities',
      group: 'skills',
      groupLabel: 'Skills',
      groupColor: '#7c3aed',
    },
    { id: 'tool_1', type: 'tool', label: 'web_search', zone: 'tools' },
  ]

  const EDGES: TopologyEdge[] = [
    { source: 'agent', target: 'skill_1', style: 'solid' },
    { source: 'skill_1', target: 'tool_1', style: 'dashed', color: '#E53935' },
  ]

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renders the hub as a vertical bar with its label — not as a node', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    const { container } = render(
      <TopologyDiagramRenderer
        nodes={NODES}
        edges={EDGES}
        zones={ZONES}
        hubBar={{ label: 'Communication Hub', afterZone: 'capabilities' }}
      />,
    )

    // The bar renders with its vertical label…
    expect(container.querySelector('[data-testid="topology-hub-bar"]')).not.toBeNull()
    expect(screen.getByText('Communication Hub')).toBeDefined()
    // …and there is NO hub node (no type badge "COMMUNICATION_HUB").
    const texts = Array.from(container.querySelectorAll('text')).map((el) => el.textContent ?? '')
    expect(texts.some((txt) => txt.toLowerCase() === 'communication_hub')).toBe(false)
  })

  it('spans the same height as the zone bands', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    const { container } = render(
      <TopologyDiagramRenderer
        nodes={NODES}
        edges={EDGES}
        zones={ZONES}
        hubBar={{ label: 'Communication Hub', afterZone: 'capabilities' }}
      />,
    )

    const barRect = container
      .querySelector('[data-testid="topology-hub-bar"]')
      ?.querySelector('rect')
    const zoneRects = Array.from(container.querySelectorAll('rect')).filter((r) =>
      (r.getAttribute('fill') ?? '').startsWith('#'),
    )
    // Any zone band (first band rect) matches the bar's height.
    expect(barRect?.getAttribute('height')).toBeTruthy()
    expect(zoneRects.length).toBeGreaterThan(0)
    expect(barRect?.getAttribute('height')).toBe(zoneRects[0]?.getAttribute('height'))
    expect(barRect?.getAttribute('y')).toBe(zoneRects[0]?.getAttribute('y'))
  })

  it('is not rendered when no hubBar prop is passed (backwards compatible)', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    const { container } = render(<TopologyDiagramRenderer nodes={NODES} edges={EDGES} zones={ZONES} />)

    expect(container.querySelector('[data-testid="topology-hub-bar"]')).toBeNull()
  })

  it('routes capability→tool connectors orthogonally THROUGH the hub bar area', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    const { container } = render(
      <TopologyDiagramRenderer
        nodes={NODES}
        edges={EDGES}
        zones={ZONES}
        hubBar={{ label: 'Communication Hub', afterZone: 'capabilities' }}
      />,
    )

    // The colored connector's path is orthogonal (L-segments, no bezier C).
    const coloredPath = Array.from(container.querySelectorAll('path')).find(
      (p) => p.getAttribute('stroke') === '#E53935',
    )
    expect(coloredPath).toBeDefined()
    expect(coloredPath?.getAttribute('d')).toMatch(/^M [\d.]+,[\d.]+ L [\d.]+,[\d.]+ L [\d.]+,[\d.]+ L [\d.]+,[\d.]+$/)
    // The vertical jog happens inside the bar's x-range (crossing it).
    const barRect = container
      .querySelector('[data-testid="topology-hub-bar"]')
      ?.querySelector('rect')
    const barX = Number(barRect?.getAttribute('x') ?? 0)
    const barW = Number(barRect?.getAttribute('width') ?? 0)
    const segmentXs = (coloredPath?.getAttribute('d') ?? '')
      .split(' L ')
      .map((seg) => Number(seg.split(',')[0]))
    expect(segmentXs.some((x) => x > barX && x < barX + barW)).toBe(true)
  })
})

// ── Zoned per-edge colours + entity-type icons ────────────────────────────────

describe('TopologyDiagramRenderer — per-capability colours and entity-type icons', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('strokes colored edges with their explicit colour and defines a matching arrow marker', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    const { container } = render(
      <TopologyDiagramRenderer
        nodes={[
          { id: 'skill_1', type: 'skill', label: 'web-search', accentColor: '#E53935' },
          { id: 'tool_1', type: 'tool', label: 'web_search' },
        ]}
        edges={[{ source: 'skill_1', target: 'tool_1', style: 'dashed', color: '#E53935' }]}
      />,
    )

    const coloredPath = container.querySelector('path[stroke="#E53935"]')
    expect(coloredPath).not.toBeNull()
    // One arrow marker per distinct explicit colour.
    expect(container.querySelector('marker[id="zoned-arrow-c-E53935"]')).not.toBeNull()
  })

  it('uses the node accent colour for the node border', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    render(
      <TopologyDiagramRenderer
        nodes={[{ id: 'skill_1', type: 'skill', label: 'web-search', accentColor: '#8E24AA' }]}
        edges={[]}
      />,
    )

    const rect = screen.getByText('web-search').parentElement?.querySelector('rect')
    expect(rect?.getAttribute('stroke')).toBe('#8E24AA')
  })

  it('renders a small entity-type icon for every known node type', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    const types = [
      'agent',
      'identity',
      'role',
      'sop',
      'skill',
      'input_data_type',
      'output_data_type',
      'model',
      'tool',
      'mcp_server',
    ] as const
    render(
      <TopologyDiagramRenderer
        nodes={types.map((type, i) => ({ id: `n${i}`, type, label: `node-${type}` }))}
        edges={[]}
      />,
    )

    for (const type of types) {
      expect(document.querySelector(`[data-node-icon="${type}"]`)).not.toBeNull()
    }
  })

  it('renders icons of every node kind with explicit geometry inside their node rect', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )

    // Full zoned panel graph covering EVERY icon-bearing node kind at once:
    // the agent boundary (icon in the header), contained identity/role, the
    // contract chips (input/output/model), skills, SOP, tool, MCP server —
    // plus a dashed empty placeholder and a locked slot (icons there too).
    const nodes: TopologyNode[] = [
      { id: 'agent', type: 'agent', label: 'research-agent', zone: 'config', caption: 'Agent Type · typed output' },
      { id: 'identity', type: 'identity', label: 'svc-agent', zone: 'config', containedIn: 'agent', caption: 'signs in as' },
      { id: 'role', type: 'role', label: 'Researcher', zone: 'config', containedIn: 'agent', caption: 'assumes as' },
      { id: 'input_data_type', type: 'input_data_type', label: 'Report', zone: 'config', containedIn: 'agent' },
      { id: 'output_data_type', type: 'output_data_type', label: 'Locked output', zone: 'config', containedIn: 'agent', usage: 'locked' },
      { id: 'model', type: 'model', label: 'gpt-4o', zone: 'config', containedIn: 'agent' },
      { id: 'sop_1', type: 'sop', label: 'research-sop', zone: 'capabilities', group: 'sops' },
      { id: 'skill_1', type: 'skill', label: 'web-search', zone: 'capabilities', group: 'skills' },
      { id: 'skill_empty', type: 'skill', label: 'Skills (empty)', zone: 'capabilities', usage: 'empty' },
      { id: 'tool_1', type: 'tool', label: 'web_search', zone: 'tools', group: 'mcp-github' },
      { id: 'server_1', type: 'mcp_server', label: 'mcp-github', zone: 'tools' },
    ]
    const { container } = render(
      <TopologyDiagramRenderer nodes={nodes} edges={[]} zones={ZONED_TEST_ZONES} />,
    )

    const icons = Array.from(container.querySelectorAll('[data-node-icon]'))
    expect(icons.length).toBeGreaterThanOrEqual(nodes.length)
    for (const icon of icons) {
      // The icon is a nested <svg> with its own viewBox, scaled by explicit
      // width/height attributes (never the parent SVG's viewport size).
      expect(icon.getAttribute('viewBox')).toBe('0 0 24 24')
      const nodeGroup = icon.closest('g')
      expect(nodeGroup).not.toBeNull()
      const rect = nodeGroup!.querySelector('rect')
      expect(rect).not.toBeNull()
      const nodeW = Number(rect!.getAttribute('width'))
      const nodeH = Number(rect!.getAttribute('height'))
      const w = Number(icon.getAttribute('width'))
      const h = Number(icon.getAttribute('height'))
      const x = Number(icon.getAttribute('x'))
      const y = Number(icon.getAttribute('y'))

      // Small explicit size (12–15px range) — never "original" 24px+ and
      // never the parent viewport: strictly smaller than the node bounds.
      expect(w).toBeGreaterThan(0)
      expect(w).toBeLessThanOrEqual(15)
      expect(h).toBeGreaterThan(0)
      expect(h).toBeLessThanOrEqual(15)
      expect(w).toBeLessThan(nodeW)
      expect(h).toBeLessThan(nodeH)
      // Positioned INSIDE the node rect (left gutter), not overflowing it.
      // The rect carries a y offset on captioned nodes (caption strip above),
      // so the vertical containment check uses the rect's own origin.
      const rectY = Number(rect!.getAttribute('y') ?? '0')
      expect(x).toBeGreaterThanOrEqual(0)
      expect(x + w).toBeLessThanOrEqual(nodeW)
      expect(y).toBeGreaterThanOrEqual(rectY)
      expect(y + h).toBeLessThanOrEqual(rectY + nodeH)
    }
  })
})

// ── Zoned SOP composition tree (indented children + elbow connectors) ─────────

describe('TopologyDiagramRenderer — SOP composition tree layout', () => {
  const SOP_COLOR = '#8E24AA'
  const GROUP_COLOR = '#7c3aed'

  /** SOP with TWO composed skills marked as its tree children (childOf). */
  const TREE_NODES: TopologyNode[] = [
    {
      id: 'sop_1',
      type: 'sop',
      label: 'research-sop',
      zone: 'capabilities',
      accentColor: SOP_COLOR,
      group: 'sops',
      groupLabel: 'SOPs',
      groupColor: GROUP_COLOR,
    },
    {
      id: 'skill_2',
      type: 'skill',
      label: 'doc-gen',
      zone: 'capabilities',
      accentColor: '#43A047',
      group: 'sops',
      groupLabel: 'SOPs',
      groupColor: GROUP_COLOR,
      childOf: 'sop_1',
    },
    {
      id: 'skill_3',
      type: 'skill',
      label: 'summarize',
      zone: 'capabilities',
      accentColor: '#1E88E5',
      group: 'sops',
      groupLabel: 'SOPs',
      groupColor: GROUP_COLOR,
      childOf: 'sop_1',
    },
  ]

  const TREE_EDGES: TopologyEdge[] = [
    { source: 'sop_1', target: 'skill_2', style: 'solid', color: SOP_COLOR, label: 'composed of' },
    { source: 'sop_1', target: 'skill_3', style: 'solid', color: SOP_COLOR },
  ]

  afterEach(() => {
    vi.clearAllMocks()
  })

  async function renderTree() {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    return render(<TopologyDiagramRenderer nodes={TREE_NODES} edges={TREE_EDGES} zones={ZONED_TEST_ZONES} />)
  }

  /** Parsed geometry of a node: its translate offset + rect size. */
  function nodeGeometry(label: string) {
    const g = screen.getByText(label).closest('g')
    expect(g).not.toBeNull()
    const [, tx, ty] = (g!.getAttribute('transform') ?? '').match(/translate\(([\d.]+), ([\d.]+)\)/) ?? []
    const rect = g!.querySelector('rect')
    return {
      x: Number(tx),
      y: Number(ty),
      w: Number(rect?.getAttribute('width')),
      h: Number(rect?.getAttribute('height')),
    }
  }

  /** Parses an SVG path `d` into its polyline points. */
  function pathPoints(d: string): Array<[number, number]> {
    return d
      .split(' ')
      .filter((tok) => tok !== 'M' && tok !== 'L')
      .map((tok) => tok.split(',').map(Number) as [number, number])
  }

  it('indents composed skills beneath their SOP as narrower child nodes', async () => {
    await renderTree()

    const sop = nodeGeometry('research-sop')
    for (const label of ['doc-gen', 'summarize']) {
      const child = nodeGeometry(label)
      // Indented to the right of the parent (indent 24 — threshold 20)…
      expect(child.x).toBeGreaterThan(sop.x + 20)
      // …stacked BELOW the parent…
      expect(child.y).toBeGreaterThan(sop.y + sop.h)
      // …and narrower than the parent — a child component look.
      expect(child.w).toBeLessThan(sop.w)
    }
  })

  it('routes SOP → composed-skill edges as tree elbows from the indent gutter', async () => {
    const { container } = await renderTree()

    const sop = nodeGeometry('research-sop')
    const children = [nodeGeometry('doc-gen'), nodeGeometry('summarize')]
    const paths = Array.from(container.querySelectorAll('path')).filter(
      (p) => p.getAttribute('stroke') === SOP_COLOR,
    )
    expect(paths).toHaveLength(2)

    paths.forEach((path, i) => {
      const pts = pathPoints(path.getAttribute('d') ?? '')
      // Three-point orthogonal elbow: vertical trunk, then horizontal entry.
      expect(pts).toHaveLength(3)
      const [p1, p2, p3] = pts
      // Trunk is vertical (both points share x) and drops from the parent's
      // bottom edge downward.
      expect(p2[0]).toBe(p1[0])
      expect(p1[1]).toBeCloseTo(sop.y + sop.h, 0)
      expect(p2[1]).toBeGreaterThan(p1[1])
      // Entry is horizontal into the child's LEFT edge, at its mid height.
      expect(p3[1]).toBe(p2[1])
      expect(p3[0]).toBeCloseTo(children[i].x, 0)
      expect(p2[1]).toBeCloseTo(children[i].y + children[i].h / 2, 0)
      // The shared trunk runs inside the indent gutter — right of the
      // parent's left edge, left of the child's left edge (never through
      // the parent's or the child's body).
      expect(p1[0]).toBeGreaterThan(sop.x)
      expect(p1[0]).toBeLessThan(children[i].x)
      // The elbow moves right, INTO the child.
      expect(p3[0]).toBeGreaterThan(p1[0])
    })
    // The localized composition label still renders (first edge only).
    expect(screen.getByText('composed of')).toBeDefined()
  })

  it('wraps each SOP and its child stack in its own group box', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    // TWO bound SOPs, each composing one skill — each SOP gets its OWN box
    // wrapping itself and its child stack.
    const { container } = render(
      <TopologyDiagramRenderer
        nodes={[
          { id: 'sop_1', type: 'sop', label: 'research-sop', zone: 'capabilities', accentColor: SOP_COLOR, group: 'sops', groupLabel: 'SOPs', groupColor: GROUP_COLOR },
          { id: 'skill_2', type: 'skill', label: 'doc-gen', zone: 'capabilities', accentColor: '#43A047', group: 'sops', groupLabel: 'SOPs', groupColor: GROUP_COLOR, childOf: 'sop_1' },
          { id: 'sop_2', type: 'sop', label: 'deploy-sop', zone: 'capabilities', accentColor: '#3949AB', group: 'sops', groupLabel: 'SOPs', groupColor: GROUP_COLOR },
          { id: 'skill_3', type: 'skill', label: 'summarize', zone: 'capabilities', accentColor: '#1E88E5', group: 'sops', groupLabel: 'SOPs', groupColor: GROUP_COLOR, childOf: 'sop_2' },
        ]}
        edges={[]}
        zones={ZONED_TEST_ZONES}
      />,
    )

    // Group boxes are the only rects with fill-opacity 0.08.
    const boxes = Array.from(container.querySelectorAll('rect[fill-opacity="0.08"]'))
    // Per-root boxes: one per SOP — not one shared section box.
    expect(boxes).toHaveLength(2)

    /** Stable primitive key for a box rect (keeps chai messages readable). */
    const boxKey = (b: Element) => `${b.getAttribute('x')},${b.getAttribute('y')}`
    /** Key of the (single) box rect whose bounds fully contain the node. */
    const containingBoxKey = (label: string): string => {
      const n = nodeGeometry(label)
      const hit = boxes.find((b) => {
        const bx = Number(b.getAttribute('x'))
        const by = Number(b.getAttribute('y'))
        const bw = Number(b.getAttribute('width'))
        const bh = Number(b.getAttribute('height'))
        return (
          n.x >= bx && n.x + n.w <= bx + bw &&
          n.y >= by && n.y + n.h <= by + bh
        )
      })
      expect(hit).not.toBeNull()
      return boxKey(hit!)
    }

    // Each SOP shares exactly ONE box with its OWN child…
    const sop1Box = containingBoxKey('research-sop')
    const sop2Box = containingBoxKey('deploy-sop')
    expect(containingBoxKey('doc-gen')).toBe(sop1Box)
    expect(containingBoxKey('summarize')).toBe(sop2Box)
    // …and the boxes are distinct — one child stack per SOP.
    expect(sop1Box).not.toBe(sop2Box)

    // The two boxes stack vertically without overlapping.
    const boxRects = boxes.map((b) => ({
      y: Number(b.getAttribute('y')),
      h: Number(b.getAttribute('height')),
    }))
    boxRects.sort((a, b) => a.y - b.y)
    expect(boxRects[0].y + boxRects[0].h).toBeLessThanOrEqual(boxRects[1].y)
  })

  it('keeps a childless SOP group as a single labeled section box (flat fallback)', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    // No childOf anywhere → the original shared labeled box behaviour.
    const { container } = render(
      <TopologyDiagramRenderer
        nodes={[
          { id: 'sop_9', type: 'sop', label: 'solo-sop', zone: 'capabilities', group: 'sops', groupLabel: 'SOPs', groupColor: GROUP_COLOR },
        ]}
        edges={[]}
        zones={ZONED_TEST_ZONES}
      />,
    )

    const boxes = Array.from(container.querySelectorAll('rect[fill-opacity="0.08"]'))
    expect(boxes).toHaveLength(1)
    // The section label renders for the flat box (tree boxes are unlabeled).
    expect(screen.getByText('SOPs')).toBeDefined()
    expect(screen.getByText('solo-sop')).toBeDefined()
  })
})

// ── Dense icons, left-aligned width-fitted labels (text overflow fix) ─────────

describe('TopologyDiagramRenderer — dense icons and fitted left-aligned labels', () => {
  const LONG_LABEL = 'gpt-4o (OpenAI Production Large Context Window)'

  afterEach(() => {
    vi.clearAllMocks()
  })

  /** The left-aligned node label <text> (text-anchor="start" at the gutter x). */
  function labelOf(container: HTMLElement): SVGTextElement {
    const label = Array.from(container.querySelectorAll('text')).find(
      (el) => el.getAttribute('text-anchor') === 'start' && el.getAttribute('x') === String(NODE_LABEL_X),
    )
    expect(label).not.toBeNull()
    return label as SVGTextElement
  }

  /**
   * Direct text-node content of an element — the `<title>` child carrying the
   * full label is excluded (textContent would concatenate it).
   */
  function directText(el: Element): string {
    return Array.from(el.childNodes)
      .filter((n) => n.nodeType === Node.TEXT_NODE)
      .map((n) => n.textContent ?? '')
      .join('')
  }

  it('renders dense node icons of at most 11px', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    const { container } = render(
      <TopologyDiagramRenderer
        nodes={[
          { id: 'agent', type: 'agent', label: 'research-agent', zone: 'config', caption: 'Agent Type · typed' },
          { id: 'skill_1', type: 'skill', label: 'web-search', zone: 'capabilities' },
          { id: 'tool_1', type: 'tool', label: 'web_search', zone: 'tools' },
        ]}
        edges={[]}
        zones={ZONED_TEST_ZONES}
      />,
    )

    // Boundary header icon and node icons are all proportionally small.
    const icons = Array.from(container.querySelectorAll('[data-node-icon]'))
    expect(icons.length).toBeGreaterThanOrEqual(3)
    for (const icon of icons) {
      const width = Number(icon.getAttribute('width'))
      expect(width).toBeGreaterThan(0)
      expect(width).toBeLessThanOrEqual(11)
      expect(Number(icon.getAttribute('height'))).toBe(width)
    }
  })

  it('left-aligns the label next to the icon (x = icon right + gap, vertically centred)', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    const { container } = render(
      <TopologyDiagramRenderer nodes={[{ id: 'skill_1', type: 'skill', label: 'web-search' }]} edges={[]} />,
    )

    const icon = container.querySelector('[data-node-icon="skill"]')
    expect(icon).not.toBeNull()
    const label = labelOf(container)
    expect(label.getAttribute('text-anchor')).toBe('start')
    // Label starts at the icon's right edge + the 4-unit gap (never overlaps).
    expect(Number(label.getAttribute('x'))).toBe(
      Number(icon!.getAttribute('x')) + Number(icon!.getAttribute('width')) + 4,
    )
    expect(Number(label.getAttribute('x'))).toBe(NODE_LABEL_X)
    // Vertically centred on the icon: baseline ≈ icon centre + 4.
    const iconCentreY = Number(icon!.getAttribute('y')) + Number(icon!.getAttribute('height')) / 2
    expect(Number(label.getAttribute('y'))).toBeCloseTo(iconCentreY + 4, 0)
  })

  it('truncates an overflowing label with an ellipsis and exposes the full text via <title>', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    const { container } = render(
      <TopologyDiagramRenderer nodes={[{ id: 'model', type: 'model', label: LONG_LABEL }]} edges={[]} />,
    )

    const label = labelOf(container)
    expect(directText(label)).toMatch(/…$/)
    // Native browser tooltips carry the FULL label — on the text element and
    // on the node group (hover anywhere on the node shows the full text).
    const titles = Array.from(container.querySelectorAll('title'))
    expect(titles.length).toBeGreaterThanOrEqual(2)
    for (const title of titles) {
      expect(title.textContent).toBe(LONG_LABEL)
    }
  })

  it('keeps short labels untruncated and title-free', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    const { container } = render(
      <TopologyDiagramRenderer nodes={[{ id: 'skill_1', type: 'skill', label: 'web-search' }]} edges={[]} />,
    )
    const label = labelOf(container)
    expect(directText(label)).toBe('web-search')
    expect(container.querySelector('title')).toBeNull()
  })

  it('renders the long panel model label truncated exactly as the e2e suite expects', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    const { container } = render(
      <TopologyDiagramRenderer
        nodes={[{ id: 'model', type: 'model', label: 'gpt-4o (Panel E2E GPT)' }]}
        edges={[]}
        zones={ZONED_TEST_ZONES}
      />,
    )
    expect(directText(labelOf(container))).toBe('gpt-4o (Panel E2E G…')
  })

  it('still invokes onNodeClick when clicking a truncated node (tooltip must not hijack handlers)', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    const onNodeClick = vi.fn()
    const { container } = render(
      <TopologyDiagramRenderer
        nodes={[{ id: 'model', type: 'model', label: LONG_LABEL }]}
        edges={[]}
        onNodeClick={onNodeClick}
      />,
    )
    fireEvent.click(container.querySelector('g')!)
    expect(onNodeClick).toHaveBeenCalledTimes(1)
    expect((onNodeClick.mock.calls[0][0] as TopologyNode).id).toBe('model')
  })

  it('fits every truncated label within its node inner width (generic + zoned incl. tree children)', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    const longNodes: TopologyNode[] = [
      { id: 'model', type: 'model', label: LONG_LABEL },
      { id: 'sop_1', type: 'sop', label: `${LONG_LABEL} SOP`, zone: 'capabilities', group: 'sops' },
      {
        id: 'skill_2',
        type: 'skill',
        label: `${LONG_LABEL} child`,
        zone: 'capabilities',
        group: 'sops',
        childOf: 'sop_1',
      },
      { id: 'tool_1', type: 'tool', label: `${LONG_LABEL} tool`, zone: 'tools' },
    ]
    const { container } = render(
      <TopologyDiagramRenderer nodes={longNodes} edges={[]} zones={ZONED_TEST_ZONES} />,
    )

    const truncatedLabels = Array.from(container.querySelectorAll('text')).filter((el) =>
      directText(el).endsWith('…'),
    )
    expect(truncatedLabels.length).toBeGreaterThanOrEqual(4)
    for (const label of truncatedLabels) {
      const rect = label.closest('g')?.querySelector('rect')
      expect(rect).not.toBeNull()
      const nodeWidth = Number(rect!.getAttribute('width'))
      const fontSize = Number(label.getAttribute('font-size'))
      // The estimator guarantee: the rendered (fitted) label never exceeds
      // the node's inner width right of the icon gutter.
      expect(estimateTextWidth(directText(label), fontSize)).toBeLessThanOrEqual(
        nodeTextMaxWidth(nodeWidth),
      )
    }
  })
})

// ── withCommunicationHub helper (Phase 5.2) ───────────────────────────────────

describe('withCommunicationHub', () => {
  it('appends the hub node and dashed agent→hub edge to an existing graph', async () => {
    const { withCommunicationHub, COMMUNICATION_HUB_NODE_ID } = await import(
      '../components/agents/topologyHub'
    )

    const { nodes, edges } = withCommunicationHub(
      [{ id: 'agent', type: 'agent', label: 'My Agent' }],
      [],
      'Communication Hub',
      'platform messaging',
    )

    expect(nodes).toHaveLength(2)
    expect(nodes[1]).toEqual({
      id: COMMUNICATION_HUB_NODE_ID,
      type: 'communication_hub',
      label: 'Communication Hub',
    })
    expect(edges).toEqual([
      { source: 'agent', target: COMMUNICATION_HUB_NODE_ID, style: 'dashed', label: 'platform messaging' },
    ])
  })

  it('is idempotent — never duplicates the hub on repeated calls', async () => {
    const { withCommunicationHub } = await import('../components/agents/topologyHub')

    const once = withCommunicationHub(
      [{ id: 'agent', type: 'agent', label: 'My Agent' }],
      [],
      'Communication Hub',
    )
    const twice = withCommunicationHub(once.nodes, once.edges, 'Communication Hub')

    expect(twice.nodes.filter((n) => n.id === 'communication_hub')).toHaveLength(1)
    expect(twice.edges.filter((e) => e.target === 'communication_hub')).toHaveLength(1)
    expect(twice.nodes).toBe(once.nodes)
    expect(twice.edges).toBe(once.edges)
  })
})
