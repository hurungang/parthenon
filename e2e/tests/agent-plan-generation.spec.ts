import { expect, test, type Page, type Route } from '@playwright/test'
import { FAKE_TOKEN, mockApiCatchAllProxyAware, standardSetup } from './_helpers'

/**
 * E2E: System Config — the workspace authoring model (explicit generation).
 *
 * Fully mocked (mock-first convention, `page.route()`): no live backend.
 *
 * The single tenant-scoped authoring model (`workflow_generation_model_id`) is
 * the one model used by Skill/SOP workflow generation, implementation-plan
 * generation, and optimization-plan generation. The UI must explain those three
 * uses, state the workspace scope, recommend a larger model (advisory only),
 * and remind the operator while the setting is unset or stale
 * (docs/changes/separate-optimization-from-execution/test-plan.md —
 * "System Config: three uses, advisory recommendation, tenant scope, unset
 * reminder").
 *
 * This is also the destination of the Plan Preview / Optimize "Open System
 * Config" shortcuts when the authoring model blocks generation.
 */

test.describe.configure({ timeout: 90_000 })

// Copy resolved from `frontend/src/i18n/locales/en.json` (the only locale).
const SECTION_TITLE = 'Plan & Workflow Authoring Model'
const WORKSPACE_SCOPE =
  "Options are limited to this workspace's enabled model configurations."
const USE_SKILLS = 'Skill and SOP workflow generation'
const USE_IMPLEMENTATION = 'Implementation-plan generation'
const USE_OPTIMIZATION = 'Optimization-plan generation'
const REMINDER_UNSET =
  'No authoring model is configured for this workspace. Plan and workflow generation (including the Optimize action) is unavailable until you select one.'
const REMINDER_UNAVAILABLE =
  'The saved authoring model “{{modelId}}” is no longer available in this workspace. Re-select an enabled model.'
const UNAVAILABLE_OPTION = '{{modelId}} — no longer available'
const SAVE_SUCCESS = 'Settings saved successfully'

const OPTIONS = [
  {
    model_id: 'gpt-4o',
    config_id: 'mc-p1',
    config_display_name: 'Panel E2E GPT',
    provider_type: 'openai',
  },
  {
    model_id: 'gpt-4o-mini',
    config_id: 'mc-p1',
    config_display_name: 'Panel E2E Mini',
    provider_type: 'openai',
  },
]

interface AuthoringModelState {
  /** Current server-side stored selection (null ⇒ not configured). */
  selected: string | null
  /** Bodies of PUT /agents/model-configs/workflow-generation. */
  putBodies: Record<string, unknown>[]
  /** Number of GETs of the authoring-model endpoint. */
  reads: number
}

function json(route: Route, status: number, body: unknown) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

function workflowConfig(state: AuthoringModelState) {
  return { selected_model_id: state.selected, options: OPTIONS }
}

/**
 * Registers the System Config model endpoints. MUST be registered after the
 * catch-all (routes resolve last-registered-first).
 */
async function mockAuthoringModelApi(page: Page, state: AuthoringModelState) {
  await page.route(/\/api\/v1\/agents\/model-configs\/workflow-generation$/, (route) => {
    if (route.request().method() === 'GET') {
      state.reads += 1
      return json(route, 200, workflowConfig(state))
    }
    if (route.request().method() === 'PUT') {
      const body = route.request().postDataJSON() as { model_id?: string | null }
      state.putBodies.push(body)
      // The backend persists the (enabled) selection; the page re-reads it.
      state.selected = body.model_id ?? null
      return json(route, 200, workflowConfig(state))
    }
    return route.fallback()
  })

  // The page also loads the per-tenant assistant model — it has its own
  // endpoint and its own single save path (no options here, so it renders the
  // "no model configurations" note and no second combobox).
  await page.route(/\/api\/v1\/agents\/model-configs\/assistant-model$/, (route) =>
    json(route, 200, { selected_model_id: null, options: [] }),
  )
}

async function gotoSystemConfig(page: Page) {
  await page.goto('/system-config')
  await page.waitForLoadState('load')
  if (page.url().includes('/login')) {
    test.skip()
    return null
  }
  const section = page.getByTestId('authoring-model-section')
  await expect(section).toBeVisible()
  return section
}

