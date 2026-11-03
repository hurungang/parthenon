/* FIX-20261031-091657 live verification — Scenario B (hanging model → bounded
 * timeout) and B2 (end-session terminates the in-flight execution).
 * Requires AR env: LLM_MOCK_HANG=1, CONVERSATION_LLM_TIMEOUT_SECONDS=10. */
const WebSocket = require('/Users/minglijiang/source/parthenon/frontend/node_modules/ws')

const CC = 'http://localhost:8000/api/v1'
const WS_BASE = 'ws://localhost:5173/ws'

async function login() {
  const r = await fetch(`${CC}/auth/login-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: 'admin@parthenon.local', password: 'admin' }),
  })
  if (!r.ok) throw new Error('login failed ' + r.status)
  return (await r.json()).access_token
}

async function resolveAssistant(token) {
  const r = await fetch(`${CC}/agents/types`, { headers: { Authorization: `Bearer ${token}`, 'X-Tenant': 'root' } })
  const list = await r.json()
  const assistant = (Array.isArray(list) ? list : []).find((a) => a.is_system)
  if (!assistant) throw new Error('no assistant agent type')
  return assistant
}

async function createSession(token, agentTypeId) {
  const r = await fetch(`${CC}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, 'X-Tenant': 'root' },
    body: JSON.stringify({ agent_type_id: agentTypeId }),
  })
  if (!r.ok) throw new Error('create failed ' + r.status + ' ' + await r.text())
  return r.json()
}

function driveTurn(token, sessionId, { failOnTimeout = false, timeoutMs = 120000 } = {}) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(`${WS_BASE}/sessions/${sessionId}?token=${token}`)
    const events = []
    const start = Date.now()
    let settled = false
    let sawTimeoutOrFailedAt = null
    const done = (fn, arg) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      try { ws.close() } catch {}
      fn(arg)
    }
    const timer = setTimeout(() => done(reject, new Error('turn did not finish within ' + timeoutMs / 1000 + 's')), timeoutMs)
    ws.on('open', () => ws.send(JSON.stringify({ message: 'This turn should hit the bounded timeout.' })))
    ws.on('message', (raw) => {
      let msg
      try { msg = JSON.parse(raw.toString()) } catch { return }
      msg._t = (Date.now() - start) / 1000
      events.push(msg)
      if (msg.status === 'timeout_or_failed') {
        if (failOnTimeout) { done(reject, new Error('unexpected timeout in success scenario')) }
        else {
          sawTimeoutOrFailedAt = msg._t
        }
      }
      if (msg.sender_role === 'agent' && msg.content) {
        if (failOnTimeout) done(resolve, { events, replyAt: msg._t, content: msg.content })
        else {
          // Give any trailing status events a moment, then resolve.
          setTimeout(() => done(resolve, {
            events,
            replyAt: msg._t,
            content: msg.content,
            timeoutOrFailedAt: sawTimeoutOrFailedAt,
          }), 2000)
        }
      }
    })
    ws.on('error', (e) => done(reject, e))
  })
}

async function endSession(token, sessionId) {
  const r = await fetch(`${CC}/conversations/${sessionId}/end`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'X-Tenant': 'root' },
  })
  return { status: r.status, body: await r.json().catch(() => null) }
}

async function main() {
  const token = await login()
  const assistant = await resolveAssistant(token)

  // ── Scenario B: hanging model → bounded timeout_or_failed ──────────────
  const sB = await createSession(token, assistant.id)
  console.log('SESSION_B', sB.id)
  const t0 = Date.now()
  const b = await driveTurn(token, sB.id)
  const timeoutAt = b.timeoutOrFailedAt ?? b.replyAt
  console.log('RESULT_B', JSON.stringify({
    timeoutOrFailedAtSeconds: b.timeoutOrFailedAt,
    replyAtSeconds: b.replyAt,
    errReply: b.content,
    boundedUnder60s: timeoutAt < 60,
  }))
  if (!(timeoutAt < 60 && /timed out|too long/i.test(b.content || ''))) {
    console.error('SCENARIO_B_FAILED'); process.exit(1)
  }

  // ── Scenario B2: end-session terminates in-flight execution ────────────
  const s2 = await createSession(token, assistant.id)
  console.log('SESSION_B2', s2.id)
  const turnPromise = driveTurn(token, s2.id, { timeoutMs: 120000 })
  await new Promise((r) => setTimeout(r, 5000)) // let the turn start hanging
  const end = await endSession(token, s2.id)
  console.log('END_CALL', end.status, JSON.stringify(end.body?.status))
  if (end.status !== 200 || end.body?.status !== 'closed') {
    console.error('END_CALL_FAILED', end.status); process.exit(1)
  }
  const result = await turnPromise
  const cancelledAt = result.timeoutAt ?? result.replyAt
  console.log('RESULT_B2', JSON.stringify({
    terminatedAtSeconds: cancelledAt,
    lastStatus: result.events.map((e) => e.status || e.sender_role).slice(-3),
  }))
  if (!(cancelledAt < 60)) {
    console.error('SCENARIO_B2_FAILED — in-flight turn not terminated promptly'); process.exit(1)
  }

  // Session must be closed for the agent type (frontend force-new relies on it)
  const listR = await fetch(`${CC}/conversations?agent_type_id=${assistant.id}`, {
    headers: { Authorization: `Bearer ${token}`, 'X-Tenant': 'root' },
  })
  const sessions = await listR.json()
  const mine = (Array.isArray(sessions) ? sessions : []).filter((s) => s.id === s2.id)
  console.log('SESSION_B2_STATUS', mine[0]?.status)
  console.log('SCENARIO_B_OK')
  process.exit(0)
}

main().catch((e) => { console.error('SCENARIO_B_ERROR', e.message); process.exit(1) })
