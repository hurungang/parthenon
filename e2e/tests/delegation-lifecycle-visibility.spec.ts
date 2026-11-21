import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { FAKE_TOKEN, mockHealth, mockIdentityStatus, mockTelemetry } from './_helpers'

/**
 * Delegation lifecycle visibility (mocked API).
 *
 * The execution-details surface is `AgentJobPage` (`/agents/sessions/:id`), which
 * renders `LogViewer` -> `WorkingStepsPanel`. Delegation lifecycle events are
 * rendered inline inside the "Agent Working Steps" tree (there is no separate
 * "Delegation Timeline" panel any more), using the labels from
 * `executions.delegationTimeline.*` whose defaults are DELEGATING / COMPLETED /
 * DELEGATION BLOCKED / DELEGATION TIMEOUT / DELEGATION FAILED.
 *
 * Endpoints the page calls on mount:
 *   GET /agents/sessions/:id                 (AgentJob)
 *   GET /agents/sessions/:id/logs            (ExecutionLogEntry[])
 *   GET /agents/sessions/:id/execution-logs  (ExecutionLogRead[])
 *   GET /intervene/requests?...              (InterveneRequest[])
 */

interface LogEntryInput {
  id: string
  sessionId: string
  timestamp: string
  eventType: string
  logLevel: string
  eventCategory: 'functional' | 'guardrail'
  message: string
  data: Record<string, unknown>
}

function logEntry(input: LogEntryInput) {
  return {
    id: input.id,
    session_id: input.sessionId,
    timestamp: input.timestamp,
    event_type: input.eventType,
    log_level: input.logLevel,
    event_category: input.eventCategory,
    message: input.message,
    data: input.data,
  }
}

function agentJob(sessionId: string) {
  return {
    id: sessionId,
    agent_type_id: 'agent-type-1',
    agent_type_name: 'Test Agent',
    triggered_by_user_id: null,
    triggered_by_user_name: null,
    input_data: null,
    status: 'completed',
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

/** Mocks every endpoint `AgentJobPage` hits for a session with the given log entries. */
async function mockSessionExecution(
  page: Page,
  sessionId: string,
  entries: ReturnType<typeof logEntry>[],
) {
  // Generic collection mocks registered before the session-specific ones.
  await page.route('**/api/v1/intervene/requests**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  )

  await page.route(`**/api/v1/agents/sessions/${sessionId}/logs`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(entries),
    })
  )

  await page.route(`**/api/v1/agents/sessions/${sessionId}/execution-logs`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  )

  await page.route(`**/api/v1/agents/sessions/${sessionId}`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(agentJob(sessionId)),
    })
  )
}

