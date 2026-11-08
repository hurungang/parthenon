import { test, expect } from '@playwright/test'
import { mockApiCatchAllProxyAware, standardSetup } from './_helpers'

/**
 * Phase 5 task 5.5 — assistant-conversation UI journey (MOCKED WS/API layer).
 *
 * ⚠️ LABEL: this spec mocks the WebSocket + REST layers (page.route) — the
 * REAL conversation loop (prepare-turn → AR → human_intervene → CH-routed
 * cc____update_agent_type → persisted record) is proven end-to-end by the
 * backend integration test
 * `backend/tests/e2e/test_assistant_agent_type_update_e2e.py`. This spec
 * exists to assert the UI JOURNEY shape only (frontend is unchanged in this
 * change; this is journey-level coverage, not capability coverage).
 *
 * Journey asserted:
 *   1. The assistant conversation carries the canonical old → new preview
 *      (role assignment + input/output configuration).
 *   2. The approval intervention is presented and the approval is sent
 *      (POST …/respond with approval_value: true).
 *   3. After approval the Agent Types list reflects the updated state
 *      (role assignment + input/output configuration).
 */

const OLD_AGENT = {
  id: 'at-e2e-update',
  name: 'Ops Agent',
  description: '',
  identity_id: null,
  role_id: null,
  model_id: null,
  system_instruction: 'old instructions',
  input_type: 'none',
  output_type: 'auto',
  is_active: true,
  is_system: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const UPDATED_AGENT = {
  ...OLD_AGENT,
  role_id: 'role-1',
  input_type: 'typed',
  output_type: 'typed',
  system_instruction: 'new instructions',
  updated_at: '2026-11-08T00:00:00Z',
}

const PREVIEW_MARKDOWN = [
  '**Update Agent Type: Ops Agent**',
  '',
  '| Field | Value |',
  '| --- | --- |',
  '| role_id | (none) → Reviewer Role |',
  '| input_type | none → typed |',
  '| output_type | auto → typed |',
  '| system_instruction | old instructions → new instructions |',
].join('\n')

let approved = false

test.describe('Control Center Assistant — agent-type update journey (mocked WS/API)', () => {
  test.beforeEach(async ({ page }) => {
    // Lowest-priority hermetic catch-all FIRST — any API request not covered
    // by a specific mock below is fulfilled (never reaches the real backend,
    // whose 401 would trip the axios interceptor and abort the journey).
    await mockApiCatchAllProxyAware(page)
    await standardSetup(page)
    approved = false

    // The conversation WS layer is mocked at the transport level: the real
    // loop runs in backend tests; here the persisted outcome is served by
    // mocked REST reads (conversation turns + intervention records).
    await page.route('**/ws/**', (route) => route.abort())

    // Agent Types list: flips to the UPDATED record once approval is sent,
    // mirroring "persisted record matches all approved fields".
    await page.route('**/api/v1/agents/types*', (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          body: JSON.stringify(approved ? [UPDATED_AGENT] : [OLD_AGENT]),
        })
      }
      return route.fulfill({ status: 200, body: JSON.stringify(OLD_AGENT) })
    })
    await page.route('**/api/v1/agents/roles', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify([
          { id: 'role-1', name: 'Reviewer Role', description: '', is_active: true },
        ]),
      }),
    )
    await page.route('**/api/v1/agents/identities', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) }),
    )

    // Conversation session with the assistant's canonical preview turn.
    const iso = new Date().toISOString()
    await page.route('**/api/v1/conversations*', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify([
          {
            id: 'sess-at-update',
            agent_type_id: 'at-assistant',
            title: 'Update Ops Agent',
            channel: 'web',
            // The history list hides ACTIVE sessions — show it as closed.
            status: 'closed',
            turn_count: 3,
            created_at: iso,
            updated_at: iso,
          },
        ]),
      }),
    )
    await page.route('**/api/v1/conversations/sess-at-update*', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify({
          id: 'sess-at-update',
          agent_type_id: 'at-assistant',
          title: 'Update Ops Agent',
          channel: 'web',
          status: 'active',
          turn_count: 3,
          created_at: iso,
          updated_at: iso,
          turns: [
            {
              id: 't-1',
              session_id: 'sess-at-update',
              role: 'user',
              turn_type: 'message',
              content: 'Assign the Reviewer Role to Ops Agent and switch it to typed input/output.',
              intervene_request_id: null,
              token_count: null,
              created_at: iso,
              tool_calls: [],
            },
            {
              id: 't-2',
              session_id: 'sess-at-update',
              role: 'agent',
              turn_type: 'message',
              content: PREVIEW_MARKDOWN,
              intervene_request_id: 'req-at-update',
              token_count: null,
              created_at: iso,
              tool_calls: [],
            },
          ],
        }),
      }),
    )

    // Pending interventions: the confirmation approval for the preview.
    await page.route(
      '**/api/v1/conversations/sess-at-update/interventions/pending*',
      (route) =>
        route.fulfill({
          status: 200,
          body: JSON.stringify(
            approved
              ? []
              : [
                  {
                    id: 'req-at-update',
                    request_id: 'req-at-update',
                    intervention_type: 'approval',
                    reason: PREVIEW_MARKDOWN,
                    status: 'pending',
                    conversation_session_id: 'sess-at-update',
                    delegation_depth: 0,
                    created_at: iso,
                  },
                ],
          ),
        }),
    )

    // Approval POST — flips the mocked persisted state.
    await page.route(
      '**/api/v1/conversations/sess-at-update/interventions/*/respond*',
      async (route) => {
        approved = true
        const body = route.request().postDataJSON()
        expect(body.approval_value).toBe(true)
        return route.fulfill({
          status: 200,
          body: JSON.stringify({
            id: 'resp-at-update',
            request_id: 'req-at-update',
            operator_user_id: 'user-1',
            approval_value: true,
            responded_at: iso,
          }),
        })
      },
    )

    // The operator's intervention inbox carries the pending approval.
    await page.route('**/api/v1/intervene/requests*', (route) => {
      const url = route.request().url()
      if (url.includes('/respond')) {
        return route.continue()
      }
      return route.fulfill({
        status: 200,
        body: JSON.stringify(
          approved
            ? []
            : [
                {
                  id: 'req-at-update',
                  agent_session_id: null,
                  agent_type_id: 'at-assistant',
                  conversation_session_id: 'sess-at-update',
                  intervention_type: 'approval',
                  reason: PREVIEW_MARKDOWN,
                  status: 'pending',
                  delegation_depth: 0,
                  created_at: iso,
                },
              ],
        ),
      })
    })

    // Approving from the inbox sends the approval → the mocked persisted
    // state flips (asserted below via the updated Agent Types list).
    await page.route('**/api/v1/intervene/requests/*/respond*', async (route) => {
      approved = true
      const body = route.request().postDataJSON()
      expect(body.approval_value).toBe(true)
      return route.fulfill({
        status: 200,
        body: JSON.stringify({
          id: 'resp-at-update',
          request_id: 'req-at-update',
          operator_user_id: 'user-1',
          approval_value: true,
          responded_at: iso,
        }),
      })
    })
    await page.route('**/api/v1/intervene/metrics*', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify({ pending_count: 0, avg_response_time_seconds: 0, resolution_rate: 1 }),
      }),
    )
    await page.route('**/api/v1/health*', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify({ status: 'ok' }) }),
    )
  })

  test('preview is presented, approval is sent, and the list reflects the update', async ({
    page,
  }) => {
    // Step 1: expand the assistant conversation session and verify the
    // canonical old → new preview turn is rendered (role + input/output).
    await page.goto('/conversations')
    await page.waitForLoadState('load')
    await page.locator('table tbody tr').first().locator('button').first().click()
    await expect(page.getByText('**Update Agent Type: Ops Agent**')).toBeVisible()
    await expect(page.getByText('| role_id | (none) → Reviewer Role |')).toBeVisible()
    await expect(page.getByText('| input_type | none → typed |')).toBeVisible()

    // Step 3: approving from the intervention inbox sends approval_value:
    // true (asserted inside the respond mock) and resolves the request.
    await page.goto('/agents/intervene')
    await page.waitForLoadState('load')
    const respondButton = page.getByRole('button', { name: /respond/i }).first()
    await respondButton.click()
    // The approval dialog confirms the canonical preview — approve it.
    const approveButton = page.getByRole('button', { name: /approve|confirm|yes/i }).first()
    await approveButton.click()

    // Step 4: after approval, the Agent Types list reflects the persisted
    // update (role assignment + typed input/output configuration).
    await page.goto('/agents')
    await page.waitForLoadState('load')
    const row = page.locator('table').getByText('Ops Agent')
    await expect(row).toBeVisible()
    await expect(page.locator('table').getByText('Reviewer Role')).toBeVisible()
    await expect(page.locator('table').getByText('typed').first()).toBeVisible()
  })
})
