import { expect, test } from '@playwright/test'

import { standardSetup } from './_helpers'

const MOCK_DELEGATION_PLAN = {
  id: 'plan-a2a-1',
  agent_type_id: 'agent-type-a2a-1',
  plan_steps: [
    { order: 1, type: 'skill_invocation', name: 'Use Search Skill', description: 'Gather the required context' },
    { order: 2, type: 'agent_delegation', name: 'Delegate Research', description: 'Target agent type: research-agent' },
  ],
  topology_nodes: [
    { id: 'role:r1', type: 'role', label: 'Coordinator Role', meta: null },
    { id: 'skill:s1', type: 'skill', label: 'Search Skill', meta: null },
    { id: 'agent_type:a1', type: 'agent_type', label: 'research-agent', meta: null },
  ],
  topology_edges: [
    { source: 'role:r1', target: 'skill:s1', label: 'uses skill' },
    { source: 'role:r1', target: 'agent_type:a1', label: 'delegates to' },
  ],
  generation_status: 'success',
  generation_error: null,
  agent_config_hash: 'a2a-plan-123',
  generated_at: '2026-05-20T12:00:00Z',
}

async function mockAgentManagementRoutes(page: Parameters<typeof test>[0]['page']) {
  await page.route('**/api/v1/agents/types**', (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({ status: 200, body: JSON.stringify([]) })
    } else {
      route.fulfill({
        status: 201,
        body: JSON.stringify({
          id: 'agent-type-a2a-1',
          name: 'delegator-agent',
          description: null,
          identity_id: null,
          role_id: null,
          model_id: null,
          system_instruction: null,
          input_type: 'typed',
          input_schema: null,
          output_type: 'markdown',
          output_schema: null,
          sop_bindings: [],
          skill_bindings: [],
          is_active: true,
          created_at: '2026-05-20T12:00:00Z',
          updated_at: '2026-05-20T12:00:00Z',
          plan: MOCK_DELEGATION_PLAN,
        }),
      })
    }
  })
  await page.route('**/api/v1/agents/types/**', (route) =>
    route.fulfill({
      status: 200,
      body: JSON.stringify({
        id: 'agent-type-a2a-1',
        name: 'delegator-agent',
        description: null,
        identity_id: null,
        role_id: null,
        model_id: null,
        system_instruction: null,
        input_type: 'typed',
        input_schema: null,
        output_type: 'markdown',
        output_schema: null,
        primary_sop_id: null,
        is_active: true,
        created_at: '2026-05-20T12:00:00Z',
        updated_at: '2026-05-20T12:00:00Z',
        plan: MOCK_DELEGATION_PLAN,
      }),
    })
  )
  await page.route('**/api/v1/agents/roles**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
  await page.route('**/api/v1/agents/identities**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
  await page.route('**/api/v1/agents/model-configs**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
  await page.route('**/api/v1/sops**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
}

async function mockRoleRoutes(page: Parameters<typeof test>[0]['page']) {
  await page.route('**/api/v1/agents/roles**', (route) =>
    route.fulfill({
      status: 200,
      body: JSON.stringify([
        {
          id: 'role-a2a-1',
          name: 'Delegator Role',
          description: 'Routes work to a delegated research agent',
          sop_ids: ['sop-a2a-1'],
          skill_ids: [],
          created_at: '2026-05-20T12:00:00Z',
          updated_at: '2026-05-20T12:00:00Z',
        },
      ]),
    })
  )
  await page.route('**/api/v1/sops**', (route) =>
    route.fulfill({
      status: 200,
      body: JSON.stringify([
        { id: 'sop-a2a-1', name: 'Delegation SOP', required_skill_ids: [] },
      ]),
    })
  )
  await page.route('**/api/v1/skills**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
  await page.route('**/api/v1/mcp/tools**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
  await page.route('**/api/v1/agents/roles/role-a2a-1/identities', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
  await page.route('**/api/v1/agents/roles/role-a2a-1/mcp-sessions', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
  await page.route('**/api/v1/agents/roles/role-a2a-1/mcp-tools**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
  await page.route('**/api/v1/agents/roles/role-a2a-1/allowed-agent-types**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(['research-agent', 'review-agent']) })
  )
}

async function mockMcpRoutes(page: Parameters<typeof test>[0]['page']) {
  await page.route('**/api/v1/mcp/servers**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
  await page.route('**/api/v1/mcp/tools**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
}

async function bindRoleSop(page: Parameters<typeof test>[0]['page']) {
  // Save is gated on at least one SOP/skill binding drawn from the role.
  const dialog = page.getByRole('dialog')
  // MUI's InputLabel here has no id association, so target the field by its
  // visible label inside the FormControl.
  const roleField = dialog
    .locator('.MuiFormControl-root')
    .filter({ hasText: 'Agent Role' })
    .first()
  await roleField.getByRole('combobox').click()
  await page.getByRole('option', { name: 'Delegator Role' }).click()
  await dialog.getByRole('button', { name: 'Add Binding' }).click()
  await dialog.getByText('Select an item…').click()
  await page.getByRole('option', { name: 'Delegation SOP' }).click()
  await dialog.getByRole('button', { name: 'Add', exact: true }).click()
}

async function createBoundAgentType(page: Parameters<typeof test>[0]['page']) {
  await page.getByRole('button', { name: /create agent type/i }).click()
  await page.getByLabel('Name').fill('delegator-agent')
  await bindRoleSop(page)
  await page.getByText('None (no input required)').click()
  await page.locator('[role="option"][data-value="typed"]').click()
  await page.getByRole('dialog').getByRole('button', { name: /save/i }).click()
}

test.describe('Agent A2A Communication and Slug Enforcement', () => {
  test('agent type name rejects non-slug input in the management dialog', async ({ page }) => {
    await standardSetup(page)
    await mockAgentManagementRoutes(page)

    await page.goto('/agents')
    await page.waitForLoadState('load')

    await page.getByRole('button', { name: /create agent type/i }).click()
    await page.getByLabel('Name').fill('Invalid Agent')

    await expect(
      page.getByText('Agent type name must use lowercase letters, numbers, and hyphens only.')
    ).toBeVisible()
  })

  test('slug-safe agent type creation opens the generated plan with delegation steps', async ({ page }) => {
    await standardSetup(page)
    await mockAgentManagementRoutes(page)
    await mockRoleRoutes(page)

    await page.goto('/agents')
    await page.waitForLoadState('load')

    await createBoundAgentType(page)

    // Saving opens the agent-type details dialog; the generated plan lives on
    // the Implementation Plan tab (there is no separate plan-preview modal).
    await expect(page.getByRole('dialog').getByText('delegator-agent').first()).toBeVisible()
    await page.getByRole('tab', { name: /implementation plan/i }).click()
    await expect(page.getByText('Use Search Skill')).toBeVisible()
    await expect(page.getByText('Delegate Research')).toBeVisible()
  })

  test('created agent type opens details with the topology canvas', async ({ page }) => {
    await standardSetup(page)
    await mockAgentManagementRoutes(page)
    await mockRoleRoutes(page)

    await page.goto('/agents')
    await page.waitForLoadState('load')

    await createBoundAgentType(page)

    await page.getByRole('tab', { name: /topology/i }).click()
    await expect(page.getByTestId('panel-topology-canvas')).toBeVisible()
  })

  test('agent role edit preview shows allowed delegated agent types', async ({ page }) => {
    await standardSetup(page)
    await mockRoleRoutes(page)

    await page.goto('/agents/roles')
    await page.waitForLoadState('load')

    await expect(page.getByText('Delegator Role')).toBeVisible()
    await page.getByRole('button', { name: /^Edit$/ }).first().click()

    await expect(page.getByText('Allowed Agent Types Preview')).toBeVisible()
    await expect(page.getByText('research-agent')).toBeVisible()
    await expect(page.getByText('review-agent')).toBeVisible()
  })

  test('mcp server registration blocks invalid slug values', async ({ page }) => {
    await standardSetup(page)
    await mockMcpRoutes(page)

    await page.goto('/mcp')
    await page.waitForLoadState('load')

    await page.getByRole('button', { name: /register server/i }).click()
    const dialog = page.getByRole('dialog', { name: /register server/i })
    // The server's identity is its slug; there is no separate Name field.
    await dialog.getByLabel('Slug').fill('bad slug')
    await dialog.getByLabel('Base URL').fill('http://example.test')
    await expect(dialog.getByRole('button', { name: /save/i })).toBeDisabled()
  })
})