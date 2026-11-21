import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { FAKE_TOKEN, mockApiCatchAllProxyAware, standardSetup } from './_helpers'
import {
  mockPanelWorld,
  selectMuiOption,
  type PanelWorldState,
} from './_agent_panel_world'

/**
 * Delegation depth scoping (mocked API) — `remove-delegation-depth-cap`.
 *
 * Covers the three operator-visible promises of the change:
 *  1. Configuration: the Agent Type create dialog and the Agent Properties panel
 *     accept a Max Delegation Depth above the former 32 ceiling, submit it
 *     unchanged, and never advertise a platform cap.
 *  2. Execution-log scoping: the parent log shows only the parent's own work and
 *     its DIRECT delegation lifecycle. The delegation card's peek excludes the
 *     child's own delegation activity, and "View Execution Logs" opens the
 *     child's own (unfiltered) log where that delegation IS visible.
 *  3. Status display: the guardrail usage indicator shows the configured maximum
 *     (3 vs 7 for two agent types), never a fixed one-level platform value.
 *
 * Everything is mocked through `page.route()` — no Keycloak / backend required.
 */

// ── Log fixtures ─────────────────────────────────────────────────────────────

interface LogEntryInput {
  id: string
  sessionId: string
  timestamp: string
  eventType: string
  logLevel?: string
  eventCategory?: 'functional' | 'guardrail'
  message: string
  data?: Record<string, unknown>
}

function logEntry(input: LogEntryInput) {
  return {
    id: input.id,
    session_id: input.sessionId,
    timestamp: input.timestamp,
    event_type: input.eventType,
    log_level: input.logLevel ?? 'INFO',
    event_category: input.eventCategory ?? 'functional',
    message: input.message,
    data: input.data ?? {},
  }
}

function agentJob(sessionId: string, status = 'completed') {
  return {
    id: sessionId,
    agent_type_id: 'agent-type-1',
    agent_type_name: 'Test Agent',
    triggered_by_user_id: null,
    triggered_by_user_name: null,
    input_data: null,
    status,
    started_at: '2026-06-17T12:00:00Z',
    completed_at: '2026-06-17T12:01:00Z',
    output_data: null,
    error_message: null,
    conversation_history: null,
    created_at: '2026-06-17T12:00:00Z',
    output_id: null,
    output_type: null,
  }
}

/**
 * Registers every endpoint a session page (`AgentJobPage`) hits.
 * Routes are keyed by full path so parent / child / grandchild sessions can be
 * mocked independently on the same page.
 */
async function mockSession(
  page: Page,
  sessionId: string,
  opts: {
    entries: ReturnType<typeof logEntry>[]
    status?: string
  },
) {
  // Collection endpoints first — the session-specific ones below win for their id.
  await page.route('**/api/v1/intervene/requests**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
  )

  await page.route(new RegExp(`/api/v1/agents/sessions/${sessionId}/logs$`), (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(opts.entries),
    }),
  )

  await page.route(
    new RegExp(`/api/v1/agents/sessions/${sessionId}/execution-logs$`),
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
  )

  await page.route(new RegExp(`/api/v1/agents/sessions/${sessionId}$`), (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(agentJob(sessionId, opts.status ?? 'completed')),
    }),
  )
}

async function installToken(page: Page) {
  await page.addInitScript((token) => {
    localStorage.setItem('access_token', token)
  }, FAKE_TOKEN)
}

// ── Configuration inputs ─────────────────────────────────────────────────────

