import { useMemo, useState } from 'react'
import { filterWorkspaces, sortWorkspaces } from './lib.js'
import { usePrefs } from './prefs.jsx'
import WorkspaceRow from './WorkspaceRow.jsx'
import Icon from './Icons.jsx'

const KINDS = [['all', 'All'], ['github', 'GitHub'], ['local', 'Local'], ['empty', 'Empty']]

export default function WorkspacesView({ wsl, onOpen, onRename, onDelete, onNew, onOpenRepo }) {
  const { prefs, set } = usePrefs()
  const [q, setQ] = useState('')
  const [kind, setKind] = useState('all')
  const sort = prefs['workspaces.sort']
  const shown = useMemo(() => sortWorkspaces(filterWorkspaces(wsl.workspaces, { q, kind }), sort), [wsl.workspaces, q, kind, sort])
  const none = wsl.workspaces.length === 0
  return (
    <div className="page">
      <div className="page-inner">
        <div className="page-head">
          <h1>Workspaces</h1>
          <span className="actions">
            <button onClick={onOpenRepo}><Icon name="github" size={14} />Open Repository…</button>
            <button className="primary" onClick={onNew}><Icon name="plus" size={14} />New Workspace…</button>
          </span>
        </div>
        <div className="filters">
          <div className="search-field"><Icon name="search" size={14} />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search workspaces" aria-label="Search workspaces" /></div>
          <div className="seg" role="radiogroup" aria-label="Source">
            {KINDS.map(([v, l]) => <button key={v} role="radio" aria-checked={kind === v} className={kind === v ? 'on' : ''} onClick={() => setKind(v)}>{l}</button>)}
          </div>
          <label className="sort">Sort
            <select value={sort} onChange={(e) => set('workspaces.sort', e.target.value)}>
              <option value="recent">Recently opened</option><option value="name">Name</option><option value="events">Most events</option>
            </select>
          </label>
        </div>
        {none ? (
          <div className="empty-block"><h2>No workspaces yet</h2>
            <p className="muted">Open a repository or create an empty workspace to get started.</p>
            <div className="actions"><button className="primary" onClick={onOpenRepo}>Open Repository…</button></div></div>
        ) : shown.length === 0 ? (
          <div className="empty-block"><h2>No matches</h2>
            <p className="muted">No workspace matches those filters.</p>
            <div className="actions"><button onClick={() => { setQ(''); setKind('all') }}>Clear Filters</button></div></div>
        ) : (
          <ul className="wlist full">
            {shown.map((w) => <WorkspaceRow key={w.id} w={w} active={wsl.active === w.id} onOpen={onOpen}
                                            onRename={onRename} onDelete={onDelete} />)}
          </ul>
        )}
        <p className="muted small count-line">{shown.length} of {wsl.workspaces.length} {wsl.workspaces.length === 1 ? 'workspace' : 'workspaces'}</p>
      </div>
    </div>
  )
}
