import { expect, test, type Page, type Route } from '@playwright/test'
import { FAKE_TOKEN, mockApiCatchAllProxyAware, standardSetup } from './_helpers'
import { mockPanelWorld, seedAgents } from './_agent_panel_world'
import {
  COPY,
  OPTIMIZER_MODEL_OPTIONS,
  TYPED_AGENT_ID,
  TYPED_AGENT_NAME,
  availableNow,
  gotoAgentsList,
  installFakeChatSocket,
  json,
  mockOptimizerApi,
  openAgentDialog,
  openOptimizedPlanTab,
  openOptimizerChat,
  readyPlan,
  typedGate,
  typedWorldState,
} from './_agent_optimizer_world'

/**
 * E2E: the workspace-scoped optimizer model
 * (`docs/changes/optimizer-conversational-agent/test-plan.md` → Optimizer-model
 * config API & System Config).
 *
 * Fully mocked (`page.route()`): no live backend.
 *
 * Journeys:
 *   1. System Config explains what the model powers (workspace scope, inherits
 *      the plan-authoring model, catalogue-only, no substitution) and shows the
 *      inherited state when nothing is selected;
 *   2. saving an explicit catalogue model writes exactly one selection; clearing
 *      submits `null` and falls back to inherit;
 *   3. a stale saved value stays visible (disabled), shows the re-select
 *      reminder and blocks Save until re-selected;
 *   4. a rejected save (422) is surfaced through the dialog error standard and
 *      keeps the previous selection;
 *   5. with no usable model the Optimized Plan entry is annotated with the
 *      reason + System Config shortcut, and the chat blocks the composer and
 *      points at System Config.
 */

test.describe.configure({ timeout: 120_000 })

interface OptimizerConfigState {
  selected: string | null
  effective: string | null
  source: 'optimizer' | 'authoring' | null
  configured: boolean
  enabled: boolean
  reason_code: string | null
  reads: number
  putBodies: Array<{ model_id: string | null }>
  reject422: boolean
}

function configState(overrides: Partial<OptimizerConfigState> = {}): OptimizerConfigState {
  return {
    selected: null,
    effective: 'gpt-4o',
    source: 'authoring',
    configured: true,
    enabled: true,
    reason_code: null,
    reads: 0,
    putBodies: [],
    reject422: false,
    ...overrides,
  }
}

function configPayload(state: OptimizerConfigState) {
  return {
    selected_model_id: state.selected,
    effective_model_id: state.effective,
    source: state.source,
    configured: state.configured,
    enabled: state.enabled,
    reason_code: state.reason_code,
    options: OPTIMIZER_MODEL_OPTIONS,
  }
}

