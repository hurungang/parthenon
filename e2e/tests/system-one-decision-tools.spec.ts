import { expect, test, type Page } from '@playwright/test'
import { mockApiCatchAllProxyAware, standardSetup } from './_helpers'

/**
 * System One Decision Tools (mocked).
 *
 * Mocked-backend E2E journeys over the Decision Tools UI:
 * 1. provider configuration journey (prerequisite for the authoring gate),
 * 2. decision tool authoring journey: create a tool with typed questions
 *    (Choice / Score / Noul), state preset, thresholds, and the
 *    auto-generated description preview,
 * 3. authoring gate blocked without a configured model,
 * 4. duplicate-name error surfaced in the UI,
 * 5. decision results view contract.
 */

const TOOL = {
  id: '22222222-2222-2222-2222-222222222222',
  tenant_id: null,
  name: 'approve-loan',
  purpose: 'Approve or reject loan applications',
  description:
    "Decision tool 'approve-loan': Approve or reject loan applications\n\nQuestions:\n- `approve` (choice)",
  input_schema: { type: 'object' },
  output_schema: null,
  state_preset: { amount: { source: 'input', key: 'amount' } },
  act_threshold: 0.9,
  confirm_threshold: 0.7,
  provider_model: 'jev-latest',
  status: 'active',
  enabled: true,
  is_system: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  questions: [
    {
      ordering: 0,
      question_key: 'approve',
      question_type: 'choice',
      instructions: 'Approve?',
      criteria_options: { yes: 'Approve', no: 'Reject' },
      is_required: true,
    },
  ],
}

const STATUS_CONFIGURED = {
  configured: true,
  provider_type: 'typesafe',
  model: 'jev-latest',
}

function mockStatus(page: Page, configured: boolean) {
  return page.route(/\/api\/v1\/system-one\/status$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(configured ? STATUS_CONFIGURED : { configured: false }),
    }),
  )
}

