import { expect, test } from '@playwright/test'

import { mockHealth, mockIdentityStatus, mockTelemetry } from './_helpers'

test.describe('Delegation Lifecycle Visibility (mocked API)', () => {
  test.beforeEach(async ({ page }) => {
    await mockHealth(page)
    await mockTelemetry(page)
    await mockIdentityStatus(page)

    await page.addInitScript(() => {
      localStorage.setItem('access_token', 'fake.jwt.token')
    })
  })

  test('renders delegation_started event in execution details', async ({ page }) => {
    await page.route('http://localhost:8000/api/v1/agent-runtime/sessions/session-abc/logs', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          logs: [
            {
              id: 'log-1',
              session_id: 'session-abc',
              timestamp: '2026-06-17T12:00:00Z',
              event_type: 'delegation_started',
              log_level: 'INFO',
              event_category: 'functional',
              message: 'Delegating to agent sub-agent',
              data: { delegation_target: 'sub-agent' },
            },
          ],
        }),
      })
    )

    await page.route('http://localhost:8000/api/v1/agent-runtime/sessions/session-abc/structured-log', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          summary: {
            identity: 'test-agent',
            role: 'test-role',
            model: 'gpt-4',
            inputType: 'object',
            sopsSkills: [],
            planCompleted: 1,
            planTotal: 1,
            resultStatus: 'success',
            startedAt: '2026-06-17T12:00:00Z',
            completedAt: '2026-06-17T12:01:00Z',
            durationMs: 60000,
            guardrailUsage: null,
          },
          spans: [],
          workingSteps: [],
          rawLog: '',
        }),
      })
    )

    await page.goto('/executions/session-abc')
    await page.waitForTimeout(1000)

    await expect(page.getByText('Delegation Timeline')).toBeVisible({ timeout: 10000 })
  })

  test('renders delegation_resumed event', async ({ page }) => {
    await page.route('http://localhost:8000/api/v1/agent-runtime/sessions/session-resumed/logs', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          logs: [
            {
              id: 'log-1',
              session_id: 'session-resumed',
              timestamp: '2026-06-17T12:00:00Z',
              event_type: 'delegation_resumed',
              log_level: 'INFO',
              event_category: 'functional',
              message: 'Delegation resumed — exit condition: completed',
              data: { delegation_target: 'sub-agent', exit_condition: 'completed' },
            },
          ],
        }),
      })
    )

    await page.route('http://localhost:8000/api/v1/agent-runtime/sessions/session-resumed/structured-log', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          summary: { identity: 'test-agent', role: 'test-role', model: 'gpt-4', inputType: 'object', sopsSkills: [], planCompleted: 1, planTotal: 1, resultStatus: 'success', startedAt: '2026-06-17T12:00:00Z', completedAt: '2026-06-17T12:01:00Z', durationMs: 60000, guardrailUsage: null },
          spans: [], workingSteps: [], rawLog: '',
        }),
      })
    )

    await page.goto('/executions/session-resumed')
    await page.waitForTimeout(1000)
    await expect(page.getByText('Delegation Timeline')).toBeVisible({ timeout: 10000 })
  })

  test('renders delegation_depth_blocked event', async ({ page }) => {
    await page.route('http://localhost:8000/api/v1/agent-runtime/sessions/session-blocked/logs', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          logs: [
            {
              id: 'log-1',
              session_id: 'session-blocked',
              timestamp: '2026-06-17T12:00:00Z',
              event_type: 'delegation_depth_blocked',
              log_level: 'WARN',
              event_category: 'guardrail',
              message: 'Delegation depth limit exceeded for sub-agent',
              data: {
                delegation_target: 'sub-agent',
                current_depth: 4,
                max_depth: 3,
                reason: GuardrailStopReason.DELEGATION_DEPTH_EXCEEDED,
              },
            },
          ],
        }),
      })
    )

    await page.route('http://localhost:8000/api/v1/agent-runtime/sessions/session-blocked/structured-log', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          summary: { identity: 'test-agent', role: 'test-role', model: 'gpt-4', inputType: 'object', sopsSkills: [], planCompleted: 1, planTotal: 1, resultStatus: 'success', startedAt: '2026-06-17T12:00:00Z', completedAt: '2026-06-17T12:01:00Z', durationMs: 60000, guardrailUsage: null },
          spans: [], workingSteps: [], rawLog: '',
        }),
      })
    )

    await page.goto('/executions/session-blocked')
    await page.waitForTimeout(1000)
    await expect(page.getByText('Delegation Timeline')).toBeVisible({ timeout: 10000 })
  })

  test('renders delegation_timeout event', async ({ page }) => {
    await page.route('http://localhost:8000/api/v1/agent-runtime/sessions/session-timeout/logs', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          logs: [
            {
              id: 'log-1',
              session_id: 'session-timeout',
              timestamp: '2026-06-17T12:00:00Z',
              event_type: 'delegation_timeout',
              log_level: 'WARN',
              event_category: 'functional',
              message: "Delegated agent 'sub-agent' timed out",
              data: { delegation_target: 'sub-agent', error: 'A2A request timed out' },
            },
          ],
        }),
      })
    )

    await page.route('http://localhost:8000/api/v1/agent-runtime/sessions/session-timeout/structured-log', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          summary: { identity: 'test-agent', role: 'test-role', model: 'gpt-4', inputType: 'object', sopsSkills: [], planCompleted: 1, planTotal: 1, resultStatus: 'success', startedAt: '2026-06-17T12:00:00Z', completedAt: '2026-06-17T12:01:00Z', durationMs: 60000, guardrailUsage: null },
          spans: [], workingSteps: [], rawLog: '',
        }),
      })
    )

    await page.goto('/executions/session-timeout')
    await page.waitForTimeout(1000)
    await expect(page.getByText('Delegation Timeline')).toBeVisible({ timeout: 10000 })
  })

  test('renders delegation_failed event', async ({ page }) => {
    await page.route('http://localhost:8000/api/v1/agent-runtime/sessions/session-failed/logs', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          logs: [
            {
              id: 'log-1',
              session_id: 'session-failed',
              timestamp: '2026-06-17T12:00:00Z',
              event_type: 'delegation_failed',
              log_level: 'ERROR',
              event_category: 'functional',
              message: "Delegated agent 'sub-agent' failed: runtime error",
              data: { delegation_target: 'sub-agent', error: 'Runtime error occurred' },
            },
          ],
        }),
      })
    )

    await page.route('http://localhost:8000/api/v1/agent-runtime/sessions/session-failed/structured-log', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          summary: { identity: 'test-agent', role: 'test-role', model: 'gpt-4', inputType: 'object', sopsSkills: [], planCompleted: 1, planTotal: 1, resultStatus: 'success', startedAt: '2026-06-17T12:00:00Z', completedAt: '2026-06-17T12:01:00Z', durationMs: 60000, guardrailUsage: null },
          spans: [], workingSteps: [], rawLog: '',
        }),
      })
    )

    await page.goto('/executions/session-failed')
    await page.waitForTimeout(1000)
    await expect(page.getByText('Delegation Timeline')).toBeVisible({ timeout: 10000 })
  })

  test('does not render Delegation Timeline for non-delegation events', async ({ page }) => {
    await page.route('http://localhost:8000/api/v1/agent-runtime/sessions/session-plain/logs', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          logs: [
            {
              id: 'log-1',
              session_id: 'session-plain',
              timestamp: '2026-06-17T12:00:00Z',
              event_type: 'observe',
              log_level: 'INFO',
              event_category: 'functional',
              message: 'Observe phase',
              data: {},
            },
          ],
        }),
      })
    )

    await page.route('http://localhost:8000/api/v1/agent-runtime/sessions/session-plain/structured-log', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          summary: { identity: 'test-agent', role: 'test-role', model: 'gpt-4', inputType: 'object', sopsSkills: [], planCompleted: 1, planTotal: 1, resultStatus: 'success', startedAt: '2026-06-17T12:00:00Z', completedAt: '2026-06-17T12:01:00Z', durationMs: 60000, guardrailUsage: null },
          spans: [], workingSteps: [], rawLog: '',
        }),
      })
    )

    await page.goto('/executions/session-plain')
    await page.waitForTimeout(1000)
    await expect(page.getByText('Delegation Timeline')).not.toBeVisible()
  })

  test('renders multiple delegation events in a single view', async ({ page }) => {
    await page.route('http://localhost:8000/api/v1/agent-runtime/sessions/session-multi/logs', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          logs: [
            {
              id: 'log-1',
              session_id: 'session-multi',
              timestamp: '2026-06-17T12:00:00Z',
              event_type: 'delegation_started',
              log_level: 'INFO',
              event_category: 'functional',
              message: 'Delegating to agent sub-qa',
              data: { delegation_target: 'sub-qa' },
            },
            {
              id: 'log-2',
              session_id: 'session-multi',
              timestamp: '2026-06-17T12:00:30Z',
              event_type: 'delegation_resumed',
              log_level: 'INFO',
              event_category: 'functional',
              message: 'Delegation resumed — exit condition: completed',
              data: { delegation_target: 'sub-qa', exit_condition: 'completed' },
            },
          ],
        }),
      })
    )

    await page.route('http://localhost:8000/api/v1/agent-runtime/sessions/session-multi/structured-log', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          summary: { identity: 'test-agent', role: 'test-role', model: 'gpt-4', inputType: 'object', sopsSkills: [], planCompleted: 1, planTotal: 1, resultStatus: 'success', startedAt: '2026-06-17T12:00:00Z', completedAt: '2026-06-17T12:01:00Z', durationMs: 60000, guardrailUsage: null },
          spans: [], workingSteps: [], rawLog: '',
        }),
      })
    )

    await page.goto('/executions/session-multi')
    await page.waitForTimeout(1000)
    await expect(page.getByText('Delegation Timeline')).toBeVisible({ timeout: 10000 })
  })
})
