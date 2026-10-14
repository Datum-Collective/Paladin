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
  hPr: (id) => req('POST', `/api/harness/jobs/${id}/pr`),
  events: () => req('GET', '/api/events?limit=100'),
  simStatus: () => req('GET', '/api/simulate/status'),
  metrics: () => req('GET', '/api/metrics'),
  timeline: () => req('GET', '/api/timeline'),
  benchmarks: () => req('GET', '/api/benchmarks'),
  createKey: (label) => req('POST', '/api/keys', { label }),
}
