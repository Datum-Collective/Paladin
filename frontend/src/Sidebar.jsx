import Icon from './Icons.jsx'
import { Severity } from './parts.jsx'
import WorkspaceSwitcher from './WorkspaceSwitcher.jsx'

const mod = typeof navigator !== 'undefined' && /Mac/.test(navigator.platform) ? '⌘' : 'Ctrl+'
const TOP = [['home', 'Home', 'home', '⇧H'], ['workspaces', 'Workspaces', 'folder', '6']]
const WS = [['analysis', 'Analysis', 'graph', '1'], ['repo', 'Repository', 'repo', '2'], ['insights', 'Insights', 'chart', '3'],
  ['assistant', 'Assistant', 'chat', '4'], ['activity', 'Activity', 'activity', '5']]
const FOOT = [['integrations', 'Integrations', 'plug', '7'], ['settings', 'Settings', 'settings', ',']]

export default function Sidebar({ view, setView, graph, empty, canPlay, playing, onPlay, onReset, onPalette, rems, desktop,
                                  user, onSignOut, workspaces, current, onOpenWs, onCreateWs, onHome, onManage, rail, onToggleRail }) {
  const open = rems.filter((r) => !['verified', 'rolled_back'].includes(r.state)).length
  const item = ([id, label, icon, k]) => (
    <button key={id} className={view === id ? 'nav-item on' : 'nav-item'} onClick={() => setView(id)}
            aria-current={view === id ? 'page' : undefined} aria-label={label} title={rail ? `${label}  ${mod}${k}` : undefined}>
      <Icon name={icon} size={16} />{!rail && <span>{label}</span>}
      {id === 'analysis' && open > 0 && <span className="badge" title="Open remediations">{open}</span>}
      {!rail && <kbd>{`${mod}${k}`}</kbd>}
    </button>
  )
  return (
    <aside className={rail ? 'sidebar rail' : 'sidebar'}>
      <div className="sidebar-top drag" aria-hidden="true" />
      <button className="palette-trigger nodrag" onClick={onPalette} aria-label="Open command palette" title={rail ? `Search  ${mod}K` : undefined}>
        <Icon name="search" size={14} />{!rail && <><span>Search</span><kbd>{mod}K</kbd></>}
      </button>
      <nav aria-label="App" className="nav">{TOP.map(item)}</nav>

      {!rail && <div className="side-label">Open workspace</div>}
      <WorkspaceSwitcher workspaces={workspaces} current={current} onOpen={onOpenWs} onCreate={onCreateWs}
                         onHome={onHome} onManage={onManage} rail={rail} />
      <nav aria-label="Workspace" className="nav">{WS.map(item)}</nav>

      <span className="spacer" />
      <nav aria-label="System" className="nav">{FOOT.map(item)}</nav>
      {!desktop && user && (
        <button className="nav-item" onClick={onSignOut} aria-label="Sign Out" title={rail ? 'Sign Out' : undefined}>
          <Icon name="logout" size={16} />{!rail && <span>Sign Out</span>}</button>
      )}
      <button className="nav-item collapse" onClick={onToggleRail} aria-label={rail ? 'Expand sidebar' : 'Collapse sidebar'}
              title={rail ? 'Expand sidebar' : undefined}>
        <Icon name={rail ? 'chevrons-right' : 'chevrons-left'} size={16} />{!rail && <span>Collapse</span>}
      </button>
    </aside>
  )
}
