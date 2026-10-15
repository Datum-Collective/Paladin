// Pure helpers shared by the shell. Kept free of React/DOM so they are unit-testable.

/** Subsequence fuzzy score: higher is better, -1 means no match. Rewards prefix, word starts and adjacency. */
export function fuzzy(query, text) {
  const q = query.trim().toLowerCase()
  if (!q) return 0
  const t = text.toLowerCase()
  let ti = 0, score = 0, prev = -2
  for (const ch of q) {
    const at = t.indexOf(ch, ti)
    if (at < 0) return -1
    score += 1
    if (at === prev + 1) score += 2
    if (at === 0 || /[\s/→\-_.]/.test(t[at - 1])) score += 3
    prev = at
    ti = at + 1
  }
  if (t.startsWith(q)) score += 5
  return score - t.length * 0.01
}

/** Filter and rank commands by title + keywords; an empty query keeps the original order. */
export function rankCommands(commands, query) {
  if (!query.trim()) return commands
  return commands
    .map((c) => ({ c, s: fuzzy(query, `${c.title} ${c.keywords || ''}`) }))
    .filter((x) => x.s >= 0)
    .sort((a, b) => b.s - a.s)
    .map((x) => x.c)
}

/** Palette rows with each group in one run (first-seen order), so a heading never appears twice. */
export function groupCommands(commands) {
  const order = []
  const by = new Map()
  for (const c of commands) {
    if (!by.has(c.group)) { by.set(c.group, []); order.push(c.group) }
    by.get(c.group).push(c)
  }
  return order.flatMap((g) => by.get(g))
}

export const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n))

/** Relative "x ago" for a unix-seconds or ISO timestamp, in compact form. */
export function ago(ts, now = Date.now()) {
  const t = typeof ts === 'number' ? ts * 1000 : Date.parse(ts)
  if (Number.isNaN(t)) return ''
  const s = Math.max(0, Math.round((now - t) / 1000))
  if (s < 45) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}

export const hhmm = (ts) => (ts || '').replace('T', ' ').replace('Z', '').slice(5, 16)

/** Move `id` to the front of a recents list, de-duplicated and capped. */
export function pushRecent(list, id, cap = 5) {
  return [id, ...list.filter((x) => x !== id)].slice(0, cap)
}

/** Sentence-case a snake/kebab identifier for display: "pr_opened" -> "PR opened" is handled by callers. */
export const label = (s) => String(s || '').replace(/[_-]/g, ' ').replace(/^./, (c) => c.toUpperCase())

/** Build a provider-safe history from the UI thread: drop errored or empty assistant turns, then merge consecutive
 *  same-role messages so the conversation strictly alternates and always ends with the user's message. */
export function toHistory(msgs) {
  const out = []
  for (const m of msgs) {
    if (m.error) continue
    const content = (m.content || '').trim()
    if (!content) continue
    const last = out[out.length - 1]
    if (last && last.role === m.role) last.content += `\n\n${content}`
    else out.push({ role: m.role, content })
  }
  return out
}

/** Local, instant read of what the landing input contains, so the UI can react before any network call. */
export function looksLikeRepo(text) {
  const t = (text || '').trim()
  if (/^(https:\/\/(www\.)?github\.com\/|git@github\.com:)[A-Za-z0-9-]+\/[\w.-]+/.test(t)) return true
  const m = /^(?:github\.com\/)?([A-Za-z0-9-]+)\/([\w.-]+)$/.exec(t)
  if (!m) return false
  const ext = m[2].includes('.') ? m[2].split('.').pop().toLowerCase() : ''
  return !FILE_EXT.has(ext)      // "src/main.py" is a path, not a repository
}
const FILE_EXT = new Set(['py', 'js', 'ts', 'tsx', 'jsx', 'md', 'json', 'txt', 'yml', 'yaml', 'toml', 'html', 'css', 'go', 'rs',
  'java', 'c', 'h', 'sh', 'ini', 'cfg', 'lock', 'xml', 'csv'])

/** What the launcher input holds: a filesystem path, a GitHub repo reference, a search query, or nothing. */
export function classifyInput(text) {
  const t = (text || '').trim()
  if (!t) return 'empty'
  if (/^(\/|~\/|[A-Za-z]:[\\/]|\\\\)/.test(t)) return 'path'
  if (looksLikeRepo(t)) return 'github'
  return 'search'
}