/** Registers the optimizer-model config endpoints (tenant-scoped, mocked). */
async function mockOptimizerModelConfigApi(page: Page, state: OptimizerConfigState) {
  await page.route(/\/api\/v1\/agents\/model-configs\/optimizer-model$/, (route: Route) => {
    if (route.request().method() === 'GET') {
      state.reads += 1
      return json(route, 200, configPayload(state))
    }
    if (route.request().method() === 'PUT') {
      const body = route.request().postDataJSON() as { model_id?: string | null }
      state.putBodies.push({ model_id: body.model_id ?? null })
      if (state.reject422) {
        return json(route, 422, {
          detail: 'The chosen optimizer model is not enabled in this workspace.',
        })
      }
      if (body.model_id == null) {
        // Clearing falls back to the plan-authoring model — no second value.
        state.selected = null
        state.effective = 'gpt-4o'
        state.source = 'authoring'
        state.configured = true
        state.enabled = true
        state.reason_code = null
      } else {
        state.selected = body.model_id
        state.effective = body.model_id
        state.source = 'optimizer'
        state.configured = true
        state.enabled = true
        state.reason_code = null
      }
      return json(route, 200, configPayload(state))
    }
    return route.fallback()
  })

  // The page loads the other model settings too — keep them quiet and empty.
  await page.route(/\/api\/v1\/agents\/model-configs\/workflow-generation$/, (route: Route) =>
    json(route, 200, { selected_model_id: 'gpt-4o', options: OPTIMIZER_MODEL_OPTIONS }),
  )
  await page.route(/\/api\/v1\/agents\/model-configs\/assistant-model$/, (route: Route) =>
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
  const section = page.getByTestId('optimizer-model-section')
  await expect(section).toBeVisible()
  return section
}

/** Picks an option from the optimizer-model Select. */
async function pickOptimizerModel(page: Page, section: ReturnType<Page['getByTestId']>, name: string) {
  await section.getByRole('combobox').click()
  await page.getByRole('option', { name }).click()
}

test.describe('System Config — optimizer model (workspace-scoped)', () => {
  let state: OptimizerConfigState

  test.beforeEach(async ({ page }) => {
    state = configState()
    // Lowest-priority catch-all FIRST (handlers resolve last-registered-first).
    await mockApiCatchAllProxyAware(page)
    await page.addInitScript((token: string) => {
      localStorage.setItem('access_token', token)
    }, FAKE_TOKEN)
    await standardSetup(page)
    await mockOptimizerModelConfigApi(page, state)
  })

  test('explains scope, inherit-from-authoring and no substitution; shows the inherited state', async ({
    page,
  }) => {
    const section = await gotoSystemConfig(page)
    if (!section) return

    await expect(section.getByRole('heading', { name: COPY.systemConfigSection })).toBeVisible()
    await expect(section.getByTestId('optimizer-model-scope')).toHaveText(COPY.systemConfigScope)
    // It powers the optimization conversation — explicitly not a runtime model.
    await expect(section).toContainText('not a runtime model')
    // Unset inherits the plan-authoring model; there is no second setting.
    await expect(section).toContainText('leave it unset and optimization uses this workspace')
    // Workspace boundary + catalogue-only + no silent substitution.
    await expect(section).toContainText('changing it affects subsequent optimization in this workspace only')
    await expect(section).toContainText('Only models enabled in this workspace')
    await expect(section.getByTestId('optimizer-model-no-substitution')).toContainText(
      COPY.systemConfigNoSubstitutionPrefix,
    )
    // The derived state is the inherited plan-authoring model, no reminder.
    await expect(section.getByTestId('optimizer-model-state')).toHaveText(
      COPY.systemConfigStateInherited('gpt-4o'),
    )
    await expect(section.getByTestId('optimizer-model-reminder')).toHaveCount(0)

    // Catalogue-only options plus an explicit "inherit" entry.
    await section.getByRole('combobox').click()
    await expect(page.getByRole('option', { name: COPY.systemConfigInheritOption })).toBeVisible()
    await expect(page.getByRole('option', { name: 'gpt-4o (Panel E2E GPT)' })).toBeVisible()
    await expect(page.getByRole('option', { name: 'claude-sonnet (Anthropic)' })).toBeVisible()
    await page.keyboard.press('Escape')
  })

  test('saves an explicit catalogue model with a single PUT and reflects it', async ({ page }) => {
    const section = await gotoSystemConfig(page)
    if (!section) return

    await pickOptimizerModel(page, section, 'claude-sonnet (Anthropic)')
    await section.getByTestId('optimizer-model-save').click()

    await expect.poll(() => state.putBodies.length).toBe(1)
    expect(state.putBodies[0]).toEqual({ model_id: 'claude-sonnet' })
    await expect(page.getByText(COPY.saveSuccess)).toBeVisible()
    await expect(section.getByTestId('optimizer-model-state')).toHaveText(
      COPY.systemConfigStateSelected('claude-sonnet'),
    )
    await expect(section.getByTestId('optimizer-model-reminder')).toHaveCount(0)
  })

  test('clearing back to inherit submits null and falls back to the authoring model', async ({
    page,
  }) => {
    state = configState({
      selected: 'gpt-4o',
      effective: 'gpt-4o',
      source: 'optimizer',
    })
    await mockOptimizerModelConfigApi(page, state)
    const section = await gotoSystemConfig(page)
    if (!section) return

    await expect(section.getByTestId('optimizer-model-state')).toHaveText(
      COPY.systemConfigStateSelected('gpt-4o'),
    )

    await pickOptimizerModel(page, section, COPY.systemConfigInheritOption)
    await section.getByTestId('optimizer-model-save').click()

    await expect.poll(() => state.putBodies.length).toBe(1)
    // `null` clears the setting — the fallback is not written as a second value.
    expect(state.putBodies[0]).toEqual({ model_id: null })
    await expect(section.getByTestId('optimizer-model-state')).toHaveText(
      COPY.systemConfigStateInherited('gpt-4o'),
    )
  })

  test('a stale saved value stays visible, blocks Save, and can be re-selected', async ({ page }) => {
    state = configState({
      selected: 'retired-model',
      effective: null,
      source: 'optimizer',
      configured: false,
      enabled: false,
      reason_code: 'optimizer_model_not_enabled',
    })
    await mockOptimizerModelConfigApi(page, state)
    const section = await gotoSystemConfig(page)
    if (!section) return

    const reminder = section.getByTestId('optimizer-model-reminder')
    await expect(reminder).toBeVisible()
    await expect(reminder).toContainText('retired-model')
    await expect(reminder).toContainText('no longer available')

    // The stale id is never re-submitted as-is.
    await expect(section.getByTestId('optimizer-model-save')).toBeDisabled()
    // …and stays visible as a disabled option (never auto-cleared).
    await section.getByRole('combobox').click()
    const staleOption = page.getByRole('option', { name: 'retired-model — no longer available' })
    await expect(staleOption).toHaveAttribute('aria-disabled', 'true')
    await page.getByRole('option', { name: 'gpt-4o (Panel E2E GPT)' }).click()

    // Re-selecting a valid model unblocks Save and persists the new choice.
    await expect(section.getByTestId('optimizer-model-save')).toBeEnabled()
    await section.getByTestId('optimizer-model-save').click()
    await expect.poll(() => state.putBodies.length).toBe(1)
    expect(state.putBodies[0]).toEqual({ model_id: 'gpt-4o' })
    await expect(section.getByTestId('optimizer-model-reminder')).toHaveCount(0)
    await expect(section.getByTestId('optimizer-model-state')).toHaveText(
      COPY.systemConfigStateSelected('gpt-4o'),
    )
  })

  test('a rejected save (422) is surfaced through the dialog error standard', async ({ page }) => {
    const section = await gotoSystemConfig(page)
    if (!section) return
    state.reject422 = true

    await pickOptimizerModel(page, section, 'claude-sonnet (Anthropic)')
    await section.getByTestId('optimizer-model-save').click()

    await expect(
      page.getByText('The chosen optimizer model is not enabled in this workspace.'),
    ).toBeVisible()
    expect(state.putBodies).toEqual([{ model_id: 'claude-sonnet' }])
    // Nothing was "saved": the previous selection surface is intact.
    await expect(section.getByTestId('optimizer-model-select')).toBeVisible()
    await expect(section).toContainText('claude-sonnet')
  })
})

test.describe('Optimizer model missing — entry annotated, chat blocked, System Config path', () => {
  test('the Optimized Plan entry explains the reason and the chat blocks on the model', async ({
    page,
  }) => {
    const config = configState({
      selected: null,
      effective: null,
      source: null,
      configured: false,
      enabled: false,
      reason_code: 'optimizer_model_not_configured',
    })

    const state = typedWorldState({
      gate: typedGate({
        optimization_conversation_available: false,
        optimization_conversation_reason_code: 'optimizer_model_not_configured',
        optimizer_model_configured: false,
        optimizer_model_id: null,
        optimizer_model_reason_code: 'optimizer_model_not_configured',
      }),
      availability: availableNow({
        available: false,
        reason_code: 'optimizer_model_not_configured',
        reason: COPY.modelReasonsNotConfigured,
        can_start_work: false,
        plan_present: false,
        optimized_plan_status: null,
        optimizer_model: {
          model_id: null,
          effective_model_id: null,
          source: null,
          configured: false,
          enabled: false,
          reason_code: 'optimizer_model_not_configured',
        },
      }),
      plan: readyPlan(TYPED_AGENT_ID),
    })

    await mockApiCatchAllProxyAware(page)
    await page.addInitScript((token: string) => {
      localStorage.setItem('access_token', token)
    }, FAKE_TOKEN)
    await standardSetup(page)
    await installFakeChatSocket(page)
    await mockPanelWorld(page, { agents: seedAgents() })
    await mockOptimizerApi(page, state)
    await mockOptimizerModelConfigApi(page, config)

    if (!(await gotoAgentsList(page, TYPED_AGENT_NAME))) return
    const details = await openAgentDialog(page, TYPED_AGENT_NAME)
    await openOptimizedPlanTab(details)

    // ── The entry is annotated with the shared reason + the fix ─────────────
    const blocked = details.getByTestId('talk-to-optimizer-blocked')
    await expect(blocked).toBeVisible()
    await expect(blocked).toContainText(COPY.modelReasonsNotConfigured)
    // The conversation still opens — that is where the operator learns the fix.
    const talk = details.getByTestId('talk-to-optimizer')
    await expect(talk).toBeEnabled()
    await expect(details.getByTestId('talk-to-optimizer-system-config')).toBeVisible()

    const chat = await openOptimizerChat(page, details)
    const alert = chat.getByTestId('optimization-conversation-dialog-optimizer-model-alert')
    await expect(alert).toBeVisible()
    await expect(alert).toContainText(COPY.modelAlertTitle)
    await expect(alert).toContainText(COPY.modelAlertBodyNotConfigured)
    // No work can start on an unapproved model: the composer is disabled.
    await expect(chat.getByPlaceholder(COPY.inputBlockedModel)).toBeDisabled()
    // …and nothing was created just by opening the chat.
    expect(state.createRequests).toHaveLength(0)

    // ── The System Config shortcut lands on the fix ────────────────────────
    await chat
      .getByTestId('optimization-conversation-dialog-optimizer-open-system-config')
      .click()
    await expect(page).toHaveURL(/\/system-config$/)
    const section = page.getByTestId('optimizer-model-section')
    await expect(section).toBeVisible()
    await expect(section.getByTestId('optimizer-model-reminder')).toContainText(
      COPY.systemConfigReminderUnset,
    )
    // Nothing ran: no conversation was ever created.
    expect(state.createRequests).toHaveLength(0)
  })
})
