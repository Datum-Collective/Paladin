import { useEffect, useRef, useState } from 'react'
import Icon from './Icons.jsx'

/** Sidebar workspace selector: current workspace, recents, and the entry points to create or import. */
export default function WorkspaceSwitcher({ workspaces, current, onOpen, onCreate, onHome, onManage, rail }) {
  const [open, setOpen] = useState(false)
  const root = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const down = (e) => { if (root.current && !root.current.contains(e.target)) setOpen(false) }
    const key = (e) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('mousedown', down)
    window.addEventListener('keydown', key)
    return () => { window.removeEventListener('mousedown', down); window.removeEventListener('keydown', key) }
  }, [open])
  const act = (fn) => () => { setOpen(false); fn() }
  const name = current ? current.name : 'Workspace'
  return (
    <div className="switcher nodrag" ref={root}>
      <button className="switcher-btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}
              aria-label={`Workspace: ${name}`} title={rail ? name : undefined}>
        <Icon name={current && current.repo_url ? 'github' : 'folder'} size={16} />
        {!rail && <><span className="switcher-name">{name}</span><Icon name="down" size={14} /></>}
      </button>
      {open && (
        <div className="popover" role="menu" aria-label="Workspaces">
          <div className="popover-head">Workspaces</div>
          {workspaces.slice(0, 8).map((w) => (
            <button key={w.id} role="menuitemradio" aria-checked={current && w.id === current.id} className="pop-item"
                    onClick={act(() => onOpen(w.id))}>
              <span className="pop-check">{current && w.id === current.id ? <Icon name="check" size={14} /> : null}</span>
              <span className="pop-name">{w.name}</span>
            </button>
          ))}
          <div className="pop-sep" />
          <button role="menuitem" className="pop-item" onClick={act(onHome)}><span className="pop-check"><Icon name="github" size={14} /></span>Open Repository…</button>
          <button role="menuitem" className="pop-item" onClick={act(onCreate)}><span className="pop-check"><Icon name="plus" size={14} /></span>New Workspace</button>
          <button role="menuitem" className="pop-item" onClick={act(onManage)}><span className="pop-check"><Icon name="settings" size={14} /></span>Manage Workspaces…</button>
        </div>
      )}
    </div>
  )
}
