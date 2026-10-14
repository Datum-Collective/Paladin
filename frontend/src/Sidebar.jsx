import Icon from './Icons.jsx'
import { Severity } from './parts.jsx'
import WorkspaceSwitcher from './WorkspaceSwitcher.jsx'

const mod = typeof navigator !== 'undefined' && /Mac/.test(navigator.platform) ? '⌘' : 'Ctrl+'
const TOP = [['home', 'Home', 'home', '⇧H'], ['workspaces', 'Workspaces', 'folder', '6']]
const WS = [['analysis', 'Analysis', 'graph', '1'], ['repo', 'Repository', 'repo', '2'], ['insights', 'Insights', 'chart', '3'],
  ['assistant', 'Assistant', 'chat', '4'], ['activity', 'Activity', 'activity', '5']]
const FOOT = [['integrations', 'Integrations', 'plug', '7'], ['settings', 'Settings', 'settings', ',']]

export default function Sidebar({ view, setView, graph, empty, canPlay, playing, onPlay, onReset, onPalette, rems, desktop,
                                  user, onSignOut, workspaces, current, onOpenWs, onCreateWs, onHome, onManage }) {
  const open = rems.filter((r) => !['verified', 'rolled_back'].includes(r.state)).length
  const item = ([id, label, icon, k]) => (
    <button key={id} className={view === id ? 'nav-item on' : 'nav-item'} onClick={() => setView(id)}
            aria-current={view === id ? 'page' : undefined}>
      <Icon name={icon} size={16} /><span>{label}</span>
      {id === 'analysis' && open > 0 && <span className="badge" title="Open remediations">{open}</span>}
      <kbd>{k.length === 1 && k !== ',' ? `${mod}${k}` : k === ',' ? `${mod},` : `${mod}${k}`}</kbd>
    </button>
  )
  return (
    <aside className="sidebar">
      <div className="sidebar-top drag" aria-hidden="true" />
      <button className="palette-trigger nodrag" onClick={onPalette} aria-label="Open command palette">
        <Icon name="search" size={14} /><span>Search</span><kbd>{mod}K</kbd>
      </button>
      <nav aria-label="App" className="nav">{TOP.map(item)}</nav>

      <div className="side-label">Open workspace</div>
      <WorkspaceSwitcher workspaces={workspaces} current={current} onOpen={onOpenWs} onCreate={onCreateWs}
                         onHome={onHome} onManage={onManage} />
      <nav aria-label="Workspace" className="nav">{WS.map(item)}</nav>

      <section className="side-group" aria-label="Workspace status">
        {empty ? <p className="muted small">No data yet. Import a repository or add logs.</p> : (
          <>
            <div className="row-top"><Severity level={graph.severity} />
              <span className="muted small">{graph.events} {graph.events === 1 ? 'event' : 'events'}</span></div>
            <dl className="kv">
              <dt>Worst path</dt><dd>{graph.worst.toFixed(2)}</dd>
              <dt>Combined</dt><dd>{graph.risk.toFixed(2)}</dd>
            </dl>
          </>
        )}
        <div className="actions">
          {canPlay && <button onClick={onPlay} disabled={playing}><Icon name="play" size={14} />{playing ? 'Playing' : 'Play Sample'}</button>}
          <button onClick={onReset}><Icon name="refresh" size={14} />Reset…</button>
        </div>
      </section>

      <span className="spacer" />
      <nav aria-label="System" className="nav">{FOOT.map(item)}</nav>
      {!desktop && user && (
        <button className="nav-item" onClick={onSignOut}><Icon name="logout" size={16} /><span>Sign out</span></button>
      )}
    </aside>
  )
}
