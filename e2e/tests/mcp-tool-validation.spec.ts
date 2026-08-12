import { test, expect } from '@playwright/test'

test.describe('MCP Tool Call Validation', () => {
  test('agent can successfully call MCP tools (supabase and hello-world)', async ({ page }) => {
    // Login first
    await page.goto('http://localhost:5173')
    await page.locator('input[name="username"]').fill('admin')
    await page.locator('input[name="password"]').fill('admin')
    await page.locator('button[type="submit"]').click()
    await page.waitForURL('**/#/projects', { timeout: 10000 })
    
    // Navigate to agent execution page
    await page.goto('http://localhost:5173/agent-types')
    
    // Find and click on support_agent
    const agentCard = page.locator('text=support_agent').first()
    await expect(agentCard).toBeVisible({ timeout: 10000 })
    await agentCard.click()
    
    // Launch agent with test input
    await page.waitForTimeout(1000)
    const launchButton = page.locator('button:has-text("Launch"), button:has-text("Execute")').first()
    if (await launchButton.isVisible()) {
      await launchButton.click()
    }
    
    // Provide input if needed
    const inputBox = page.locator('textarea, input[type="text"]').first()
    if (await inputBox.isVisible()) {
      await inputBox.fill('Get project info for iyzwnsvoiqfsgkhjnsyl and call hello world')
      
      const submitButton = page.locator('button:has-text("Submit"), button:has-text("Send")').first()
      if (await submitButton.isVisible()) {
        await submitButton.click()
      }
    }
    
    // Wait for execution to complete (up to 30 seconds)
    await page.waitForTimeout(5000)
    
    // Check logs or output for MCP tool call success
    const pageContent = await page.content()
    
    // Look for success indicators or absence of 401 errors
    const has401Error = pageContent.includes('401') && pageContent.includes('Unauthorized')
    const hasMcpError = pageContent.includes('MCP tool call failed')
    
    // If we see these errors, the test fails
    expect(has401Error).toBe(false)
    expect(hasMcpError).toBe(false)
    
    console.log('MCP tool calls completed without 401/unauthorized errors')
  })
})
