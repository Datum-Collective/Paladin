import { errorText } from './lib.js'

// every request names its workspace, so a second window switching workspaces cannot redirect this one
let currentWs = null
export const setWorkspace = (id) => { currentWs = id }
export const workspaceId = () => currentWs
const wsHeader = () => (currentWs ? { 'X-Workspace': String(currentWs) } : {})

async function req(method, url, body, signal) {
  const r = await fetch(url, {
    method,
    signal,
    credentials: 'same-origin',
    headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...wsHeader() },
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) {
    const e = new Error(errorText(data.detail))
    e.status = r.status
    throw e
  }
  return data
}

export const api = {
  config: () => req('GET', '/api/config'),
  me: () => req('GET', '/api/me'),
  // desktop: collect a sign-in finished in the browser (Electron's main process authorises this one request)
  claim: () => req('POST', '/api/auth/desktop/claim'),
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
  mitreExplain: (ids) => req('GET', `/api/mitre/explain?ids=${encodeURIComponent(ids.join(','))}`),
  hJob: (id) => req('GET', `/api/harness/jobs/${id}`),
  hCancel: (id) => req('POST', `/api/harness/jobs/${id}/cancel`),
  hFile: (id, path) => req('GET', `/api/harness/jobs/${id}/file?path=${encodeURIComponent(path)}`),
  hPr: (id) => req('POST', `/api/harness/jobs/${id}/pr`),
  events: () => req('GET', '/api/events?limit=100'),
  simStatus: () => req('GET', '/api/simulate/status'),
  metrics: () => req('GET', '/api/metrics'),
  timeline: () => req('GET', '/api/timeline'),
  benchmarks: () => req('GET', '/api/benchmarks'),
  createKey: (label) => req('POST', '/api/keys', { label }),
  keys: () => req('GET', '/api/keys'),
  revokeKey: (id) => req('DELETE', `/api/keys/${encodeURIComponent(id)}`),
  // GitHub App (web): connect, list, manage, disconnect
  githubInstallUrl: () => req('GET', '/api/github/install-url'),
  githubRepos: () => req('GET', '/api/github/repos'),
  githubDisconnect: (id) => req('DELETE', `/api/github/installations/${encodeURIComponent(id)}`),
  workspaces: () => req('GET', '/api/workspaces'),
  createWorkspace: (name) => req('POST', '/api/workspaces', { name: name || null }),
  importRepo: (query, rescan = false) => req('POST', '/api/workspaces/import', { query, rescan }),
  openWorkspace: (id) => req('POST', `/api/workspaces/${id}/open`),
  renameWorkspace: (id, name) => req('PATCH', `/api/workspaces/${id}`, { name }),
  deleteWorkspace: (id) => req('DELETE', `/api/workspaces/${id}`),
  resolveRepo: (query) => req('POST', '/api/repos/resolve', { query }),
  suggestRepos: (q, signal) => req('GET', `/api/repos/suggest?q=${encodeURIComponent(q)}`, undefined, signal),
  githubStatus: () => req('GET', '/api/github/status'),
  resolveLocal: (path) => req('POST', '/api/repos/resolve-local', { path }),
  importLocal: (path) => req('POST', '/api/workspaces/import-local', { path }),
  activity: () => req('GET', '/api/activity?limit=150'),
  storage: () => req('GET', '/api/storage'),
  clearClones: () => req('DELETE', '/api/storage/clones'),
  prefs: () => req('GET', '/api/prefs'),
  setPrefs: (patch) => req('PUT', '/api/prefs', patch),
  providers: () => req('GET', '/api/providers'),
  models: (pid) => req('GET', `/api/providers/${pid}/models`),
  validate: (pid) => req('POST', `/api/providers/${pid}/validate`),
  // web: the signed-in user's own model key, checked by the server and held in its memory for this account only
  setKey: (pid, key) => req('PUT', `/api/providers/${pid}/key`, { key }),
  removeKey: (pid) => req('DELETE', `/api/providers/${pid}/key`),
  conversations: () => req('GET', '/api/conversations'),
  createConversation: (title = '') => req('POST', '/api/conversations', { title }),
  renameConversation: (id, title) => req('PATCH', `/api/conversations/${id}`, { title }),
  deleteConversation: (id) => req('DELETE', `/api/conversations/${id}`),
  conversationMessages: (id) => req('GET', `/api/conversations/${id}/messages`),
  remediationPatchUrl: (id) => `/api/remediations/${id}/patch`,
  testProvider: (pid, model) => req('POST', `/api/providers/${pid}/test`, { model }),
}

/** Save a text response from the engine as a file. An <a target=_blank> does nothing in the desktop window (every
 *  non-https popup is denied), and a plain link would also drop the workspace header. */
export async function downloadText(url, filename) {
  const r = await fetch(url, { credentials: 'same-origin', headers: wsHeader() })
  if (!r.ok) {
    const d = await r.json().catch(() => ({}))
    throw new Error(typeof d.detail === 'string' ? d.detail : 'Could not download the patch.')
  }
  const blob = new Blob([await r.text()], { type: 'text/x-diff' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  document.body.append(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}

/** POST the conversation and call onEvent for each normalised event. Resolves when the stream ends; abort with the
 *  signal. Network and HTTP failures are delivered as an error event so callers handle one shape. */
/** The fixing agent's event stream (start, text, tool, tool_result, tests, status, error, verdict). */
export async function agentStream(body, onEvent, signal) {
  let r
  try {
    r = await fetch('/api/agent/fix', { method: 'POST', credentials: 'same-origin', signal,
      headers: { 'Content-Type': 'application/json', ...wsHeader() }, body: JSON.stringify(body) })
  } catch (e) {
    if (e.name !== 'AbortError') onEvent({ type: 'error', message: 'Could not reach the Paladin engine.' })
    return
  }
  if (!r.ok) {
    const d = await r.json().catch(() => ({}))
    onEvent({ type: 'error', message: typeof d.detail === 'string' ? d.detail : `The agent could not start (${r.status}).` })
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
        const line = buf.slice(0, i).split('\n').find((l) => l.startsWith('data: '))
        buf = buf.slice(i + 2)
        if (line) { try { onEvent(JSON.parse(line.slice(6))) } catch { /* a malformed frame */ } }
      }
    }
  } catch (e) {
    if (e.name !== 'AbortError') onEvent({ type: 'error', message: 'The connection to the agent was interrupted.' })
  }
}

export async function chatStream(body, onEvent, signal) {
  let r
  try {
    r = await fetch('/api/assistant/chat', {
      method: 'POST', credentials: 'same-origin', signal,
      headers: { 'Content-Type': 'application/json', ...wsHeader() }, body: JSON.stringify(body),
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
