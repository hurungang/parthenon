import { expect, test } from '@playwright/test'
import { FAKE_TOKEN, mockApiCatchAllProxyAware, standardSetup } from './_helpers'

/**
 * Agent Runtime Monitor — full map flow (mock-first).
 *
 * Covers the interactive map canvas: auto-fit, zoom, pan, fullscreen toggle,
 * per-delegation-tree team containers, delegation connectors, orthogonal
 * tool-call routing (hub → MCP → tool chips, incl. the synthetic "System
 * Tools" node), and the human-intervention alert path (alert icon on a
 * sleeping `needs_intervention` node → the reused `InterveneResponseDialog`).
 * A single real-backend smoke variant (no mocks) is included at the bottom
 * and skips cleanly when the backend is unreachable.
 */

interface MockNode {
  session_id: string
  agent_type_id: string
  agent_type_name: string
  status: string
  depth_from_root: number
  parent_session_id: string | null
  kind: 'agent' | 'conversation' | 'instance'
  needs_intervention?: boolean
  title?: string | null
  trigger_source?: 'user' | 'schedule' | 'delegated' | 'unknown'
  trigger_source_label?: string | null
  /**
   * Creator-attribution contract (Phase 13): the resolved HUMAN for the
   * trigger — the triggering user, the schedule creator (for schedule
   * sources), or the inherited delegation source. `null`/absent when
   * unknown; the schedule name must never be sent here.
   */
  trigger_user_label?: string | null
  tool_calls?: Array<{
    tool_name: string
    mcp_slug: string
    route_type?: 'system' | 'mcp' | 'a2a' | null
    called_at: string | null
  }>
}

function mkNode(overrides: Partial<MockNode> = {}): MockNode {
  return {
    session_id: 'sess-1',
    agent_type_id: 'at-1',
    agent_type_name: 'Test Agent',
    status: 'running',
    depth_from_root: 0,
    parent_session_id: null,
    kind: 'agent',
    needs_intervention: false,
    ...overrides,
  }
}

function mkTopology(nodes: MockNode[], edges: unknown[] = []) {
  return {
    nodes,
    edges,
    root_session_ids: nodes.map((n) => n.session_id),
  }
}

function fullNode(node: MockNode) {
  return {
    ...node,
    started_at: null,
    created_at: '2026-06-01T00:00:00Z',
    termination_category: null,
  }
}

// The Vite dev/preview server compiles the route on first hit; under load this
// can exceed Playwright's 30s default. Give the map page generous headroom.
test.describe.configure({ timeout: 90_000 })

const MOCK_AGENT_TYPE = {
  id: 'at-1',
  name: 'Shared Type',
  input_type: 'typed',
  output_type: 'auto',
  is_active: true,
  guardrail_max_iterations: 25,
  guardrail_max_delegation_depth: 3,
  guardrail_token_budget: 100000,
  created_at: '2026-06-01T00:00:00Z',
  updated_at: '2026-06-01T00:00:00Z',
}

