import { expect, test, type Page } from '@playwright/test'
import { mockApiCatchAllProxyAware, standardSetup } from './_helpers'

/**
 * Token Expiry Alerting — execution preflight gate, user-visible journey.
 *
 * All API calls are mocked; the preflight verdict is represented by what the
 * backend returns to the UI when an execution is started:
 *  - BLOCKED → session creation returns HTTP 422 whose detail names the
 *    affected identity (including an expired SUBAGENT identity); the user
 *    sees the actionable message and NO session is created.
 *  - EXPIRING → session creation succeeds (execution proceeds with a
 *    backend-surfaced warning); the user is not blocked.
 */

const CONVERSATION_AGENT = {
  id: 'at-conv-1',
  name: 'Research Agent',
  description: '',
  identity_id: null,
  role_id: 'role-p1',
  llm_provider: 'openai',
  llm_model: 'gpt-4o',
  system_instruction: null,
  input_type: 'conversation',
  input_schema: null,
  output_type: 'markdown',
  output_schema: null,
  guardrail_max_iterations: 10,
  guardrail_max_delegation_depth: 3,
  guardrail_max_delegated_steps: 20,
  guardrail_execution_timeout_seconds: 300,
  guardrail_token_budget: null,
  guardrail_token_enforcement_mode: 'observe',
  guardrail_token_fallback_mode: 'observe_and_log',
  guardrail_conversational_token_visibility_mode: 'enabled',
  guardrail_conversational_continuation_policy: 'allow',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

async function mockAgentsPage(page: Page) {
  await page.route('**/api/v1/agents/types**', (route) =>
    route.fulfill({
      status: 200,
      body: JSON.stringify([CONVERSATION_AGENT]),
    })
  )
  await page.route('**/api/v1/agents/types/**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(CONVERSATION_AGENT) })
  )
  await page.route('**/api/v1/agents/roles**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
  await page.route('**/api/v1/agents/identities**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
  await page.route('**/api/v1/agents/sessions**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
  await page.route('**/api/v1/conversations**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
}

test.describe.configure({ timeout: 60_000 })

test.describe('Token expiry — execution preflight', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiCatchAllProxyAware(page)
    await standardSetup(page)
    await mockAgentsPage(page)
  })

  test('expired token (including a subagent) BLOCKS execution with a named identity', async ({
    page,
  }) => {
    const createCalls: { url: string; body: unknown }[] = []
    await page.route('**/api/v1/conversations?**', (route) => {
      // list requests carry a query string; POST /conversations has none and
      // falls through to the catch-all below.
      return route.fallback()
    })
    await page.route('**/api/v1/conversations', (route) => {
      if (route.request().method() === 'POST') {
        createCalls.push({
          url: route.request().url(),
          body: route.request().postDataJSON(),
        })
        // Mirrors CC preflight BLOCKED verdict surfaced by CH as 422.
        return route.fulfill({
          status: 422,
          contentType: 'application/json',
          body: JSON.stringify({
            detail:
              "Execution blocked: agent_identity 'child-researcher' token has expired — " +
              'refresh it (identity) or re-authenticate (MCP session) before executing ' +
              'this agent (expired subagent of parent run)',
          }),
        })
      }
      return route.fulfill({ status: 200, body: JSON.stringify([]) })
    })

    await page.goto('/agents')
    await page.waitForLoadState('load')
    await page.getByRole('button', { name: 'Start Chat' }).click()

    const input = page.getByRole('textbox').last()
    await input.fill('run the research task')
    await input.press('Enter')

    // The block message names the expired (subagent) identity.
    await expect(
      page.getByText(/child-researcher.*token has expired/i)
    ).toBeVisible()
    // Fail closed: NO session was created.
    expect(createCalls).toHaveLength(1)
  })

  test('expiring token (≤7 days) WARNS but execution PROCEEDS', async ({ page }) => {
    let created = false
    await page.route('**/api/v1/conversations?**', (route) => {
      // list requests carry a query string; POST /conversations has none and
      // falls through to the catch-all below.
      return route.fallback()
    })
    await page.route('**/api/v1/conversations', (route) => {
      if (route.request().method() === 'POST') {
        created = true
        // PROCEED_WITH_WARNINGS: session is created, execution starts.
        return route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 'sess-1',
            agent_type_id: CONVERSATION_AGENT.id,
            status: 'running',
            // CH execution trigger response carries expiring-token notices.
            warnings: [
              "agent_identity 'researcher' token expires within 7 days — refresh soon",
            ],
          }),
        })
      }
      return route.fulfill({ status: 200, body: JSON.stringify([]) })
    })

    await page.goto('/agents')
    await page.waitForLoadState('load')
    await page.getByRole('button', { name: 'Start Chat' }).click()

    const input = page.getByRole('textbox').last()
    await input.fill('run the research task')
    await input.press('Enter')

    // Session created — execution proceeded despite the expiring token.
    await expect
      .poll(() => created, { timeout: 10_000 })
      .toBe(true)
    // And no "expired / blocked" error surfaced to the user.
    await expect(page.getByText(/token has expired/i)).toHaveCount(0)
    await expect(
      page.getByText(/Execution blocked/i)
    ).toHaveCount(0)
  })
})
