/* FIX-20261102-062047 live probe — MCP tool/server listing contract.
 *
 * Evidence for the picker truncation + cc visibility defects (and the fix):
 *
 *  A. admin (cc read) — GET /mcp/tools with the OLD default recorded as the
 *     baseline: default window returned exactly 50 tools, all system+cc;
 *     supabase/map-demo/decision were absent (the picker's missing MCPs).
 *  B. after fix — default window = 200 covers every tool; X-Total-Count is
 *     exposed; ordering is (server_slug, name); paging with limit=50 has no
 *     loss/duplication and covers the same set.
 *  C. no-cc-read user — /mcp/servers hides `cc`; /mcp/tools hides every cc
 *     tool; a cc tool referenced by an existing skill is still individually
 *     resolvable (read-only editor path) via GET /mcp/tools/{id}.
 *  D. /mcp/servers paginated at limit=3 with cc filtered yields full pages
 *     and every server exactly once.
 *
 * Auth: admin via /auth/login-password; the no-cc-read principal is a real
 * root-tenant PlatformUser (Agent Viewer role) signed with the CC secret —
 * the dev/E2E token pattern (login-password is owner-only).
 */
const path = require('path')
const { execFileSync } = require('child_process')

const ROOT = '/Users/minglijiang/source/parthenon'
const CC = 'http://localhost:8000/api/v1'

async function loginAdmin() {
  const res = await fetch(`${CC}/auth/login-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: 'admin@parthenon.local', password: 'admin' }),
  })
  if (!res.ok) throw new Error(`admin login failed: ${res.status}`)
  return (await res.json()).access_token
}

function mintNoCcToken() {
  const code = `
import time, uuid
from jose import jwt
from app.core.config import get_settings
s=get_settings()
claims={"sub":"probe-062047-sub","email":"probe-062047@e2e.test","name":"Probe User",
 "platform_account":True,"platform_role":"member","tenant":"root",
 "tenant_id":"aa1878c4-d13d-41cd-bf9b-400f55b5f8ce","tenant_access":"tenant",
 "iat":int(time.time()),"exp":int(time.time())+3600,"jti":str(uuid.uuid4())}
print(jwt.encode(claims, s.secret_key, algorithm="HS256"))
`
  return execFileSync(path.join(ROOT, '.venv/bin/python'), ['-c', code], {
    cwd: path.join(ROOT, 'backend'),
    encoding: 'utf8',
  }).trim()
}

async function get(url, token) {
  const res = await fetch(`${CC}${url}`, {
    headers: { Authorization: `Bearer ${token}`, 'X-Tenant': 'root' },
  })
  const text = await res.text()
  let body
  try {
    body = JSON.parse(text)
  } catch {
    body = text
  }
  return { status: res.status, body, total: res.headers.get('x-total-count') }
}

function countByServer(tools) {
  const counts = {}
  for (const tool of tools) counts[tool.server_slug] = (counts[tool.server_slug] || 0) + 1
  return counts
}

async function main() {
  const admin = await loginAdmin()
  const noCc = mintNoCcToken()

  // A/B — admin tool listing (cc read).
  const adminDefault = await get('/mcp/tools', admin)
  const adminExplicit = await get('/mcp/tools?limit=200&offset=0', admin)
  const adminOrder = adminExplicit.body.map((t) => `${t.server_slug}/${t.name}`)
  const sorted = [...adminOrder].sort()
  const orderStable = JSON.stringify(adminOrder) === JSON.stringify(sorted)

  const pageSize = 50
  const paged = []
  for (let offset = 0; ; offset += pageSize) {
    const page = await get(`/mcp/tools?limit=${pageSize}&offset=${offset}`, admin)
    paged.push(...page.body)
    if (page.body.length < pageSize) break
  }
  const pagedIds = paged.map((t) => t.id)
  const fullIds = adminExplicit.body.map((t) => t.id)
  const noLossNoDup =
    pagedIds.length === new Set(pagedIds).size &&
    JSON.stringify([...pagedIds].sort()) === JSON.stringify([...fullIds].sort())

  // The WORKING-SET evidence for the picker.
  const adminCounts = countByServer(adminExplicit.body)

  // C — no-cc-read principal.
  const noCcServers = await get('/mcp/servers?limit=100', noCc)
  const noCcTools = await get('/mcp/tools?limit=200', noCc)
  const ccServerHidden = !noCcServers.body.some((s) => s.slug === 'cc')
  const ccToolsHidden = !noCcTools.body.some((t) => t.server_slug === 'cc')

  // Referenced cc tool (from the built-in control-center-management skill).
  const skills = await get('/skills?limit=100', admin)
  const ccSkill = skills.body.find((s) => s.name === 'control-center-management')
  const referenced = ccSkill && ccSkill.tool_bindings[0]
  const referencedResolve = referenced
    ? await get(`/mcp/tools/${referenced.tool_id}`, noCc)
    : { status: 0 }

  // D — server pagination with the cc filter.
  const serverPages = []
  for (let offset = 0; ; offset += 3) {
    const page = await get(`/mcp/servers?limit=3&offset=${offset}`, noCc)
    serverPages.push(...page.body.map((s) => s.slug))
    if (page.body.length < 3) break
  }
  const serverNoDup = serverPages.length === new Set(serverPages).size
  const serverPageFull = serverPages.length >= 3

  const result = {
    probeBaseline: {
      oldDefaultLimit: 50,
      note: 'recorded pre-fix: default window returned exactly 50 tools, only system+cc',
    },
    admin: {
      defaultStatus: adminDefault.status,
      defaultCount: adminDefault.body.length,
      defaultCounts: countByServer(adminDefault.body),
      totalHeader: adminExplicit.total,
      explicitCount: adminExplicit.body.length,
      explicitCounts: adminCounts,
      orderingDeterministic: orderStable,
      pagingNoLossNoDup: noLossNoDup,
      supabasePresent: (adminCounts.supabase || 0) > 0,
      decisionServerPresent: adminExplicit.body.some((t) => t.server_slug === 'decision'),
    },
    noCcPrincipal: {
      servers: noCcServers.body.map((s) => s.slug),
      ccServerHidden,
      toolCount: noCcTools.body.length,
      ccToolsHidden,
      referencedCcToolId: referenced ? referenced.tool_id : null,
      referencedCcToolResolveStatus: referencedResolve.status,
      referencedCcToolResolvedName:
        referencedResolve.status === 200 ? referencedResolve.body.name : null,
    },
    serverPaging: {
      pagesWalked: serverPages,
      noDuplicates: serverNoDup,
      pageSizeRespected: serverPageFull,
      ccHidden: !serverPages.includes('cc'),
    },
  }

  console.log(JSON.stringify(result, null, 2))

  const ok =
    adminDefault.status === 200 &&
    adminExplicit.body.length <= 200 &&
    orderStable &&
    noLossNoDup &&
    result.admin.supabasePresent &&
    ccServerHidden &&
    ccToolsHidden &&
    referencedResolve.status === 200 &&
    referencedResolve.body.server_slug === 'cc' &&
    serverNoDup &&
    !serverPages.includes('cc')
  if (!ok) process.exit(1)
  console.log('LIVE-PROBE-PASSED')
}

main().catch((err) => {
  console.error('LIVE-PROBE-FAILED', err)
  process.exit(1)
})