test.describe('Agent Runtime Monitor', () => {
  test.beforeEach(async ({ page }) => {
    // Lowest-priority catch-all FIRST (Playwright resolves handlers
    // last-registered-first) so standardSetup + test mocks always win.
    await mockApiCatchAllProxyAware(page)
    await page.addInitScript((token: string) => {
      localStorage.setItem('access_token', token)
    }, FAKE_TOKEN)
    await standardSetup(page)
  })

  test('auto-fits the map and groups each delegation tree into a team container', async ({
    page,
  }) => {
    // Grouping is per delegation TREE (one container per tree, one row each):
    //   tree t-1: root "Main Agent" (depth 0) + two delegated children (depth 1)
    //   tree o-1: a single standalone agent gets its own container
    const nodes = [
      mkNode({ session_id: 't-1', agent_type_name: 'Main Agent', depth_from_root: 0 }),
      mkNode({
        session_id: 't-2',
        agent_type_name: 'Main Agent',
        parent_session_id: 't-1',
        depth_from_root: 1,
      }),
      mkNode({
        session_id: 't-3',
        agent_type_name: 'Main Agent',
        parent_session_id: 't-1',
        depth_from_root: 1,
      }),
      mkNode({ session_id: 'o-1', agent_type_name: 'Other Type', depth_from_root: 0 }),
    ]
    await page.route('**/api/v1/agents/runtime/topology**', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify(
          mkTopology(nodes.map(fullNode), [
            { parent_session_id: 't-1', child_session_id: 't-2', depth_from_root: 1 },
            { parent_session_id: 't-1', child_session_id: 't-3', depth_from_root: 1 },
          ]),
        ),
      }),
    )
    await page.route('**/api/v1/agents/types/**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_AGENT_TYPE) }),
    )

    await page.goto('/agents/runtime-control')
    await page.waitForLoadState('load')

    if (page.url().includes('/login')) {
      test.skip()
      return
    }

    await expect(page.getByTestId('agent-runtime-map-canvas')).toBeVisible()

    // One team container per delegation tree, named after its root agent type.
    const teamContainer = page.getByTestId('team-container-t-1')
    await expect(teamContainer).toBeVisible()
    await expect(page.getByTestId('team-container-o-1')).toBeVisible()

    // All three members of the tree carry the owning container id.
    await expect(page.locator('[data-container="t-1"]')).toHaveCount(3)
    await expect(page.locator('[data-container="o-1"]')).toHaveCount(1)

    // Delegation depth maps to the container column: root in col 0,
    // depth-1 children in col 1.
    await expect(page.locator('[data-container="t-1"][data-depth="0"]')).toHaveCount(1)
    await expect(page.locator('[data-container="t-1"][data-depth="1"]')).toHaveCount(2)

    // The multi-member container shows a count chip ("3"); the single-agent
    // container shows none.
    await expect(teamContainer.getByText('3', { exact: true })).toBeVisible()

    // Both agent-type labels are visible (container label + tile labels).
    await expect(page.getByText('Main Agent').first()).toBeVisible()
    await expect(page.getByText('Other Type').first()).toBeVisible()
  })

  test('zooms in and out via the toolbar', async ({ page }) => {
    const nodes = [
      mkNode({ session_id: 'z-1', agent_type_name: 'Shared Type' }),
      mkNode({ session_id: 'z-2', agent_type_name: 'Shared Type' }),
      mkNode({ session_id: 'z-3', agent_type_name: 'Shared Type' }),
      mkNode({ session_id: 'z-4', agent_type_name: 'Other Type' }),
      mkNode({ session_id: 'z-5', agent_type_name: 'Other Type' }),
    ]
    await page.route('**/api/v1/agents/runtime/topology**', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify(mkTopology(nodes.map(fullNode))),
      }),
    )

    await page.goto('/agents/runtime-control')
    await page.waitForLoadState('load')

    if (page.url().includes('/login')) {
      test.skip()
      return
    }

    await expect(page.getByTestId('agent-runtime-map-canvas')).toBeVisible()

    const zoomLabel = page.getByText(/^\d+%$/)
    await expect(zoomLabel).toBeVisible()

    const readZoom = async () =>
      parseInt((await zoomLabel.textContent())?.replace('%', '') ?? '0', 10)

    // Wait for auto-fit to settle, then record the baseline.
    await page.waitForTimeout(150)
    const baseline = await readZoom()

    await page.getByRole('button', { name: 'Zoom in' }).click()
    // Poll instead of fixed sleeps — the state update can lag under
    // dev-server load and a plain waitForTimeout(50) reads stale values.
    await expect.poll(readZoom, { timeout: 5_000 }).toBeGreaterThan(baseline)
    const zoomedIn = await readZoom()

    await page.getByRole('button', { name: 'Zoom out' }).click()
    await expect.poll(readZoom, { timeout: 5_000 }).toBeLessThan(zoomedIn)
  })

  test('pans the canvas via drag', async ({ page }) => {
    const nodes = [
      mkNode({ session_id: 'p-1', agent_type_name: 'Shared Type' }),
      mkNode({ session_id: 'p-2', agent_type_name: 'Shared Type' }),
      mkNode({ session_id: 'p-3', agent_type_name: 'Shared Type' }),
    ]
    await page.route('**/api/v1/agents/runtime/topology**', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify(mkTopology(nodes.map(fullNode))),
      }),
    )

    await page.goto('/agents/runtime-control')
    await page.waitForLoadState('load')

    if (page.url().includes('/login')) {
      test.skip()
      return
    }

    const canvas = page.getByTestId('agent-runtime-map-canvas')
    await expect(canvas).toBeVisible()

    const world = canvas.locator('div').first()
    const transformBefore = await world.evaluate(
      (el) => getComputedStyle(el).transform,
    )

    // Drag from the empty bottom-left corner — the toolbar floats at the
    // top-right and the filter popover button at the bottom-right, so the
    // bottom-left corner is the only chrome-free canvas region.
    const box = (await canvas.boundingBox())!
    await page.mouse.move(box.x + 40, box.y + box.height - 40)
    await page.mouse.down()
    await page.mouse.move(box.x + 40 + 90, box.y + box.height - 40 - 40, {
      steps: 5,
    })
    await page.mouse.up()

    const transformAfter = await world.evaluate(
      (el) => getComputedStyle(el).transform,
    )
    expect(transformAfter).not.toBe(transformBefore)
  })

  test('toggles fullscreen and restores', async ({ page }) => {
    await page.route('**/api/v1/agents/runtime/topology**', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify(mkTopology([fullNode(mkNode())])),
      }),
    )

    await page.goto('/agents/runtime-control')
    await page.waitForLoadState('load')

    if (page.url().includes('/login')) {
      test.skip()
      return
    }

    await expect(page.getByTestId('agent-runtime-map-canvas')).toBeVisible()

    await page.getByTestId('runtime-monitor-fullscreen').click()
    await expect(
      page.getByRole('button', { name: 'Exit fullscreen' }),
    ).toBeVisible()

    await page.getByTestId('runtime-monitor-fullscreen').click()
    await expect(page.getByRole('button', { name: 'Maximise' })).toBeVisible()
  })

  test('renders a delegation connector between parent and child', async ({ page }) => {
    const parent = mkNode({ session_id: 'parent-1', agent_type_name: 'Parent' })
    const child = mkNode({
      session_id: 'child-1',
      agent_type_name: 'Child',
      parent_session_id: 'parent-1',
      depth_from_root: 1,
    })
    await page.route('**/api/v1/agents/runtime/topology**', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify(
          mkTopology([fullNode(parent), fullNode(child)], [
            {
              parent_session_id: 'parent-1',
              child_session_id: 'child-1',
              depth_from_root: 1,
            },
          ]),
        ),
      }),
    )

    await page.goto('/agents/runtime-control')
    await page.waitForLoadState('load')

    if (page.url().includes('/login')) {
      test.skip()
      return
    }

    await expect(page.getByTestId('agent-runtime-map-canvas')).toBeVisible()
    await expect(page.locator('svg path[marker-end]')).toHaveCount(1)
  })

  test('surfaces a sleeping agent awaiting intervention and opens the intervention dialog', async ({
    page,
  }) => {
    const sleepNode = mkNode({
      session_id: 'sess-awaiting-intervention',
      agent_type_name: 'Support Agent',
      status: 'sleep',
      kind: 'conversation',
      needs_intervention: true,
      title: 'Pending approval conversation',
    })
    await page.route('**/api/v1/agents/runtime/topology**', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify(mkTopology([fullNode(sleepNode)])),
      }),
    )
    await page.route(
      '**/api/v1/conversations/sess-awaiting-intervention/interventions/pending',
      (route) =>
        route.fulfill({
          status: 200,
          body: JSON.stringify([
            {
              id: 'ireq-1',
              agent_session_id: 'backing-job-1',
              agent_type_id: 'at-support',
              conversation_session_id: 'sess-awaiting-intervention',
              intervention_type: 'approval',
              reason: 'Operator must approve this action',
              status: 'pending',
              delegation_depth: 0,
              created_at: '2026-06-01T00:00:00Z',
            },
          ]),
        }),
    )

    await page.goto('/agents/runtime-control')
    await page.waitForLoadState('load')

    if (page.url().includes('/login')) {
      test.skip()
      return
    }

    await expect(page.getByTestId('agent-runtime-map-canvas')).toBeVisible()

    // The sleeping agent awaiting intervention is visible with an alert icon.
    const alertIcon = page.getByTestId('intervention-alert-sess-awaiting-intervention')
    await expect(alertIcon).toBeVisible()

    await alertIcon.click()

    // The existing human-intervention dialog opens for that session.
    await expect(
      page.getByText('Human Intervention Required').first(),
    ).toBeVisible()
    await expect(page.getByText('Operator must approve this action')).toBeVisible()
  })

  test('shows a cross-type parent/child delegation connector', async ({ page }) => {
    const parent = mkNode({ session_id: 'parent-x', agent_type_name: 'Parent Type' })
    const child = mkNode({
      session_id: 'child-x',
      agent_type_name: 'Child Type',
      parent_session_id: 'parent-x',
      depth_from_root: 1,
    })
    await page.route('**/api/v1/agents/runtime/topology**', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify(
          mkTopology([fullNode(parent), fullNode(child)], [
            {
              parent_session_id: 'parent-x',
              child_session_id: 'child-x',
              depth_from_root: 1,
            },
          ]),
        ),
      }),
    )

    await page.goto('/agents/runtime-control')
    await page.waitForLoadState('load')

    if (page.url().includes('/login')) {
      test.skip()
      return
    }

    await expect(page.getByTestId('agent-runtime-map-canvas')).toBeVisible()
    // Cross-type parent and child remain adjacent and joined by a connector.
    await expect(page.locator('svg path[marker-end]')).toHaveCount(1)
  })

  test('recovers from the filtered-empty state via "Reset filters"', async ({ page }) => {
    const nodes = [
      mkNode({ session_id: 'r-1', agent_type_name: 'Type A' }),
      mkNode({ session_id: 'r-2', agent_type_name: 'Type A' }),
    ]
    await page.route('**/api/v1/agents/runtime/topology**', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify(mkTopology(nodes.map(fullNode))),
      }),
    )

    await page.goto('/agents/runtime-control')
    await page.waitForLoadState('load')

    if (page.url().includes('/login')) {
      test.skip()
      return
    }

    await expect(page.getByTestId('agent-runtime-map-canvas')).toBeVisible()

    // Expand the filter popover (floating button, bottom-right) — the legend
    // chips only exist in the DOM while the panel is open. Hover opens the
    // panel; a click would *toggle* it shut again because the hover already
    // opened it.
    await page.getByTestId('runtime-monitor-filter-button').hover()
    await expect(page.getByTestId('runtime-monitor-filter-panel')).toBeVisible()

    // Hide every agent-kind node via the "Agent" kind legend chip (which
    // carries an aria-pressed attribute, unlike the page heading/tiles).
    const agentChip = page.locator('[aria-pressed]', { hasText: 'Agent' }).first()
    await expect(agentChip).toBeVisible()
    await agentChip.click()

    const resetButton = page.getByTestId('runtime-monitor-reset-filters')
    await expect(resetButton).toBeVisible()

    await resetButton.click()

    // Population restored without a reload.
    await expect(page.getByTestId('runtime-monitor-filtered-empty')).toHaveCount(0)
    await expect(page.getByRole('button', { name: /Type A/ }).first()).toBeVisible()
  })

  test('shows trigger provenance as a person entity wired to the execution', async ({ page }) => {
    const node = mkNode({
      session_id: 'prove-1',
      agent_type_name: 'Provenance Agent',
      trigger_source: 'user',
      trigger_source_label: 'Alice Operator',
      trigger_user_label: 'Alice Operator',
    })
    await page.route('**/api/v1/agents/runtime/topology**', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify(mkTopology([fullNode(node)])),
      }),
    )
    await page.route('**/api/v1/agents/types/**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_AGENT_TYPE) }),
    )

    await page.goto('/agents/runtime-control')
    await page.waitForLoadState('load')

    if (page.url().includes('/login')) {
      test.skip()
      return
    }

    await expect(page.getByTestId('agent-runtime-map-canvas')).toBeVisible()

    // The person entity lives in the leftmost column with a trigger edge
    // to the execution it triggered; the tile has no inline trigger line.
    await expect(page.getByTestId('trigger-entity-person:Alice Operator')).toBeVisible()
    await expect(page.getByTestId('trigger-edge-person:Alice Operator->prove-1')).toBeVisible()
    await expect(page.getByTestId('triggered-at-prove-1')).toBeVisible()
    await expect(page.getByTestId('trigger-source-prove-1')).toHaveCount(0)

    // Select the node → the detail bubble shows the trigger source.
    await page.getByRole('button', { name: /Provenance Agent/ }).click()
    await expect(page.getByTestId('agent-detail-trigger-source')).toBeVisible()
    await expect(page.getByText('Alice Operator').first()).toBeVisible()
  })

  test('shows schedule creator attribution and no person line for a null-creator schedule', async ({
    page,
  }) => {
    // Creator-attribution contract (Phase 13): a schedule-triggered node's
    // human is the schedule CREATOR (`trigger_user_label`); a legacy schedule
    // with an unknown creator renders no creator caption and never shows the
    // schedule name as a person.
    const nodes = [
      mkNode({
        session_id: 'sched-1',
        agent_type_name: 'Cleanup Agent',
        trigger_source: 'schedule',
        trigger_source_label: 'nightly-cleanup',
        trigger_user_label: 'Alice Operator',
      }),
      mkNode({
        session_id: 'sched-2',
        agent_type_name: 'Sync Agent',
        trigger_source: 'schedule',
        trigger_source_label: 'legacy-sync',
        trigger_user_label: null,
      }),
    ]
    await page.route('**/api/v1/agents/runtime/topology**', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify(mkTopology(nodes.map(fullNode))),
      }),
    )
    // The agent detail bubble fetches the agent type on selection; without
    // this mock the request hits the real backend, 401s, and the auth
    // interceptor logs the session out mid-test.
    await page.route('**/api/v1/agents/types/**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_AGENT_TYPE) }),
    )

    await page.goto('/agents/runtime-control')
    await page.waitForLoadState('load')

    if (page.url().includes('/login')) {
      test.skip()
      return
    }

    await expect(page.getByTestId('agent-runtime-map-canvas')).toBeVisible()

    // Both schedule entities render in the trigger column, each wired to the
    // execution it triggered.
    await expect(page.getByTestId('trigger-entity-schedule:nightly-cleanup')).toBeVisible()
    await expect(page.getByTestId('trigger-entity-schedule:legacy-sync')).toBeVisible()
    await expect(page.getByTestId('trigger-edge-schedule:nightly-cleanup->sched-1')).toBeVisible()
    await expect(page.getByTestId('trigger-edge-schedule:legacy-sync->sched-2')).toBeVisible()

    // Known creator: the schedule card shows the creator caption and the
    // execution list.
    await page.getByTestId('trigger-entity-schedule:nightly-cleanup').click()
    const creatorCard = page.getByTestId('trigger-detail-bubble')
    await expect(creatorCard).toHaveAttribute('data-trigger-entity', 'schedule:nightly-cleanup')
    await expect(creatorCard.getByTestId('trigger-detail-creator')).toContainText('Alice Operator')
    await expect(creatorCard.getByTestId('trigger-detail-execution-sched-1')).toBeVisible()

    // Dismissing the card closes it (same dismissal pattern as the agent
    // detail bubble; the clamped bubble overlaps its own tile, so dismissal
    // goes through the card's close button).
    await creatorCard.getByTestId('trigger-detail-bubble-close').click()
    await expect(page.getByTestId('trigger-detail-bubble')).toHaveCount(0)

    // Legacy null-creator schedule: the card shows the schedule name and its
    // executions but NO creator caption and no placeholder.
    await page.getByTestId('trigger-entity-schedule:legacy-sync').click()
    const legacyCard = page.getByTestId('trigger-detail-bubble')
    await expect(legacyCard).toHaveAttribute('data-trigger-entity', 'schedule:legacy-sync')
    await expect(legacyCard.getByTestId('trigger-detail-creator')).toHaveCount(0)
    await expect(legacyCard.getByTestId('trigger-detail-execution-sched-2')).toBeVisible()

    // Selecting the legacy execution opens the agent detail bubble — the
    // "Triggered by" line degrades to the unknown label and NEVER shows the
    // schedule name as a person.
    await legacyCard.getByTestId('trigger-detail-execution-sched-2').click()
    const triggerLine = page.getByTestId('agent-detail-trigger-source')
    await expect(triggerLine).toHaveText('Unknown')
    await expect(triggerLine).not.toContainText('legacy-sync')
  })

  test('renders the Communication Hub and tool-call routes to MCP servers', async ({ page }) => {
    const node = mkNode({
      session_id: 'tool-1',
      agent_type_name: 'Tool Agent',
      tool_calls: [
        { tool_name: 'github____list_prs', mcp_slug: 'github', route_type: 'mcp', called_at: '2026-06-01T00:00:05Z' },
        { tool_name: 'github____older', mcp_slug: 'github', route_type: 'mcp', called_at: '2026-06-01T00:00:01Z' },
      ],
    })
    await page.route('**/api/v1/agents/runtime/topology**', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify(mkTopology([fullNode(node)])),
      }),
    )
    // The detail bubble fetches the agent type on selection; without this
    // mock the request hits the real backend, 401s, and the auth interceptor
    // logs the session out mid-test.
    await page.route('**/api/v1/agents/types/**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_AGENT_TYPE) }),
    )

    await page.goto('/agents/runtime-control')
    await page.waitForLoadState('load')

    if (page.url().includes('/login')) {
      test.skip()
      return
    }

    await expect(page.getByTestId('agent-runtime-map-canvas')).toBeVisible()

    // Communication Hub is a visible node.
    await expect(page.getByTestId('communication-hub-node')).toBeVisible()

    // MCP server node for the "github" slug is visible.
    await expect(page.getByTestId('mcp-server-node-github')).toBeVisible()

    // Distinct bare tool names render as chips beside the MCP node.
    await expect(page.getByTestId('tool-chip-github-list_prs')).toBeVisible()
    await expect(page.getByTestId('tool-chip-github-older')).toBeVisible()

    // Each call routes orthogonally: agent → hub (inbound) and hub → MCP
    // (outbound), tagged with the calling session.
    await expect(
      page.locator('svg path[data-route-kind="tool"][data-route-session="tool-1"]'),
    ).toHaveCount(4) // 2 calls × (inbound + outbound)

    // Selecting the agent highlights ALL of its route segments and the
    // involved MCP node + tool chips.
    await page.getByRole('button', { name: /Tool Agent/ }).click()
    await expect(
      page.locator('svg path[data-route-kind="tool"][data-highlighted="true"]'),
    ).toHaveCount(4)
    await expect(page.getByTestId('mcp-server-node-github')).toHaveAttribute(
      'data-highlighted',
      'true',
    )
    await expect(page.getByTestId('tool-chip-github-list_prs')).toHaveAttribute(
      'data-highlighted',
      'true',
    )
  })

  test('renders the System Tools node and skips unknown-slug and a2a tool calls', async ({ page }) => {
    const node = mkNode({
      session_id: 'sys-1',
      agent_type_name: 'System Agent',
      tool_calls: [
        { tool_name: 'save_data', mcp_slug: 'system', route_type: 'system', called_at: '2026-06-01T00:00:05Z' },
        // NULL route_type — backend degrade row (e.g. legacy/unknown-slug call).
        { tool_name: 'delegate____handoff', mcp_slug: 'unknown', route_type: null, called_at: '2026-06-01T00:00:01Z' },
        // a2a rows are delegations, not tool calls — excluded outright.
        { tool_name: 'send_a2a_message', mcp_slug: 'unknown', route_type: 'a2a', called_at: '2026-06-01T00:00:00Z' },
      ],
    })
    await page.route('**/api/v1/agents/runtime/topology**', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify(mkTopology([fullNode(node)])),
      }),
    )

    await page.goto('/agents/runtime-control')
    await page.waitForLoadState('load')

    if (page.url().includes('/login')) {
      test.skip()
      return
    }

    await expect(page.getByTestId('agent-runtime-map-canvas')).toBeVisible()

    // System-slug calls collapse into the single synthetic "System Tools" node.
    await expect(page.getByTestId('system-tools-node')).toBeVisible()
    await expect(page.getByTestId('system-tools-node')).toContainText('System Tools')
    await expect(page.getByTestId('tool-chip-system-save_data')).toBeVisible()

    // Unknown-slug calls (NULL route_type degrade row) render neither an MCP
    // node nor a tool chip, and a2a rows (delegations, not tool calls) are
    // excluded outright.
    await expect(page.getByTestId('mcp-server-node-unknown')).toHaveCount(0)
    await expect(page.getByTestId('tool-chip-unknown-handoff')).toHaveCount(0)
    await expect(page.getByTestId('tool-chip-unknown-send_a2a_message')).toHaveCount(0)

    // The a2a call leaves no route at all; the unknown-slug call still leaves
    // the agent (inbound half-routes exist per call), but only the system call
    // gets an outbound route to an MCP node.
    await expect(
      page.locator('svg path[data-route-kind="tool"][data-route-session="sys-1"]'),
    ).toHaveCount(3) // 2 inbound + 1 outbound (system call only)
  })
})

test.describe('Real Backend Integration - agent runtime monitor', () => {
  test('topology endpoint returns a boolean needs_intervention per node', async ({ page }) => {
    const realToken = process.env.E2E_REAL_BACKEND_TOKEN
    if (!realToken) {
      test.skip()
      return
    }

    let healthStatus = 0
    try {
      const health = await page.request.get('http://localhost:8000/api/v1/health')
      healthStatus = health.status()
    } catch {
      healthStatus = 0
    }

    if (healthStatus === 0) {
      test.skip()
      return
    }

    const resp = await page.request.get(
      'http://localhost:8000/api/v1/agents/runtime/topology?include_terminal=false&max_nodes=200',
      { headers: { Authorization: `Bearer ${realToken}` } },
    )

    if (resp.status() !== 200) {
      expect([401, 403]).toContain(resp.status())
      test.skip()
      return
    }

    const body = await resp.json()
    expect(Array.isArray(body.nodes)).toBe(true)

    for (const node of body.nodes) {
      expect(typeof node.needs_intervention).toBe('boolean')
    }
  })
})