const RUNNING = new Set(['queued', 'cloning', 'scanning', 'fixing'])
const STATE_LABEL = { queued: 'Queued', cloning: 'Cloning', scanning: 'Scanning', fixing: 'Preparing fixes' }

/** One honest status per workspace, from its newest scan. Never "ready" unless a scan actually finished. */
export function workspaceStatus(w) {
  const st = w.status
  if (st && RUNNING.has(st.state)) return { tone: 'info', label: STATE_LABEL[st.state], busy: true, detail: '' }
  if (st && st.state === 'failed') return { tone: 'bad', label: 'Scan failed', busy: false, detail: st.error || '' }
  if (st && st.state === 'cancelled') return { tone: 'mute', label: 'Cancelled', busy: false, detail: '' }
  if (st && st.state === 'pr_opened') return { tone: 'ok', label: 'Pull request opened', busy: false, detail: '' }
  if (st && st.state === 'ready') return { tone: 'ok', label: 'Fixes ready', busy: false, detail: '' }
  if (st && st.state === 'done') return { tone: 'ok', label: 'Scanned', busy: false, detail: '' }
  if (w.kind !== 'empty') return { tone: 'warn', label: 'Not scanned', busy: false, detail: '' }
  return w.events > 0 ? { tone: 'mute', label: 'Log data', busy: false, detail: '' } : { tone: 'mute', label: 'Empty', busy: false, detail: '' }
}

export function filterWorkspaces(list, { q = '', kind = 'all' } = {}) {
  const needle = q.trim().toLowerCase()
  return list.filter((w) => (kind === 'all' || w.kind === kind)
    && (!needle || `${w.name} ${w.repo_url || ''}`.toLowerCase().includes(needle)))
}

export function sortWorkspaces(list, by = 'recent') {
  const c = [...list]
  if (by === 'name') c.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }))
  else if (by === 'events') c.sort((a, b) => b.events - a.events || b.opened - a.opened)
  else c.sort((a, b) => b.opened - a.opened)
  return c
}

export const folderName = (p) => String(p || '').replace(/[\\/]+$/, '').split(/[\\/]/).pop()

/** A link we may put in href: only https://github.com/... Anything else (javascript:, data:, another host) is dropped,
 *  because job rows are the user's own and can be edited through the API. */
export const githubUrl = (url) => (typeof url === 'string' && /^https:\/\/github\.com\//.test(url) ? url : undefined)

/** FastAPI sends `detail` as a string for our errors and as a list of {msg, loc} for request validation. */
export function errorText(detail, fallback = 'request failed') {
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail)) {
    const msgs = detail.map((d) => (d && typeof d.msg === 'string' ? d.msg : '')).filter(Boolean)
    if (msgs.length) return msgs.join('; ')
  }
  return fallback
}

const KEY_SHAPE = { anthropic: { prefix: 'sk-ant-', name: 'Claude' }, openai: { prefix: 'sk-', name: 'OpenAI' } }

/** What is visibly wrong with a pasted key, or '' when it looks fine or is still empty. Shape only: the provider
 *  is the authority on whether the key works. */
export function keyProblem(provider, value) {
  const v = String(value || '')
  const shape = KEY_SHAPE[provider]
  if (!v || !shape) return ''
  if (/\s/.test(v)) return 'Keys never contain spaces. Check that you copied the whole key and nothing else.'
  if (!v.startsWith(shape.prefix)) return `${shape.name} keys start with ${shape.prefix}`
  if (v.length < 20) return 'That key looks too short. Copy the whole key.'
  return ''
}

/** Where setup should send the user after a failed connection test, and whether trying again can help. */
export function setupAdvice(error) {
  const kind = error && error.kind
  if (kind === 'auth') return { goto: 'key', retry: false }
  if (kind === 'permission' || kind === 'not_found' || kind === 'invalid') return { goto: 'model', retry: false }
  if (kind === 'quota') return { goto: null, retry: false }
  return { goto: null, retry: true }
}