test.describe('Delegation Lifecycle Visibility (mocked API)', () => {
  test.beforeEach(async ({ page }) => {
    await mockHealth(page)
    await mockTelemetry(page)
    await mockIdentityStatus(page)

    await page.addInitScript((token) => {
      localStorage.setItem('access_token', token)
    }, FAKE_TOKEN)
  })

  test('renders delegation_started event in execution details', async ({ page }) => {
    await mockSessionExecution(page, 'session-abc', [
      logEntry({
        id: 'log-1',
        sessionId: 'session-abc',
        timestamp: '2026-06-17T12:00:00Z',
        eventType: 'delegation_started',
        logLevel: 'INFO',
        eventCategory: 'functional',
        message: 'Delegating to agent sub-agent',
        data: { delegation_target: 'sub-agent' },
      }),
    ])

    await page.goto('/agents/sessions/session-abc')

    await expect(page.getByText('Agent Working Steps')).toBeVisible({ timeout: 10000 })
    await expect(page.getByText('DELEGATING', { exact: true })).toBeVisible()
    await expect(page.getByText('Delegating to agent sub-agent')).toBeVisible()
  })

  test('renders delegation_resumed event', async ({ page }) => {
    await mockSessionExecution(page, 'session-resumed', [
      logEntry({
        id: 'log-1',
        sessionId: 'session-resumed',
        timestamp: '2026-06-17T12:00:00Z',
        eventType: 'delegation_resumed',
        logLevel: 'INFO',
        eventCategory: 'functional',
        message: 'Delegation resumed — exit condition: completed',
        data: { delegation_target: 'sub-agent', exit_condition: 'completed' },
      }),
    ])

    await page.goto('/agents/sessions/session-resumed')

    await expect(page.getByText('Agent Working Steps')).toBeVisible({ timeout: 10000 })
    await expect(page.getByText('COMPLETED', { exact: true })).toBeVisible()
    await expect(page.getByText('Delegation resumed — exit condition: completed')).toBeVisible()
  })

  test('renders delegation_depth_blocked event', async ({ page }) => {
    await mockSessionExecution(page, 'session-blocked', [
      logEntry({
        id: 'log-1',
        sessionId: 'session-blocked',
        timestamp: '2026-06-17T12:00:00Z',
        eventType: 'delegation_depth_blocked',
        logLevel: 'WARN',
        eventCategory: 'guardrail',
        message: 'Delegation depth limit exceeded for sub-agent',
        data: {
          delegation_target: 'sub-agent',
          current_depth: 4,
          max_depth: 3,
          reason: 'delegation_depth_exceeded',
        },
      }),
    ])

    await page.goto('/agents/sessions/session-blocked')

    await expect(page.getByText('Agent Working Steps')).toBeVisible({ timeout: 10000 })
    await expect(page.getByText('DELEGATION BLOCKED', { exact: true })).toBeVisible()
    await expect(page.getByText('Delegation depth limit exceeded for sub-agent')).toBeVisible()
  })

  test('renders delegation_timeout event', async ({ page }) => {
    await mockSessionExecution(page, 'session-timeout', [
      logEntry({
        id: 'log-1',
        sessionId: 'session-timeout',
        timestamp: '2026-06-17T12:00:00Z',
        eventType: 'delegation_timeout',
        logLevel: 'WARN',
        eventCategory: 'functional',
        message: "Delegated agent 'sub-agent' timed out",
        data: { delegation_target: 'sub-agent', error: 'A2A request timed out' },
      }),
    ])

    await page.goto('/agents/sessions/session-timeout')

    await expect(page.getByText('Agent Working Steps')).toBeVisible({ timeout: 10000 })
    await expect(page.getByText('DELEGATION TIMEOUT', { exact: true })).toBeVisible()
    await expect(page.getByText("Delegated agent 'sub-agent' timed out")).toBeVisible()
  })

  test('renders delegation_failed event', async ({ page }) => {
    await mockSessionExecution(page, 'session-failed', [
      logEntry({
        id: 'log-1',
        sessionId: 'session-failed',
        timestamp: '2026-06-17T12:00:00Z',
        eventType: 'delegation_failed',
        logLevel: 'ERROR',
        eventCategory: 'functional',
        message: "Delegated agent 'sub-agent' failed: runtime error",
        data: { delegation_target: 'sub-agent', error: 'Runtime error occurred' },
      }),
    ])

    await page.goto('/agents/sessions/session-failed')

    await expect(page.getByText('Agent Working Steps')).toBeVisible({ timeout: 10000 })
    await expect(page.getByText('DELEGATION FAILED', { exact: true })).toBeVisible()
    await expect(page.getByText("Delegated agent 'sub-agent' failed: runtime error")).toBeVisible()
  })

  test('does not render Delegation Timeline for non-delegation events', async ({ page }) => {
    await mockSessionExecution(page, 'session-plain', [
      logEntry({
        id: 'log-1',
        sessionId: 'session-plain',
        timestamp: '2026-06-17T12:00:00Z',
        eventType: 'observe',
        logLevel: 'INFO',
        eventCategory: 'functional',
        message: 'Observe phase',
        data: {},
      }),
    ])

    await page.goto('/agents/sessions/session-plain')

    // The working-steps tree renders, but no delegation block/label appears.
    await expect(page.getByText('Agent Working Steps')).toBeVisible({ timeout: 10000 })
    await expect(page.getByText('Observe phase')).toBeVisible()
    await expect(page.getByText('DELEGATING', { exact: true })).toHaveCount(0)
    await expect(page.getByText('Delegation Timeline')).toHaveCount(0)
  })

  test('renders multiple delegation events in a single view', async ({ page }) => {
    await mockSessionExecution(page, 'session-multi', [
      logEntry({
        id: 'log-1',
        sessionId: 'session-multi',
        timestamp: '2026-06-17T12:00:00Z',
        eventType: 'delegation_started',
        logLevel: 'INFO',
        eventCategory: 'functional',
        message: 'Delegating to agent sub-qa',
        data: { delegation_target: 'sub-qa' },
      }),
      logEntry({
        id: 'log-2',
        sessionId: 'session-multi',
        timestamp: '2026-06-17T12:00:30Z',
        eventType: 'delegation_resumed',
        logLevel: 'INFO',
        eventCategory: 'functional',
        message: 'Delegation resumed — exit condition: completed',
        data: { delegation_target: 'sub-qa', exit_condition: 'completed' },
      }),
    ])

    await page.goto('/agents/sessions/session-multi')

    await expect(page.getByText('Agent Working Steps')).toBeVisible({ timeout: 10000 })
    // Started+resumed for the same target merge into one `delegation_merged`
    // block (labelled DELEGATION) carrying the terminal state (Completed) and
    // both lifecycle events in the mini-timeline.
    await expect(page.getByText('DELEGATION', { exact: true })).toBeVisible()
    await expect(page.getByText('Delegating to agent sub-qa')).toBeVisible()
    await expect(
      page.getByText('Delegation resumed — exit condition: completed').first()
    ).toBeVisible()
  })
})
