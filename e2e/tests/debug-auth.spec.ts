import { test, expect } from '@playwright/test'

test.describe('Debug Authentication', () => {
  test('debug unauthenticated user sees the login page', async ({ page }) => {
    console.log('Starting test...')
    await page.addInitScript(() => { localStorage.removeItem('access_token') })
    
    console.log('Navigating to /')
    await page.goto('/')
    await page.waitForTimeout(10000) // 10 second delay
    
    console.log('Waiting for button')
    await expect(page.locator('button').first()).toBeVisible({ timeout: 10000 })
    await page.waitForTimeout(10000) // 10 second delay
    
    console.log('Test complete')
  })
})