export const THEMES = ['system', 'light', 'dark']
/** A stored theme choice, or "system" for anything unrecognised (an old or hand-edited value). */
export const normalizeTheme = (v) => (THEMES.includes(v) ? v : 'system')

/** A stable attack-path identity across refreshes; server ranks may change as events arrive. */
export function pathKey(path) {
  return path && path.hops && path.hops.length ? path.hops.map((hop) => hop.edge).join('|') : path ? path.id : null
}

/** Path node ids -> the labels people read ("Internet (any client)", "server.py"), id when a label is missing. */
export function pathLabels(ids, nodes) {
  const by = new Map((nodes || []).map((n) => [n.id, n.label]))
  return ids.map((i) => by.get(i) || i)
}

/** The address to hand back to the engine to scan a stored job's repository again (stored as owner/name or a path). */
export function scanTarget(repoUrl) {
  const r = String(repoUrl || '')
  return /^[A-Za-z0-9-]+\/[\w.-]+$/.test(r) ? `https://github.com/${r}` : r
}

/** The line shown above the analysis while a scan is running, was cut off, or failed; null when there is nothing to say.
 *  `action` is "rescan" when scanning again is the useful next step. */
export function scanBanner(scan, paths = 0) {
  if (!scan) return null
  const repo = scan.repo_url ? scan.repo_url.split(/[\\/]/).filter(Boolean).slice(-2).join('/') : 'the repository'
  const found = (n) => `${n} attack path${n === 1 ? '' : 's'}`
  const kept = paths ? ` Showing the ${found(paths)} found before it stopped.` : ''
  const age = scan.updated ? Date.now() / 1000 - scan.updated : 0
  if (scan.state === 'queued' || scan.state === 'cloning') return { busy: true, tone: 'info', text: `Fetching ${repo}…` }
  if (scan.state === 'scanning') return { busy: true, tone: 'info', text: `Scanning ${repo}. ${found(paths)} so far; the graph, paths and fixes update as findings arrive.` }
  if (scan.state === 'fixing') return { busy: true, tone: 'info', text: `Preparing fixes for ${repo}. ${found(paths)} so far.` }
  if (scan.state === 'failed' && /^Interrupted/.test(scan.error || '')) {      // the app closed mid-scan: always worth saying
    return { busy: false, tone: 'warn', action: 'rescan', text: `The last scan of ${repo} was interrupted when Paladin closed.${kept || ' Nothing had been found yet.'}` }
  }
  if (scan.state === 'failed' && age < 600) {
    return { busy: false, tone: 'bad', action: 'rescan', text: `The scan of ${repo} failed${scan.error ? `: ${scan.error}` : ''}.${kept}` }
  }
  if (scan.state === 'cancelled' && age < 600) return { busy: false, tone: 'warn', action: 'rescan', text: `The scan of ${repo} was cancelled.${kept}` }
  return null
}

const STAGES = [['clone', 'Fetch repository', ['queued', 'cloning']], ['scan', 'Find weaknesses', ['scanning']],
  ['paths', 'Build attack paths', ['fixing']], ['done', 'Results ready', ['ready', 'done', 'pr_opened']]]

/** The four visible stages of a scan with a status each. `failedAt` is the last state seen before a failure. */
export function scanStages(state, failedAt = '') {
  const idx = (st) => STAGES.findIndex((s) => s[2].includes(st))
  const cur = state === 'failed' || state === 'cancelled' ? idx(failedAt) : idx(state)
  return STAGES.map(([id, label], i) => {
    let status = 'pending'
    if (STAGES[3][2].includes(state)) status = 'done'
    else if (i < cur) status = 'done'
    else if (i === cur) status = state === 'failed' ? 'failed' : state === 'cancelled' ? 'pending' : 'current'
    return { id, label, status }
  })
}

/** A stored message -> what the thread renders: failures, stops and cut-off replies keep their text and say so. */
export function fromStored(m) {
  const meta = m.meta || {}
  return { id: m.id, role: m.role, content: m.content, created: m.created,
    error: m.status === 'error' ? (meta.error || { message: 'The reply failed.' }) : undefined,
    stopped: m.status === 'stopped', interrupted: m.status === 'interrupted' || m.status === 'streaming',
    stop: meta.stop_reason, usage: meta.usage }
}
