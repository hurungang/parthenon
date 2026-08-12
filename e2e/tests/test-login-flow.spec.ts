import { test } from '@playwright/test'

test.skip('debug login flow', async ({ page }) => {
  // This is a debug test - skipped in normal test runs
  console.log('1. Navigating to http://localhost:5173/')
  await page.goto('http://localhost:5173/')
  await page.waitForLoadState('networkidle')
  console.log('2. Current URL:', page.url())
  
  // Take screenshot of initial state
  await page.screenshot({ path: 'tmp/login-debug-1-initial.png' })
  
  // Wait for /login page
  await page.waitForURL('**/login', { timeout: 5000 })
  console.log('3. On login page:', page.url())
  
  // Take screenshot of login page
  await page.screenshot({ path: 'tmp/login-debug-2-loginpage.png' })
  
  // Try to find the login button
  const loginButton = await page.locator('button:has-text("Login")').count()
  console.log('4. Login buttons found:', loginButton)
  
  // Get all buttons
  const allButtons = await page.locator('button').allTextContents()
  console.log('5. All buttons:', allButtons)
  
  // Click the login button
  console.log('6. Clicking login button...')
  await page.click('button:has-text("Login")')
  
  // Wait a bit
  await page.waitForTimeout(2000)
  console.log('7. After click URL:', page.url())
  
  // Take screenshot after click
  await page.screenshot({ path: 'tmp/login-debug-3-afterclick.png' })
  
  // Try waiting for Keycloak
  console.log('8. Waiting for Keycloak redirect...')
  await page.waitForURL('**/realms/**/protocol/openid-connect/**', { timeout: 15000 })
  console.log('9. On Keycloak page:', page.url())
})
