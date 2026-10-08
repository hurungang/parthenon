import { createServer, type Server } from 'node:http'
import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import path from 'node:path'

/**
 * Real Backend Integration - Decision Tools.
 *
 * No route mocks: exercises the real Control Center API + real PostgreSQL.
 * - a local stub HTTP server mimics POST /v1/systemone (the TypeSafe Jev
 *   contract), so no external provider call is needed,
 * - the provider config stores the stub's base_url; the API key is accepted
 *   write-only and never returned,
 * - identical decision tools ("tool_a") are authored in TWO tenants via the
 *   real decision-tools API (per-tenant name uniqueness: both persist, a
 *   same-tenant duplicate is rejected),
 * - the auto-generated description is verified,
 * - execution goes through the real internal system-tools decision execute
 *   endpoint (/decision/execute — the same path Communication Hub forwards
 *   to, authenticated with the CH service certificate exactly as CH sends
 *   it),
 * - persistence is verified directly via psql in parthenon-postgres,
 * - unauthenticated calls are rejected.
 *
 * Skips cleanly when the backend is unreachable.
 */

const API = 'http://localhost:8000/api/v1'

const CERT_PEM = readFileSync(
  path.resolve(__dirname, '../../backend/certs/communication-hub-cert.pem'),
  'utf8',
)

const psql = promisify(execFile)

/** Minimal TypeSafe Jev stub: answers every question deterministically. */
async function startTypesafeStub(): Promise<{ server: Server; port: number }> {
  const server = createServer((req, res) => {
    let body = ''
    req.on('data', (chunk) => (body += chunk))
    req.on('end', () => {
      const parsed = body ? JSON.parse(body) : {}
      const answers: Record<string, unknown> = {}
      for (const [qid, q] of Object.entries(
        (parsed.questions ?? {}) as Record<string, { type: string }>,
      )) {
        if (q.type === 'choice') {
          answers[qid] = {
            type: 'choice',
            choice: 'refund',
            probabilities: { refund: 0.7, escalate: 0.3 },
            confidence: 0.95,
          }
        } else if (q.type === 'score') {
          answers[qid] = {
            type: 'score',
            score: 4,
            legend: ['low', 'critical'],
            confidence: 0.92,
          }
        } else {
          answers[qid] = { type: 'noul', noul: 1.0 }
        }
      }
      res.writeHead(200, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ model: 'jev-latest', answers }))
    })
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const port = (server.address() as { port: number }).port
  return { server, port }
}

async function login(email: string): Promise<string | null> {
  const resp = await fetch(`${API}/auth/login-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password: 'E2ePassword1' }),
  })
  if (resp.status !== 200) return null
  const body = (await resp.json()) as { access_token: string }
  return body.access_token
}

/**
 * Resolve a tenant session: prefer the persistent E2E accounts (registration
 * is rate-limited to 10/hour per IP, so tests must not depend on fresh
 * registrations). All e2e accounts share E2ePassword1, so previously
 * registered fallback accounts are reusable. Registers only as a last resort.
 */
async function registerTenant(email: string): Promise<{ token: string; slug: string }> {
  const existing = await login(email)
  if (existing) {
    const memberships = await psql('docker', [
      'exec',
      'parthenon-postgres',
      'psql',
      '-U',
      'parthenon',
      '-d',
      'parthenon',
      '-tAc',
      `SELECT t.slug FROM tenants t JOIN tenant_user_memberships m ON m.tenant_id = t.id JOIN platform_users u ON u.id = m.user_id WHERE u.email = '${email}' LIMIT 1`,
    ])
    return { token: existing, slug: memberships.stdout.trim() }
  }

  // Try previously registered fallback accounts (same shared password).
  const { stdout: candidates } = await psql('docker', [
    'exec',
    'parthenon-postgres',
    'psql',
    '-U',
    'parthenon',
    '-d',
    'parthenon',
    '-tAc',
    `SELECT u.email, t.slug FROM platform_users u JOIN tenant_user_memberships m ON m.user_id = u.id JOIN tenants t ON t.id = m.tenant_id WHERE u.email LIKE 'e2e-ds-%@e2e.test' AND u.email <> '${email}' ORDER BY m.created_at DESC LIMIT 20`,
  ])
  for (const line of candidates.trim().split('\n').filter(Boolean)) {
    const [candidateEmail, slug] = line.split('|')
    const token = await login(candidateEmail)
    if (token) return { token, slug: slug.trim() }
  }

  const unique = `e2e-ds-b-${Date.now()}-${Math.floor(Math.random() * 1e6)}`
  const resp = await fetch(`${API}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      email: `${unique}@e2e.test`,
      password: 'E2ePassword1',
      organization_name: `E2E DT Org ${unique}`,
      slug: unique,
    }),
  })
  if (resp.status !== 200) {
    throw new Error(
      `No reusable E2E account and registration failed (rate-limited?): ` +
        `${resp.status} ${await resp.text()}`,
    )
  }
  const body = (await resp.json()) as { access_token: string; slug: string }
  return { token: body.access_token, slug: body.slug }
}

