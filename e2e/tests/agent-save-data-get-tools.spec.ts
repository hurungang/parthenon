import { expect, test } from '@playwright/test'
import { standardSetup } from './_helpers'

const JSON_HEADERS = {
  'content-type': 'application/json',
  'access-control-allow-origin': '*',
  'access-control-allow-methods': 'GET,POST,OPTIONS',
  'access-control-allow-headers': 'content-type,authorization',
}

async function fetchJson<T>(
  page: import('@playwright/test').Page,
  url: string,
  method: 'GET' | 'POST',
  body?: unknown,
): Promise<{ status: number; payload: T }> {
  return page.evaluate(
    async ({ inputUrl, inputMethod, inputBody }) => {
      const response = await fetch(inputUrl, {
        method: inputMethod,
        headers: { 'Content-Type': 'application/json' },
        body: inputBody ? JSON.stringify(inputBody) : undefined,
      })
      const payload = await response.json()
      return { status: response.status, payload }
    },
    { inputUrl: url, inputMethod: method, inputBody: body },
  )
}

test.describe('agent-save-data-get-tools', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
    await page.goto('/')
  })

  test('agent context does not expose save_result', async ({ page }) => {
    await page.route('http://localhost:8000/api/v1/internal/data/agent-types/**/context', (route) => {
      if (route.request().method() === 'OPTIONS') {
        return route.fulfill({ status: 204, headers: JSON_HEADERS })
      }
      return route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({
          tool_definitions: [
            { type: 'function', function: { name: 'save_data', description: 'Save named data' } },
            { type: 'function', function: { name: 'get_data', description: 'Get named data' } },
            { type: 'function', function: { name: 'get_output', description: 'Get output history' } },
          ],
        }),
      })
    })

    const result = await fetchJson<{ tool_definitions: Array<{ function: { name: string } }> }>(
      page,
      'http://localhost:8000/api/v1/internal/data/agent-types/00000000-0000-0000-0000-000000000111/context',
      'GET',
    )

    const toolNames = result.payload.tool_definitions.map((t) => t.function.name)
    expect(result.status).toBe(200)
    expect(toolNames).toContain('save_data')
    expect(toolNames).toContain('get_data')
    expect(toolNames).toContain('get_output')
    expect(toolNames).not.toContain('save_result')
  })

  test('save_data stores multiple records per session', async ({ page }) => {
    const savedCalls: Array<{ data_name: string; session_id: string }> = []

    await page.route('http://localhost:8000/internal/tools/call', async (route) => {
      if (route.request().method() === 'OPTIONS') {
        return route.fulfill({ status: 204, headers: JSON_HEADERS })
      }

      const body = route.request().postDataJSON() as {
        tool_name: string
        session_id: string
        tool_args: { data_name: string }
      }

      if (body.tool_name === 'save_data') {
        savedCalls.push({ data_name: body.tool_args.data_name, session_id: body.session_id })
      }

      return route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({ result: { status: 'saved', index: savedCalls.length } }),
      })
    })

    const sessionId = 'session-abc-001'
    const first = await fetchJson<{ result: { status: string } }>(
      page,
      'http://localhost:8000/internal/tools/call',
      'POST',
      {
        tool_name: 'save_data',
        session_id: sessionId,
        agent_type_id: 'agent-type-1',
        tool_args: { data_name: 'first_record', data_value: { value: 1 } },
      },
    )
    const second = await fetchJson<{ result: { status: string } }>(
      page,
      'http://localhost:8000/internal/tools/call',
      'POST',
      {
        tool_name: 'save_data',
        session_id: sessionId,
        agent_type_id: 'agent-type-1',
        tool_args: { data_name: 'second_record', data_value: { value: 2 } },
      },
    )

    expect(first.status).toBe(200)
    expect(second.status).toBe(200)
    expect(savedCalls).toHaveLength(2)
    expect(savedCalls[0]).toEqual({ data_name: 'first_record', session_id: sessionId })
    expect(savedCalls[1]).toEqual({ data_name: 'second_record', session_id: sessionId })
  })

  test('get_data requires at least one filter', async ({ page }) => {
    await page.route('http://localhost:8000/internal/tools/call', async (route) => {
      if (route.request().method() === 'OPTIONS') {
        return route.fulfill({ status: 204, headers: JSON_HEADERS })
      }

      const body = route.request().postDataJSON() as {
        tool_name: string
        tool_args: Record<string, unknown>
      }

      if (
        body.tool_name === 'get_data' &&
        !body.tool_args.data_name &&
        !body.tool_args.agent_type_id &&
        !body.tool_args.session_id
      ) {
        return route.fulfill({
          status: 400,
          headers: JSON_HEADERS,
          body: JSON.stringify({
            error: 'At least one filter is required',
            handled_gracefully: true,
          }),
        })
      }

      return route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify({ result: { records: [] } }) })
    })

    const result = await fetchJson<{ error: string; handled_gracefully: boolean }>(
      page,
      'http://localhost:8000/internal/tools/call',
      'POST',
      {
        tool_name: 'get_data',
        session_id: 'session-abc-001',
        agent_type_id: 'agent-type-1',
        tool_args: {},
      },
    )

    expect(result.status).toBe(400)
    expect(result.payload.error).toContain('At least one filter')
    expect(result.payload.handled_gracefully).toBe(true)
  })

  test('get_output returns output history by date range', async ({ page }) => {
    await page.route('http://localhost:8000/internal/tools/call', async (route) => {
      if (route.request().method() === 'OPTIONS') {
        return route.fulfill({ status: 204, headers: JSON_HEADERS })
      }

      const body = route.request().postDataJSON() as {
        tool_name: string
        tool_args: { date_from?: string; date_to?: string }
      }

      if (body.tool_name === 'get_output') {
        return route.fulfill({
          status: 200,
          headers: JSON_HEADERS,
          body: JSON.stringify({
            result: {
              records: [
                {
                  id: 'out-1',
                  execution_session_id: 'session-abc-001',
                  raw_output: 'daily summary',
                  created_at: '2026-07-02T10:30:00Z',
                },
                {
                  id: 'out-2',
                  execution_session_id: 'session-abc-002',
                  raw_output: 'trend summary',
                  created_at: '2026-07-02T16:00:00Z',
                },
              ],
              date_from: body.tool_args.date_from,
              date_to: body.tool_args.date_to,
            },
          }),
        })
      }

      return route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify({ result: { records: [] } }) })
    })

    const dateFrom = '2026-07-02T00:00:00Z'
    const dateTo = '2026-07-02T23:59:59Z'

    const result = await fetchJson<{
      result: { records: Array<{ id: string; raw_output: string }>; date_from: string; date_to: string }
    }>(
      page,
      'http://localhost:8000/internal/tools/call',
      'POST',
      {
        tool_name: 'get_output',
        session_id: 'session-abc-001',
        agent_type_id: 'agent-type-1',
        tool_args: { date_from: dateFrom, date_to: dateTo },
      },
    )

    expect(result.status).toBe(200)
    expect(result.payload.result.records).toHaveLength(2)
    expect(result.payload.result.records[0].raw_output).toContain('summary')
    expect(result.payload.result.date_from).toBe(dateFrom)
    expect(result.payload.result.date_to).toBe(dateTo)
  })
})
