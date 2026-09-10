import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { AgentRuntimeMapCanvas } from '../components/agents/AgentRuntimeMapCanvas'
import type {
  RuntimeTopologyNode,
  RuntimeTopologyProjection,
} from '../types'

// The canvas hosts TriggerDetailBubble, which fetches trigger-own details
// (schedule cron / identity email) via react-query — stub it; detail-fetch
// behaviour is covered in TriggerDetailBubble.test.tsx.
vi.mock('@tanstack/react-query', () => ({
  useQuery: vi.fn(() => ({ data: undefined, isLoading: false })),
}))

vi.mock('react-i18next', () => ({
  // Interpolate only the `count` param (execution-count heading); every
  // other call — including `t(key, defaultValueString)` — resolves to the
  // raw key, as the previous mock did.
  useTranslation: () => ({
    t: (k: string, params?: unknown) =>
      params !== null && typeof params === 'object' && 'count' in params
        ? `${k} (${String((params as Record<string, unknown>).count)})`
        : k,
  }),
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
 *  (MUI ``sx`` values are compiled into classes, not inline styles). */
function sxValue(el: HTMLElement | SVGElement, property: string): string | null {
  // SVG elements expose className as an SVGAnimatedString, not a string.
  const classStr =
    typeof el.className === 'string' ? el.className : el.className.baseVal
  const classes = classStr.split(/\s+/)
  for (const sheet of Array.from(document.styleSheets)) {
    const css = sheet as CSSStyleSheet
    if (!css.cssRules) continue
    for (const rule of Array.from(css.cssRules)) {
      if (!(rule instanceof CSSStyleRule)) continue
      const selector = rule.selectorText ?? ''
      if (!classes.some((c: string) => selector === `.${c}`)) continue
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

  it('renders the dot grid on the STAGE so it covers the whole canvas in the empty state', () => {
    renderCanvas({ topology: mkTopology([]) })
    const stage = screen.getByTestId('agent-runtime-map-canvas')
    expect(sxValue(stage, 'background-image')).toContain('radial-gradient')
    expect(sxValue(stage, 'background-size')).toBe('22px 22px')
  })

  it('keeps the world layer transparent so the stage grid shows through beyond content', () => {
    renderCanvas({ topology: mkTopology([mkNode()]) })
    const world = screen.getByTestId('agent-runtime-map-canvas')
      .firstElementChild as HTMLElement
    expect(sxValue(world, 'background-image')).toBeNull()
    expect(sxValue(world, 'background-color')).toBeNull()
  })

  it('renders the hub full canvas height on a zero-agent load from the first paint', () => {
    renderCanvas({ topology: mkTopology([]) })

    // The full map renders (not a bare placeholder): the hub is a
    // full-height fixture pinned near the right edge of the 1000x700 stage.
    const hub = screen.getByTestId('communication-hub-node')
    const left = parseInt(sxValue(hub, 'left') ?? '', 10)
    const width = parseInt(sxValue(hub, 'width') ?? '', 10)
    const height = parseInt(sxValue(hub, 'height') ?? '', 10)
    expect(height).toBeGreaterThanOrEqual(700)
    expect(left).toBeGreaterThan(500)
    expect(left).toBeLessThanOrEqual(1000 - width)
    // …and the empty-state message shows as an overlay on top of it.
    expect(screen.getByTestId('runtime-monitor-empty')).toBeDefined()
    expect(screen.getByText('agents.sessions.runtimeMonitorEmpty')).toBeDefined()
  })

  it('auto-fits a large population below the interactive minimum zoom', async () => {
    const nodes = Array.from({ length: 40 }, (_, i) =>
      mkNode({ session_id: `pop-${i}`, agent_type_name: `Agent ${i}` }),
    )
    renderCanvas({ topology: mkTopology(nodes) })
    await settle()

    // The initial fit is NOT clamped to MIN_ZOOM (25%) — the whole
    // population fits on first load — but never below the relaxed floor.
    const pct = readZoomPct()
    expect(pct).toBeLessThan(25)
    expect(pct).toBeGreaterThanOrEqual(5)
  })

  it('keeps the interactive zoom-out clamp at 25% after a sub-minimum auto-fit', async () => {
    const nodes = Array.from({ length: 40 }, (_, i) =>
      mkNode({ session_id: `pop-${i}`, agent_type_name: `Agent ${i}` }),
    )
    renderCanvas({ topology: mkTopology(nodes) })
    await settle()
    expect(readZoomPct()).toBeLessThan(25)

    // User zoom interactions keep the MIN_ZOOM/MAX_ZOOM clamps intact.
    fireEvent.click(screen.getByRole('button', { name: 'agents.sessions.runtimeMonitorZoomOut' }))
    expect(readZoomPct()).toBe(25)
  })

  it('re-fits when the first non-empty population arrives after an empty load', async () => {
    const view = renderCanvas({ topology: mkTopology([]) })
    await settle()
    const emptyZoom = readZoomPct()

    // Live data arrives: the first non-empty population gets auto-fitted
    // (the empty placeholder fit must not stick).
    const nodes = Array.from({ length: 5 }, (_, i) =>
      mkNode({ session_id: `late-${i}`, agent_type_name: `Agent ${i}` }),
    )
    view.rerender(
      <AgentRuntimeMapCanvas
        topology={mkTopology(nodes)}
        selectedSessionId={null}
        onSelectSession={vi.fn()}
        onOpenIntervention={vi.fn()}
        onTerminateNode={vi.fn()}
        isFullscreen={false}
        onToggleFullscreen={vi.fn()}
      />,
    )
    await settle()
    expect(readZoomPct()).not.toBe(emptyZoom)
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

  it('brightens historical hub routes on HOVER too (agent colour, not grey)', () => {
    const node = mkNode({
      session_id: 'agent-hover',
      agent_type_name: 'Hoverable',
      tool_calls: [
        { tool_name: 'github____latest', mcp_slug: 'github', called_at: '2026-06-01T00:00:05Z' },
        { tool_name: 'github____older', mcp_slug: 'github', called_at: '2026-06-01T00:00:01Z' },
      ],
    })
    const { container } = renderCanvas({ topology: mkTopology([node]) })

    const routesFor = (sid: string) =>
      Array.from(
        container.querySelectorAll(`path[data-route-kind="tool"][data-route-session="${sid}"]`),
      )

    // Before hover: the older call renders grey.
    expect(routesFor('agent-hover').some((p) => p.getAttribute('stroke') === ROUTE_GRAY_HEX)).toBe(
      true,
    )

    fireEvent.mouseEnter(screen.getByRole('button', { name: /Hoverable/ }))

    // After hover: every route of the agent is highlighted in the agent's
    // own colour — the grey historical hub lines brighten like on selection.
    const paths = routesFor('agent-hover')
    expect(paths.length).toBeGreaterThan(0)
    for (const p of paths) {
      expect(p.getAttribute('data-highlighted')).toBe('true')
      expect(p.getAttribute('stroke')).toBe('#E53935')
    }
  })

  it('marks running agents with a spinning execution indicator and a highlight', () => {
    renderCanvas({
      topology: mkTopology([
        mkNode({ session_id: 'run-1', status: 'running', agent_type_name: 'Spinning' }),
        mkNode({ session_id: 'queue-1', status: 'queued', agent_type_name: 'Waiting' }),
        mkNode({ session_id: 'done-1', status: 'completed', kind: 'agent', agent_type_name: 'Finished' }),
      ]),
    })

    // Spinner only on the running tile, driven by the spin keyframes.
    const spinner = screen.getByTestId('running-spinner-run-1')
    expect(sxValue(spinner, 'animation')).toContain('armRunningSpin')
    expect(sxValue(spinner, 'animation')).toContain('infinite')
    expect(screen.queryByTestId('running-spinner-queue-1')).toBeNull()
    expect(screen.queryByTestId('running-spinner-done-1')).toBeNull()

    // The running tile is highlighted (blue tint + data-running cue);
    // non-running tiles stay plain without the cue.
    const runningTile = screen.getByRole('button', { name: /Spinning/ })
    expect(runningTile.getAttribute('data-running')).toBe('true')
    expect(sxValue(runningTile, 'background-color')).toBe('#F0F7FF')

    const queuedTile = screen.getByRole('button', { name: /Waiting/ })
    expect(queuedTile.getAttribute('data-running')).toBeNull()
    expect(sxValue(queuedTile, 'background-color')).toBe('#FFFFFF')
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

  // ── Trigger entities (leftmost column) + latest-tool tile line ───────────────

  it('renders a person entity for a user-triggered root with a trigger edge to the tile', () => {
    renderCanvas({
      topology: mkTopology([
        mkNode({
          session_id: 'trigger-1',
          trigger_source: 'user',
          trigger_source_label: 'Alice Operator',
          trigger_user_label: 'Alice Operator',
        }),
      ]),
    })
    expect(screen.getByTestId('trigger-entity-person:Alice Operator')).toBeDefined()
    expect(screen.getByTestId('trigger-edge-person:Alice Operator->trigger-1')).toBeDefined()
    // The tile itself no longer carries the inline trigger line.
    expect(screen.queryByTestId('trigger-source-trigger-1')).toBeNull()
  })

  it('renders a schedule entity with its creator and person→schedule edge', () => {
    renderCanvas({
      topology: mkTopology([
        mkNode({
          session_id: 'sched-run-1',
          trigger_source: 'schedule',
          trigger_source_label: 'hourly-run-query',
          trigger_user_label: 'Tom',
        }),
        mkNode({
          session_id: 'direct-1',
          trigger_source: 'user',
          trigger_source_label: 'Tom',
          trigger_user_label: 'Tom',
        }),
      ]),
    })
    expect(screen.getByTestId('trigger-entity-schedule:hourly-run-query')).toBeDefined()
    expect(screen.getByText('hourly-run-query')).toBeDefined()
    // Creator caption on the schedule card (i18n mock renders the raw key).
    expect(screen.getByText('agents.sessions.runtimeMonitorScheduleCreator')).toBeDefined()
    // person → schedule edge (dashed connector).
    expect(screen.getByTestId('trigger-edge-person:Tom->schedule:hourly-run-query')).toBeDefined()
    // schedule → its execution edge.
    expect(screen.getByTestId('trigger-edge-schedule:hourly-run-query->sched-run-1')).toBeDefined()
    // person → directly triggered execution edge.
    expect(screen.getByTestId('trigger-edge-person:Tom->direct-1')).toBeDefined()
  })

  it('gives each trigger entity its own line colour', () => {
    renderCanvas({
      topology: mkTopology([
        mkNode({
          session_id: 'ent-a',
          trigger_source: 'user',
          trigger_source_label: 'Alice',
          trigger_user_label: 'Alice',
        }),
        mkNode({
          session_id: 'ent-b',
          trigger_source: 'user',
          trigger_source_label: 'Bob',
          trigger_user_label: 'Bob',
        }),
      ]),
    })
    const aliceEdge = screen.getByTestId('trigger-edge-person:Alice->ent-a')
    const bobEdge = screen.getByTestId('trigger-edge-person:Bob->ent-b')
    expect(aliceEdge.getAttribute('stroke')).toBeTruthy()
    expect(bobEdge.getAttribute('stroke')).toBeTruthy()
    expect(aliceEdge.getAttribute('stroke')).not.toBe(bobEdge.getAttribute('stroke'))
  })

  it('clicking a person entity highlights it, its lines, its schedules and its executions', () => {
    renderCanvas({
      topology: mkTopology([
        mkNode({
          session_id: 'tom-run-1',
          agent_type_name: 'Run One',
          trigger_source: 'user',
          trigger_source_label: 'Tom',
          trigger_user_label: 'Tom',
        }),
        mkNode({
          session_id: 'sched-run-1',
          agent_type_name: 'Scheduled Run',
          trigger_source: 'schedule',
          trigger_source_label: 'hourly-run',
          trigger_user_label: 'Tom',
        }),
      ]),
    })

    fireEvent.click(screen.getByTestId('trigger-entity-person:Tom'))

    // The person card is highlighted, plus the schedule on the other end.
    const personCard = screen.getByTestId('trigger-entity-person:Tom')
    expect(personCard.getAttribute('data-highlighted')).toBe('true')
    const schedCard = screen.getByTestId('trigger-entity-schedule:hourly-run')
    expect(schedCard.getAttribute('data-highlighted')).toBe('true')
    // All Tom-related lines are highlighted (both executions + the schedule).
    expect(screen.getByTestId('trigger-edge-person:Tom->tom-run-1').getAttribute('data-highlighted')).toBe('true')
    expect(screen.getByTestId('trigger-edge-person:Tom->schedule:hourly-run').getAttribute('data-highlighted')).toBe('true')
    expect(screen.getByTestId('trigger-edge-schedule:hourly-run->sched-run-1').getAttribute('data-highlighted')).toBe('true')
    // Related executions light up too (entity colour border via inline style).
    expect(screen.getByTestId('triggered-at-tom-run-1')).toBeDefined()
  })

  it('clicking a schedule entity highlights its creator person and its execution', () => {
    renderCanvas({
      topology: mkTopology([
        mkNode({
          session_id: 'sched-run-2',
          trigger_source: 'schedule',
          trigger_source_label: 'nightly',
          trigger_user_label: 'Erin',
        }),
      ]),
    })
    fireEvent.click(screen.getByTestId('trigger-entity-schedule:nightly'))
    expect(screen.getByTestId('trigger-entity-schedule:nightly').getAttribute('data-highlighted')).toBe('true')
    expect(screen.getByTestId('trigger-edge-schedule:nightly->sched-run-2').getAttribute('data-highlighted')).toBe('true')
  })

  it('hovering a person entity highlights the whole downstream topology', () => {
    renderCanvas({
      topology: mkTopology([
        mkNode({
          session_id: 'hv-1',
          agent_type_name: 'HV Agent',
          trigger_source: 'user',
          trigger_source_label: 'Alice',
          trigger_user_label: 'Alice',
          tool_calls: [
            { tool_name: 'github____list_prs', mcp_slug: 'github', called_at: '2026-06-01T00:00:05Z', route_type: 'mcp' },
          ],
        }),
      ]),
    })
    // No focus yet — nothing highlighted.
    expect(screen.getByTestId('trigger-edge-person:Alice->hv-1').getAttribute('data-highlighted')).toBeNull()
    fireEvent.mouseEnter(screen.getByTestId('trigger-entity-person:Alice'))
    // Trigger edge, execution, MCP node and tool chip all light up.
    expect(screen.getByTestId('trigger-edge-person:Alice->hv-1').getAttribute('data-highlighted')).toBe('true')
    expect(screen.getByTestId('mcp-server-node-github').getAttribute('data-highlighted')).toBe('true')
    expect(screen.getByTestId('tool-chip-github-list_prs').getAttribute('data-highlighted')).toBe('true')
    // Hover out clears the focus.
    fireEvent.mouseLeave(screen.getByTestId('trigger-entity-person:Alice'))
    expect(screen.getByTestId('trigger-edge-person:Alice->hv-1').getAttribute('data-highlighted')).toBeNull()
  })

  it('clicking a tool chip highlights its MCP, the agents that called it and their trigger', () => {
    renderCanvas({
      topology: mkTopology([
        mkNode({
          session_id: 'caller-1',
          agent_type_name: 'Caller',
          trigger_source: 'user',
          trigger_source_label: 'Bob',
          trigger_user_label: 'Bob',
          tool_calls: [
            { tool_name: 'github____list_prs', mcp_slug: 'github', called_at: '2026-06-01T00:00:05Z', route_type: 'mcp' },
          ],
        }),
        mkNode({
          session_id: 'other-1',
          agent_type_name: 'Other',
          trigger_source: 'user',
          trigger_source_label: 'Erin',
          trigger_user_label: 'Erin',
          tool_calls: [
            { tool_name: 'slack____post', mcp_slug: 'slack', called_at: '2026-06-01T00:00:06Z', route_type: 'mcp' },
          ],
        }),
      ]),
    })
    fireEvent.click(screen.getByTestId('tool-chip-github-list_prs'))
    // The MCP and the caller's trigger light up…
    expect(screen.getByTestId('mcp-server-node-github').getAttribute('data-highlighted')).toBe('true')
    expect(screen.getByTestId('trigger-entity-person:Bob').getAttribute('data-highlighted')).toBe('true')
    expect(screen.getByTestId('trigger-edge-person:Bob->caller-1').getAttribute('data-highlighted')).toBe('true')
    // …while the unrelated MCP stays dimmed.
    expect(screen.getByTestId('mcp-server-node-slack').getAttribute('data-dimmed')).toBe('true')
  })

  it('renders the triggered-at datetime on the tile', () => {
    renderCanvas({
      topology: mkTopology([
        mkNode({ session_id: 'when-1', created_at: '2026-09-04T08:30:00Z' }),
      ]),
    })
    expect(screen.getByTestId('triggered-at-when-1')).toBeDefined()
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

  // ── Trigger entity detail bubble (Phase 13) ───────────────────────────────

  it('clicking a person card opens the detail bubble with name, count and execution rows', () => {
    renderCanvas({
      topology: mkTopology([
        mkNode({
          session_id: 'p-run-1',
          agent_type_name: 'Alpha Agent',
          status: 'running',
          trigger_source: 'user',
          trigger_source_label: 'Alice',
          trigger_user_label: 'Alice',
        }),
        mkNode({
          session_id: 'p-run-2',
          agent_type_name: 'Beta Agent',
          status: 'completed',
          trigger_source: 'user',
          trigger_source_label: 'Alice',
          trigger_user_label: 'Alice',
        }),
        mkNode({
          session_id: 'p-run-3',
          agent_type_name: 'Gamma Agent',
          status: 'running',
          trigger_source: 'user',
          trigger_source_label: 'Bob',
          trigger_user_label: 'Bob',
        }),
      ]),
    })

    // Closed until an entity is clicked.
    expect(screen.queryByTestId('trigger-detail-bubble')).toBeNull()

    fireEvent.click(screen.getByTestId('trigger-entity-person:Alice'))

    const bubble = screen.getByTestId('trigger-detail-bubble')
    expect(bubble.getAttribute('data-trigger-entity')).toBe('person:Alice')
    // Name header + person kind caption.
    expect(within(bubble).getByText('Alice')).toBeDefined()
    expect(within(bubble).getByText('agents.sessions.runtimeMonitorTriggerPersonKind')).toBeDefined()
    // Execution count reflects ONLY this entity's executions…
    expect(
      within(bubble).getByText('agents.sessions.runtimeMonitorTriggerDetailExecutions (2)'),
    ).toBeDefined()
    // …and the rows list exactly those sessions.
    expect(within(bubble).getByTestId('trigger-detail-execution-p-run-1')).toBeDefined()
    expect(within(bubble).getByTestId('trigger-detail-execution-p-run-2')).toBeDefined()
    expect(within(bubble).queryByTestId('trigger-detail-execution-p-run-3')).toBeNull()
    // Rows carry the agent type label + a status chip.
    expect(within(bubble).getByText('Alpha Agent')).toBeDefined()
    expect(within(bubble).getByText('agents.sessions.statusRunning')).toBeDefined()
    expect(within(bubble).getByText('agents.sessions.statusCompleted')).toBeDefined()
  })

  it('clicking an execution row selects that session and dismisses the bubble', () => {
    const onSelectSession = vi.fn()
    renderCanvas({
      topology: mkTopology([
        mkNode({
          session_id: 'row-1',
          agent_type_name: 'Row Agent',
          status: 'running',
          trigger_source: 'user',
          trigger_source_label: 'Alice',
          trigger_user_label: 'Alice',
        }),
      ]),
      onSelectSession,
    })

    fireEvent.click(screen.getByTestId('trigger-entity-person:Alice'))
    expect(screen.getByTestId('trigger-detail-bubble')).toBeDefined()

    fireEvent.click(screen.getByTestId('trigger-detail-execution-row-1'))
    // The row selection is routed to the page (which owns the selection)…
    expect(onSelectSession).toHaveBeenLastCalledWith('row-1')
    // …and the trigger bubble is dismissed.
    expect(screen.queryByTestId('trigger-detail-bubble')).toBeNull()
  })

  it('re-clicking the entity toggles the bubble; clicking another entity switches it', () => {
    renderCanvas({
      topology: mkTopology([
        mkNode({
          session_id: 'alice-1',
          trigger_source: 'user',
          trigger_source_label: 'Alice',
          trigger_user_label: 'Alice',
        }),
        mkNode({
          session_id: 'bob-1',
          trigger_source: 'user',
          trigger_source_label: 'Bob',
          trigger_user_label: 'Bob',
        }),
      ]),
    })

    fireEvent.click(screen.getByTestId('trigger-entity-person:Alice'))
    expect(screen.getByTestId('trigger-detail-bubble').getAttribute('data-trigger-entity')).toBe(
      'person:Alice',
    )

    // Same entity again → toggle closed.
    fireEvent.click(screen.getByTestId('trigger-entity-person:Alice'))
    expect(screen.queryByTestId('trigger-detail-bubble')).toBeNull()

    // A different entity → the bubble opens for it.
    fireEvent.click(screen.getByTestId('trigger-entity-person:Bob'))
    expect(screen.getByTestId('trigger-detail-bubble').getAttribute('data-trigger-entity')).toBe(
      'person:Bob',
    )
  })

  it('dismisses the trigger bubble via its close button', () => {
    renderCanvas({
      topology: mkTopology([
        mkNode({
          session_id: 'dismiss-1',
          trigger_source: 'user',
          trigger_source_label: 'Alice',
          trigger_user_label: 'Alice',
        }),
      ]),
    })
    fireEvent.click(screen.getByTestId('trigger-entity-person:Alice'))
    expect(screen.getByTestId('trigger-detail-bubble')).toBeDefined()

    fireEvent.click(screen.getByTestId('trigger-detail-bubble-close'))
    expect(screen.queryByTestId('trigger-detail-bubble')).toBeNull()
  })

  it('dismisses the trigger bubble on Escape', () => {
    renderCanvas({
      topology: mkTopology([
        mkNode({
          session_id: 'esc-1',
          trigger_source: 'user',
          trigger_source_label: 'Alice',
          trigger_user_label: 'Alice',
        }),
      ]),
    })
    fireEvent.click(screen.getByTestId('trigger-entity-person:Alice'))
    expect(screen.getByTestId('trigger-detail-bubble')).toBeDefined()

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByTestId('trigger-detail-bubble')).toBeNull()
  })

  it('clicking an agent tile dismisses the trigger bubble and selects the agent', () => {
    const onSelectSession = vi.fn()
    renderCanvas({
      topology: mkTopology([
        mkNode({
          session_id: 'tile-1',
          agent_type_name: 'Tile Agent',
          trigger_source: 'user',
          trigger_source_label: 'Alice',
          trigger_user_label: 'Alice',
        }),
      ]),
      onSelectSession,
    })

    fireEvent.click(screen.getByTestId('trigger-entity-person:Alice'))
    expect(screen.getByTestId('trigger-detail-bubble')).toBeDefined()

    // The bubble's execution row shares the tile's accessible name — pick
    // the map TILE via its container attribute.
    const tile = screen
      .getAllByRole('button', { name: /Tile Agent/ })
      .find((el) => el.getAttribute('data-container') === 'tile-1') as HTMLElement
    fireEvent.click(tile)
    expect(onSelectSession).toHaveBeenLastCalledWith('tile-1')
    expect(screen.queryByTestId('trigger-detail-bubble')).toBeNull()
  })

  it('schedule bubble shows the creator row only when the creator is known', () => {
    // Known creator → schedule kind caption + creator row.
    const known = renderCanvas({
      topology: mkTopology([
        mkNode({
          session_id: 'sch-1',
          agent_type_name: 'Nightly Agent',
          status: 'completed',
          trigger_source: 'schedule',
          trigger_source_label: 'nightly',
          trigger_user_label: 'Tom',
        }),
      ]),
    })
    fireEvent.click(screen.getByTestId('trigger-entity-schedule:nightly'))
    const bubble = screen.getByTestId('trigger-detail-bubble')
    expect(within(bubble).getByText('agents.sessions.runtimeMonitorTriggerScheduleKind')).toBeDefined()
    expect(within(bubble).getByTestId('trigger-detail-creator')).toBeDefined()
    expect(within(bubble).getByText('Tom')).toBeDefined()
    // A schedule bubble is never labelled as a person.
    expect(within(bubble).queryByText('agents.sessions.runtimeMonitorTriggerPersonKind')).toBeNull()
    known.unmount()

    // Unknown creator (Phase 13: backend no longer substitutes the schedule
    // name) → no creator caption on the card and no creator row in the bubble.
    renderCanvas({
      topology: mkTopology([
        mkNode({
          session_id: 'sch-2',
          agent_type_name: 'Nightly Agent',
          status: 'completed',
          trigger_source: 'schedule',
          trigger_source_label: 'nightly',
          trigger_user_label: null,
        }),
      ]),
    })
    fireEvent.click(screen.getByTestId('trigger-entity-schedule:nightly'))
    expect(screen.getByTestId('trigger-detail-bubble')).toBeDefined()
    expect(screen.queryByTestId('trigger-detail-creator')).toBeNull()
    expect(screen.queryByText('agents.sessions.runtimeMonitorScheduleCreator')).toBeNull()
  })

  it('person bubble counts executions directly AND via their schedules', () => {
    renderCanvas({
      topology: mkTopology([
        mkNode({
          session_id: 'direct-run',
          agent_type_name: 'Direct Agent',
          status: 'running',
          trigger_source: 'user',
          trigger_source_label: 'Tom',
          trigger_user_label: 'Tom',
        }),
        mkNode({
          session_id: 'sched-run',
          agent_type_name: 'Scheduled Agent',
          status: 'completed',
          trigger_source: 'schedule',
          trigger_source_label: 'hourly-run',
          trigger_user_label: 'Tom',
        }),
      ]),
    })

    // The schedule entity sees only its own execution.
    fireEvent.click(screen.getByTestId('trigger-entity-schedule:hourly-run'))
    const scheduleBubble = screen.getByTestId('trigger-detail-bubble')
    expect(
      within(scheduleBubble).getByText('agents.sessions.runtimeMonitorTriggerDetailExecutions (1)'),
    ).toBeDefined()
    expect(within(scheduleBubble).getByTestId('trigger-detail-execution-sched-run')).toBeDefined()
    fireEvent.click(screen.getByTestId('trigger-detail-bubble-close'))

    // The creator person sees BOTH the direct execution and the one via
    // their schedule (person → schedule → execution focus-graph walk).
    fireEvent.click(screen.getByTestId('trigger-entity-person:Tom'))
    const personBubble = screen.getByTestId('trigger-detail-bubble')
    expect(
      within(personBubble).getByText('agents.sessions.runtimeMonitorTriggerDetailExecutions (2)'),
    ).toBeDefined()
    expect(within(personBubble).getByTestId('trigger-detail-execution-direct-run')).toBeDefined()
    expect(within(personBubble).getByTestId('trigger-detail-execution-sched-run')).toBeDefined()
  })

  it('hides the trigger bubble when a filter removes its executions and it does not reappear after reset', () => {
    renderCanvas({
      topology: mkTopology([
        mkNode({
          session_id: 'filt-1',
          status: 'running',
          trigger_source: 'user',
          trigger_source_label: 'Alice',
          trigger_user_label: 'Alice',
        }),
      ]),
    })

    fireEvent.click(screen.getByTestId('trigger-entity-person:Alice'))
    expect(screen.getByTestId('trigger-detail-bubble')).toBeDefined()

    // Hide the execution's status via the legend chip → the entity loses its
    // only execution and the bubble disappears.
    clickLegendChip('agents.sessions.statusRunning')
    expect(screen.queryByTestId('trigger-detail-bubble')).toBeNull()

    // Restoring the population must NOT resurrect the dismissed bubble.
    fireEvent.click(screen.getByTestId('runtime-monitor-reset-filters'))
    expect(screen.getByRole('button', { name: /Test Agent/ })).toBeDefined()
    expect(screen.queryByTestId('trigger-detail-bubble')).toBeNull()
  })
})

const ROUTE_GRAY_HEX = '#C7D0D8'
