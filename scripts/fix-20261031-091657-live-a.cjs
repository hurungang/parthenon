/* FIX-20261031-091657 live verification — Scenario A (slow-but-alive turn).
 * Drives a REAL assistant turn through the Vite-proxied WS (5173) with the
 * LLM mock layer in scripted mode + 100s delay: asserts live reply delivery,
 * thinking heartbeats, and socket survival > 90s mid-turn. */
const WebSocket = require('/Users/minglijiang/source/parthenon/frontend/node_modules/ws')

const CC = 'http://localhost:8000/api/v1'
const WS_BASE = 'ws://localhost:5173/ws'

async function main() {
  // 1. Login (platform account, tenant-bound token)
  const login = await fetch(`${CC}/auth/login-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: 'admin@parthenon.local', password: 'admin' }),
  })
  if (!login.ok) throw new Error(`login failed: ${login.status} ${await login.text()}`)
  const { access_token: token } = await login.json()

  // 2. Resolve the system assistant agent type
  const ats = await fetch(`${CC}/agents/types`, { headers: { Authorization: `Bearer ${token}`, 'X-Tenant': 'root' } })
  const atBody = await ats.json()
  const list = Array.isArray(atBody) ? atBody : (atBody.items || atBody.results || [])
  const assistant = list.find((a) => a.is_system)
  if (!assistant) throw new Error('no system assistant agent type found: ' + JSON.stringify(atBody).slice(0, 300))

  // 3. Create a conversation session
  const created = await fetch(`${CC}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, 'X-Tenant': 'root' },
    body: JSON.stringify({ agent_type_id: assistant.id }),
  })
  if (!created.ok) throw new Error(`session create failed: ${created.status} ${await created.text()}`)
  const session = await created.json()
  console.log('SESSION', session.id, 'status', session.status)

  // 4. Drive the real turn through the Vite-proxied WS
  const ws = new WebSocket(`${WS_BASE}/sessions/${session.id}?token=${token}`)
  const events = []
  const start = Date.now()
  let replyAt = null
  let heartbeats = 0

  const done = new Promise((resolve, reject) => {
    const failTimer = setTimeout(() => reject(new Error('turn did not complete within 180s')), 180000)
    ws.on('open', () => {
      ws.send(JSON.stringify({ message: 'Run the live verification check please.' }))
    })
    ws.on('message', (raw) => {
      let msg
      try { msg = JSON.parse(raw.toString()) } catch { return }
      events.push({ ...msg, _t: (Date.now() - start) / 1000 })
      if (msg.status === 'thinking_heartbeat') heartbeats += 1
      if (msg.sender_role === 'agent' && msg.content) {
        replyAt = (Date.now() - start) / 1000
        clearTimeout(failTimer)
        resolve()
      }
      if (msg.status === 'timeout_or_failed') {
        clearTimeout(failTimer)
        reject(new Error('unexpected timeout_or_failed in scenario A'))
      }
    })
    ws.on('error', (e) => { clearTimeout(failTimer); reject(e) })
    ws.on('close', (code, reason) => {
      if (replyAt === null) { clearTimeout(failTimer); reject(new Error(`socket closed before reply code=${code} reason=${reason}`)) }
    })
  })

  await done
  const survivedPast90 = events.some((e) => e._t > 90) || replyAt > 90
  console.log('RESULT_A', JSON.stringify({
    replyAtSeconds: replyAt,
    heartbeats,
    socketSurvivedPast90s: survivedPast90,
    statusTimeline: events.filter((e) => e.type === 'chat_status').map((e) => `${e.status}@${e._t.toFixed(0)}s`),
  }, null, 2))

  // 5. Verify persistence: reopen via resume endpoint
  await new Promise((r) => setTimeout(r, 1500))
  const resumed = await fetch(`${CC}/conversations/${session.id}/resume`, {
    method: 'POST', headers: { Authorization: `Bearer ${token}`, 'X-Tenant': 'root' },
  })
  const detail = await resumed.json()
  const turns = detail.turns || []
  console.log('PERSISTED_TURNS', turns.length, 'last:', JSON.stringify(turns[turns.length - 1]?.content || '').slice(0, 120))
  ws.close()
  if (!(replyAt > 90 && heartbeats >= 4)) {
    console.error('SCENARIO_A_FAILED')
    process.exit(1)
  }
  console.log('SCENARIO_A_OK')
  process.exit(0)
}

main().catch((e) => { console.error('SCENARIO_A_ERROR', e.message); process.exit(1) })
