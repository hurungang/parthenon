import { expect, test, type Page } from '@playwright/test'
import { FAKE_TOKEN, mockApiCatchAllProxyAware, standardSetup } from './_helpers'
import {
  makeAgentType,
  mockPanelWorld,
  muiCombobox,
  type PanelWorldState,
} from './_agent_panel_world'

/**
 * Agent Management Panel — equipment slots (all seven).
 *
 * Per slot: the inline "Create new" flow mounts the REAL shared module dialog
 * (identical-dialog equivalence: same title and signature fields as the source
 * module — the PRD forbids a reduced/divergent variant) and the created
 * resource is immediately assigned to the draft ("create-and-assign").
 * "Assign existing" is also exercised. All data is timestamped and lives in a
 * per-test mocked world, so no cross-test cleanup is required.
 *
 * The identity slot's OAuth popup sign-in flow is MANUAL-ONLY per the test
 * plan (needs a real Keycloak/EntraID); here we assert the inline dialog opens
 * and surfaces a mocked provider failure via the Dialog Error Handling
 * Standard, then exercise assign-existing instead.
 */

test.describe.configure({ timeout: 90_000 })

async function gotoPanel(page: Page) {
  await page.goto('/agents/panel')
  await page.waitForLoadState('load')
  if (page.url().includes('/login')) {
    test.skip()
    return false
  }
  await expect(page.getByRole('heading', { name: 'Agent Management Panel' })).toBeVisible()
  return true
}

function slot(page: Page, label: string) {
  return page.locator('.MuiPaper-outlined').filter({
    has: page.getByText(label, { exact: true }),
  })
}

async function selectAgent(page: Page, name: string) {
  await page.getByRole('button', { name }).click()
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
}

