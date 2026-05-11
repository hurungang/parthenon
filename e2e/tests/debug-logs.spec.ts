import { test, expect } from '@playwright/test'
import { standardSetup, FAKE_TOKEN } from './_helpers'

const SESSION_ID = 'test-debug-001'

test('Debug LogViewer render', async ({ page }) => {
  // Capture all console messages
  const consoleMessages: string[] = []
  page.on('console', msg => consoleMessages.push(`[${msg.type()}] ${msg.text()}`))
  page.on('pageerror', err => consoleMessages.push(`[ERROR] ${err.message}`))

  await standardSetup(page)

  // Mock session
  await page.route(`**/api/v1/agents/sessions/${SESSION_ID}`, (route) =>
    route.fulfill({ 
      status: 200, 
      body: JSON.stringify({ 
        id: SESSION_ID, 
        status: 'completed',
        started_at: '2026-01-01T10:00:00Z',
        completed_at: '2026-01-01T10:05:00Z',
        created_at: '2026-01-01T10:00:00Z',
        output_data: {result: 'done'},
        agent_type_id: 'at-1',
        triggered_by_user_id: 'u1',
        input_data: {}
      })
    })
  )

  // Mock execution-logs
  await page.route(`**/api/v1/agents/sessions/${SESSION_ID}/execution-logs`, (route) => {
    console.log('Execution logs route hit!')
    route.fulfill({ 
      status: 200, 
      body: JSON.stringify([{
        id: 'log-1',
        session_id: SESSION_ID,
        system_instruction: 'test',
        user_prompt: 'test prompt',
        logged_at: '2026-01-01T10:00:01Z'
      }])
    })
  })

  // Mock log entries  
  await page.route(`**/api/v1/agents/sessions/${SESSION_ID}/logs`, (route) => {
    console.log('Log entries route hit!')
    route.fulfill({ 
      status: 200, 
      body: JSON.stringify([{
        id: 'e1',
        timestamp: '2026-01-01T10:00:00Z',
        event_type: 'session_started',
        log_level: 'INFO',
        message: 'Started',
        data: {identity_name: 'test', role_name: 'TestRole', model_id: 'gpt-4o'}
      }])
    })
  })

  await page.goto(`/agents/sessions/${SESSION_ID}`)
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(2000)

  // Check if LogViewer rendered
  const logViewerTitle = page.getByText('Execution Log')
  const isVisible = await logViewerTitle.isVisible().catch(() => false)
  
  console.log('=== CONSOLE MESSAGES ===')
  consoleMessages.forEach(msg => console.log(msg))
  console.log('=== LogViewer visible:', isVisible, '===')
  
  // Take screenshot
  await page.screenshot({ path: 'test-results/debug-screenshot.png', fullPage: true })
  
  // Print HTML of the page
  const html = await page.content()
  console.log('=== PAGE HTML (first 2000 chars) ===')
  console.log(html.substring(0, 2000))
})
