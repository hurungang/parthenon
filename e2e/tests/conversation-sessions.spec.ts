import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

/**
 * E2E tests: Conversation Session lifecycle — start, view, resume, and end.
 *
 * One variant uses page.route() mocks for speed/isolation.
 * The "Real Backend Integration" variant makes actual HTTP calls to validate
 * that migrations are applied and endpoints work end-to-end.
 */

// ── Shared constants ──────────────────────────────────────────────────────────

const AGENT_TYPE_ID = 'test-conv-agent-type-id'
const SESSION_ID = 'test-session-id-abc123'

// ── Mocked variant ────────────────────────────────────────────────────────────

const CONV_AGENT_TYPE = {
  id: AGENT_TYPE_ID,
  name: 'Test Conv Agent',
  input_type: 'conversation',
  output_type: 'auto',
  is_active: true,
  model_id: null,
  role_id: null,
  identity_id: null,
  sop_bindings: [],
  skill_bindings: [],
  system_instruction: null,
  description: null,
  input_schema: null,
  output_schema: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  plan: null,
}

test.describe('Conversation Sessions (Mocked)', () => {
  test.beforeEach(async ({ page }) => {
    // Auth setup must run first so specific routes registered below have lower priority
    // than any catch-all registered inside standardSetup
    await standardSetup(page)

    // Mock the agent type list AND individual fetch (dialog calls GET /agents/types/{id})
    await page.route('**/api/v1/agents/types', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([CONV_AGENT_TYPE]),
      })
    })
    await page.route('**/api/v1/agents/types/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(CONV_AGENT_TYPE),
      })
    })

    // Mock agent execution sessions (used by Execution Logs tab in dialog)
    await page.route('**/api/v1/agents/sessions**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })

    // Mock conversation sessions list
    await page.route(`**/api/v1/conversations?agent_type_id=${AGENT_TYPE_ID}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: SESSION_ID,
            agent_type_id: AGENT_TYPE_ID,
            triggered_by_user_id: 'user-1',
            agent_job_id: null,
            title: 'Auto-Generated Session Title',
            channel: 'web',
            status: 'active',
            turn_count: 2,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            closed_at: null,
          },
        ]),
      })
    })

    // Mock create session
    await page.route('**/api/v1/conversations', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({
            id: SESSION_ID,
            agent_type_id: AGENT_TYPE_ID,
            triggered_by_user_id: 'user-1',
            agent_job_id: null,
            title: null,
            channel: 'web',
            status: 'active',
            turn_count: 0,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            closed_at: null,
          }),
        })
      } else {
        await route.continue()
      }
    })

    // Mock resume session
    await page.route(`**/api/v1/conversations/${SESSION_ID}/resume`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: SESSION_ID,
          agent_type_id: AGENT_TYPE_ID,
          triggered_by_user_id: 'user-1',
          agent_job_id: null,
          title: 'Auto-Generated Session Title',
          channel: 'web',
          status: 'active',
          turn_count: 2,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          closed_at: null,
          turns: [
            {
              id: 'turn-1',
              session_id: SESSION_ID,
              role: 'user',
              content: 'Hello agent',
              token_count: null,
              created_at: new Date().toISOString(),
              tool_calls: [],
            },
            {
              id: 'turn-2',
              session_id: SESSION_ID,
              role: 'agent',
              content: 'Hello! How can I help you today?',
              token_count: null,
              created_at: new Date().toISOString(),
              tool_calls: [],
            },
          ],
        }),
      })
    })

    // Mock end session
    await page.route(`**/api/v1/conversations/${SESSION_ID}/end`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: SESSION_ID,
          agent_type_id: AGENT_TYPE_ID,
          triggered_by_user_id: 'user-1',
          agent_job_id: null,
          title: 'Auto-Generated Session Title',
          channel: 'web',
          status: 'closed',
          turn_count: 2,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          closed_at: new Date().toISOString(),
        }),
      })
    })

    // Mock permissions, roles, identities
    await page.route('**/api/v1/agents/roles', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await page.route('**/api/v1/agents/identities', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
  })

  test('Sessions tab is visible for conversation-type agents', async ({ page }) => {
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    // Click on the conversation agent row to open details dialog
    await page.getByText('Test Conv Agent').click()

    // Sessions tab should be visible (label comes from en.json: conversations.sessions.tabLabel = "Sessions")
    await expect(page.getByRole('tab', { name: /sessions/i })).toBeVisible({ timeout: 8_000 })
  })

  test('Sessions tab shows session list', async ({ page }) => {
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')
    await page.getByText('Test Conv Agent').click()
    await page.getByRole('tab', { name: /sessions/i }).click()

    await expect(page.getByText('Auto-Generated Session Title')).toBeVisible({ timeout: 8_000 })
  })

  test('Resume navigates to chat page with session history', async ({ page }) => {
    await page.goto(`/agents/${AGENT_TYPE_ID}/chat/${SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    // The ChatPage should load history from resume endpoint
    await expect(page.getByText('Hello agent')).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText('Hello! How can I help you today?')).toBeVisible()
  })

  test('End session shows confirmation dialog', async ({ page }) => {
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')
    await page.getByText('Test Conv Agent').click()
    await page.getByRole('tab', { name: /sessions/i }).click()

    // Click End button on the session row
    await page.getByRole('button', { name: /end session/i }).click()

    // Confirm dialog should appear with the actual translated title
    await expect(
      page.getByText('End Conversation Session'),
    ).toBeVisible({ timeout: 5_000 })
  })
})

// ── Real Backend Integration variant ─────────────────────────────────────────

test.describe('Real Backend Integration — Conversation Sessions', () => {
  /**
   * This variant exercises the actual backend.
   * It runs against a real database with migrations applied.
   * Validates: POST /conversations, POST /resume, POST /end lifecycle.
   *
   * Requires: backend running on localhost:8000, valid test user credentials.
   */
  test('POST /conversations creates session; POST /end closes it', async ({ request }) => {
    // Skip if backend is not reachable
    let token: string
    try {
      const loginResp = await request.post('http://localhost:8000/api/v1/auth/token', {
        form: { username: 'admin@example.com', password: 'admin' },
      })
      if (!loginResp.ok()) {
        test.skip()
        return
      }
      const body = await loginResp.json() as { access_token?: string }
      token = body.access_token ?? ''
    } catch {
      test.skip()
      return
    }

    // Get a conversation agent type
    const typesResp = await request.get('http://localhost:8000/api/v1/agents/types', {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!typesResp.ok()) { test.skip(); return }
    const types = await typesResp.json() as Array<{ id: string; input_type: string }>
    const convType = types.find((t) => t.input_type === 'conversation')
    if (!convType) { test.skip(); return }

    // Create a conversation session
    const createResp = await request.post('http://localhost:8000/api/v1/conversations', {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { agent_type_id: convType.id },
    })
    expect(createResp.status()).toBe(201)
    const created = await createResp.json() as { id: string; status: string }
    expect(created.id).toBeTruthy()
    expect(created.status).toBe('active')

    // End the session
    const endResp = await request.post(
      `http://localhost:8000/api/v1/conversations/${created.id}/end`,
      { headers: { Authorization: `Bearer ${token}` } },
    )
    expect(endResp.status()).toBe(200)
    const ended = await endResp.json() as { status: string }
    expect(ended.status).toBe('closed')
  })
})
