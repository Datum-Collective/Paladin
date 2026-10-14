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
