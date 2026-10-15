import { useEffect, useState } from 'react'
import { api } from './api.js'

/* MITRE codes in plain words. Every code Paladin shows (CWE, CAPEC, ATT&CK technique or mitigation) can be explained
   from the offline MITRE pack: MITRE's own name and description, and what it means for you. One shared cache and
   one batched request per screen. */

const cache = new Map()
const waiting = new Set()
let timer = null
const listeners = new Set()

function flush() {
  timer = null
  const ids = [...waiting].filter((i) => !cache.has(i))
  waiting.clear()
  if (!ids.length) return
  for (let i = 0; i < ids.length; i += 40) {
    const chunk = ids.slice(i, i + 40)
    api.mitreExplain(chunk).then((r) => {
      for (const id of chunk) cache.set(id, r.codes[id] || { id, unknown: true })
      listeners.forEach((f) => f())
    }).catch(() => { for (const id of chunk) cache.set(id, { id, unknown: true, failed: true }); listeners.forEach((f) => f()) })
  }
}

const CODE = /^(CWE-\d+|CAPEC-\d+|T\d{4}(\.\d{3})?|M\d{4})$/

export function useMitre(ids) {
  const [, tick] = useState(0)
  const list = (ids || []).filter((i) => typeof i === 'string' && CODE.test(i))
  const key = list.join(',')
  useEffect(() => {
    const f = () => tick((n) => n + 1)
    listeners.add(f)
    let missing = false
    for (const id of list) if (!cache.has(id)) { waiting.add(id); missing = true }
    if (missing && !timer) timer = setTimeout(flush, 30)
    return () => listeners.delete(f)
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps
  return list.map((id) => cache.get(id) || { id, loading: true })
}

/** One code: the id, MITRE's short name, and the plain-language meaning, always visible (no hover needed). */
export function MitreCode({ id, compact = false }) {
  const [e] = useMitre([id])
  if (!e || !CODE.test(id || '')) return id ? <span className="mono">{id}</span> : null
  if (e.loading) return <span className="mitre"><code>{id}</code></span>
  if (e.unknown) return <span className="mitre"><code>{id}</code> <span className="muted">(not in the MITRE pack)</span></span>
  return (
    <span className="mitre">
      <a href={e.url} target="_blank" rel="noopener noreferrer"><code>{id}</code></a> <b>{e.short}</b>
      {!compact && e.summary && <span className="mitre-sum"> — {e.summary}</span>}
    </span>
  )
}

/** Several codes as a block: what each one is (MITRE's words), what it means for you, and MITRE's first fix. */
export function MitreExplain({ ids, title = 'What these MITRE codes mean' }) {
  const items = useMitre([...new Set((ids || []).filter(Boolean))])
  if (!items.length) return null
  return (
    <details className="mitre-block">
      <summary>{title}</summary>
      <ul>
        {items.map((e) => (
          <li key={e.id}>
            {e.loading ? <code>{e.id}</code> : e.unknown ? <><code>{e.id}</code> <span className="muted">not in the MITRE pack</span></> : (
              <>
                <div><a href={e.url} target="_blank" rel="noopener noreferrer"><code>{e.id}</code></a> <b>{e.name}</b>
                  <span className="muted small"> · {e.kind}</span></div>
                {e.summary && <div className="mitre-plain">{e.summary}</div>}
                {e.what && <div className="muted small">MITRE: “{e.what}”</div>}
                {e.fix && e.fix.length > 0 && <div className="small"><b>MITRE’s guidance:</b> {e.fix[0]}</div>}
              </>
            )}
          </li>
        ))}
      </ul>
    </details>
  )
}
