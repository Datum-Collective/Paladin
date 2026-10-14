import { useState } from 'react'
import { ago, workspaceStatus } from './lib.js'
import Icon from './Icons.jsx'

const SRC_ICON = { github: 'github', local: 'folder', empty: 'file' }

/** One workspace as a list row: identity, honest status, and the actions that apply to it. */
export default function WorkspaceRow({ w, active, onOpen, onRename, onDelete, showSource = true }) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(w.name)
  const st = workspaceStatus(w)
  const commit = async () => {
    setEditing(false)
    if (name.trim() && name.trim() !== w.name) await onRename(w.id, name.trim())
    else setName(w.name)
  }
  return (
    <li className={active ? 'wrow on' : 'wrow'}>
      <button className="wrow-main" onClick={() => !editing && onOpen(w.id)} aria-label={`Open ${w.name}`}>
        <Icon name={SRC_ICON[w.kind] || 'folder'} size={16} />
        <span className="wrow-text">
          {editing ? (
            <input autoFocus value={name} maxLength={60} aria-label="Workspace name" onClick={(e) => e.stopPropagation()}
                   onChange={(e) => setName(e.target.value)} onBlur={commit}
                   onKeyDown={(e) => { e.stopPropagation(); if (e.key === 'Enter') commit(); if (e.key === 'Escape') { setEditing(false); setName(w.name) } }} />
          ) : <span className="wrow-name">{w.name}{active && <span className="pill mute">Open</span>}</span>}
          {showSource && (
            <span className="muted small wrow-sub">{w.repo_url ? w.repo_url.replace('https://', '') : 'No repository'}</span>
          )}
          {st.tone === 'bad' && st.detail && <span className="err small wrow-sub">{st.detail}</span>}
        </span>
        <span className={`pill ${st.tone}`}>{st.busy && <span className="spinner tiny" aria-hidden="true" />}{st.label}</span>
        <span className="muted small wrow-meta">{w.events} {w.events === 1 ? 'event' : 'events'} · {ago(w.opened)}</span>
      </button>
      {(onRename || onDelete) && (
        <span className="wrow-actions">
          {onRename && <button className="tool" aria-label={`Rename ${w.name}`} title="Rename" onClick={() => { setName(w.name); setEditing(true) }}><Icon name="edit" size={14} /></button>}
          {onDelete && <button className="tool" aria-label={`Delete ${w.name}`} title="Delete…" onClick={() => onDelete(w)}><Icon name="trash" size={14} /></button>}
        </span>
      )}
    </li>
  )
}
