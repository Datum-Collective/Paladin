async function req(method, url, body) {
  const r = await fetch(url, {
    method,
    credentials: 'same-origin',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) {
    const e = new Error(typeof data.detail === 'string' ? data.detail : 'request failed')
    e.status = r.status
    throw e
  }
  return data
}

export const api = {
  config: () => req('GET', '/api/config'),
  local: () => req('POST', '/api/auth/local'),
  me: () => req('GET', '/api/me'),
  login: (email, password) => req('POST', '/api/auth/login', { email, password }),
  register: (email, password) => req('POST', '/api/auth/register', { email, password }),
  demo: () => req('POST', '/api/auth/demo'),
  logout: () => req('POST', '/api/auth/logout'),
  graph: () => req('GET', '/api/graph'),
  paths: () => req('GET', '/api/paths?k=15'),
  fixes: () => req('GET', '/api/fixes'),
  applyFix: (edges) => req('POST', '/api/fixes/apply', { edges }),
  simStart: () => req('POST', '/api/simulate/start'),
  simStep: (n = 20) => req('POST', `/api/simulate/step?n=${n}`),
  simReset: () => req('POST', '/api/simulate/reset'),
  ingest: (format, lines) => req('POST', '/api/ingest', { format, lines }),
  remediations: () => req('GET', '/api/remediations'),
  remediation: (id) => req('GET', `/api/remediations/${id}`),
  propose: (edges, title) => req('POST', '/api/remediations', { edges, title }),
  rstep: (id, action) => req('POST', `/api/remediations/${id}/${action}`),
  codeScan: (repo, files) => req('POST', '/api/codescan', { repo, files }),
  codeReport: () => req('GET', '/api/codescan'),
  codeClear: () => req('DELETE', '/api/codescan'),
  hConfig: () => req('GET', '/api/harness/config'),
  hStart: (repo_url) => req('POST', '/api/harness/jobs', { repo_url }),
  hJobs: () => req('GET', '/api/harness/jobs'),
  hJob: (id) => req('GET', `/api/harness/jobs/${id}`),
  hFile: (id, path) => req('GET', `/api/harness/jobs/${id}/file?path=${encodeURIComponent(path)}`),
  hPr: (id) => req('POST', `/api/harness/jobs/${id}/pr`),
  events: () => req('GET', '/api/events?limit=100'),
  simStatus: () => req('GET', '/api/simulate/status'),
  metrics: () => req('GET', '/api/metrics'),
  timeline: () => req('GET', '/api/timeline'),
  benchmarks: () => req('GET', '/api/benchmarks'),
  createKey: (label) => req('POST', '/api/keys', { label }),
  providers: () => req('GET', '/api/providers'),
  models: (pid) => req('GET', `/api/providers/${pid}/models`),
  validate: (pid) => req('POST', `/api/providers/${pid}/validate`),
}

/** POST the conversation and call onEvent for each normalised event. Resolves when the stream ends; abort with the
 *  signal. Network and HTTP failures are delivered as an error event so callers handle one shape. */
export async function chatStream(body, onEvent, signal) {
  let r
  try {
    r = await fetch('/api/assistant/chat', {
      method: 'POST', credentials: 'same-origin', signal,
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
  } catch (e) {
    if (e.name === 'AbortError') return
    onEvent({ type: 'error', kind: 'network', message: 'Could not reach the analysis engine.', hint: 'Check that Paladin is running.', retryable: true })
    return
  }
  if (!r.ok) {
    const d = await r.json().catch(() => ({}))
    onEvent({ type: 'error', kind: 'invalid', message: typeof d.detail === 'string' ? d.detail : 'The request was rejected.', retryable: false })
    return
  }
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      let i
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const chunk = buf.slice(0, i)
        buf = buf.slice(i + 2)
        const line = chunk.split('\n').find((l) => l.startsWith('data: '))
        if (line) { try { onEvent(JSON.parse(line.slice(6))) } catch { /* ignore a malformed frame */ } }
      }
    }
  } catch (e) {
    if (e.name !== 'AbortError') onEvent({ type: 'error', kind: 'network', message: 'The connection was interrupted.', hint: 'Try again.', retryable: true })
  }
}
