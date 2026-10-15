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


function mockEnabledModels(page: Page, models: Array<Record<string, unknown>> = []) {
  // Both feed endpoints must return ARRAYS — the catch-all's `{}` would
  // crash list rendering (defensive mocking for the multi-provider feeds).
  return Promise.all([
    page.route(/\/api\/v1\/system-one\/enabled-models$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(models),
      }),
    ),
    page.route(/\/api\/v1\/decision-tools\/enabled-models$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(models),
      }),
    ),
    // model hierarchy feed: empty array default (tests needing entries
    // register their own /system-one/models route, which takes priority)
    page.route(/\/api\/v1\/system-one\/models$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      }),
    ),
  ])
}

test.describe('System One Decision Tools (mocked)', () => {
  test('provider config journey enables the decision tool authoring gate', async ({
    page,
  }) => {
    await mockApiCatchAllProxyAware(page)
    await mockEnabledModels(page)
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
    await expect(dialog.getByRole('button', { name: 'Save' })).toBeDisabled()
    await dialog.getByText('Open Decision Model Providers config').click()
    await expect(page).toHaveURL(/system\/system-one/)
  })

  test('decision tool authoring journey: create tool with questions and description preview', async ({
    page,
  }) => {
    await mockApiCatchAllProxyAware(page)
    await mockEnabledModels(page)
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

    // Typed-input flow: state mapping requires an input data type. Register
    // the mock BEFORE the dialog mounts (it fetches the catalogue on open).
    const DATA_TYPE = {
      id: 'dt-22222222-3333-4444-5555-666666666666',
      name: 'Loan Application',
      slug: 'loan-application',
      description: 'Input loan fields',
      fields: [{ name: 'amount', type: 'number', description: 'Loan amount' }],
    }
    await page.route(/\/api\/v1\/data-types/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [DATA_TYPE], total: 1 }),
      }),
    )

    await standardSetup(page)
    await page.goto('/agents/decision-tools')

    await page.getByRole('button', { name: 'Add Decision Tool' }).click()
    const dialog = page.getByRole('dialog')

    // Gate open: configured hint visible.
    await expect(
      dialog.getByText('Decision Model available: jev-latest (typesafe)'),
    ).toBeVisible({ timeout: 10_000 })

    await dialog.getByLabel('Tool Name').fill('approve-loan')
    await dialog.getByLabel('Purpose').fill('Approve or reject loan applications')

    // Question builder: questions are optional — add a manual row first.
    await dialog.getByRole('button', { name: 'Add Question' }).click()
    await dialog.getByLabel('Question Key').fill('approve')
    await dialog.getByLabel('Option key').fill('yes')
    await dialog.getByLabel('Option description').fill('Approve')

    // Select the input data type (state preset maps from its properties).
    await dialog.getByLabel('Input Data Type').click()
    await page.getByRole('option', { name: 'Loan Application (loan-application)' }).click()

    // Expand the State Preset accordion if collapsed, then add the mapping.
    const presetHeading = dialog.getByText('State Preset')
    const summary = presetHeading.locator(
      'xpath=ancestor-or-self::*[@aria-expanded]',
    )
    if ((await summary.count()) > 0 && (await summary.first().getAttribute('aria-expanded')) !== 'true') {
      await presetHeading.click()
    }
    await dialog.getByRole('button', { name: 'Add State Mapping' }).click()
    await dialog.getByLabel('Input Property').click()
    await page.getByRole('option', { name: 'amount', exact: true }).click()
    await dialog.getByLabel('State Key').fill('amount')

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

    // List shows the saved tool (the retired `decision:` display prefix is
    // gone — MCP exposure as `decision____<name>` is internal only).
    await expect(
      page.locator('table tbody tr', { hasText: 'approve-loan' }),
    ).toBeVisible()
  })

  test('duplicate tool name shows a structured error and keeps the dialog open', async ({
    page,
  }) => {
    await mockApiCatchAllProxyAware(page)
    await mockEnabledModels(page)
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
      dialog.getByText('Decision Model available: jev-latest (typesafe)'),
    ).toBeVisible({ timeout: 10_000 })
    await dialog.getByLabel('Tool Name').fill('approve-loan')
    await dialog.getByLabel('Purpose').fill('Duplicate attempt')
    await dialog.getByRole('button', { name: 'Add Question' }).click()
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
    await mockEnabledModels(page)

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
    await mockEnabledModels(page)
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
      dialog.getByText('Decision Model available: jev-latest (typesafe)'),
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
    // The State Preset accordion may be collapsed — expand it first.
    const presetHeading = dialog.getByText('State Preset')
    if ((await presetHeading.locator('xpath=ancestor-or-self::*[@aria-expanded]').first().getAttribute('aria-expanded')) !== 'true') {
      await presetHeading.click()
    }
    await dialog.getByRole('button', { name: 'Add State Mapping' }).click()
    await dialog.getByLabel('Input Property').click()
    await page.getByRole('option', { name: 'amount', exact: true }).click()
    await dialog.getByLabel('State Key').fill('amount')

    // State keys auto-match input properties 1:1 (the retired
    // "auto-detect placeholders" flow is superseded): adding a state key
    // named like the input property needs no explicit mapping.
    await dialog.getByRole('button', { name: 'Add State Mapping' }).click()
    await dialog.getByLabel('State Key').nth(1).fill('tier')

    await dialog.getByLabel('Tool Name').fill('typed-tool')
    await dialog.getByLabel('Purpose').fill('Round-2 typed journey')

    // AI generate fills the questions from the mocked draft.
    await dialog.getByRole('button', { name: 'Generate with AI' }).click()
    await expect(dialog.getByLabel('Question Key')).toHaveValue('risk', { timeout: 10_000 })
    expect(generateCalled).toBe(true)

    // The AI draft's `tier` mapping needs its input property selected
    // (the combobox without a value is the unmapped draft row).
    await dialog
      .getByRole('combobox', { name: 'Input Property', exact: true })
      .click()
    await page.getByRole('option', { name: 'tier', exact: true }).click()
    await dialog.getByRole('button', { name: 'Save' }).click()

    await expect.poll(() => createdPayload).toBeTruthy()
    const payload = createdPayload as Record<string, unknown>
    expect(payload['input_data_type_id']).toBe(DATA_TYPE.id)
    // the draft's tier mapping is present with the correct shape (the
    // preset may also carry the manually added rows)
    expect(payload['state_preset']).toMatchObject({
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
    await mockEnabledModels(page)

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

// ── Decision Model Providers journeys (mocked, per test-plan §4.1–4.3) ─────

const PROVIDER = {
  id: 'p-e2e-1',
  provider_type: 'typesafe',
  display_name: 'E2E Primary Vendor',
  base_url: 'https://api.typesafe.example/v1',
  default_model: 'jev-latest',
  enabled: true,
  enabled_models: ['jev-latest', 'jev-mini'],
  has_api_key: true,
}

const HIERARCHY = [
  {
    provider_id: PROVIDER.id,
    display_name: PROVIDER.display_name,
    provider_type: 'typesafe',
    default_model: 'jev-latest',
    is_disabled: false,
    models: [
      {
        availability_id: 'av-1',
        model_name: 'jev-latest',
        effective_is_disabled: false,
        disabled_reason: 'manual',
      },
      {
        availability_id: 'av-2',
        model_name: 'jev-mini',
        effective_is_disabled: false,
        disabled_reason: 'manual',
      },
    ],
  },
]

test.describe('Decision Model Providers (mocked)', () => {
  test('settings > navigation and page header show "Decision Model Providers" with no trace of "System One Providers"', async ({
    page,
  }) => {
    await mockApiCatchAllProxyAware(page)
    await mockEnabledModels(page)
    await mockStatus(page, true)
    await page.route(/\/api\/v1\/system-one\/providers$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([PROVIDER]),
      }),
    )
    await page.route(/\/api\/v1\/system-one\/models$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(HIERARCHY),
      }),
    )

    await standardSetup(page)
    await page.goto('/system/system-one')

    // Page header uses the renamed term.
    await expect(
      page.getByRole('heading', { name: 'Decision Model Providers' }),
    ).toBeVisible()
    // No legacy "System One Provider(s)" string anywhere in the rendered DOM
    // (internal identifiers like "system-one" in URLs are exempt).
    const body = await page.locator('body').innerText()
    expect(body).not.toMatch(/System One Providers?/i)
  })

  test('settings > admin creates a decision model provider and sees it appear without reload', async ({
    page,
  }) => {
    await mockApiCatchAllProxyAware(page)
    await mockEnabledModels(page)
    let providers = [PROVIDER]
    await page.route(/\/api\/v1\/system-one\/providers$/, async (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(providers),
        })
      }
      if (route.request().method() === 'POST') {
        const body = route.request().postDataJSON() as Record<string, unknown>
        providers = [
          ...providers,
          {
            ...PROVIDER,
            id: 'p-e2e-new',
            display_name: body['display_name'] as string,
            base_url: body['base_url'] as string,
            has_api_key: true,
          },
        ]
        return route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify(providers[providers.length - 1]),
        })
      }
      return route.fulfill({ status: 405, body: '{}' })
    })
    await page.route(/\/api\/v1\/system-one\/models$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(HIERARCHY),
      }),
    )

    await standardSetup(page)
    await page.goto('/system/system-one')
    const rowsBefore = await page.locator('table tbody tr').count()

    await page.getByRole('button', { name: 'Add Provider' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    // Terminology: dialog title + help text use the new term keys.
    await expect(dialog.getByText('Add Provider')).toBeVisible()
    await dialog.getByLabel('Display Name').fill('E2E Second Vendor')
    await dialog.getByLabel('API Key', { exact: false }).fill('sk-e2e-provider-key')
    await dialog.getByRole('button', { name: 'Save' }).click()

    await expect(dialog).not.toBeVisible({ timeout: 10_000 })
    // Table gains the row WITHOUT a page reload (row count grows in-place).
    await expect(page.getByText('E2E Second Vendor')).toBeVisible({
      timeout: 10_000,
    })
    const rowsAfter = await page.locator('table tbody tr').count()
    expect(rowsAfter).toBeGreaterThan(rowsBefore)
    // Stored-credential chip is shown, never the key itself.
    await expect(page.getByText('Stored').first()).toBeVisible()
    expect(await page.locator('body').innerText()).not.toContain('sk-e2e-provider-key')
  })

  test('settings > admin cannot delete a provider referenced by a decision tool (error inside the confirm dialog)', async ({
    page,
  }) => {
    await mockApiCatchAllProxyAware(page)
    await mockEnabledModels(page)
    await page.route(/\/api\/v1\/system-one\/providers$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([PROVIDER]),
      }),
    )
    await page.route(/\/api\/v1\/system-one\/models$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(HIERARCHY),
      }),
    )
    await page.route(/\/api\/v1\/system-one\/providers\/.+$/, (route) =>
      route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({
          detail:
            "Provider 'E2E Primary Vendor' cannot be deleted while decision tools reference its models: approve-loan",
        }),
      }),
    )

    await standardSetup(page)
    await page.goto('/system/system-one')
    await expect(page.getByText('E2E Primary Vendor')).toBeVisible()

    await page.getByRole('button', { name: 'Delete' }).first().click()
    const confirm = page.getByRole('dialog')
    await expect(confirm).toBeVisible()
    await confirm.getByRole('button', { name: 'Delete' }).click()

    // Blocking error names the tool and the provider row remains.
    await expect(
      page.getByText(/cannot be deleted while decision tools reference/),
    ).toBeVisible({ timeout: 10_000 })
    await expect(
      page.getByText('E2E Primary Vendor', { exact: true }),
    ).toBeVisible()
  })

  test('settings > inline model catalogue drawer removed; embedded guardrail section renders decision-scoped data', async ({
    page,
  }) => {
    await mockApiCatchAllProxyAware(page)
    await mockEnabledModels(page)
    await page.route(/\/api\/v1\/system-one\/providers$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([PROVIDER]),
      }),
    )
    await page.route(/\/api\/v1\/system-one\/models$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(HIERARCHY),
      }),
    )
    const guardrailCalls: string[] = []
    await page.route(/\/api\/v1\/system-one\/providers\/.+\/guardrails$/, (route) => {
      guardrailCalls.push(route.request().url())
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'g-1',
            decision_provider_id: PROVIDER.id,
            model_id: null,
            model_name: 'jev-latest',
            period: 'day',
            limit_value: 100,
            unit: 'k',
            enforcement_posture: 'terminate',
            is_active: true,
            details: {},
            created_at: '2026-10-14T00:00:00Z',
            updated_at: '2026-10-14T00:00:00Z',
          },
        ]),
      })
    })
    await page.route(
      /\/api\/v1\/system-one\/providers\/.+\/guardrails\/posture/,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([]),
        }),
    )
    // No availability toggle may ever fire — model management lives in the
    // editor dialog now.
    let availabilityCalls = 0
    await page.route(/\/api\/v1\/system-one\/.+\/availability$/, (route) => {
      availabilityCalls += 1
      return route.fulfill({ status: 200, body: '{}' })
    })

    await standardSetup(page)
    await page.goto('/system/system-one')
    await expect(page.getByText('E2E Primary Vendor')).toBeVisible()

    // The drawer is gone: no "Manage models" control, no cascade switch.
    await expect(page.getByRole('button', { name: 'Manage models' })).toHaveCount(0)
    await expect(page.getByText('Provider enabled (cascades to all models)')).toHaveCount(0)

    // Embedded guardrail section: open it and verify the reused panel with
    // decision-scoped data (decision endpoints, never the LLM ones).
    await page.getByTestId('guardrails-section-toggle').click()
    const panel = page.getByTestId('vendor-model-guardrail-panel')
    await expect(panel).toBeVisible({ timeout: 10_000 })
    await expect(panel.getByText('E2E Primary Vendor')).toBeVisible()
    await expect
      .poll(() => guardrailCalls.length, { timeout: 10_000 })
      .toBeGreaterThan(0)
    expect(guardrailCalls[0]).toContain(`/system-one/providers/${PROVIDER.id}/guardrails`)
    expect(availabilityCalls).toBe(0)
  })


  test('decision tools > model selector lists only enabled models and submits the availability id', async ({
    page,
  }) => {
    await mockApiCatchAllProxyAware(page)
    await mockEnabledModels(page)
    await mockStatus(page, true)
    await page.route(/\/api\/v1\/system-one\/enabled-models$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            availability_id: 'av-1',
            provider_id: PROVIDER.id,
            provider_type: 'typesafe',
            provider_display_name: PROVIDER.display_name,
            model_name: 'jev-latest',
          },
        ]),
      }),
    )
    await page.route(/\/api\/v1\/data-types/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total: 0 }),
      }),
    )

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
      dialog.getByText('Decision Model available: jev-latest (typesafe)'),
    ).toBeVisible({ timeout: 10_000 })

    // Selector lists ONLY the enabled model(s), with provider identity.
    await dialog.getByLabel('Decision Model').click()
    await page
      .getByRole('option', { name: /jev-latest — E2E Primary Vendor/ })
      .click()
    // disabled models are absent — only the single enabled option existed
    await dialog.getByLabel('Tool Name').fill('selector-tool')
    await dialog.getByLabel('Purpose').fill('Model selection journey')
    await dialog.getByRole('button', { name: 'Add Question' }).click()
    await dialog.getByLabel('Question Key').fill('approve')
    await dialog.getByLabel('Option key').fill('yes')
    await dialog.getByLabel('Option description').fill('Approve')
    await dialog.getByRole('button', { name: 'Save' }).click()

    await expect.poll(() => createdPayload).toBeTruthy()
    expect((createdPayload as Record<string, unknown>)['decision_model_availability_id']).toBe(
      'av-1',
    )
  })

  test('settings > editing a provider pre-populates the dialog and keeps the stored credential when the API key field is left empty', async ({
    page,
  }) => {
    await mockApiCatchAllProxyAware(page)
    await mockEnabledModels(page)
    let providers = [{ ...PROVIDER }]
    await page.route(/\/api\/v1\/system-one\/providers$/, async (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(providers),
        })
      }
      return route.fulfill({ status: 405, body: '{}' })
    })
    await page.route(/\/api\/v1\/system-one\/models$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(HIERARCHY),
      }),
    )

    let updatePayload: Record<string, unknown> | null = null
    await page.route(/\/api\/v1\/system-one\/providers\/[^/]+$/, async (route) => {
      if (route.request().method() === 'PATCH') {
        updatePayload = route.request().postDataJSON() as Record<string, unknown>
        providers = [{ ...PROVIDER, display_name: 'E2E Renamed Vendor' }]
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(providers[0]),
        })
      }
      return route.fulfill({ status: 405, body: '{}' })
    })

    await standardSetup(page)
    await page.goto('/system/system-one')
    await expect(page.getByText('E2E Primary Vendor')).toBeVisible()

    // Open the edit dialog.
    await page.getByRole('button', { name: 'Edit' }).first().click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    // Pre-populated with current values; API key is write-only and NEVER prefilled.
    await expect(dialog.getByLabel('Display Name')).toHaveValue('E2E Primary Vendor')
    const apiKeyValue = await dialog
      .getByLabel('API Key', { exact: false })
      .inputValue()
    expect(apiKeyValue).toBe('')

    // Change only the display name; leave the API key field empty (placeholder semantics).
    await dialog.getByLabel('Display Name').fill('E2E Renamed Vendor')
    await dialog.getByRole('button', { name: 'Save' }).click()

    await expect(dialog).not.toBeVisible({ timeout: 10_000 })
    // Table refreshes automatically, no reload.
    await expect(page.getByText('E2E Renamed Vendor')).toBeVisible({ timeout: 10_000 })

    // The PUT payload must NOT contain api_key — submitting nothing keeps the stored secret.
    await expect.poll(() => updatePayload).toBeTruthy()
    expect(updatePayload).not.toHaveProperty('api_key')
    // The stored key never leaks into the DOM.
    expect(await page.locator('body').innerText()).not.toContain('sk-e2e-primary-key')
  })

  test('settings > duplicate provider display name is rejected with a visible error inside the dialog', async ({
    page,
  }) => {
    await mockApiCatchAllProxyAware(page)
    await mockEnabledModels(page)
    await page.route(/\/api\/v1\/system-one\/providers$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([PROVIDER]),
      }),
    )
    await page.route(/\/api\/v1\/system-one\/models$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(HIERARCHY),
      }),
    )
    await page.route(/\/api\/v1\/system-one\/providers$/, async (route) => {
      if (route.request().method() === 'POST') {
        return route.fulfill({
          status: 409,
          contentType: 'application/json',
          body: JSON.stringify({
            detail:
              "A provider with display name 'E2E Primary Vendor' already exists for this vendor type",
          }),
        })
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([PROVIDER]),
      })
    })

    await standardSetup(page)
    await page.goto('/system/system-one')
    await page.getByRole('button', { name: 'Add Provider' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await dialog.getByLabel('Display Name').fill('E2E Primary Vendor')
    await dialog.getByLabel('API Key', { exact: false }).fill('sk-duplicate-key')
    await dialog.getByRole('button', { name: 'Save' }).click()

    // Error is surfaced INSIDE the dialog; the dialog stays open (no silent failure).
    await expect(dialog).toBeVisible({ timeout: 10_000 })
    await expect(dialog.getByText(/already exists for this vendor type/)).toBeVisible({
      timeout: 10_000,
    })
    // Terminology: the error copy must not resurrect the legacy term.
    expect(await dialog.innerText()).not.toMatch(/System One Providers?/i)
  })

  test('settings > admin deletes an unreferenced provider and can recreate the same name afterwards', async ({
    page,
  }) => {
    await mockApiCatchAllProxyAware(page)
    await mockEnabledModels(page)
    let providers = [{ ...PROVIDER }]
    const deletedIds: string[] = []
    await page.route(/\/api\/v1\/system-one\/providers$/, async (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(providers),
        })
      }
      if (route.request().method() === 'POST') {
        const body = route.request().postDataJSON() as Record<string, unknown>
        const created = {
          ...PROVIDER,
          id: 'p-e2e-recreated',
          display_name: body['display_name'] as string,
        }
        providers = [...providers, created]
        return route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify(created),
        })
      }
      return route.fulfill({ status: 405, body: '{}' })
    })
    await page.route(/\/api\/v1\/system-one\/providers\/[^/]+$/, async (route) => {
      if (route.request().method() === 'DELETE') {
        deletedIds.push(route.request().url())
        providers = []
        return route.fulfill({ status: 204, body: '' })
      }
      return route.fulfill({ status: 405, body: '{}' })
    })
    await page.route(/\/api\/v1\/system-one\/models$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(HIERARCHY),
      }),
    )

    await standardSetup(page)
    await page.goto('/system/system-one')
    await expect(page.getByText('E2E Primary Vendor')).toBeVisible()

    // Delete the (unreferenced) provider.
    await page.getByRole('button', { name: 'Delete' }).first().click()
    const confirm = page.getByRole('dialog')
    await expect(confirm).toBeVisible()
    await confirm.getByRole('button', { name: 'Delete' }).click()

    // Confirm dialog closes, then the row disappears — all without reload.
    await expect(confirm).not.toBeVisible({ timeout: 10_000 })
    expect(deletedIds.length).toBe(1)
    // No providers row remains (the models hierarchy table may still render).
    await expect(
      page.locator('table tbody tr', { hasText: 'E2E Primary Vendor' }),
    ).toHaveCount(0, { timeout: 10_000 })

    // Recreate with the identical display name → succeeds (proves true deletion).
    await page.getByRole('button', { name: 'Add Provider' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await dialog.getByLabel('Display Name').fill('E2E Primary Vendor')
    await dialog.getByLabel('API Key', { exact: false }).fill('sk-recreated-key')
    await dialog.getByRole('button', { name: 'Save' }).click()
    await expect(dialog).not.toBeVisible({ timeout: 10_000 })
    await expect(page.getByText('E2E Primary Vendor')).toBeVisible({ timeout: 10_000 })
  })

  test('decision tools > disabling a model removes it from the tool model selector without reload', async ({
    page,
  }) => {
    await mockApiCatchAllProxyAware(page)
    await mockStatus(page, true)
    await page.route(/\/api\/v1\/data-types/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total: 0 }),
      }),
    )

    // Simulates another admin disabling 'jev-mini' in a second context.
    let enabledModels = [
      {
        availability_id: 'av-1',
        provider_id: PROVIDER.id,
        provider_type: 'typesafe',
        provider_display_name: PROVIDER.display_name,
        model_name: 'jev-latest',
      },
      {
        availability_id: 'av-2',
        provider_id: PROVIDER.id,
        provider_type: 'typesafe',
        provider_display_name: PROVIDER.display_name,
        model_name: 'jev-mini',
      },
    ]
    const feed = () =>
      Promise.all([
        page.route(/\/api\/v1\/system-one\/enabled-models$/, (route) =>
          route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(enabledModels),
          }),
        ),
        page.route(/\/api\/v1\/decision-tools\/enabled-models$/, (route) =>
          route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(enabledModels),
          }),
        ),
      ])
    const unrouteFeeds = () =>
      Promise.all([
        page.unroute(/\/api\/v1\/system-one\/enabled-models$/),
        page.unroute(/\/api\/v1\/decision-tools\/enabled-models$/),
      ])

    await mockEnabledModels(page)
    await feed()
    await page.route(/\/api\/v1\/decision-tools$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      }),
    )
    await standardSetup(page)
    await page.goto('/agents/decision-tools')
    await page.getByRole('button', { name: 'Add Decision Tool' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Decision Model').click()
    // Both models offered while both are enabled.
    await expect(page.getByRole('option', { name: /jev-latest — E2E Primary Vendor/ })).toBeVisible()
    await expect(page.getByRole('option', { name: /jev-mini — E2E Primary Vendor/ })).toBeVisible()
    await page.keyboard.press('Escape')

    // jev-mini becomes disabled elsewhere → refresh the feed and reopen the selector.
    enabledModels = enabledModels.filter((m) => m['model_name'] !== 'jev-mini')
    await unrouteFeeds()
    await feed()
    await page.reload()
    await page.getByRole('button', { name: 'Add Decision Tool' }).click()
    await dialog.getByLabel('Decision Model').click()
    await expect(page.getByRole('option', { name: /jev-latest — E2E Primary Vendor/ })).toBeVisible()
    // The disabled model is absent — no silent fallback, just filtered out.
    await expect(page.getByRole('option', { name: /jev-mini — E2E Primary Vendor/ })).toHaveCount(0)
  })
})
