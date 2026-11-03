/* FIX-20261031-133253 live verification.
 * Drives a REAL assistant turn through the Vite-proxied WS (5173) with the
 * LLM mock layer in scripted mode. Scripted flow:
 *   1. invoke list_model_configs (read — must NOT require confirmation)
 *   2. present markdown-table preview + human_intervene (approval)
 *   3. script sends intervene_response (approve) via the real WS flow
 *   4. on approve, the REAL invoke_management_tool create_agent_type runs
 * Asserts: intervene_request received with markdown table in prompt/payload,
 * intervene_status responded, final agent reply, and the agent type actually
 * created via the REST API afterwards. */
const WebSocket = require('/Users/minglijiang/source/parthenon/frontend/node_modules/ws')

const CC = 'http://localhost:8000/api/v1'
const WS_BASE = 'ws://localhost:5173/ws'

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
  console.log('SESSION', session.id)

  const ws = new WebSocket(`${WS_BASE}/sessions/${session.id}?token=${token}`)
  const events = []
  const start = Date.now()
  let interveneRequest = null
  let responded = false
  let finalReply = null
  let approved = false

  const done = new Promise((resolve, reject) => {
    const failTimer = setTimeout(() => reject(new Error('flow did not complete within 180s; events=' + JSON.stringify(events.map(e => ({ t: e.type || e.status, _t: e._t }))), null, 1)), 180000)
    ws.on('open', () => {
      ws.send(JSON.stringify({ message: 'Please create the fraud detection agent for me.' }))
    })
    ws.on('message', (raw) => {
      let msg
      try { msg = JSON.parse(raw.toString()) } catch { return }
      events.push({ ...msg, _t: (Date.now() - start) / 1000 })
      if (msg.type === 'intervene_request' && !interveneRequest) {
        interveneRequest = msg
        console.log('INTERVENE_REQUEST received @', ((Date.now() - start) / 1000).toFixed(1) + 's')
        console.log('  reason:', (msg.reason || '').slice(0, 120))
        console.log('  has markdown table in reason/prompt:',
          /\|\s*Field\s*\|/.test(msg.reason || '') || /\|\s*Field\s*\|/.test(msg.prompt || ''))
        // Approve through the REAL intervene_response message flow
        setTimeout(() => {
          approved = true
          ws.send(JSON.stringify({ type: 'intervene_response', request_id: msg.request_id, approval_value: true }))
          console.log('APPROVE sent @', ((Date.now() - start) / 1000).toFixed(1) + 's')
        }, 1000)
      }
      if (msg.type === 'intervene_status' && msg.status === 'responded') responded = true
      if (msg.sender_role === 'agent' && msg.content && approved && /created with model/.test(msg.content) && !finalReply) {
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

  // Verify the create ACTUALLY happened (real management dispatch)
  const verify = await fetch(`${CC}/agents/types`, { headers: authHeaders })
  const vBody = await verify.json()
  const vList = Array.isArray(vBody) ? vBody : (vBody.items || vBody.results || [])
  const createdAgent = vList.find((a) => a.name === 'fraud-detection-agent-133253')

  const result = {
    interveneRequestReceived: !!interveneRequest,
    interventionType: interveneRequest && interveneRequest.intervention_type,
    markdownTableInPrompt: !!(interveneRequest && /\|\s*Field\s*\|/.test(interveneRequest.reason || interveneRequest.prompt || '')),
    approveSent: approved,
    interveneStatusResponded: responded,
    finalReply: (finalReply || '').slice(0, 200),
    agentTypeActuallyCreated: !!createdAgent,
    createdAgent: createdAgent && {
      id: createdAgent.id, name: createdAgent.name,
      model_id: createdAgent.model_id, input_type: createdAgent.input_type,
    },
    statusTimeline: events.filter((e) => e.type === 'chat_status').map((e) => `${e.status}@${e._t.toFixed(0)}s`),
  }
  console.log('RESULT_133253', JSON.stringify(result, null, 2))
  if (!result.interveneRequestReceived || !result.markdownTableInPrompt || !result.interveneStatusResponded || !result.agentTypeActuallyCreated) {
    process.exit(1)
  }
  console.log('LIVE-VERIFICATION-PASSED')
}

main().catch((e) => { console.error('LIVE-VERIFICATION-FAILED', e.message); process.exit(1) })