test.describe('Delegation Depth Configuration (mocked API)', () => {
  test.describe.configure({ timeout: 90_000 })

  let state: PanelWorldState

  test.beforeEach(async ({ page }) => {
    await mockApiCatchAllProxyAware(page)
    await installToken(page)
    await standardSetup(page)
    state = await mockPanelWorld(page)
  })

  test('create dialog accepts a depth above 32 and submits it unchanged', async ({ page }) => {
    await page.goto('/agents/panel')
    await expect(page.getByRole('heading', { name: 'Agent Management Panel' })).toBeVisible()

    await page.getByRole('button', { name: 'Create Agent', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    // Required basics: slug valid + at least one binding (Save stays disabled otherwise).
    await dialog.getByLabel('Name').fill('e2e-depth-create')
    await selectMuiOption(page, dialog, 'Agent Role', 'panel-e2e-role')

    // Bind the role's skill so the form passes its binding requirement.
    await dialog.getByRole('button', { name: 'Add Binding' }).click()
    await dialog.getByRole('button', { name: 'Skill', exact: true }).click()
    await dialog
      .getByRole('combobox')
      .filter({ hasText: 'Select an item…' })
      .last()
      .click()
    await page.getByRole('option', { name: 'panel-e2e-skill' }).click()
    await dialog.getByRole('button', { name: 'Add', exact: true }).click()

    // Guardrails: no numeric ceiling is advertised anywhere in the section.
    await dialog.getByRole('button', { name: 'Execution Guardrails' }).click()
    const sectionHint = dialog.getByText(
      'Configure per-agent-type execution boundaries for recursion, delegation, timeout, and token policy.',
    )
    await expect(sectionHint).toBeVisible()
    expect(await sectionHint.textContent()).not.toMatch(/32/)

    const depthInput = dialog.getByRole('spinbutton', { name: 'Max Delegation Depth' })
    await expect(depthInput).toBeVisible()
    expect(await depthInput.getAttribute('max')).toBeNull()
    expect(await depthInput.getAttribute('min')).toBe('0')

    await depthInput.fill('40')
    await expect(depthInput).toHaveValue('40')

    await dialog.getByRole('button', { name: 'Save' }).click()

    await expect.poll(() => state.agentPostBodies.length).toBe(1)
    expect(state.agentPostBodies[0].guardrail_max_delegation_depth).toBe(40)

    // The dialog closes and the saved agent is selected in the panel.
    await expect(dialog).not.toBeVisible()
    await expect(page.getByRole('heading', { name: 'e2e-depth-create' })).toBeVisible()
  })

  test('Agent Properties panel accepts a depth above 32 and persists it unchanged', async ({
    page,
  }) => {
    await page.goto('/agents/panel')
    await expect(page.getByRole('heading', { name: 'Agent Management Panel' })).toBeVisible()

    await page.getByRole('button', { name: 'panel-e2e-alpha' }).click()
    await expect(page.getByRole('heading', { name: 'panel-e2e-alpha', exact: true })).toBeVisible()

    await page.getByRole('button', { name: 'Execution Guardrails' }).click()

    const depthInput = page.getByRole('spinbutton', { name: 'Max Delegation Depth' })
    await expect(depthInput).toBeVisible()
    expect(await depthInput.getAttribute('max')).toBeNull()
    expect(await depthInput.getAttribute('min')).toBe('0')

    await depthInput.fill('40')
    await expect(depthInput).toHaveValue('40')

    // Other guardrail constraints are untouched by this change.
    const iterations = page.getByRole('spinbutton', { name: 'Max Iterations' })
    expect(await iterations.getAttribute('max')).toBe('1000')

    const saveButton = page.getByRole('button', { name: 'Save Changes' })
    await expect(saveButton).toBeEnabled()
    await saveButton.click()

    await expect.poll(() => state.agentPutBodies.length).toBe(1)
    expect(state.agentPutBodies[0].guardrail_max_delegation_depth).toBe(40)

    // Server-side persistence: the mocked world stored exactly what was sent.
    await expect.poll(() => state.agents[0].guardrail_max_delegation_depth).toBe(40)
    await expect(page.getByText('saved', { exact: true })).toBeVisible()
  })
})

// ── Execution-log scoping ────────────────────────────────────────────────────

test.describe('Execution Log Scoping (mocked API)', () => {
  const PARENT = 'parent-session-depth'
  const CHILD = 'child-session-depth'
  const GRANDCHILD = 'grandchild-session-depth'

  const parentEntries = [
    logEntry({
      id: 'parent-1',
      sessionId: PARENT,
      timestamp: '2026-06-17T12:00:00Z',
      eventType: 'session_started',
      message: 'Parent session started',
    }),
    logEntry({
      id: 'parent-2',
      sessionId: PARENT,
      timestamp: '2026-06-17T12:00:01Z',
      eventType: 'llm_request',
      message: 'Parent planning request',
    }),
    logEntry({
      id: 'parent-3',
      sessionId: PARENT,
      timestamp: '2026-06-17T12:00:02Z',
      eventType: 'delegation_started',
      message: 'Delegating to agent research-helper',
      data: { delegation_target: 'research-helper', delegation_depth: 1 },
    }),
    logEntry({
      id: 'parent-4',
      sessionId: PARENT,
      timestamp: '2026-06-17T12:00:03Z',
      eventType: 'delegation_waiting',
      message: 'Waiting for delegated response…',
      data: { delegation_target: 'research-helper', receiver_session_id: CHILD },
    }),
    logEntry({
      id: 'parent-5',
      sessionId: PARENT,
      timestamp: '2026-06-17T12:00:09Z',
      eventType: 'delegation_resumed',
      message: 'Delegation resumed — exit condition: completed',
      data: { delegation_target: 'research-helper', receiver_session_id: CHILD },
    }),
    logEntry({
      id: 'parent-6',
      sessionId: PARENT,
      timestamp: '2026-06-17T12:00:10Z',
      eventType: 'session_completed',
      message: 'Parent completed',
    }),
  ]

  /**
   * The child's own log: it initialises, then delegates ONWARD to a grandchild,
   * then completes. The child's own delegation activity must never surface in the
   * parent's peek (only in the child's own log).
   */
  const childEntries = [
    logEntry({
      id: 'child-1',
      sessionId: CHILD,
      timestamp: '2026-06-17T12:00:02Z',
      eventType: 'agent_initialized',
      message: 'Child initialised',
    }),
    logEntry({
      id: 'child-2',
      sessionId: CHILD,
      timestamp: '2026-06-17T12:00:03Z',
      eventType: 'llm_request',
      message: 'Child model request',
    }),
    logEntry({
      id: 'child-3',
      sessionId: CHILD,
      timestamp: '2026-06-17T12:00:04Z',
      eventType: 'tool_call',
      message: 'Tool call: agent____research-grandchild',
      data: { tool: 'agent____research-grandchild' },
    }),
    logEntry({
      id: 'child-4',
      sessionId: CHILD,
      timestamp: '2026-06-17T12:00:04Z',
      eventType: 'tool_response',
      message: 'Delegation response returned to the child',
      data: { delegation_target: 'research-grandchild' },
    }),
    logEntry({
      id: 'child-5',
      sessionId: CHILD,
      timestamp: '2026-06-17T12:00:05Z',
      eventType: 'delegation_started',
      message: 'Delegating to agent research-grandchild',
      data: { delegation_target: 'research-grandchild', delegation_depth: 2 },
    }),
    logEntry({
      id: 'child-6',
      sessionId: CHILD,
      timestamp: '2026-06-17T12:00:07Z',
      eventType: 'tool_call',
      message: 'Tool call: server____search',
      data: { tool: 'server____search' },
    }),
    logEntry({
      id: 'child-7',
      sessionId: CHILD,
      timestamp: '2026-06-17T12:00:09Z',
      eventType: 'session_completed',
      message: 'Child completed',
    }),
  ]

  test.beforeEach(async ({ page }) => {
    await mockApiCatchAllProxyAware(page)
    await installToken(page)
    await standardSetup(page)

    await mockSession(page, PARENT, { entries: parentEntries, status: 'completed' })
    await mockSession(page, CHILD, { entries: childEntries, status: 'completed' })
    // The child's peek fetches its own delegated child; keep it hermetic.
    await mockSession(page, GRANDCHILD, {
      entries: [
        logEntry({
          id: 'grandchild-1',
          sessionId: GRANDCHILD,
          timestamp: '2026-06-17T12:00:06Z',
          eventType: 'agent_initialized',
          message: 'Grandchild initialised',
        }),
      ],
      status: 'completed',
    })
  })

  test('parent log shows direct delegation only and the peek hides the child’s own delegation', async ({
    page,
  }) => {
    // The parent page must never query a grandchild session directly.
    const requestedUrls: string[] = []
    page.on('request', (request) => requestedUrls.push(request.url()))

    await page.goto(`/agents/sessions/${PARENT}`)

    await expect(page.getByText('Agent Working Steps')).toBeVisible({ timeout: 15000 })
    await expect(page.getByText('Parent planning request')).toBeVisible()
    // Direct delegation lifecycle is rendered as one merged block.
    await expect(page.getByText('DELEGATION', { exact: true })).toBeVisible()
    await expect(page.getByText('Delegating to agent research-helper')).toBeVisible()

    // Direct-child peek keeps the child's OWN activity…
    await expect(page.getByText('Child initialised')).toBeVisible({ timeout: 15000 })
    await expect(page.getByText('Child model request')).toBeVisible()
    await expect(page.getByText('Tool call: server____search')).toBeVisible()

    // …but never the child's onward delegation (tool call / response / lifecycle).
    await expect(page.getByText('Tool call: agent____research-grandchild')).toHaveCount(0)
    await expect(page.getByText('Delegation response returned to the child')).toHaveCount(0)
    await expect(page.getByText('Delegating to agent research-grandchild')).toHaveCount(0)

    // Single-session scope: only the direct child is fetched, never the grandchild.
    expect(requestedUrls.some((url) => url.includes(`/sessions/${GRANDCHILD}`))).toBe(false)
  })

  test('View Execution Logs drills into the child log, which shows the child’s own delegation', async ({
    page,
  }) => {
    await page.goto(`/agents/sessions/${PARENT}`)

    await expect(page.getByText('Agent Working Steps')).toBeVisible({ timeout: 15000 })
    const drillIn = page.getByRole('button', { name: 'View Execution Logs' })
    await expect(drillIn).toBeVisible({ timeout: 15000 })
    await drillIn.click()

    const childDialog = page.getByRole('dialog', { name: /Execution Details/ })
    await expect(childDialog).toBeVisible({ timeout: 15000 })

    // The drill-in opens on the Result tab; the execution log lives on the
    // Execution tab (no new navigation model — same dialog, same tabs).
    await childDialog.getByRole('tab', { name: 'Execution' }).click()
    await expect(childDialog.getByText('Agent Working Steps')).toBeVisible({ timeout: 15000 })

    // The child's own log is NOT filtered: its delegation block and the
    // delegation tool call it made are visible here.
    await expect(childDialog.getByText('DELEGATING', { exact: true })).toBeVisible({
      timeout: 15000,
    })
    await expect(childDialog.getByText('Delegating to agent research-grandchild')).toBeVisible()
    await expect(childDialog.getByText('Tool call: agent____research-grandchild')).toBeVisible()

    // Return to the parent: its contents are unchanged and still scoped.
    await page.keyboard.press('Escape')
    await expect(childDialog).not.toBeVisible()
    await expect(page.getByText('Parent planning request')).toBeVisible()
    await expect(page.getByText('DELEGATION', { exact: true })).toBeVisible()
    await expect(page.getByText('Delegating to agent research-grandchild')).toHaveCount(0)
  })
})

// ── Status display reflects configuration ────────────────────────────────────

test.describe('Delegation Depth Status Display (mocked API)', () => {
  function snapshotEntry(sessionId: string, maxDepth: number) {
    return logEntry({
      id: `${sessionId}-snapshot`,
      sessionId,
      timestamp: '2026-06-17T12:00:05Z',
      eventType: 'guardrail.runtime.snapshot',
      message: 'Guardrail runtime snapshot',
      data: {
        policy_snapshot_id: 'snap-e2e',
        current_value: { delegation_depth: 1 },
        threshold_value: { max_delegation_depth: maxDepth },
      },
    })
  }

  test.beforeEach(async ({ page }) => {
    await mockApiCatchAllProxyAware(page)
    await installToken(page)
    await standardSetup(page)
  })

  test('shows the configured maximum for each agent type (3 and 7), not a fixed 1', async ({
    page,
  }) => {
    await mockSession(page, 'session-depth-3', {
      entries: [
        logEntry({
          id: 'start-3',
          sessionId: 'session-depth-3',
          timestamp: '2026-06-17T12:00:00Z',
          eventType: 'session_started',
          message: 'Session started',
        }),
        snapshotEntry('session-depth-3', 3),
      ],
    })
    await mockSession(page, 'session-depth-7', {
      entries: [
        logEntry({
          id: 'start-7',
          sessionId: 'session-depth-7',
          timestamp: '2026-06-17T12:00:00Z',
          eventType: 'session_started',
          message: 'Session started',
        }),
        snapshotEntry('session-depth-7', 7),
      ],
    })

    await page.goto('/agents/sessions/session-depth-3')
    await expect(page.getByText('Guardrail Usage')).toBeVisible({ timeout: 15000 })
    const depthCard3 = page
      .getByText('Delegation Depth', { exact: true })
      .locator('xpath=ancestor::div[contains(@class,"MuiPaper-outlined")][1]')
    await expect(depthCard3.getByText('1 / 3', { exact: true })).toBeVisible()
    await expect(depthCard3.getByText('1 / 1', { exact: true })).toHaveCount(0)

    await page.goto('/agents/sessions/session-depth-7')
    await expect(page.getByText('Guardrail Usage')).toBeVisible({ timeout: 15000 })
    const depthCard7 = page
      .getByText('Delegation Depth', { exact: true })
      .locator('xpath=ancestor::div[contains(@class,"MuiPaper-outlined")][1]')
    await expect(depthCard7.getByText('1 / 7', { exact: true })).toBeVisible()
  })
})
