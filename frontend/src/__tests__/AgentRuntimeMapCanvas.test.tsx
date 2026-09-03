import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { AgentRuntimeMapCanvas } from '../components/agents/AgentRuntimeMapCanvas'
import type {
  RuntimeTopologyNode,
  RuntimeTopologyProjection,
} from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

// Isolate the detail bubble so the canvas tests focus on map behaviour.
vi.mock('../components/agents/AgentDetailBubble', () => ({
  AgentDetailBubble: ({ node }: { node: RuntimeTopologyNode }) => (
    <div data-testid="agent-detail-bubble">bubble-{node.session_id}</div>
  ),
}))

function mkNode(overrides: Partial<RuntimeTopologyNode> = {}): RuntimeTopologyNode {
  return {
    session_id: 'sess-1',
    agent_type_id: 'at-1',
    agent_type_name: 'Test Agent',
    status: 'running',
    depth_from_root: 0,
    parent_session_id: null,
    started_at: null,
    created_at: '2026-06-01T00:00:00Z',
    termination_category: null,
    kind: 'agent',
    needs_intervention: false,
    ...overrides,
  }
}

function mkTopology(
  nodes: RuntimeTopologyNode[],
  edges: RuntimeTopologyProjection['edges'] = [],
): RuntimeTopologyProjection {
  return { nodes, edges, root_session_ids: nodes.map((n) => n.session_id) }
}

function renderCanvas(props: Partial<React.ComponentProps<typeof AgentRuntimeMapCanvas>> = {}) {
  const defaultProps = {
    topology: mkTopology([mkNode()]),
    selectedSessionId: null,
    onSelectSession: vi.fn(),
    onOpenIntervention: vi.fn(),
    onTerminateNode: vi.fn(),
    isFullscreen: false,
    onToggleFullscreen: vi.fn(),
  }
  return render(<AgentRuntimeMapCanvas {...defaultProps} {...props} />)
}

/** Let the 60ms fullscreen re-fit timeout settle before asserting zoom. */
async function settle() {
  await new Promise((r) => setTimeout(r, 80))
}

function readZoomPct(): number {
  const el = screen.getByText(/%$/)
  return parseInt(el.textContent ?? '', 10)
}

/** Open the (collapsed-by-default) filter panel. */
function openFilterPanel() {
  fireEvent.click(screen.getByTestId('runtime-monitor-filter-button'))
}

/** Click a legend status/kind chip by its (already-translated) label text.
 *
 * The filter panel is collapsed by default, so it is opened first. The same
 * status label can also appear on a tile; the legend chip is the one carrying
 * an ``aria-pressed`` attribute, so we disambiguate by that.
 */
function clickLegendChip(label: string) {
  if (screen.queryByTestId('runtime-monitor-filter-panel') === null) {
    openFilterPanel()
  }
  const matches = screen.getAllByText(label)
  const chipRoot = matches
    .map((el) => el.closest('[aria-pressed]'))
    .find((el) => el !== null) as HTMLElement | undefined
  if (!chipRoot) throw new Error(`No legend chip found for label: ${label}`)
  fireEvent.click(chipRoot)
}

/** Read a layout value from the element's emotion-generated class rule
 * (MUI ``sx`` values are compiled into classes, not inline styles). */
function sxValue(el: HTMLElement, property: string): string | null {
  const classes = el.className.split(/\s+/)
  for (const sheet of Array.from(document.styleSheets)) {
    const css = sheet as CSSStyleSheet
    if (!css.cssRules) continue
    for (const rule of Array.from(css.cssRules)) {
      if (!(rule instanceof CSSStyleRule)) continue
      const selector = rule.selectorText ?? ''
      if (!classes.some((c) => selector === `.${c}`)) continue
      const value = rule.style.getPropertyValue(property)
      if (value) return value
    }
  }
  return null
}

