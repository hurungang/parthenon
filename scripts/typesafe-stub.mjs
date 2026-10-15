/**
 * Local TypeSafe Jev stub — mimics POST /v1/systemone for decision tool testing.
 * Usage: node scripts/typesafe-stub.mjs [port]   (default 18099)
 *
 * Responds to POST /v1/systemone with one answer per question in the request
 * payload: choice/score questions answer with the first option (or mid score),
 * text questions with a short string. Deterministic — good for manual testing.
 */
import http from 'node:http'

const port = Number(process.argv[2] || 18099)

function buildAnswers(body) {
  const answers = {}
  const questions = body?.questions ?? body?.state?.questions ?? []
  for (const q of questions) {
    const key = q.question_key ?? q.key
    if (!key) continue
    const type = (q.question_type ?? q.type ?? '').toLowerCase()
    if (type === 'choice') {
      const options = Object.keys(q.criteria_options ?? {})
      answers[key] = { type: 'choice', value: options[0] ?? 'yes' }
    } else if (type === 'score') {
      answers[key] = { type: 'score', value: 4 }
    } else if (type === 'noul') {
      answers[key] = { type: 'noul', value: 1 }
    } else {
      answers[key] = { type: 'text', value: `stub answer for ${key}` }
    }
  }
  return answers
}

const server = http.createServer((req, res) => {
  if (req.method === 'POST' && req.url.includes('/systemone')) {
    let raw = ''
    req.on('data', (c) => (raw += c))
    req.on('end', () => {
      let body = {}
      try {
        body = JSON.parse(raw || '{}')
      } catch {}
      const answers = buildAnswers(body)
      console.log(`[typesafe-stub] ${new Date().toISOString()} answered ${Object.keys(answers).length} question(s)`)
      res.writeHead(200, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ answers, model: body?.model ?? 'jev-latest' }))
    })
    return
  }
  res.writeHead(404, { 'content-type': 'application/json' })
  res.end(JSON.stringify({ detail: 'Not Found' }))
})

server.listen(port, () => console.log(`[typesafe-stub] listening on http://127.0.0.1:${port}/v1/systemone`))
