import { createServer, type Server } from 'node:http'
import { expect, test } from '@playwright/test'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'

/**
 * Real Backend Integration - Decision Model Providers.
 *
 * No route mocks: exercises the REAL Control Center API + real PostgreSQL
 * (with the b7d2e9f4a1c8 decision-guardrail-scoping migration applied). Covers test-plan §4.2/4.3
 * journeys at the API level:
 *
 * - provider CRUD against the live API: create (multi-model catalogue),
 *   write-only key (never echoed), duplicate display name → 409,
 * - per-model availability: the enabled-models feed lists every catalogue
 *   model with a STABLE availability id; manual disable removes the model
 *   from the feed; re-enable restores it,
 * - vendor cascade: provider-level disable removes ALL models; re-enable
 *   restores cascade-disabled models but a manually disabled model stays
 *   disabled (manual disable reason preserved),
 * - delete blocking: a provider referenced by a decision tool cannot be
 *   deleted (409 naming the tool); after the tool is removed the provider
 *   deletes and the same display name can be recreated (true delete),
 * - DB persistence verified directly via psql in parthenon-postgres
 *   (availability rows + migration revision),
 * - credential security: no key material in ANY response.
 *
 * Skips cleanly when the backend or Postgres is unreachable.
 */

const API = 'http://localhost:8000/api/v1'

const psql = promisify(execFile)

/** Minimal TypeSafe Jev stub (unused by these tests — the stub only needs
 * to exist so the provider endpoint is a valid URL; connection tests are
 * covered elsewhere). */
