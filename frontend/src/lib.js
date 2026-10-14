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