const TOOL_BODY = {
  name: 'tool_a',
  purpose: 'Route a customer support request (E2E real backend)',
  input_schema: {
    type: 'object',
    properties: { tier: { type: 'string' } },
  },
  output_schema: {
    type: 'object',
    properties: { action: { type: 'string' } },
  },
  state_preset: {
    tier: { source: 'input', key: 'tier' },
  },
  act_threshold: 0.9,
  confirm_threshold: 0.7,
  provider_model: 'jev-latest',
  questions: [
    {
      question_key: 'route',
      question_type: 'choice',
      instructions: 'Pick the routing action.',
      criteria_options: {
        refund: 'Refund the customer',
        escalate: 'Send to a human',
      },
      ordering: 0,
    },
    {
      question_key: 'severity',
      question_type: 'score',
      instructions: 'Rate the severity.',
      criteria_options: ['1 = low', '5 = critical'],
      ordering: 1,
    },
    {
      question_key: 'is_outage',
      question_type: 'noul',
      instructions: 'Is this an outage?',
      ordering: 2,
    },
  ],
}

test.describe('Real Backend Integration - Decision Tools', () => {
  test('provider + per-tenant authoring + internal execution + DB persistence', async ({
    request,
  }) => {
    test.setTimeout(180_000)

    // ── 0. Liveness — skip when no backend is running. ────────────────
    let health = 0
    try {
      health = (await request.get(`${API}/health`)).status()
    } catch {
      health = 0
    }
    test.skip(health === 0, 'Live backend not reachable on :8000')

    const { server, port } = await startTypesafeStub()
    const stubBaseUrl = `http://127.0.0.1:${port}/v1`

    try {
      const tenantA = await registerTenant('e2e-ds-persistent@e2e.test')
      const tenantB = await registerTenant('e2e-ds-persistent-2@e2e.test')
      const authA = {
        Authorization: `Bearer ${tenantA.token}`,
        'X-Tenant': tenantA.slug,
        'Content-Type': 'application/json',
      }
      const authB = {
        Authorization: `Bearer ${tenantB.token}`,
        'X-Tenant': tenantB.slug,
        'Content-Type': 'application/json',
      }

      // ── 1. Idempotency: remove any tool_a left by a previous run. ───
      for (const auth of [authA, authB]) {
        const existing = await request.get(`${API}/decision-tools`, { headers: auth })
        expect(existing.status()).toBe(200)
        for (const t of (await existing.json()) as Array<{
          id: string
          name: string
        }>) {
          if (t.name === 'tool_a') {
            const del = await request.delete(`${API}/decision-tools/${t.id}`, {
              headers: auth,
            })
            expect([204, 404]).toContain(del.status())
          }
        }
      }

      // Authoring gate: if no System One model is configured yet, authoring
      // must be blocked with a structured error.
      const statusProbe = await request.get(`${API}/system-one/status`, {
        headers: authA,
      })
      expect(statusProbe.status()).toBe(200)
      if ((await statusProbe.json()).configured !== true) {
        const gated = await request.post(`${API}/decision-tools`, {
          headers: authA,
          data: TOOL_BODY,
        })
        expect(gated.status()).toBe(422)
        expect(JSON.stringify(await gated.json())).toContain(
          'No System One model',
        )
      }

      // ── 2. Create the provider config pointing at the stub. ─────────
      const created = await request.post(`${API}/system-one/providers`, {
        headers: authA,
        data: {
          provider_type: 'typesafe',
          display_name: 'E2E Typesafe Stub (decision tools)',
          base_url: stubBaseUrl,
          default_model: 'jev-latest',
          api_key: 'sk-e2e-real-backend-key',
          enabled: true,
        },
      })
      expect(created.status()).toBe(201)
      const provider = await created.json()
      expect(provider.id).toBeTruthy()
      // Write-only: no key material anywhere in the response.
      expect(JSON.stringify(provider)).not.toContain('sk-e2e-real-backend-key')
      expect(provider.has_api_key).toBe(true)

      const statusAfter = await request.get(`${API}/system-one/status`, {
        headers: authA,
      })
      expect((await statusAfter.json()).configured).toBe(true)

      // ── 3. Author identical "tool_a" in BOTH tenants. ────────────────
      // Provider configs are tenant-scoped: tenant B needs its own enabled
      // provider (same stub) before its authoring gate opens.
      const createdB = await request.post(`${API}/system-one/providers`, {
        headers: authB,
        data: {
          provider_type: 'typesafe',
          display_name: 'E2E Typesafe Stub (tenant B)',
          base_url: stubBaseUrl,
          default_model: 'jev-latest',
          api_key: 'sk-e2e-real-backend-key',
          enabled: true,
        },
      })
      expect(createdB.status()).toBe(201)

      const createA = await request.post(`${API}/decision-tools`, {
        headers: authA,
        data: TOOL_BODY,
      })
      expect(createA.status()).toBe(201)
      const toolA = await createA.json()

      const createB = await request.post(`${API}/decision-tools`, {
        headers: authB,
        data: TOOL_BODY,
      })
      if (createB.status() !== 201) {
        const dbgStatus = await request.get(`${API}/system-one/status`, {
          headers: authB,
        })
        throw new Error(
          `createB ${createB.status()}: ${await createB.text()} | statusB=${dbgStatus.status()} ${await dbgStatus.text()}`,
        )
      }
      const toolB = await createB.json()

      // Tenant isolation: separate rows, same name.
      expect(toolA.id).not.toBe(toolB.id)
      expect(toolA.name).toBe('tool_a')
      expect(toolB.name).toBe('tool_a')

      // Auto-generated description present and definition-derived.
      expect(toolA.description).toContain("Decision tool 'tool_a'")
      expect(toolA.description).toContain(TOOL_BODY.purpose)
      expect(toolA.description).toContain('`route` (choice)')
      const desc = await request.get(
        `${API}/decision-tools/${toolA.id}/description`,
        { headers: authA },
      )
      expect(desc.status()).toBe(200)
      expect(((await desc.json()) as { description: string }).description).toBe(
        toolA.description,
      )

      // Duplicate name within one tenant → 409; questions not persisted.
      const duplicate = await request.post(`${API}/decision-tools`, {
        headers: authA,
        data: TOOL_BODY,
      })
      expect(duplicate.status()).toBe(409)

      // Per-type validation negative: noul with criteria.
      const badTool = await request.post(`${API}/decision-tools`, {
        headers: authA,
        data: {
          ...TOOL_BODY,
          name: 'tool_bad',
          questions: [
            {
              question_key: 'bad_noul',
              question_type: 'noul',
              criteria_options: { x: 'y' },
              ordering: 0,
            },
          ],
        },
      })
      expect(badTool.status()).toBe(422)

      // Cross-tenant read → 404 (tenant-filtered).
      const crossRead = await request.get(`${API}/decision-tools/${toolA.id}`, {
        headers: authB,
      })
      expect(crossRead.status()).toBe(404)

      // ── 4. Execute BOTH tenants through the real internal endpoint ──
      //      (/decision/execute — the CH-forwarded path, service
      //      certificate authentication). ────────────────────────────────
      const execA = await request.post(
        `${API}/internal/system-tools/decision/execute`,
        {
          headers: {
            'Content-Type': 'application/json',
            // The backend expects the PEM with literal "\n" escapes (it
            // unescapes them itself) — raw newlines are invalid in headers.
            'X-Client-Certificate': CERT_PEM.replace(/\n/g, '\\n'),
          },
          data: {
            session_id: 'e2e-real-backend-a',
            tenant_id: toolA.tenant_id,
            tool_name: 'tool_a',
            input_state: { tier: 'gold' },
          },
        },
      )
      expect(execA.status()).toBe(200)
      const resultA = (await execA.json()).result
      expect(resultA.status).toBe('completed')
      expect(resultA.outcome).toBe('act')
      expect(resultA.provider_model).toBe('jev-latest')
      expect(resultA.tool_name).toBe('tool_a')
      expect(resultA.answers.route.choice).toBe('refund')
      expect(resultA.answers.severity.score).toBe(4)
      expect(resultA.answers.is_outage.noul).toBe(1.0)
      expect(resultA.input_state_snapshot).toEqual({ tier: 'gold' })
      expect(JSON.stringify(resultA)).not.toContain('sk-e2e-real-backend-key')

      // Same tool name resolves WITHIN tenant B (stub answers 404? no —
      // provider is tenant A's; tenant B execution fails gracefully with a
      // failed result, proving tenant containment of provider resolution is
      // NOT required: the provider is global, the TOOL is tenant-contained).
      const execB = await request.post(
        `${API}/internal/system-tools/decision/execute`,
        {
          headers: {
            'Content-Type': 'application/json',
            'X-Client-Certificate': CERT_PEM.replace(/\n/g, '\\n'),
          },
          data: {
            session_id: 'e2e-real-backend-b',
            tenant_id: toolB.tenant_id,
            tool_name: 'tool_a',
            input_state: { tier: 'silver' },
          },
        },
      )
      expect(execB.status()).toBe(200)
      const resultB = (await execB.json()).result
      expect(resultB.tool_name).toBe('tool_a')
      expect(resultB.input_state_snapshot).toEqual({ tier: 'silver' })

      // Tenant-scoped catalog via the internal list endpoint.
      const listA = await request.post(
        `${API}/internal/system-tools/decision/list`,
        {
          headers: {
            'Content-Type': 'application/json',
            'X-Client-Certificate': CERT_PEM.replace(/\n/g, '\\n'),
          },
          data: { tenant_id: toolA.tenant_id },
        },
      )
      expect(listA.status()).toBe(200)
      const toolsA = ((await listA.json()) as { tools: Array<{ name: string }> }).tools
      expect(toolsA.map((t) => t.name)).toContain('tool_a')

      // ── 5. Persistence: verified directly against the real PostgreSQL
      //      in the parthenon-postgres container. ────────────────────────
      const { stdout } = await psql('docker', [
        'exec',
        'parthenon-postgres',
        'psql',
        '-U',
        'parthenon',
        '-d',
        'parthenon',
        '-tAc',
        `SELECT status || '|' || outcome || '|' || COALESCE(provider_model, '') || '|' || answers::text FROM decision_execution_results WHERE decision_tool_id = '${toolA.id}' ORDER BY created_at DESC LIMIT 1`,
      ])
      const dbRows = stdout.trim().split('\n').filter(Boolean)
      expect(dbRows.length).toBe(1)
      const [dbStatus, dbOutcome, dbModel, dbAnswers] = dbRows[0].split('|')
      expect(dbStatus).toBe('completed')
      expect(dbOutcome).toBe('act')
      expect(dbModel).toBe('jev-latest')
      expect(dbAnswers).toContain('"choice"')
      expect(dbAnswers).toContain('refund')
      expect(dbAnswers).not.toContain('sk-e2e-real-backend-key')

      // Tenant A's tool has results; verify tenant B's tool row exists too.
      const { stdout: toolBCount } = await psql('docker', [
        'exec',
        'parthenon-postgres',
        'psql',
        '-U',
        'parthenon',
        '-d',
        'parthenon',
        '-tAc',
        `SELECT count(*) FROM decision_tools WHERE name = 'tool_a' AND id IN ('${toolA.id}', '${toolB.id}')`,
      ])
      expect(parseInt(toolBCount.trim(), 10)).toBe(2)

      // ── 6. Results queryable via the tenant API keyed to the tool. ──
      const results = await request.get(`${API}/results/decision`, {
        headers: authA,
        params: { decision_tool_id: toolA.id },
      })
      expect(results.status()).toBe(200)
      const items = (await results.json()) as Array<Record<string, unknown>>
      expect(items.length).toBeGreaterThanOrEqual(1)
      expect(items[0]['decision_tool_id']).toBe(toolA.id)
      expect(JSON.stringify(items)).not.toContain('sk-e2e-real-backend-key')

      // ── 7. Delete the provider → removed from the listing. ─────────
      const deleted = await request.delete(
        `${API}/system-one/providers/${provider.id}`,
        { headers: authA },
      )
      expect(deleted.status()).toBe(204)
      const remaining = await request.get(`${API}/system-one/providers`, {
        headers: authA,
      })
      const ids = ((await remaining.json()) as Array<{ id: string }>).map(
        (p) => p.id,
      )
      expect(ids).not.toContain(provider.id)
    } finally {
      server.close()
    }
  })

  test('round 2: data type reference + test-connection + MCP listing + reserved slug', async ({
    request,
  }) => {
    test.setTimeout(120_000)

    // ── 0. Liveness — skip when no backend is running. ────────────────
    let health = 0
    try {
      health = (await request.get(`${API}/health`)).status()
    } catch {
      health = 0
    }
    test.skip(health === 0, 'Live backend not reachable on :8000')

    const { server, port } = await startTypesafeStub()
    const stubBaseUrl = `http://127.0.0.1:${port}/v1`
    const suffix = Date.now().toString(36)

    try {
      const tenant = await registerTenant('e2e-ds-persistent@e2e.test')
      const auth = {
        Authorization: `Bearer ${tenant.token}`,
        'X-Tenant': tenant.slug,
        'Content-Type': 'application/json',
      }

      // Provider pointing at the local stub (needed for the authoring gate
      // and for the real test-connection probe).
      const created = await request.post(`${API}/system-one/providers`, {
        headers: auth,
        data: {
          provider_type: 'typesafe',
          display_name: `E2E Round2 Stub ${suffix}`,
          base_url: stubBaseUrl,
          default_model: 'jev-latest',
          api_key: 'sk-e2e-round2-key',
          enabled: true,
        },
      })
      expect(created.status()).toBe(201)
      const provider = await created.json()

      // ── 1. Create a REAL AgentDataType via the real data types API. ──
      const dtResp = await request.post(`${API}/data-types`, {
        headers: auth,
        data: {
          name: `e2e-round2-loan-${suffix}`,
          slug: `e2e-round2-loan-${suffix}`,
          description: 'Round-2 e2e input contract',
          fields: [
            { name: 'amount', type: 'number', description: 'Loan amount' },
            { name: 'tier', type: 'string', description: 'Customer tier' },
          ],
        },
      })
      expect(dtResp.status()).toBe(201, await dtResp.text())
      const dataType = await dtResp.json()

      // ── 2. Decision tool referencing the real data type. ─────────────
      const toolName = `tool_dt2_${suffix}`
      const createTool = await request.post(`${API}/decision-tools`, {
        headers: auth,
        data: {
          name: toolName,
          purpose: 'Round-2 real-backend data type reference journey',
          input_data_type_id: dataType.id,
          output_data_type_id: dataType.id,
          state_preset: { tier: { source: 'input', key: 'tier' } },
          questions: [
            {
              question_key: 'approve',
              question_type: 'choice',
              instructions: 'Approve?',
              criteria_options: { yes: 'y', no: 'n' },
              ordering: 0,
            },
          ],
        },
      })
      expect(createTool.status()).toBe(201, await createTool.text())
      const tool = await createTool.json()
      expect(tool.input_data_type.id).toBe(dataType.id)
      // Generated description derived from the referenced type's fields.
      expect(tool.description).toContain(dataType.name)
      expect(tool.description).toContain('amount, tier')

      // State preset validated against the input type's fields: unknown
      // field → 422.
      const badPreset = await request.post(`${API}/decision-tools`, {
        headers: auth,
        data: {
          name: `tool_bad_${suffix}`,
          purpose: 'bad preset',
          input_data_type_id: dataType.id,
          state_preset: { x: { source: 'input', key: 'not_a_field' } },
          questions: [
            {
              question_key: 'q',
              question_type: 'noul',
              ordering: 0,
            },
          ],
        },
      })
      expect(badPreset.status()).toBe(422)

      // ── 3. Test-connection against the stub → ok, no key material. ──
      const testConn = await request.post(
        `${API}/system-one/providers/${provider.id}/test`,
        { headers: auth },
      )
      expect(testConn.status()).toBe(200)
      const testBody = await testConn.json()
      expect(testBody.ok).toBe(true)
      expect(JSON.stringify(testBody)).not.toContain('sk-e2e-round2-key')

      // ── 4. MCP tools listing includes the decision____ tool. ─────────
      const mcpTools = await request.get(`${API}/mcp/tools`, { headers: auth })
      expect(mcpTools.status()).toBe(200)
      const tools = (await mcpTools.json()) as Array<{
        name: string
        server_slug?: string
      }>
      const entry = tools.find((t) => t.name === `decision____${toolName}`)
      expect(entry, 'decision____ tool in /mcp/tools').toBeTruthy()
      expect(entry!.server_slug).toBe('decision')

      // ── 5. MCP hub rejects the reserved "decision" slug with 409. ────
      const reserved = await request.post(`${API}/mcp/servers`, {
        headers: auth,
        data: {
          name: 'decision',
          slug: 'decision',
          base_url: 'http://localhost:9/mcp',
        },
      })
      expect(reserved.status()).toBe(409)

      // ── 6. Cleanup: remove the tool, then the now-unreferenced type. ─
      const delTool = await request.delete(`${API}/decision-tools/${tool.id}`, {
        headers: auth,
      })
      expect(delTool.status()).toBe(204)
      const delProvider = await request.delete(
        `${API}/system-one/providers/${provider.id}`,
        { headers: auth },
      )
      expect([204, 404]).toContain(delProvider.status())
    } finally {
      server.close()
    }
  })

  test('decision tool routes reject unauthenticated access', async ({ request }) => {    let health = 0
    try {
      health = (await request.get(`${API}/health`)).status()
    } catch {
      health = 0
    }
    test.skip(health === 0, 'Live backend not reachable on :8000')

    const noAuthList = await request.get(`${API}/decision-tools`)
    expect([401, 403]).toContain(noAuthList.status())

    const noAuthCreate = await request.post(`${API}/decision-tools`, {
      data: TOOL_BODY,
    })
    expect([401, 403]).toContain(noAuthCreate.status())

    const noAuthResults = await request.get(`${API}/results/decision`)
    expect([401, 403]).toContain(noAuthResults.status())

    const noAuthProviders = await request.get(`${API}/system-one/providers`)
    expect([401, 403]).toContain(noAuthProviders.status())
  })
})
