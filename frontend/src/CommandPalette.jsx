import { useEffect, useMemo, useRef, useState } from 'react'
import { groupCommands, rankCommands } from './lib.js'
import Icon from './Icons.jsx'

/** commands: [{ id, title, group, hint?, keywords?, icon?, run }] */
export default function CommandPalette({ open, onClose, commands, recents = [], onRun }) {
  const [q, setQ] = useState('')
  const [i, setI] = useState(0)
  const input = useRef(null)
  const list = useRef(null)
  const shown = useMemo(() => {
    if (q.trim()) return rankCommands(commands, q)
    const byId = new Map(commands.map((c) => [c.id, c]))
    const rec = recents.map((id) => byId.get(id)).filter(Boolean).map((c) => ({ ...c, id: `recent-${c.id}`, group: 'Recent', _id: c.id }))
    return [...rec, ...groupCommands(commands)]
  }, [commands, q, recents])

  useEffect(() => { if (open) { setQ(''); setI(0); setTimeout(() => input.current && input.current.focus(), 0) } }, [open])
  useEffect(() => { setI(0) }, [q])
  useEffect(() => {
    const el = list.current && list.current.querySelector('[aria-selected="true"]')
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' })
  }, [i, shown])
  if (!open) return null

  const run = (c) => { onClose(); if (onRun) onRun(c._id || c.id); c.run() }
  const key = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); onClose() }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setI((n) => Math.min(shown.length - 1, n + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setI((n) => Math.max(0, n - 1)) }
    else if (e.key === 'Enter' && shown[i]) { e.preventDefault(); run(shown[i]) }
  }
  let last = null
  return (
    <div className="scrim" onMouseDown={onClose}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Command palette"
           onMouseDown={(e) => e.stopPropagation()} onKeyDown={key}>
        <div className="palette-input">
          <Icon name="search" />
          <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search commands, paths, views"
                 aria-label="Search commands" role="combobox" aria-expanded="true" aria-controls="palette-list" />
          <kbd>esc</kbd>
        </div>
        <ul id="palette-list" className="palette-list" role="listbox" ref={list}>
          {shown.length === 0 && <li className="palette-empty">No matching commands</li>}
          {shown.map((c, n) => {
            const head = !q && c.group !== last ? c.group : null
            last = c.group
            return (
              <li key={c.id} role="presentation">
                {head && <div className="palette-group">{head}</div>}
                <div role="option" aria-selected={n === i} className={n === i ? 'palette-item on' : 'palette-item'}
                     onMouseMove={() => setI(n)} onClick={() => run(c)}>
                  {c.icon && <Icon name={c.icon} />}
                  <span className="palette-title">{c.title}</span>
                  {c.hint && <span className="muted small palette-hint">{c.hint}</span>}
                </div>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
