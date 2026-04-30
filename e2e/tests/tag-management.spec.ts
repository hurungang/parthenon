import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

const JSON_HEADERS = { 'Content-Type': 'application/json' }

test.describe('Tag Management - Allowed Values', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
  })

  test('create tag with allowed values and verify they are saved', async ({ page }) => {
    const newTagId = 'new-tag-123'
    let createPayload: any = null
    let getTagsCalled = false

    // Mock GET /user-tags/definitions to return empty initially
    await page.route('**/api/v1/user-tags/definitions**', async (route) => {
      if (route.request().method() === 'GET') {
        getTagsCalled = true
        // After creating, return the new tag
        if (createPayload) {
          route.fulfill({
            status: 200,
            headers: JSON_HEADERS,
            body: JSON.stringify([
              {
                id: newTagId,
                key: createPayload.key,
                scope: createPayload.scope,
                resource_type: createPayload.resource_type,
                description: createPayload.description,
                allowed_values: createPayload.allowed_values.map((value: string, index: number) => ({
                  id: `value-${index}`,
                  tag_definition_id: newTagId,
                  value,
                  created_at: new Date().toISOString(),
                })),
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
              },
            ]),
          })
        } else {
          route.fulfill({
            status: 200,
            headers: JSON_HEADERS,
            body: JSON.stringify([]),
          })
        }
      } else if (route.request().method() === 'POST') {
        // Capture the create request payload
        createPayload = route.request().postDataJSON()
        console.log('CREATE TAG PAYLOAD:', JSON.stringify(createPayload, null, 2))
        
        route.fulfill({
          status: 201,
          headers: JSON_HEADERS,
          body: JSON.stringify({
            id: newTagId,
            key: createPayload.key,
            scope: createPayload.scope,
            resource_type: createPayload.resource_type,
            description: createPayload.description,
            allowed_values: createPayload.allowed_values.map((value: string, index: number) => ({
              id: `value-${index}`,
              tag_definition_id: newTagId,
              value,
              created_at: new Date().toISOString(),
            })),
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }),
        })
      }
    })

    // Navigate to permissions page
    await page.goto('/user-permissions')
    await page.waitForLoadState('networkidle')

    // Click "Add Tag" button
    await page.getByRole('button', { name: /add tag/i }).click()

    // Wait for dialog to open
    await page.waitForSelector('[role="dialog"]')

    // Fill in tag details
    await page.getByLabel(/key/i).first().fill('environment')
    await page.getByLabel(/description/i).fill('Environment tag')

    // Add allowed values
    const valueInput = page.getByPlaceholder(/value/i).first()
    const addValueButton = page.getByRole('button', { name: /add value/i })

    // Add "dev"
    await valueInput.fill('dev')
    await addValueButton.click()

    // Verify "dev" chip appears
    await expect(page.locator('text=dev').first()).toBeVisible()

    // Add "prod"
    await valueInput.fill('prod')
    await addValueButton.click()

    // Verify "prod" chip appears
    await expect(page.locator('text=prod').first()).toBeVisible()

    // Add "staging"
    await valueInput.fill('staging')
    await addValueButton.click()

    // Verify "staging" chip appears
    await expect(page.locator('text=staging').first()).toBeVisible()

    // Click Save button
    await page.getByRole('button', { name: /save/i }).click()

    // Wait for dialog to close
    await page.waitForSelector('[role="dialog"]', { state: 'hidden' })

    // Verify the payload was sent correctly
    expect(createPayload).not.toBeNull()
    expect(createPayload.key).toBe('environment')
    expect(createPayload.scope).toBe('global')
    expect(createPayload.description).toBe('Environment tag')
    expect(createPayload.allowed_values).toEqual(['dev', 'prod', 'staging'])

    // Verify GET was called to refresh the list
    expect(getTagsCalled).toBe(true)
  })

  test('update tag and add more allowed values', async ({ page }) => {
    const tagId = 'existing-tag-123'
    let updatePayload: any = null
    let getCalled = 0

    const existingTag = {
      id: tagId,
      key: 'environment',
      scope: 'global',
      resource_type: null,
      description: 'Environment tag',
      allowed_values: [
        { id: 'value-1', tag_definition_id: tagId, value: 'dev', created_at: '2024-01-01T00:00:00Z' },
        { id: 'value-2', tag_definition_id: tagId, value: 'prod', created_at: '2024-01-01T00:00:00Z' },
      ],
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    }

    // Mock GET /user-tags/definitions
    await page.route('**/api/v1/user-tags/definitions**', async (route) => {
      if (route.request().method() === 'GET') {
        getCalled++
        // After updating, return the updated tag
        if (updatePayload) {
          route.fulfill({
            status: 200,
            headers: JSON_HEADERS,
            body: JSON.stringify([
              {
                ...existingTag,
                allowed_values: [
                  ...existingTag.allowed_values,
                  ...(updatePayload.add_values || []).map((value: string, index: number) => ({
                    id: `value-new-${index}`,
                    tag_definition_id: tagId,
                    value,
                    created_at: new Date().toISOString(),
                  })),
                ],
              },
            ]),
          })
        } else {
          route.fulfill({
            status: 200,
            headers: JSON_HEADERS,
            body: JSON.stringify([existingTag]),
          })
        }
      }
    })

    // Mock PATCH /user-tags/definitions/{id}
    await page.route(`**/api/v1/user-tags/definitions/${tagId}`, async (route) => {
      if (route.request().method() === 'PATCH') {
        updatePayload = route.request().postDataJSON()
        console.log('UPDATE TAG PAYLOAD:', JSON.stringify(updatePayload, null, 2))

        route.fulfill({
          status: 200,
          headers: JSON_HEADERS,
          body: JSON.stringify({
            ...existingTag,
            description: updatePayload.description || existingTag.description,
            allowed_values: [
              ...existingTag.allowed_values,
              ...(updatePayload.add_values || []).map((value: string, index: number) => ({
                id: `value-new-${index}`,
                tag_definition_id: tagId,
                value,
                created_at: new Date().toISOString(),
              })),
            ],
          }),
        })
      }
    })

    // Navigate to permissions page
    await page.goto('/user-permissions')
    await page.waitForLoadState('networkidle')

    // Wait for tag to load
    await page.waitForSelector('text=environment')

    // Click Edit button for the tag
    await page.locator('[data-testid="EditIcon"]').first().click()

    // Wait for dialog to open
    await page.waitForSelector('[role="dialog"]')

    // Verify existing values are shown
    await expect(page.locator('text=dev').first()).toBeVisible()
    await expect(page.locator('text=prod').first()).toBeVisible()

    // Add new value "staging"
    const valueInput = page.getByPlaceholder(/value/i).first()
    const addValueButton = page.getByRole('button', { name: /add value/i })

    await valueInput.fill('staging')
    await addValueButton.click()

    // Verify "staging" chip appears
    await expect(page.locator('text=staging').first()).toBeVisible()

    // Click Save button
    await page.getByRole('button', { name: /save/i }).click()

    // Wait for dialog to close
    await page.waitForSelector('[role="dialog"]', { state: 'hidden' })

    // Verify the payload was sent correctly
    expect(updatePayload).not.toBeNull()
    expect(updatePayload.add_values).toEqual(['staging'])

    // Verify GET was called at least twice (initial load and after update)
    expect(getCalled).toBeGreaterThanOrEqual(2)
  })

  test('prevent adding duplicate allowed values', async ({ page }) => {
    const tagId = 'existing-tag-456'

    const existingTag = {
      id: tagId,
      key: 'status',
      scope: 'global',
      resource_type: null,
      description: 'Status tag',
      allowed_values: [
        { id: 'value-1', tag_definition_id: tagId, value: 'active', created_at: '2024-01-01T00:00:00Z' },
      ],
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    }

    await page.route('**/api/v1/user-tags/definitions**', async (route) => {
      route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify([existingTag]),
      })
    })

    await page.goto('/user-permissions')
    await page.waitForLoadState('networkidle')

    // Click Edit button
    await page.locator('[data-testid="EditIcon"]').first().click()
    await page.waitForSelector('[role="dialog"]')

    // Try to add duplicate value
    const valueInput = page.getByPlaceholder(/value/i).first()
    const addValueButton = page.getByRole('button', { name: /add value/i })

    await valueInput.fill('active')

    // Button should be disabled for duplicate
    await expect(addValueButton).toBeDisabled()
  })

  test('prevent adding empty allowed values', async ({ page }) => {
    await page.route('**/api/v1/user-tags/definitions**', async (route) => {
      route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify([]),
      })
    })

    await page.goto('/user-permissions')
    await page.waitForLoadState('networkidle')

    // Click "Add Tag" button
    await page.getByRole('button', { name: /add tag/i }).click()
    await page.waitForSelector('[role="dialog"]')

    const addValueButton = page.getByRole('button', { name: /add value/i })

    // Button should be disabled when input is empty
    await expect(addValueButton).toBeDisabled()

    // Type something
    const valueInput = page.getByPlaceholder(/value/i).first()
    await valueInput.fill('test')

    // Button should now be enabled
    await expect(addValueButton).toBeEnabled()

    // Clear the input
    await valueInput.clear()

    // Button should be disabled again
    await expect(addValueButton).toBeDisabled()
  })
})