describe('AgentRuntimeMapCanvas', () => {
  beforeEach(() => {
    // Give the viewport a deterministic size so auto-fit computes a real zoom.
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
      configurable: true,
      value: 1000,
    })
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      value: 700,
    })
    // jsdom lacks ResizeObserver; stub it so the canvas learns the mocked
    // stage size (the observer callback reads clientWidth/clientHeight and
    // sets viewportSize → world ≥ stage, hub pinned to the stage edges).
    vi.stubGlobal(
      'ResizeObserver',
      class MockResizeObserver {
        private callback: ResizeObserverCallback
        constructor(callback: ResizeObserverCallback) {
          this.callback = callback
        }
        observe(): void {
          this.callback([], this as unknown as ResizeObserver)
        }
        unobserve(): void {}
        disconnect(): void {}
      },
    )
  })

  it('shows a loading state while topology is undefined', () => {
    renderCanvas({ topology: undefined })
    expect(screen.getByTestId('runtime-monitor-loading')).toBeDefined()
  })

  it('shows an empty state when there are no nodes', () => {
    renderCanvas({ topology: mkTopology([]) })
    expect(screen.getByTestId('runtime-monitor-empty')).toBeDefined()
    expect(screen.getByText('agents.sessions.runtimeMonitorEmpty')).toBeDefined()
  })

  it('auto-fits content on mount (zoom leaves the 100% default)', async () => {
    renderCanvas({ topology: mkTopology([mkNode()]) })
    await settle()
    expect(readZoomPct()).not.toBe(100)
  })

  it('zooms in and out via the toolbar controls', async () => {
    renderCanvas({ topology: mkTopology([mkNode()]) })
    await settle()

    const before = readZoomPct()
    fireEvent.click(screen.getByRole('button', { name: 'agents.sessions.runtimeMonitorZoomIn' }))
    const zoomedIn = readZoomPct()
    expect(zoomedIn).toBeGreaterThan(before)

    fireEvent.click(screen.getByRole('button', { name: 'agents.sessions.runtimeMonitorZoomOut' }))
    const zoomedOut = readZoomPct()
    expect(zoomedOut).toBeLessThan(zoomedIn)
  })

  it('drags to pan the empty canvas', async () => {
    renderCanvas({ topology: mkTopology([mkNode()]) })
    await settle()

    const canvas = screen.getByTestId('agent-runtime-map-canvas')
    // The world layer's dynamic `transform` is applied via an Emotion class;
    // dragging updates panX/panY, which changes the generated class.
    const worldBefore = canvas.firstElementChild as HTMLElement
    const before = worldBefore.className

    fireEvent.mouseDown(canvas, { button: 0, clientX: 100, clientY: 100 })
    fireEvent.mouseMove(window, { clientX: 160, clientY: 140 })
    fireEvent.mouseUp(window)

    const worldAfter = screen.getByTestId('agent-runtime-map-canvas')
      .firstElementChild as HTMLElement
    expect(worldAfter.className).not.toBe(before)
  })

  it('places each delegation tree in its own container row (root col 0, child col 1)', () => {
    const parent = mkNode({ session_id: 'tree-root', agent_type_name: 'Team Lead' })
    const child = mkNode({
      session_id: 'tree-child',
      agent_type_name: 'Worker',
      parent_session_id: 'tree-root',
      depth_from_root: 1,
    })
    // Two unrelated agents of the SAME type: no type-grouping anymore —
    // each is its own single-node team container row.
    const solo1 = mkNode({ session_id: 'solo-1', agent_type_name: 'Shared Type' })
    const solo2 = mkNode({ session_id: 'solo-2', agent_type_name: 'Shared Type' })
    renderCanvas({
      topology: mkTopology(
        [parent, child, solo1, solo2],
        [{ parent_session_id: 'tree-root', child_session_id: 'tree-child', depth_from_root: 1 }],
      ),
    })

    // Root and child share ONE team container…
    const rootTile = screen.getByRole('button', { name: /Team Lead/ })
    const childTile = screen.getByRole('button', { name: /Worker/ })
    expect(rootTile.getAttribute('data-container')).toBe('tree-root')
    expect(childTile.getAttribute('data-container')).toBe('tree-root')
    // …with the root in column 0 and the delegated child in column 1.
    expect(rootTile.getAttribute('data-depth')).toBe('0')
    expect(childTile.getAttribute('data-depth')).toBe('1')
    expect(screen.getByTestId('team-container-tree-root')).toBeDefined()

    // Unrelated same-type agents each get their own container row.
    expect(screen.getByTestId('team-container-solo-1')).toBeDefined()
    expect(screen.getByTestId('team-container-solo-2')).toBeDefined()
    const solo1Tile = screen
      .getAllByRole('button', { name: /Shared Type/ })
      .find((el) => el.getAttribute('data-container') === 'solo-1')
    const solo2Tile = screen
      .getAllByRole('button', { name: /Shared Type/ })
      .find((el) => el.getAttribute('data-container') === 'solo-2')
    expect(solo1Tile).toBeDefined()
    expect(solo2Tile).toBeDefined()
  })

  it('renders a delegation connector when parent and child are both visible', () => {
    const parent = mkNode({ session_id: 'parent-1', agent_type_name: 'Parent' })
    const child = mkNode({
      session_id: 'child-1',
      agent_type_name: 'Child',
      parent_session_id: 'parent-1',
      depth_from_root: 1,
    })
    const { container } = renderCanvas({
      topology: mkTopology(
        [parent, child],
        [{ parent_session_id: 'parent-1', child_session_id: 'child-1', depth_from_root: 1 }],
      ),
    })

    expect(container.querySelector('svg path[marker-end]')).not.toBeNull()
  })

  it('does not render a delegation connector without edges', () => {
    const parent = mkNode({ session_id: 'parent-1', agent_type_name: 'Parent' })
    const child = mkNode({
      session_id: 'child-1',
      agent_type_name: 'Child',
      parent_session_id: 'parent-1',
      depth_from_root: 1,
    })
    const { container } = renderCanvas({ topology: mkTopology([parent, child]) })

    expect(container.querySelector('svg path[marker-end]')).toBeNull()
  })

  it('invokes onToggleFullscreen when the maximize control is clicked', () => {
    const onToggleFullscreen = vi.fn()
    renderCanvas({ onToggleFullscreen })

    fireEvent.click(screen.getByTestId('runtime-monitor-fullscreen'))
    expect(onToggleFullscreen).toHaveBeenCalledTimes(1)
  })

  it('shows the exit-fullscreen control when already fullscreen', () => {
    renderCanvas({ isFullscreen: true })
    expect(
      screen.getByRole('button', { name: 'agents.sessions.runtimeMonitorExitFullscreen' }),
    ).toBeDefined()
  })

  it('renders the filter button collapsed by default (panel hidden)', () => {
    renderCanvas({ topology: mkTopology([mkNode()]) })

    const button = screen.getByTestId('runtime-monitor-filter-button')
    expect(button).toBeDefined()
    expect(button.getAttribute('aria-expanded')).toBe('false')
    expect(screen.queryByTestId('runtime-monitor-filter-panel')).toBeNull()
  })

  it('expands the filter panel on click and folds on a second click', () => {
    renderCanvas({ topology: mkTopology([mkNode()]) })

    openFilterPanel()
    expect(screen.getByTestId('runtime-monitor-filter-panel')).toBeDefined()
    expect(
      screen.getByTestId('runtime-monitor-filter-button').getAttribute('aria-expanded'),
    ).toBe('true')

    openFilterPanel()
    expect(screen.queryByTestId('runtime-monitor-filter-panel')).toBeNull()
  })

  it('expands the filter panel on hover and folds after click outside', () => {
    renderCanvas({ topology: mkTopology([mkNode()]) })

    fireEvent.mouseEnter(screen.getByTestId('runtime-monitor-filter-root'))
    expect(screen.getByTestId('runtime-monitor-filter-panel')).toBeDefined()

    // A pointer-down outside the button/panel folds it immediately.
    fireEvent.mouseDown(document.body)
    expect(screen.queryByTestId('runtime-monitor-filter-panel')).toBeNull()
  })

  it('folds the expanded filter panel on Escape', () => {
    renderCanvas({ topology: mkTopology([mkNode()]) })

    openFilterPanel()
    expect(screen.getByTestId('runtime-monitor-filter-panel')).toBeDefined()

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByTestId('runtime-monitor-filter-panel')).toBeNull()
  })

  it('badges the filter button with the count of active restrictions', () => {
    renderCanvas({ topology: mkTopology([mkNode({ session_id: 's-1', status: 'running' })]) })

    // Collapsed, no restrictions → badge element present but invisible.
    const badgeEl = () =>
      screen.getByTestId('runtime-monitor-filter-badge').querySelector('.MuiBadge-badge') as HTMLElement
    expect(badgeEl().className).toContain('MuiBadge-invisible')

    // Hide one status chip → the badge becomes visible with count 1.
    clickLegendChip('agents.sessions.statusRunning')
    expect(badgeEl().className).not.toContain('MuiBadge-invisible')
    expect(badgeEl().textContent).toContain('1')
  })

  it('shows the recently-completed toggle and window controls in the panel', () => {
    renderCanvas({ topology: mkTopology([mkNode()]) })
    openFilterPanel()

    expect(screen.getByText('agents.sessions.runtimeMonitorRecentToggle')).toBeDefined()
    const toggleInput = screen
      .getByTestId('runtime-monitor-recent-toggle')
      .querySelector('input') as HTMLInputElement
    expect(toggleInput.checked).toBe(true)

    const minutesInput = screen.getByTestId('runtime-monitor-recent-minutes-input') as HTMLInputElement
    expect(minutesInput.value).toBe('30')

    const unit = screen.getByTestId('runtime-monitor-recent-unit') as HTMLSelectElement
    expect(unit.value).toBe('minutes')
    expect(screen.getByText('agents.sessions.runtimeMonitorWindowUnitMinutes')).toBeDefined()
    expect(screen.getByText('agents.sessions.runtimeMonitorWindowUnitHours')).toBeDefined()
  })

  it('commits a clamped ≥1 window value and converts the hours unit to minutes', () => {
    const onRecentMinutesChange = vi.fn()
    renderCanvas({ topology: mkTopology([mkNode()]), onRecentMinutesChange })
    openFilterPanel()

    const minutesInput = screen.getByTestId('runtime-monitor-recent-minutes-input')
    fireEvent.change(minutesInput, { target: { value: '90' } })
    expect(onRecentMinutesChange).toHaveBeenLastCalledWith(90)

    // 0 clamps to ≥ 1 minute.
    fireEvent.change(minutesInput, { target: { value: '0' } })
    expect(onRecentMinutesChange).toHaveBeenLastCalledWith(1)

    // Hours unit multiplies into minutes.
    fireEvent.change(screen.getByTestId('runtime-monitor-recent-unit'), {
      target: { value: 'hours' },
    })
    fireEvent.change(minutesInput, { target: { value: '2' } })
    expect(onRecentMinutesChange).toHaveBeenLastCalledWith(120)
  })

  it('propagates the recently-completed toggle to the page callback', () => {
    const onRecentEnabledChange = vi.fn()
    renderCanvas({ topology: mkTopology([mkNode()]), onRecentEnabledChange })
    openFilterPanel()

    const toggleInput = screen
      .getByTestId('runtime-monitor-recent-toggle')
      .querySelector('input') as HTMLInputElement
    fireEvent.click(toggleInput)
    expect(onRecentEnabledChange).toHaveBeenCalledWith(false)
  })

  it('filters nodes via the click-to-filter legend', () => {
    renderCanvas({ topology: mkTopology([mkNode()]) })

    // The kind chip label is unique to the legend (tiles render a kind icon, not a label).
    openFilterPanel()
    fireEvent.click(screen.getByText('agents.sessions.runtimeKindAgent'))

    // All agent-kind nodes hidden → filter-driven empty state.
    expect(screen.getByTestId('runtime-monitor-filtered-empty')).toBeDefined()
    expect(screen.getByText('agents.sessions.runtimeMonitorFilteredEmpty')).toBeDefined()
  })

  it('selects a node when its tile is clicked', () => {
    const onSelectSession = vi.fn()
    renderCanvas({ topology: mkTopology([mkNode({ session_id: 'sess-9' })]), onSelectSession })

    fireEvent.click(screen.getByRole('button', { name: /Test Agent/ }))
    expect(onSelectSession).toHaveBeenCalledWith('sess-9')
  })

  // ── Delegation legibility (refined feature) ──────────────────────────────────

  it('keeps a cross-type parent/child adjacent and connected', () => {
    const parent = mkNode({ session_id: 'parent-x', agent_type_name: 'Type A' })
    const child = mkNode({
      session_id: 'child-x',
      agent_type_name: 'Type B',
      parent_session_id: 'parent-x',
      depth_from_root: 1,
    })
    const { container } = renderCanvas({
      topology: mkTopology(
        [parent, child],
        [{ parent_session_id: 'parent-x', child_session_id: 'child-x', depth_from_root: 1 }],
      ),
    })

    // Parent + child land in the same delegation cluster (one group) so both a
    // single dashed container is rendered, regardless of differing agent types.
    const connector = container.querySelector('svg path[marker-end]')
    expect(connector).not.toBeNull()
  })

  it('promotes a delegated child to a root when its parent is filtered out', () => {
    const parent = mkNode({ session_id: 'parent-p', agent_type_name: 'Parent', status: 'running' })
    const child = mkNode({
      session_id: 'child-p',
      agent_type_name: 'Child',
      parent_session_id: 'parent-p',
      depth_from_root: 1,
      status: 'queued',
    })
    renderCanvas({
      topology: mkTopology(
        [parent, child],
        [{ parent_session_id: 'parent-p', child_session_id: 'child-p', depth_from_root: 1 }],
      ),
    })

    // Hide the parent only by clicking the legend status chip for "running".
    clickLegendChip('agents.sessions.statusRunning')

    // The child remains rendered (promoted to a root), not hidden with its parent.
    expect(screen.getByRole('button', { name: /Child/ })).toBeDefined()
    // The parent tile is gone.
    expect(screen.queryByRole('button', { name: /Parent/ })).toBeNull()
  })

  it('preserves the connector when an unrelated node is filtered out', () => {
    const parent = mkNode({ session_id: 'parent-p2', agent_type_name: 'Parent', status: 'running' })
    const child = mkNode({
      session_id: 'child-p2',
      agent_type_name: 'Child',
      parent_session_id: 'parent-p2',
      depth_from_root: 1,
      status: 'running',
    })
    const unrelated = mkNode({ session_id: 'other-1', agent_type_name: 'Unrelated', status: 'queued' })
    const { container } = renderCanvas({
      topology: mkTopology(
        [parent, child, unrelated],
        [{ parent_session_id: 'parent-p2', child_session_id: 'child-p2', depth_from_root: 1 }],
      ),
    })

    // Hide the unrelated node (status "queued") via the legend chip.
    clickLegendChip('agents.sessions.statusQueued')

    // The parent→child connector remains.
    expect(container.querySelector('svg path[marker-end]')).not.toBeNull()
  })

  // ── Empty-state filter recovery (refined feature) ────────────────────────────

  it('shows filter-driven empty state and recovers via reset filters', () => {
    const nodes = [
      mkNode({ session_id: 's-1', status: 'running' }),
      mkNode({ session_id: 's-2', status: 'running' }),
    ]
    renderCanvas({ topology: mkTopology(nodes) })

    // Hide all agent-kind nodes via the kind chip → filtered empty state.
    openFilterPanel()
    fireEvent.click(screen.getByText('agents.sessions.runtimeKindAgent'))

    // Toolbar/legend still usable: the "reset filters" button is present.
    const reset = screen.getByTestId('runtime-monitor-reset-filters')
    expect(reset).toBeDefined()
    expect(screen.getByTestId('runtime-monitor-filtered-empty')).toBeDefined()
    expect(screen.getByText('agents.sessions.runtimeMonitorFilteredEmpty')).toBeDefined()

    // Legend remains present.
    expect(screen.getByText('agents.sessions.runtimeMonitorLegendStatus')).toBeDefined()

    // Reset restores the population without a page reload.
    fireEvent.click(reset)

    expect(screen.queryByTestId('runtime-monitor-filtered-empty')).toBeNull()
    // Both agent tiles are visible again (queryAllByRole for the shared name).
    expect(screen.getAllByRole('button', { name: /Test Agent/ }).length).toBe(2)
  })

  // ── Communication Hub + tool-call routes (refined feature) ───────────────────

  it('renders the Communication Hub as a visible node', () => {
    renderCanvas({ topology: mkTopology([mkNode()]) })
    expect(screen.getByTestId('communication-hub-node')).toBeDefined()
    expect(screen.getByText('agents.sessions.runtimeCommunicationHub')).toBeDefined()
  })

  it('renders the hub as a full-height fixture pinned right in the filtered-empty state', () => {
    // One node, then hide it via the kind filter → filter-driven empty state.
    renderCanvas({ topology: mkTopology([mkNode({ session_id: 'hub-empty-1' })]) })
    openFilterPanel()
    fireEvent.click(screen.getByText('agents.sessions.runtimeKindAgent'))
    expect(screen.getByTestId('runtime-monitor-filtered-empty')).toBeDefined()

    // The hub remains a fixed fixture: pinned near the right edge of the
    // 1000px-wide stage and spanning its full 700px height.
    const hub = screen.getByTestId('communication-hub-node')
    const left = parseInt(sxValue(hub, 'left') ?? '', 10)
    const width = parseInt(sxValue(hub, 'width') ?? '', 10)
    const height = parseInt(sxValue(hub, 'height') ?? '', 10)
    expect(left).toBeGreaterThan(500)
    expect(left).toBeLessThanOrEqual(1000 - width)
    expect(height).toBeGreaterThanOrEqual(700)
    // No MCP/tool columns render without tool data in the empty state.
    expect(screen.queryByTestId(/^mcp-server-node-/)).toBeNull()
  })

  it('renders an MCP server node for each non-system tool-call slug', () => {
    const node = mkNode({
      tool_calls: [
        { tool_name: 'github____list_prs', mcp_slug: 'github', called_at: null },
        { tool_name: 'slack____post', mcp_slug: 'slack', called_at: null },
      ],
    })
    renderCanvas({ topology: mkTopology([node]) })

    expect(screen.getByTestId('mcp-server-node-github')).toBeDefined()
    expect(screen.getByTestId('mcp-server-node-slack')).toBeDefined()
  })

  it('renders ONE System Tools node for system tool calls (never "unknown")', () => {
    const node = mkNode({
      tool_calls: [
        { tool_name: 'save_data', mcp_slug: 'system', called_at: null },
        { tool_name: 'get_output', mcp_slug: 'system', called_at: null },
      ],
    })
    renderCanvas({ topology: mkTopology([node]) })

    expect(screen.getByTestId('system-tools-node')).toBeDefined()
    expect(screen.getByText('agents.sessions.runtimeMonitorSystemTools')).toBeDefined()
    // Only one System Tools node even with multiple system calls.
    expect(screen.getAllByTestId('system-tools-node').length).toBe(1)
    expect(screen.queryByTestId('mcp-server-node-unknown')).toBeNull()
  })

  it('never renders an "unknown" MCP node for unparseable (A2A-style) slugs', () => {
    const node = mkNode({
      tool_calls: [{ tool_name: 'agent__delegate_helper', mcp_slug: 'unknown', called_at: null }],
    })
    renderCanvas({ topology: mkTopology([node]) })

    expect(screen.queryByTestId('mcp-server-node-unknown')).toBeNull()
    expect(screen.queryByTestId('system-tools-node')).toBeNull()
  })

  it('renders tool chips for the distinct bare tool names used per MCP', () => {
    const node = mkNode({
      tool_calls: [
        { tool_name: 'github____list_prs', mcp_slug: 'github', called_at: null },
        { tool_name: 'github____create_issue', mcp_slug: 'github', called_at: null },
        { tool_name: 'github____create_issue', mcp_slug: 'github', called_at: null },
      ],
    })
    renderCanvas({ topology: mkTopology([node]) })

    // Distinct bare names only (the duplicate create_issue call collapses).
    expect(screen.getByTestId('tool-chip-github-list_prs')).toBeDefined()
    expect(screen.getByTestId('tool-chip-github-create_issue')).toBeDefined()
    expect(screen.getAllByTestId('tool-chip-github-create_issue').length).toBe(1)
  })

  it('draws a tool-call route from agent through the hub to the MCP server', () => {
    const node = mkNode({
      tool_calls: [
        { tool_name: 'github____list_prs', mcp_slug: 'github', called_at: null },
      ],
    })
    const { container } = renderCanvas({ topology: mkTopology([node]) })

    // Tool-call route paths are the SVG paths in the canvas WITHOUT a
    // marker-end (delegation connectors carry the arrow marker).
    const routePaths = Array.from(container.querySelectorAll('svg path')).filter(
      (p) => !p.hasAttribute('marker-end'),
    )
    expect(routePaths.length).toBeGreaterThan(0)
  })

  it('highlights the latest call in a per-agent colour and greys older calls', () => {
    const node = mkNode({
      tool_calls: [
        { tool_name: 'github____latest', mcp_slug: 'github', called_at: '2026-06-01T00:00:05Z' },
        { tool_name: 'github____older', mcp_slug: 'github', called_at: '2026-06-01T00:00:01Z' },
      ],
    })
    const { container } = renderCanvas({
      topology: mkTopology([node]),
      selectedSessionId: null,
    })

    const routePaths = Array.from(container.querySelectorAll('svg path')).filter(
      (p) => !p.hasAttribute('marker-end'),
    )

    // The latest route uses a saturated colour; the older is grey.
    const strokes = routePaths.map((p) => p.getAttribute('stroke'))
    expect(strokes.some((s) => s === ROUTE_GRAY_HEX)).toBe(true)
    expect(strokes.some((s) => s !== ROUTE_GRAY_HEX && s !== null)).toBe(true)
  })

  it('brightens historical routes when the agent is selected', () => {
    const node = mkNode({
      session_id: 'agent-sel',
      tool_calls: [
        { tool_name: 'github____latest', mcp_slug: 'github', called_at: '2026-06-01T00:00:05Z' },
        { tool_name: 'github____older', mcp_slug: 'github', called_at: '2026-06-01T00:00:01Z' },
      ],
    })

    const props = {
      topology: mkTopology([node]),
      selectedSessionId: null as string | null,
      onSelectSession: vi.fn(),
      onOpenIntervention: vi.fn(),
      onTerminateNode: vi.fn(),
      isFullscreen: false,
      onToggleFullscreen: vi.fn(),
    }

    const { container, rerender } = render(<AgentRuntimeMapCanvas {...props} />)

    const greyBefore = Array.from(container.querySelectorAll('svg path')).filter(
      (p) => p.getAttribute('stroke') === ROUTE_GRAY_HEX,
    ).length

    // Select the agent → older routes brighten to the per-agent colour.
    rerender(<AgentRuntimeMapCanvas {...props} selectedSessionId="agent-sel" />)

    const greyAfter = Array.from(container.querySelectorAll('svg path')).filter(
      (p) => p.getAttribute('stroke') === ROUTE_GRAY_HEX,
    ).length

    expect(greyAfter).toBeLessThan(greyBefore)
  })

  it('marks the selected agent routes and involved MCP + tool nodes as highlighted', () => {
    const agent = mkNode({
      session_id: 'agent-hl',
      tool_calls: [
        { tool_name: 'github____list_prs', mcp_slug: 'github', called_at: '2026-06-01T00:00:05Z' },
      ],
    })
    const other = mkNode({
      session_id: 'agent-other',
      tool_calls: [
        { tool_name: 'slack____post', mcp_slug: 'slack', called_at: '2026-06-01T00:00:05Z' },
      ],
    })
    const { container } = renderCanvas({
      topology: mkTopology([agent, other]),
      selectedSessionId: 'agent-hl',
    })

    // The selected agent's route paths carry the non-color cue flag.
    const highlightedPaths = container.querySelectorAll('path[data-highlighted="true"]')
    expect(highlightedPaths.length).toBeGreaterThan(0)
    for (const p of highlightedPaths) {
      expect(p.getAttribute('data-route-session')).toBe('agent-hl')
    }

    // The involved MCP node and its tool chip are outlined as highlighted;
    // unrelated MCP/tool nodes are dimmed instead.
    expect(screen.getByTestId('mcp-server-node-github').getAttribute('data-highlighted')).toBe('true')
    expect(screen.getByTestId('tool-chip-github-list_prs').getAttribute('data-highlighted')).toBe('true')
    expect(screen.getByTestId('mcp-server-node-slack').getAttribute('data-dimmed')).toBe('true')
    expect(screen.getByTestId('tool-chip-slack-post').getAttribute('data-dimmed')).toBe('true')
  })

  it('highlights ONLY the tool chips the selected agent actually called', () => {
    // The selected agent called ONE system tool + ONE github tool; a sibling
    // agent called a second github tool so that chip exists on the map.
    const agent = mkNode({
      session_id: 'agent-precise',
      tool_calls: [
        { tool_name: 'github____list_prs', mcp_slug: 'github', called_at: '2026-06-01T00:00:05Z' },
        { tool_name: 'system____save_data', mcp_slug: 'system', called_at: '2026-06-01T00:00:04Z' },
      ],
    })
    const sibling = mkNode({
      session_id: 'agent-sibling',
      tool_calls: [
        { tool_name: 'github____create_issue', mcp_slug: 'github', called_at: '2026-06-01T00:00:05Z' },
      ],
    })
    renderCanvas({
      topology: mkTopology([agent, sibling]),
      selectedSessionId: 'agent-precise',
    })

    // Used chips are highlighted, including via the System Tools node.
    expect(screen.getByTestId('tool-chip-github-list_prs').getAttribute('data-highlighted')).toBe('true')
    expect(screen.getByTestId('tool-chip-system-save_data').getAttribute('data-highlighted')).toBe('true')
    expect(screen.getByTestId('system-tools-node').getAttribute('data-highlighted')).toBe('true')
    expect(screen.getByTestId('mcp-server-node-github').getAttribute('data-highlighted')).toBe('true')

    // The UNUSED chip on the SAME MCP is NOT highlighted (never the whole
    // chip list) and stays dimmed while an agent is selected.
    expect(screen.getByTestId('tool-chip-github-create_issue').getAttribute('data-highlighted')).toBeNull()
    expect(screen.getByTestId('tool-chip-github-create_issue').getAttribute('data-dimmed')).toBe('true')
  })

  it('excludes A2A delegation rows from routes and MCP/chip rendering', () => {
    const node = mkNode({
      session_id: 'agent-a2a',
      tool_calls: [
        // Delegation row: excluded client-side (belt-and-braces with the
        // backend filter) — no "agent"/"unknown" MCP node, no route drawn.
        { tool_name: 'agent____helper', mcp_slug: 'agent', route_type: 'a2a', called_at: null },
        { tool_name: 'github____list_prs', mcp_slug: 'github', route_type: 'mcp', called_at: null },
      ],
    })
    const { container } = renderCanvas({ topology: mkTopology([node]) })

    expect(screen.queryByTestId('mcp-server-node-agent')).toBeNull()
    expect(screen.queryByTestId('mcp-server-node-unknown')).toBeNull()
    expect(screen.queryByTestId('tool-chip-agent-helper')).toBeNull()

    // Exactly ONE route (2 path segments: inbound + outbound) was drawn —
    // only for the MCP call.
    const routePaths = container.querySelectorAll('path[data-route-kind="tool"]')
    expect(routePaths.length).toBe(2)
  })

  // ── Intervention alert on ANY needs_intervention node (live-data round) ──────

  it('shows the intervention alert on a waiting_for_human agent node', () => {
    // The backend can now report HITL-paused agent jobs live; ANY node with
    // needs_intervention gets the alert treatment — including agent-kind
    // nodes (not just sleeping conversations).
    renderCanvas({
      topology: mkTopology([
        mkNode({ session_id: 'hitl-1', status: 'waiting_for_human', needs_intervention: true }),
      ]),
    })
    expect(screen.getByTestId('intervention-alert-hitl-1')).toBeDefined()
  })

  it('shows the intervention alert on a conversation-kind node (any-kind rule)', () => {
    renderCanvas({
      topology: mkTopology([
        mkNode({
          session_id: 'conv-hitl',
          kind: 'conversation',
          status: 'sleep',
          needs_intervention: true,
        }),
      ]),
    })
    expect(screen.getByTestId('intervention-alert-conv-hitl')).toBeDefined()
  })

  it('does not render an intervention alert without needs_intervention', () => {
    renderCanvas({ topology: mkTopology([mkNode({ session_id: 'calm-1' })]) })
    expect(screen.queryByTestId('intervention-alert-calm-1')).toBeNull()
  })

  it('clicking the intervention alert opens the intervention flow for that node', () => {
    const onOpenIntervention = vi.fn()
    renderCanvas({
      topology: mkTopology([
        mkNode({ session_id: 'hitl-2', status: 'waiting_for_human', needs_intervention: true }),
      ]),
      onOpenIntervention,
    })

    fireEvent.click(screen.getByTestId('intervention-alert-hitl-2'))
    expect(onOpenIntervention).toHaveBeenCalledTimes(1)
    expect(onOpenIntervention.mock.calls[0][0].session_id).toBe('hitl-2')
  })

  // ── Trigger / latest-tool tile lines (live-data round) ───────────────────────

  it('renders the trigger source line on the tile', () => {
    renderCanvas({
      topology: mkTopology([
        mkNode({
          session_id: 'trigger-1',
          trigger_source: 'user',
          trigger_source_label: 'Alice Operator',
        }),
      ]),
    })
    expect(screen.getByTestId('trigger-source-trigger-1')).toBeDefined()
  })

  it('renders the latest tool call line on the tile', () => {
    renderCanvas({
      topology: mkTopology([
        mkNode({
          session_id: 'tool-tile-1',
          tool_calls: [
            { tool_name: 'github____list_prs', mcp_slug: 'github', called_at: '2026-06-01T00:00:05Z' },
          ],
        }),
      ]),
    })
    expect(screen.getByTestId('latest-tool-tool-tile-1')).toBeDefined()
    expect(screen.getByText('github____list_prs')).toBeDefined()
  })

  it('omits the latest tool call line when the node has no calls', () => {
    renderCanvas({ topology: mkTopology([mkNode({ session_id: 'no-calls-1' })]) })
    expect(screen.queryByTestId('latest-tool-no-calls-1')).toBeNull()
  })
})

const ROUTE_GRAY_HEX = '#C7D0D8'