test.describe('System Config — plan & workflow authoring model', () => {
  let state: AuthoringModelState

  test.beforeEach(async ({ page }) => {
    state = { selected: null, putBodies: [], reads: 0 }
    // Lowest-priority catch-all FIRST (handlers resolve last-registered-first).
    await mockApiCatchAllProxyAware(page)
    await page.addInitScript((token: string) => {
      localStorage.setItem('access_token', token)
    }, FAKE_TOKEN)
    await standardSetup(page)
    await mockAuthoringModelApi(page, state)
  })

  test('explains the three uses, the workspace scope, and the advisory larger-model recommendation', async ({
    page,
  }) => {
    const section = await gotoSystemConfig(page)
    if (!section) return

    await expect(section.getByText(SECTION_TITLE)).toBeVisible()
    // The three consumers of the single setting.
    await expect(section.getByText(USE_SKILLS)).toBeVisible()
    await expect(section.getByText(USE_IMPLEMENTATION)).toBeVisible()
    await expect(section.getByText(USE_OPTIMIZATION)).toBeVisible()

    // The choice is workspace-scoped, fed only by this workspace's catalogue.
    await expect(section.getByTestId('authoring-model-workspace-note')).toHaveText(
      WORKSPACE_SCOPE,
    )

    // Advisory recommendation: larger model preferred, agents' runtime models
    // are a separate choice, and it never blocks a save.
    const recommendation = section.getByTestId('authoring-model-recommendation')
    await expect(recommendation).toContainText('choose a larger, higher-end model')
    await expect(recommendation).toContainText('advisory')
    await expect(recommendation).toContainText('does not change the model your agents run on')
  })

  test('unset authoring model: reminder is visible, and saving a model clears it', async ({
    page,
  }) => {
    const section = await gotoSystemConfig(page)
    if (!section) return

    // Unset ⇒ a clearly visible reminder (plan/optimize are blocked until set).
    const reminder = section.getByTestId('authoring-model-reminder')
    await expect(reminder).toBeVisible()
    await expect(reminder).toHaveText(REMINDER_UNSET)

    // Pick an enabled model from this workspace's catalogue.
    await section.getByRole('combobox').click()
    await page.getByRole('option', { name: 'gpt-4o (Panel E2E GPT)' }).click()
    await section.getByRole('button', { name: 'Save' }).click()

    // Exactly one save path, with the selected model.
    await expect.poll(() => state.putBodies.length).toBe(1)
    expect(state.putBodies[0]).toEqual({ model_id: 'gpt-4o' })

    // The reminder disappears as soon as a valid selection is stored.
    await expect(page.getByText(SAVE_SUCCESS)).toBeVisible()
    await expect(section.getByTestId('authoring-model-reminder')).toHaveCount(0)
  })

  test('a stored model that is no longer available shows the re-select reminder and blocks saving it as-is', async ({
    page,
  }) => {
    state.selected = 'retired-model'
    const section = await gotoSystemConfig(page)
    if (!section) return

    const reminder = section.getByTestId('authoring-model-reminder')
    await expect(reminder).toBeVisible()
    await expect(reminder).toHaveText(
      REMINDER_UNAVAILABLE.replace('{{modelId}}', 'retired-model'),
    )

    // The stale value stays visible in the selector but cannot be saved as-is.
    await expect(section.getByRole('button', { name: 'Save' })).toBeDisabled()
    await section.getByRole('combobox').click()
    const staleOption = page.getByRole('option', {
      name: UNAVAILABLE_OPTION.replace('{{modelId}}', 'retired-model'),
    })
    await expect(staleOption).toBeVisible()
    await expect(staleOption).toHaveAttribute('aria-disabled', 'true')

    // Re-selecting an enabled model re-enables the single save path.
    await page.getByRole('option', { name: 'gpt-4o (Panel E2E GPT)' }).click()
    await expect(section.getByRole('button', { name: 'Save' })).toBeEnabled()
    await section.getByRole('button', { name: 'Save' }).click()
    await expect.poll(() => state.putBodies.length).toBe(1)
    expect(state.putBodies[0]).toEqual({ model_id: 'gpt-4o' })
    await expect(section.getByTestId('authoring-model-reminder')).toHaveCount(0)
  })

  test('the larger-model recommendation is advisory — a smaller enabled model saves fine', async ({
    page,
  }) => {
    state.selected = 'gpt-4o'
    const section = await gotoSystemConfig(page)
    if (!section) return

    await expect(section.getByRole('combobox')).toBeVisible()
    await section.getByRole('combobox').click()
    await page.getByRole('option', { name: 'gpt-4o-mini (Panel E2E Mini)' }).click()
    await section.getByRole('button', { name: 'Save' }).click()

    // Nothing blocked the save of the smaller model.
    await expect.poll(() => state.putBodies.length).toBe(1)
    expect(state.putBodies[0]).toEqual({ model_id: 'gpt-4o-mini' })
    await expect(page.getByText(SAVE_SUCCESS)).toBeVisible()
    await expect(section.getByTestId('authoring-model-reminder')).toHaveCount(0)
  })
})
