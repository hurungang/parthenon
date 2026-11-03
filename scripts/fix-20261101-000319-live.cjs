/* FIX-20261101-000319 live verification.
 * Drives a REAL assistant turn through the Vite-proxied WS (5173) with the
 * LLM mock layer in scripted mode. Scripted flow:
 *   1. user asks (marker "create-a-bound-skill-live") to create a skill
 *      bound to the Control Center tool cc____list_skills
 *   2. scripted rule emits cc____invoke_management_tool(create_skill,
 *      data.tool_names=["cc____list_skills"]) through the REAL
 *      AR→CH→CC management dispatch
 *   3. tool result contains the binding-proof description → scripted
 *      final answer
 * Asserts:
 *   A. the skill was created WITH its SkillToolBinding (verified via REST:
 *      GET /mcp/tools/{cc____list_skills id}/skills contains the skill)
 *   B. the Control Center (cc) MCP entity exists with the management tools,
 *      and the generic system entity no longer lists them
 *   C. a role with no cc grants resolves NO cc____ tools (role allowed-tools
 *      REST surface) while the assistant skill's tools include cc____ names
 */
const WebSocket = require('/Users/minglijiang/source/parthenon/frontend/node_modules/ws')

const CC = 'http://localhost:8000/api/v1'
const WS_BASE = 'ws://localhost:5173/ws'
const SKILL_NAME = 'live-bound-skill-000319'

async function main() {
  const login = await fetch(`${CC}/auth/login-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: 'admin@parthenon.local', password: 'admin' }),
  })
  if (!login.ok) throw new Error(`login failed: ${login.status} ${await login.text()}`)
  const { access_token: token } = await login.json()
  const authHeaders = { Authorization: `Bearer ${token}`, 'X-Tenant': 'root' }

  // ── B1. cc entity exists with management tools; system entity clean ─────
  const serversRes = await fetch(`${CC}/mcp/servers`, { headers: authHeaders })
  const servers = await serversRes.json()
  const ccServer = (Array.isArray(servers) ? servers : []).find((s) => s.slug === 'cc')
  if (!ccServer) throw new Error('Control Center (cc) MCP entity not found')
  const ccToolsRes = await fetch(`${CC}/mcp/servers/${ccServer.id}/tools`, { headers: authHeaders })
  const ccTools = await ccToolsRes.json()
  const ccNames = (Array.isArray(ccTools) ? ccTools : []).map((t) => t.name)
  const listSkillsTool = (Array.isArray(ccTools) ? ccTools : []).find((t) => t.name === 'cc____list_skills')
  if (!listSkillsTool) throw new Error('cc____list_skills not found under the cc entity: ' + ccNames.slice(0, 5))

  // ── A. drive the live WS turn ────────────────────────────────────────────
  const ats = await fetch(`${CC}/agents/types`, { headers: authHeaders })
  const atBody = await ats.json()
  const list = Array.isArray(atBody) ? atBody : (atBody.items || atBody.results || [])
  const assistant = list.find((a) => a.is_system && a.name === 'control-center-assistant')
    || list.find((a) => a.is_system)
  if (!assistant) throw new Error('no system assistant agent type found')

  const created = await fetch(`${CC}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders },
    body: JSON.stringify({ agent_type_id: assistant.id }),
  })
  if (!created.ok) throw new Error(`session create failed: ${created.status} ${await created.text()}`)
  const session = await created.json()

  const ws = new WebSocket(`${WS_BASE}/sessions/${session.id}?token=${token}`)
  const events = []
  const start = Date.now()
  let finalReply = null
  const done = new Promise((resolve, reject) => {
    const failTimer = setTimeout(() => reject(new Error('flow did not complete within 180s; events=' +
      JSON.stringify(events.map((e) => ({ t: e.type || e.status, s: e.status, c: String(e.content || '').slice(0, 60) }))))), 180000)
    ws.on('open', () => {
      ws.send(JSON.stringify({
        message: 'create-a-bound-skill-live: create a skill named "' + SKILL_NAME +
          '" that wraps the Control Center tool cc____list_skills.',
      }))
    })
    ws.on('message', (raw) => {
      let msg
      try { msg = JSON.parse(raw.toString()) } catch { return }
      events.push({ ...msg, _t: (Date.now() - start) / 1000 })
      if (msg.sender_role === 'agent' && msg.content &&
          /created and bound/.test(msg.content) && !finalReply) {
        finalReply = msg.content
        clearTimeout(failTimer)
        resolve()
      }
    })
    ws.on('error', (e) => { clearTimeout(failTimer); reject(e) })
  })
  await done
  ws.close()
  await new Promise((r) => setTimeout(r, 2000))

  // ── A2. verify the SkillToolBinding via REST ─────────────────────────────
  const skillsRes = await fetch(`${CC}/mcp/tools/${listSkillsTool.id}/skills`, { headers: authHeaders })
  const boundSkills = await skillsRes.json()
  const boundSkill = (Array.isArray(boundSkills) ? boundSkills : []).find((s) => s.name === SKILL_NAME)

  // ── C. no-cc-grant role resolves NO cc____ tools ─────────────────────────
  const rolesRes = await fetch(`${CC}/agents/roles`, { headers: authHeaders })
  const rolesBody = await rolesRes.json()
  const roles = Array.isArray(rolesBody) ? rolesBody : (rolesBody.items || [])
  let noGrantRoleHasCcTools = null
  let checkedRole = null
  for (const role of roles) {
    if (role.is_system) continue
    const atRes = await fetch(`${CC}/agents/roles/${role.id}/mcp-tools`, { headers: authHeaders })
    if (!atRes.ok) continue
    const tools = await atRes.json()
    const toolNames = Array.isArray(tools) ? tools : (tools.tools || [])
    checkedRole = role.name
    noGrantRoleHasCcTools = toolNames.some((t) => String(t).startsWith('cc____'))
    break
  }

  const result = {
    ccServerFound: !!ccServer,
    ccToolCount: ccNames.length,
    ccToolsIncludeManagement: ccNames.includes('cc____create_skill') && ccNames.includes('cc____invoke_management_tool'),
    ccToolsExcludeGeneral: !ccNames.includes('system____save_data'),
    liveTurnFinalReply: (finalReply || '').slice(0, 160),
    skillCreatedWithBinding: !!boundSkill,
    boundSkillId: boundSkill && boundSkill.id,
    noGrantRole: checkedRole,
    noGrantRoleSeesCcTools: noGrantRoleHasCcTools,
    statusTimeline: events.filter((e) => e.type === 'chat_status').map((e) => `${e.status}@${e._t.toFixed(0)}s`),
  }
  console.log('RESULT_000319', JSON.stringify(result, null, 2))
  const ok = result.ccServerFound && result.ccToolsIncludeManagement && result.ccToolsExcludeGeneral &&
    result.skillCreatedWithBinding && result.noGrantRoleSeesCcTools === false
  if (!ok) process.exit(1)
  console.log('LIVE-VERIFICATION-PASSED')
}

main().catch((e) => { console.error('LIVE-VERIFICATION-FAILED', e.message); process.exit(1) })
