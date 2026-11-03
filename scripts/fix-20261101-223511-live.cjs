/* FIX-20261101-223511 live verification.
 * Drives a REAL assistant turn through the Vite-proxied WS (5173) with the
 * LLM mock layer in scripted mode (requires the stack restarted with
 * LLM_MOCK_MODE=scripted and LLM_MOCK_SCRIPTED_RESPONSES=@tmp/fix-223511-scripted.json).
 * Scripted flow:
 *   1. user asks (marker "create-preview-live") to create skill
 *      confirm-preview-live-223511
 *   2. scripted rule emits human_intervene(approval) with the CANONICAL
 *      preview: bold title line + '| Field | Value |' markdown table
 *   3. script approves via the real intervene_response flow
 *   4. the REAL invoke_management_tool create_skill runs WITHOUT tools
 * Asserts:
 *   A. the intervene_request prompt/reason is in the CANONICAL format
 *      (bold title '**Create Skill: <name>**' + '| Field | Value |' table)
 *   B. the create actually executed and its tool result carried the
 *      zero-binding warning ("no tools bound") — the scripted final reply
 *      quotes it, proving the warning reached the assistant
 *   C. the skills REST list exposes tool_bindings for every skill
 *   D. (DOM check is covered by the Vitest expand tests — this script
 *      verifies the WS/API side.)
 */
const WebSocket = require('/Users/minglijiang/source/parthenon/frontend/node_modules/ws')

const CC = 'http://localhost:8000/api/v1'
const WS_BASE = 'ws://localhost:5173/ws'
const SKILL_NAME = 'confirm-preview-live-223511'

async function main() {
  const login = await fetch(`${CC}/auth/login-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: 'admin@parthenon.local', password: 'admin' }),
  })
  if (!login.ok) throw new Error(`login failed: ${login.status} ${await login.text()}`)
  const { access_token: token } = await login.json()
  const authHeaders = { Authorization: `Bearer ${token}`, 'X-Tenant': 'root' }

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
  let interveneRequest = null
  let approved = false
  let responded = false
  let finalReply = null

  const done = new Promise((resolve, reject) => {
    const failTimer = setTimeout(() => reject(new Error('flow did not complete within 180s; events=' +
      JSON.stringify(events.map((e) => ({ t: e.type || e.status, c: String(e.content || '').slice(0, 80) }))))), 180000)
    ws.on('open', () => {
      ws.send(JSON.stringify({
        message: 'create-preview-live: create a skill named "' + SKILL_NAME + '".',
      }))
    })
    ws.on('message', (raw) => {
      let msg
      try { msg = JSON.parse(raw.toString()) } catch { return }
      events.push({ ...msg, _t: (Date.now() - start) / 1000 })
      if (msg.type === 'intervene_request' && !interveneRequest) {
        interveneRequest = msg
        console.log('INTERVENE_REQUEST received @', ((Date.now() - start) / 1000).toFixed(1) + 's')
        console.log('  preview:', (msg.reason || '').slice(0, 300).replace(/\n/g, ' ⏎ '))
        setTimeout(() => {
          approved = true
          ws.send(JSON.stringify({ type: 'intervene_response', request_id: msg.request_id, approval_value: true }))
          console.log('APPROVE sent @', ((Date.now() - start) / 1000).toFixed(1) + 's')
        }, 1000)
      }
      if (msg.type === 'intervene_status' && msg.status === 'responded') responded = true
      if (msg.sender_role === 'agent' && msg.content && approved &&
          /no tools bound/.test(msg.content) && !finalReply) {
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

  // C. REST visibility: /skills exposes tool_bindings on every skill.
  const skillsRes = await fetch(`${CC}/skills?limit=100`, { headers: authHeaders })
  const skills = await skillsRes.json()
  const skillList = Array.isArray(skills) ? skills : []
  const createdSkill = skillList.find((s) => s.name === SKILL_NAME)
  const allHaveBindingsField = skillList.length > 0 &&
    skillList.every((s) => Array.isArray(s.tool_bindings))

  const preview = (integrateReason())
  function integrateReason() { return (interveneRequest && (interveneRequest.reason || interveneRequest.prompt)) || '' }

  // A. canonical format: bold title line + Field/Value table.
  const canonicalBoldTitle = new RegExp(`\\*\\*Create Skill: ${SKILL_NAME}\\*\\*`).test(preview)
  const canonicalTable = /\|\s*Field\s*\|\s*Value\s*\|/.test(preview) && /\|\s*-{2,}/.test(preview.replace(/─/g, '-'))
  const hasResourceRows = /\|\s*Operation\s*\|/.test(preview) && /\|\s*Resource Type\s*\|/.test(preview)

  const result = {
    interveneRequestReceived: !!interveneRequest,
    interventionType: interveneRequest && interveneRequest.intervention_type,
    canonicalBoldTitle,
    canonicalTableHeader: canonicalTable,
    canonicalResourceRows: hasResourceRows,
    approveSent: approved,
    interveneStatusResponded: responded,
    finalReply: (finalReply || '').slice(0, 220),
    skillActuallyCreated: !!createdSkill,
    createdSkillToolBindings: createdSkill && createdSkill.tool_bindings,
    restListExposesToolBindings: allHaveBindingsField,
    statusTimeline: events.filter((e) => e.type === 'chat_status').map((e) => `${e.status}@${e._t.toFixed(0)}s`),
  }
  console.log('RESULT_223511', JSON.stringify(result, null, 2))
  const ok = result.interveneRequestReceived && result.canonicalBoldTitle && result.canonicalTableHeader &&
    result.canonicalResourceRows && result.interveneStatusResponded &&
    /no tools bound/.test(result.finalReply) && result.skillActuallyCreated &&
    result.restListExposesToolBindings && Array.isArray(result.createdSkillToolBindings) &&
    result.createdSkillToolBindings.length === 0
  if (!ok) process.exit(1)
  console.log('LIVE-VERIFICATION-PASSED')
}

main().catch((e) => { console.error('LIVE-VERIFICATION-FAILED', e.message); process.exit(1) })