test.describe('Agent Management Panel — equipment slots (inline create-and-assign)', () => {
  let state: PanelWorldState

  test.beforeEach(async ({ page }) => {
    await mockApiCatchAllProxyAware(page)
    await page.addInitScript((token: string) => {
      localStorage.setItem('access_token', token)
    }, FAKE_TOKEN)
    await standardSetup(page)
    state = await mockPanelWorld(page)
    // Start every slot test from an unequipped agent (fresh draft).
    const fresh = [
      {
        id: 'at-empty',
        name: 'panel-e2e-empty',
        description: 'Unequipped agent',
        identity_id: null,
        role_id: null,
        model_id: null,
        system_instruction: null,
        input_type: 'none',
        input_schema: null,
        output_type: 'auto',
        output_schema: null,
        output_data_type_id: null,
        output_data_type_name: null,
        sop_bindings: [],
        skill_bindings: [],
        is_active: true,
        created_at: '2026-06-01T00:00:00Z',
        updated_at: '2026-06-01T00:00:00Z',
        plan: null,
      },
    ]
    state.agents.length = 0
    state.agents.push(...fresh)
  })

  test('role slot: create-new mounts the real Agent Role dialog and assigns the created role', async ({
    page,
  }) => {
    if (!(await gotoPanel(page))) return
    await selectAgent(page, 'panel-e2e-empty')

    const roleSlot = slot(page, 'Role')
    await roleSlot.getByRole('button', { name: 'Create new' }).click()

    // Identical-dialog equivalence: same title + fields as the source module.
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: 'Create Agent Role' })).toBeVisible()
    await expect(dialog.getByLabel('Name')).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()

    const roleName = `e2e-inline-role-${Date.now()}`
    await dialog.getByLabel('Name').fill(roleName)
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog).toBeHidden()

    // Create-and-assign: the new role is on the draft immediately.
    await expect(roleSlot.getByText(roleName)).toBeVisible()
    await expect(page.getByText('Pending changes (1)')).toBeVisible()
    // Persisted through the role endpoint (same as the source module).
    expect(state.roles.find((r) => r.name === roleName)).toBeTruthy()
    const writes = state.requests.filter((r) => r.startsWith('POST') || r.startsWith('PUT'))
    expect(writes).toContainEqual(expect.stringMatching(/POST \/api\/v1\/agents\/roles$/))
  })

  test('identity slot: inline dialog opens, surfaces a mocked provider failure, and assign-existing works', async ({
    page,
  }) => {
    if (!(await gotoPanel(page))) return
    await selectAgent(page, 'panel-e2e-empty')

    const identitySlot = slot(page, 'Identity')
    await identitySlot.getByRole('button', { name: 'Create new' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: 'Create Agent Identity' })).toBeVisible()
    // The real OAuth sign-in dialog (popup flow itself is manual-only).
    await expect(dialog.getByRole('button', { name: 'Sign In as Agent' })).toBeVisible()

    // Mock the identity-provider failure and assert the Dialog Error
    // Handling Standard: the error renders INSIDE the dialog.
    await page.route(/\/api\/v1\/agents\/identities\/oauth\/authorize(\?.*)?$/, (route) =>
      route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: {
            required_permission: {
              resource_type: 'agent::identities',
              action: 'create',
              resource_id: null,
            },
          },
        }),
      }),
    )
    await dialog.getByRole('button', { name: 'Sign In as Agent' }).click()
    await expect(dialog.getByText('Permission Denied:')).toBeVisible()
    await expect(dialog.getByText('agent::identities')).toBeVisible()
    await dialog.getByRole('button', { name: 'Cancel' }).click()
    await expect(dialog).toBeHidden()

    // Assign-existing path (the automatable half of the identity story).
    await identitySlot.getByRole('button', { name: 'Assign existing' }).click()
    await identitySlot.getByRole('combobox').click()
    await page.getByRole('option', { name: 'panel-e2e-identity' }).click()
    await expect(identitySlot.getByText('panel-e2e-identity')).toBeVisible()
    await expect(page.getByText('Pending changes (1)')).toBeVisible()
    expect(state.agentPostBodies).toHaveLength(0)
  })

  test('skills slot: create-new mounts the real Skill editor and binds the created skill', async ({
    page,
  }) => {
    if (!(await gotoPanel(page))) return
    await selectAgent(page, 'panel-e2e-empty')

    const skillsSlot = slot(page, 'Skills')
    await skillsSlot.getByRole('button', { name: 'Create new' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText('Create Skill', { exact: true })).toBeVisible()
    await expect(dialog.getByLabel('Description')).toBeVisible()

    const skillName = `e2e-inline-skill-${Date.now()}`
    await dialog.getByLabel('Name').fill(skillName)
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog).toBeHidden()

    // Created skill is bound at order #1 immediately.
    await expect(skillsSlot.getByText('#1')).toBeVisible()
    await expect(skillsSlot.getByText(skillName)).toBeVisible()
    expect(state.skills.find((s) => s.name === skillName)).toBeTruthy()
    const writes = state.requests.filter((r) => r.startsWith('POST') || r.startsWith('PUT'))
    expect(writes).toContainEqual(expect.stringMatching(/POST \/api\/v1\/skills$/))
  })

  test('sops slot: create-new mounts the real SOP editor and binds the created SOP', async ({
    page,
  }) => {
    if (!(await gotoPanel(page))) return
    await selectAgent(page, 'panel-e2e-empty')

    const sopsSlot = slot(page, 'SOPs')
    await sopsSlot.getByRole('button', { name: 'Create new' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText('Create SOP', { exact: true })).toBeVisible()
    await expect(dialog.getByLabel('Description')).toBeVisible()

    const sopName = `e2e-inline-sop-${Date.now()}`
    await dialog.getByLabel('Name').fill(sopName)
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog).toBeHidden()

    await expect(sopsSlot.getByText('#1')).toBeVisible()
    await expect(sopsSlot.getByText(sopName)).toBeVisible()
    expect(state.sops.find((s) => s.name === sopName)).toBeTruthy()
    const writes = state.requests.filter((r) => r.startsWith('POST') || r.startsWith('PUT'))
    expect(writes).toContainEqual(expect.stringMatching(/POST \/api\/v1\/sops$/))
  })

  test('input data type slot: create-new creates the registry type and applies the typed input', async ({
    page,
  }) => {
    if (!(await gotoPanel(page))) return
    await selectAgent(page, 'panel-e2e-empty')

    const inputSlot = slot(page, 'Input Data Type')
    await inputSlot.getByRole('button', { name: 'Create new' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: 'Create Data Type' })).toBeVisible()
    // Real registry dialog: slug + field editor present.
    await expect(dialog.getByLabel('Slug')).toBeVisible()
    await expect(dialog.getByLabel('Field Name')).toBeVisible()

    const typeName = `E2E Inline Type ${Date.now()}`
    await dialog.getByRole('textbox', { name: 'Name', exact: true }).fill(typeName)
    // Unique field name → unique input schema, so the applied-type chip
    // resolves to THIS registry entry and not an equally-shaped seeded one.
    await dialog.getByLabel('Field Name').fill(`e2e_summary_${Date.now()}`)
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog).toBeHidden()

    // Input slot switched to typed with the registry type applied.
    await expect(inputSlot.getByText('Typed Arguments')).toBeVisible()
    await expect(inputSlot.getByText(typeName)).toBeVisible()
    expect(state.dataTypes.find((dt) => dt.name === typeName)).toBeTruthy()
  })

  test('output data type slot: create-new sets the typed output without touching the input slot', async ({
    page,
  }) => {
    if (!(await gotoPanel(page))) return
    await selectAgent(page, 'panel-e2e-empty')

    const outputSlot = slot(page, 'Output Data Type')
    await outputSlot.getByRole('button', { name: 'Create new' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: 'Create Data Type' })).toBeVisible()

    const typeName = `E2E Out Type ${Date.now()}`
    await dialog.getByRole('textbox', { name: 'Name', exact: true }).fill(typeName)
    await dialog.getByLabel('Field Name').fill('result')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog).toBeHidden()

    await expect(outputSlot.getByText(typeName)).toBeVisible()
    // The input slot was NOT switched by the output assignment.
    await expect(slot(page, 'Input Data Type').getByText('None', { exact: true })).toBeVisible()
    expect(state.dataTypes.find((dt) => dt.name === typeName)).toBeTruthy()
  })

  test('model slot: create-new persists through the model-config endpoint; assign-existing equips the model', async ({
    page,
  }) => {
    if (!(await gotoPanel(page))) return
    await selectAgent(page, 'panel-e2e-empty')

    const modelSlot = slot(page, 'Model')
    await modelSlot.getByRole('button', { name: 'Create new' }).click()
    const dialog = page.getByRole('dialog')
    await expect(
      dialog.getByRole('heading', { name: 'Create Model Configuration' }),
    ).toBeVisible()
    // Real model-config dialog fields (identical to the source module).
    await expect(dialog.getByLabel('Display Name')).toBeVisible()
    await expect(muiCombobox(dialog, 'Provider Type')).toBeVisible()

    const configName = `E2E Inline Config ${Date.now()}`
    await dialog.getByLabel('Display Name').fill(configName)
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog).toBeHidden()
    // Persisted via its normal endpoint.
    expect(state.requests.some((r) => r === 'POST /api/v1/agents/model-configs')).toBe(true)
    // No enabled models were picked in create mode → nothing auto-assigned.
    await expect(modelSlot.getByText('Nothing equipped yet')).toBeVisible()

    // Assign-existing: the model becomes selectable and equips the draft.
    await modelSlot.getByRole('button', { name: 'Assign existing' }).click()
    await modelSlot.getByRole('combobox').click()
    await page.getByRole('option', { name: 'gpt-4o (Panel E2E GPT)' }).click()
    await expect(modelSlot.getByText('gpt-4o (Panel E2E GPT)')).toBeVisible()
    await expect(page.getByText('Pending changes (1)')).toBeVisible()
  })

  test('conversational agent: output data type slot is locked while the input slot stays configurable', async ({
    page,
  }) => {
    state.agents.push(
      makeAgentType('at-conv', 'panel-e2e-conv', {
        input_type: 'conversation',
        model_id: null,
      }),
    )
    if (!(await gotoPanel(page))) return
    await selectAgent(page, 'panel-e2e-conv')

    const outputSlot = slot(page, 'Output Data Type')
    await expect(
      outputSlot.getByText(/do not support typed outputs/),
    ).toBeVisible()
    // Locked slot offers no write actions.
    await expect(outputSlot.getByRole('button', { name: 'Create new' })).toHaveCount(0)
    await expect(outputSlot.getByRole('button', { name: 'Assign existing' })).toHaveCount(0)

    // Input slot remains configurable.
    const inputSlot = slot(page, 'Input Data Type')
    await expect(inputSlot.getByRole('combobox')).toBeVisible()
  })

  test('assign-existing and unassign round-trip keeps the draft consistent', async ({
    page,
  }) => {
    if (!(await gotoPanel(page))) return
    await selectAgent(page, 'panel-e2e-empty')

    const roleSlot = slot(page, 'Role')
    await roleSlot.getByRole('button', { name: 'Assign existing' }).click()
    await roleSlot.getByRole('combobox').click()
    await page.getByRole('option', { name: 'panel-e2e-role' }).click()
    await expect(roleSlot.getByText('panel-e2e-role')).toBeVisible()

    // Unassign via the chip's remove icon — draft reverts to placeholder.
    await roleSlot.getByLabel('Remove').click()
    await expect(roleSlot.getByText('Nothing equipped yet')).toBeVisible()
    // Still only draft mutations — nothing persisted.
    expect(state.agentPutBodies).toHaveLength(0)
    expect(state.agentPostBodies).toHaveLength(0)
  })
})