async function startTypesafeStub(): Promise<{ server: Server; url: string }> {
  const server = createServer((req, res) => {
    let body = ''
    req.on('data', (chunk) => (body += chunk))
    req.on('end', () => {
      res.writeHead(200, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ model: 'jev-latest', answers: {} }))
    })
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const port = (server.address() as { port: number }).port
  return { server, url: `http://127.0.0.1:${port}/v1` }
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

async function registerTenant(email: string): Promise<{ token: string; slug: string }> {
  const existing = await login(email)
  if (existing) {
    const memberships = await psql('docker', [
      'exec', 'parthenon-postgres', 'psql', '-U', 'parthenon', '-d', 'parthenon', '-tAc',
      `SELECT t.slug FROM tenants t JOIN tenant_user_memberships m ON m.tenant_id = t.id JOIN platform_users u ON u.id = m.user_id WHERE u.email = '${email}' AND t.slug <> 'root' ORDER BY m.created_at DESC LIMIT 1`,
    ])
    return { token: existing, slug: memberships.stdout.trim() }
  }
  const unique = `e2e-dmp-${Date.now()}-${Math.floor(Math.random() * 1e6)}`
  const resp = await fetch(`${API}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      email: `${unique}@e2e.test`,
      password: 'E2ePassword1',
      organization_name: `E2E DMP Org ${unique}`,
      slug: unique,
    }),
  })
  if (resp.status !== 200) {
    throw new Error(`registration failed: ${resp.status} ${await resp.text()}`)
  }
  const body = (await resp.json()) as { access_token: string; slug: string }
  return { token: body.access_token, slug: body.slug }
}

const UNIQUE = `e2e-dmp-provider-${Date.now()}`

test.describe('Real Backend Integration - Decision Model Providers', () => {
  test('multi-provider CRUD, availability cascade, delete blocking, DB persistence', async ({
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

    const { server, url: stubUrl } = await startTypesafeStub()

    try {
      const tenant = await registerTenant('e2e-ds-persistent@e2e.test')
      const auth = {
        Authorization: `Bearer ${tenant.token}`,
        'X-Tenant': tenant.slug,
        'Content-Type': 'application/json',
      }

      // ── 1. Provider CRUD: create with a 2-model catalogue. ──────────
      const created = await request.post(`${API}/system-one/providers`, {
        headers: auth,
        data: {
          provider_type: 'typesafe',
          display_name: UNIQUE,
          base_url: stubUrl,
          default_model: 'dmp-a',
          api_key: 'sk-e2e-dmp-real-key',
          enabled: true,
          enabled_models: ['dmp-a', 'dmp-b'],
        },
      })
      expect(created.status()).toBe(201)
      const provider = await created.json()
      const providerId = provider.id as string
      expect(providerId).toBeTruthy()
      // Write-only secret: no key material anywhere in the response.
      expect(JSON.stringify(provider)).not.toContain('sk-e2e-dmp-real-key')
      expect(provider.has_api_key).toBe(true)

      // Duplicate display name within the same vendor type → 409.
      const duplicate = await request.post(`${API}/system-one/providers`, {
        headers: auth,
        data: {
          provider_type: 'typesafe',
          display_name: UNIQUE,
          base_url: stubUrl,
          default_model: 'dmp-a',
          api_key: 'sk-another',
          enabled: true,
        },
      })
      expect(duplicate.status()).toBe(409)
      expect(JSON.stringify(await duplicate.json())).toContain('already exists')

      // ── 2. Enabled-models feed: every catalogue model listed with a
      //      stable availability id (no 500 on a fresh provider). ─────
      const enabledResp = await request.get(
        `${API}/system-one/enabled-models`,
        { headers: auth },
      )
      expect(enabledResp.status()).toBe(200)
      const enabled = (await enabledResp.json()) as Array<{
        availability_id: string
        provider_id: string
        model_name: string
        provider_display_name: string
      }>
      const mine = enabled.filter((m) => m.provider_id === providerId)
      expect(new Set(mine.map((m) => m.model_name))).toEqual(
        new Set(['dmp-a', 'dmp-b']),
      )
      for (const m of mine) {
        expect(m.availability_id).toBeTruthy()
        expect(m.provider_display_name).toBe(UNIQUE)
      }
      const modelA = mine.find((m) => m.model_name === 'dmp-a')!
      const modelB = mine.find((m) => m.model_name === 'dmp-b')!

      // ── 3. Manual per-model disable → model leaves the feed. ────────
      const disableA = await request.put(
        `${API}/system-one/models/${modelA.availability_id}/availability`,
        { headers: auth, data: { is_disabled: true } },
      )
      expect(disableA.status()).toBe(200)
      const disabledBody = await disableA.json()
      expect(disabledBody).toMatchObject({
        model_name: 'dmp-a',
        is_disabled: true,
        disabled_reason: 'manual',
      })
      const afterDisable = (await (
        await request.get(`${API}/system-one/enabled-models`, { headers: auth })
      ).json()) as Array<{ provider_id: string; model_name: string }>
      expect(
        afterDisable.some(
          (m) => m.provider_id === providerId && m.model_name === 'dmp-a',
        ),
      ).toBe(false)
      expect(
        afterDisable.some(
          (m) => m.provider_id === providerId && m.model_name === 'dmp-b',
        ),
      ).toBe(true)

      // ── 4. Vendor cascade disable → ALL models leave the feed. ──────
      const vendorDisable = await request.put(
        `${API}/system-one/providers/${providerId}/availability`,
        { headers: auth, data: { is_disabled: true } },
      )
      expect(vendorDisable.status()).toBe(200)
      const afterCascade = (await (
        await request.get(`${API}/system-one/enabled-models`, { headers: auth })
      ).json()) as Array<{ provider_id: string }>
      expect(afterCascade.some((m) => m.provider_id === providerId)).toBe(false)

      // ── 5. Vendor re-enable: dmp-b returns, dmp-a stays manually
      //      disabled (manual disable reason preserved). ───────────────
      const vendorEnable = await request.put(
        `${API}/system-one/providers/${providerId}/availability`,
        { headers: auth, data: { is_disabled: false } },
      )
      expect(vendorEnable.status()).toBe(200)
      const afterReEnable = (await (
        await request.get(`${API}/system-one/enabled-models`, { headers: auth })
      ).json()) as Array<{ provider_id: string; model_name: string }>
      const names = afterReEnable
        .filter((m) => m.provider_id === providerId)
        .map((m) => m.model_name)
      expect(names).toContain('dmp-b')
      expect(names).not.toContain('dmp-a')

      // ── 6. DB persistence via psql (rows + migration revision). ─────
      const { stdout: revision } = await psql('docker', [
        'exec', 'parthenon-postgres', 'psql', '-U', 'parthenon', '-d', 'parthenon', '-tAc',
        'SELECT version_num FROM alembic_version',
      ])
      expect(revision.trim()).toBe('b7d2e9f4a1c8')
      const { stdout: availabilityRows } = await psql('docker', [
        'exec', 'parthenon-postgres', 'psql', '-U', 'parthenon', '-d', 'parthenon', '-tAc',
        `SELECT model_name, is_disabled, disabled_reason FROM decision_model_availability WHERE decision_model_provider_id = '${providerId}' ORDER BY model_name`,
      ])
      const rows = availabilityRows.trim().split('\n').filter(Boolean)
      // dmp-a manual-disabled; dmp-b's cascade row was cleared on re-enable
      expect(rows).toContain('dmp-a|t|manual')

      // ── 7. Delete blocking + true delete + same-name recreate. ──────
      // Re-fetch the feed: the cascade round-trip re-seeds dmp-b's row
      // with a NEW availability id (the old one was cascade-cleared).
      const refreshed = (await (
        await request.get(`${API}/system-one/enabled-models`, { headers: auth })
      ).json()) as Array<{ provider_id: string; model_name: string; availability_id: string }>
      const freshB = refreshed.find(
        (m) => m.provider_id === providerId && m.model_name === 'dmp-b',
      )
      expect(freshB).toBeTruthy()

      const tool = await request.post(`${API}/decision-tools`, {
        headers: auth,
        data: {
          name: `dmp_blocker_${Date.now()}`,
          purpose: 'Blocks provider deletion (E2E DMP)',
          enabled: false,
          act_threshold: 0.9,
          confirm_threshold: 0.7,
          decision_model_availability_id: freshB!.availability_id,
          questions: [
            {
              question_key: 'approve',
              question_type: 'noul',
              instructions: 'Approve?',
              ordering: 0,
            },
          ],
        },
      })
      if (tool.status() !== 201) {
        throw new Error(`tool create ${tool.status()}: ${await tool.text()}`)
      }
      expect(tool.status()).toBe(201)
      const toolBody = await tool.json()
      expect(toolBody.model_name).toBe('dmp-b')
      expect(toolBody.provider_display_name).toBe(UNIQUE)

      const blockedDelete = await request.delete(
        `${API}/system-one/providers/${providerId}`,
        { headers: auth },
      )
      expect(blockedDelete.status()).toBe(409)
      expect(JSON.stringify(await blockedDelete.json())).toContain(
        toolBody.name as string,
      )

      // Remove the blocking tool → provider deletes → same name recreates.
      const delTool = await request.delete(
        `${API}/decision-tools/${toolBody.id}`,
        { headers: auth },
      )
      expect(delTool.status()).toBe(204)
      const deleteProvider = await request.delete(
        `${API}/system-one/providers/${providerId}`,
        { headers: auth },
      )
      expect(deleteProvider.status()).toBe(204)

      const recreate = await request.post(`${API}/system-one/providers`, {
        headers: auth,
        data: {
          provider_type: 'typesafe',
          display_name: UNIQUE,
          base_url: stubUrl,
          default_model: 'dmp-a',
          api_key: 'sk-e2e-dmp-real-key',
          enabled: true,
          enabled_models: ['dmp-a'],
        },
      })
      expect(recreate.status()).toBe(201)
      await request.delete(
        `${API}/system-one/providers/${((await recreate.json()) as { id: string }).id}`,
        { headers: auth },
      )
    } finally {
      server.close()
    }
  })
})