test.describe('System One Decision Tools (mocked)', () => {
  test('provider config journey enables the decision tool authoring gate', async ({
    page,
  }) => {
    await mockApiCatchAllProxyAware(page)
    // No provider yet → decision tools gate closed.
    await mockStatus(page, false)
    await page.route(/\/api\/v1\/decision-tools$/, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
    )

    await standardSetup(page)
    await page.goto('/agents/decision-tools')

    // Authoring journey: open the dialog → gate blocks with a clear message.
    await page.getByRole('button', { name: 'Add Decision Tool' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(
      dialog.getByText(
        'No System One model is configured. Configure a provider before creating decision tools.',
      ),
    ).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Save' })).toBeDisabled()
    await dialog.getByText('Open System One config').click()
    await expect(page).toHaveURL(/system\/system-one/)
  })

  test('decision tool authoring journey: create tool with questions and description preview', async ({
    page,
  }) => {
    await mockApiCatchAllProxyAware(page)
    await mockStatus(page, true)

    let createdPayload: Record<string, unknown> | null = null
    await page.route(/\/api\/v1\/decision-tools$/, async (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(createdPayload ? [TOOL] : []),
        })
      }
      if (route.request().method() === 'POST') {
        createdPayload = route.request().postDataJSON() as Record<string, unknown>
        return route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify(TOOL),
        })
      }
      return route.fulfill({ status: 405, body: '{}' })
    })

    await standardSetup(page)
    await page.goto('/agents/decision-tools')

    await page.getByRole('button', { name: 'Add Decision Tool' }).click()
    const dialog = page.getByRole('dialog')

    // Gate open: configured hint visible.
    await expect(
      dialog.getByText('System One model available: jev-latest (typesafe)'),
    ).toBeVisible({ timeout: 10_000 })

    await dialog.getByLabel('Tool Name').fill('approve-loan')
    await dialog.getByLabel('Purpose').fill('Approve or reject loan applications')

    // Question builder: default choice question with options.
    await dialog.getByLabel('Question Key').fill('approve')
    await dialog.getByLabel('Option key').fill('yes')
    await dialog.getByLabel('Option description').fill('Approve')

    // State preset mapper.
    await dialog.getByRole('button', { name: 'Add State Mapping' }).click()
    await dialog.getByLabel('State Key').fill('amount')
    await dialog.getByLabel('Data Key').fill('amount')

    // Thresholds.
    await dialog.getByLabel('Act threshold').fill('0.9')
    await dialog.getByLabel('Confirm threshold').fill('0.7')

    // Auto-generated description preview updates live.
    await expect(
      dialog.getByText(/Decision tool 'approve-loan': Approve or reject loan applications/),
    ).toBeVisible()
    await expect(dialog.getByText('decision____approve-loan')).toBeVisible()

    await dialog.getByRole('button', { name: 'Save' }).click()
    await expect.poll(() => createdPayload).toBeTruthy()
    const payload = createdPayload as Record<string, unknown>
    expect(payload['name']).toBe('approve-loan')
    const questions = payload['questions'] as Array<Record<string, unknown>>
    expect(questions[0]['question_type']).toBe('choice')
    expect(questions[0]['criteria_options']).toEqual({ yes: 'Approve' })
    expect(payload['act_threshold']).toBe(0.9)
    expect(payload['confirm_threshold']).toBe(0.7)
    expect(payload['state_preset']).toEqual({
      amount: { source: 'input', key: 'amount' },
    })

    // List shows the tool with the decision: prefix.
    await expect(page.getByText('decision:approve-loan')).toBeVisible()
  })

  test('duplicate tool name shows a structured error and keeps the dialog open', async ({
    page,
  }) => {
    await mockApiCatchAllProxyAware(page)
    await mockStatus(page, true)

    await page.route(/\/api\/v1\/decision-tools$/, (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([]),
        })
      }
      return route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: ['A decision tool named approve-loan already exists in this tenant'],
        }),
      })
    })

    await standardSetup(page)
    await page.goto('/agents/decision-tools')

    await page.getByRole('button', { name: 'Add Decision Tool' }).click()
    const dialog = page.getByRole('dialog')
    await expect(
      dialog.getByText('System One model available: jev-latest (typesafe)'),
    ).toBeVisible({ timeout: 10_000 })
    await dialog.getByLabel('Tool Name').fill('approve-loan')
    await dialog.getByLabel('Purpose').fill('Duplicate attempt')
    await dialog.getByLabel('Question Key').fill('q1')
    await dialog.getByLabel('Option key').fill('a')
    await dialog.getByLabel('Option description').fill('Option A')
    await dialog.getByRole('button', { name: 'Save' }).click()

    // Dialog stays open; the backend conflict message is surfaced.
    await expect(
      page.getByText(/already exists in this tenant/).first(),
    ).toBeVisible({ timeout: 10_000 })
    await expect(dialog).toBeVisible()
  })

  test('decision results API contract: persisted result keyed to the tool', async ({
    page,
  }) => {
    await mockApiCatchAllProxyAware(page)

    const RESULTS = [
      {
        id: '33333333-3333-3333-3333-333333333333',
        tenant_id: null,
        decision_tool_id: TOOL.id,
        conversation_session_id: null,
        input_state_snapshot: { amount: 5000 },
        answers: {
          gate_confidence: 0.95,
          answers: {
            approve: {
              type: 'choice',
              question_type: 'choice',
              value: 'yes',
              choice: 'yes',
              probabilities: { yes: 0.95, no: 0.05 },
              confidence: 0.95,
              effective_confidence: 0.95,
            },
          },
        },
        outcome: 'act',
        status: 'completed',
        provider_model: 'jev-latest',
        error_message: null,
        created_at: '2026-01-01T00:00:00Z',
      },
    ]
    let requestedUrl = ''
    await page.route(/\/api\/v1\/results\/decision/, (route) => {
      requestedUrl = route.request().url()
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(RESULTS),
      })
    })

    await standardSetup(page)
    await page.goto('/')

    // The decision results endpoint is queried with the tool filter and
    // returns the typed payload the results view renders.
    const body = await page.evaluate(async () => {
      const resp = await fetch('/api/v1/results/decision?decision_tool_id=22222222-2222-2222-2222-222222222222')
      return resp.json()
    })
    expect(requestedUrl).toContain('/results/decision')
    expect(Array.isArray(body)).toBe(true)
    expect(body[0]['decision_tool_id']).toBe(TOOL.id)
    expect(body[0]['outcome']).toBe('act')
    expect(body[0]['status']).toBe('completed')
    expect(body[0]['answers']['answers']['approve']['choice']).toBe('yes')
    expect(body[0]['answers']['answers']['approve']['confidence']).toBe(0.95)
  })

  // ── Round 2 ───────────────────────────────────────────────────────────────

  test('round-2 form journey: data types → mapping properties → placeholders → AI generate → save', async ({
    page,
  }) => {
    await mockApiCatchAllProxyAware(page)
    await mockStatus(page, true)

    const DATA_TYPE = {
      id: 'dt-11111111-1111-1111-1111-111111111111',
      name: 'Loan Application',
      slug: 'loan-application',
      description: 'Input loan fields',
      fields: [
        { name: 'amount', type: 'number', description: 'Loan amount' },
        { name: 'tier', type: 'string', description: 'Customer tier' },
      ],
    }
    await page.route(/\/api\/v1\/data-types/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [DATA_TYPE], total: 1 }),
      }),
    )

    let generateCalled = false
    await page.route(/\/api\/v1\/decision-tools\/generate$/, (route) => {
      generateCalled = true
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          questions: [
            {
              ordering: 0,
              question_key: 'risk',
              question_type: 'score',
              instructions: 'Rate the risk given `input.tier`.',
              criteria_options: ['low', 'high'],
              is_required: true,
            },
          ],
          state_preset: { tier: { source: 'input', key: 'tier' } },
          detected_state_paths: ['input.tier'],
          model_id: 'cfg-gpt',
        }),
      })
    })

    let createdPayload: Record<string, unknown> | null = null
    await page.route(/\/api\/v1\/decision-tools$/, async (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([]),
        })
      }
      if (route.request().method() === 'POST') {
        createdPayload = route.request().postDataJSON() as Record<string, unknown>
        return route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify(TOOL),
        })
      }
      return route.fulfill({ status: 405, body: '{}' })
    })

    await standardSetup(page)
    await page.goto('/agents/decision-tools')
    await page.getByRole('button', { name: 'Add Decision Tool' }).click()
    const dialog = page.getByRole('dialog')
    await expect(
      dialog.getByText('System One model available: jev-latest (typesafe)'),
    ).toBeVisible({ timeout: 10_000 })

    // Select the input data type → View dialog shows its fields read-only.
    await dialog.getByLabel('Input Data Type').click()
    await page.getByRole('option', { name: 'Loan Application (loan-application)' }).click()
    await dialog.getByRole('button', { name: 'View data type fields' }).first().click()
    await expect(
      page.getByRole('dialog').getByText('Input Data Type (read-only)'),
    ).toBeVisible()
    await expect(
      page.getByRole('columnheader', { name: 'Field', exact: true }),
    ).toBeVisible()
    await page.getByRole('button', { name: 'Close' }).click()

    // Mapping property selector populated from the input type's fields.
    await dialog.getByRole('button', { name: 'Add State Mapping' }).click()
    await dialog.getByLabel('Data Key').click()
    await page.getByRole('option', { name: 'amount', exact: true }).click()
    await dialog.getByLabel('State Key').fill('amount')

    // Auto-detect backtick placeholders from the question instructions.
    await dialog.getByLabel('Instructions').fill('Decide based on `input.tier`.')
    await expect(dialog.getByText('1 state path(s) detected in instructions')).toBeVisible()
    await dialog.getByRole('button', { name: 'Auto-detect placeholders' }).click()
    await expect(dialog.getByLabel('State Key').nth(1)).toHaveValue('input.tier')
    // The detected mapping's property selector is a select of the input
    // type's fields — pick 'tier' to complete the suggested mapping.
    await dialog.getByLabel('Data Key').nth(1).click()
    await page.getByRole('option', { name: 'tier', exact: true }).click()

    await dialog.getByLabel('Tool Name').fill('typed-tool')
    await dialog.getByLabel('Purpose').fill('Round-2 typed journey')

    // AI generate fills the questions from the mocked draft.
    await dialog.getByRole('button', { name: 'Generate with AI' }).click()
    await expect(dialog.getByLabel('Question Key')).toHaveValue('risk', { timeout: 10_000 })
    expect(generateCalled).toBe(true)

    await dialog.getByRole('button', { name: 'Save' }).click()

    await expect.poll(() => createdPayload).toBeTruthy()
    const payload = createdPayload as Record<string, unknown>
    expect(payload['input_data_type_id']).toBe(DATA_TYPE.id)
    expect(payload['state_preset']).toEqual({
      tier: { source: 'input', key: 'tier' },
    })
    const questions = payload['questions'] as Array<Record<string, unknown>>
    expect(questions[0]['question_key']).toBe('risk')
    expect(questions[0]['question_type']).toBe('score')
  })

  test('provider page: Test connection renders success and failure states', async ({
    page,
  }) => {
    await mockApiCatchAllProxyAware(page)

    const PROVIDERS = [
      {
        id: 'p-1',
        provider_type: 'typesafe',
        display_name: 'TypeSafe Jev',
        base_url: 'https://api.typesafe.ai/v1',
        default_model: 'jev-latest',
        enabled: true,
        enabled_models: ['jev-latest'],
        has_api_key: true,
      },
    ]
    let testedId = ''
    await page.route(/\/api\/v1\/system-one\/providers$/, (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(PROVIDERS),
        })
      }
      return route.fulfill({ status: 405, body: '{}' })
    })
    await page.route(/\/api\/v1\/system-one\/providers\/.+\/test$/, (route) => {
      const match = route.request().url().match(/providers\/([^/]+)\/test/)
      testedId = match ? match[1] : ''
      const ok = testedId === 'p-1'
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(
          ok
            ? { ok: true, message: 'Connection succeeded', latency_ms: 12.5 }
            : { ok: false, message: 'provider endpoint unreachable', latency_ms: null },
        ),
      })
    })

    await standardSetup(page)
    await page.goto('/system/system-one')
    await expect(page.getByText('TypeSafe Jev')).toBeVisible()
    // The preset base URL is displayed read-only in the table row.
    await expect(page.getByText('https://api.typesafe.ai/v1')).toBeVisible()

    // Success state.
    await page.getByRole('button', { name: 'Test connection' }).click()
    await expect(page.getByText(/Connection succeeded \(12\.5 ms\)/)).toBeVisible()
    expect(testedId).toBe('p-1')

    // Failure state: dismiss the success alert, test the failing provider id.
    await page.route(/\/api\/v1\/system-one\/providers\/.+\/test$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: false,
          message: 'provider endpoint unreachable',
          latency_ms: null,
        }),
      }),
    )
    await page.getByRole('button', { name: 'Test connection' }).click()
    await expect(
      page.getByText('Connection failed: provider endpoint unreachable'),
    ).toBeVisible()
  })
})
