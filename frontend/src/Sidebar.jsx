import Icon from './Icons.jsx'

const NAV = [['analysis', 'Analysis', 'graph', '1'], ['repo', 'Repository', 'repo', '2'], ['insights', 'Insights', 'chart', '3']]
const mod = typeof navigator !== 'undefined' && /Mac/.test(navigator.platform) ? '⌘' : 'Ctrl+'

export default function Sidebar({ view, setView, graph, empty, severity, canPlay, playing, onPlay, onReset, onPalette,
                                  rems, desktop, user, onSignOut }) {
  const open = rems.filter((r) => !['verified', 'rolled_back'].includes(r.state)).length
  return (
    <aside className="sidebar">
      <div className="sidebar-top drag" aria-hidden="true" />
      <div className="brand-row">
        <span className="brand"><span className="brand-mark" aria-hidden="true" />Paladin</span>
      </div>
      <button className="palette-trigger nodrag" onClick={onPalette} aria-label="Open command palette">
        <Icon name="search" size={14} /><span>Search</span><kbd>{mod}K</kbd>
      </button>
      <nav aria-label="Sections" className="nav">
        {NAV.map(([id, label, icon, k]) => (
          <button key={id} className={view === id ? 'nav-item on' : 'nav-item'} onClick={() => setView(id)}
                  aria-current={view === id ? 'page' : undefined}>
            <Icon name={icon} size={16} /><span>{label}</span>
            {id === 'analysis' && open > 0 && <span className="badge" title="Open remediations">{open}</span>}
            <kbd>{mod}{k}</kbd>
          </button>
        ))}
      </nav>

      <section className="side-group" aria-label="Workspace status">
        <div className="side-head">Workspace</div>
        {empty ? <p className="muted small">No data yet. Scan a repository or add logs.</p> : (
          <>
            <div className="row-top"><span className={`pill ${severity.tone}`}>{severity.label}</span>
              <span className="muted small">{graph.events} {graph.events === 1 ? 'event' : 'events'}</span></div>
            <dl className="kv">
              <dt>Worst path</dt><dd>{graph.worst.toFixed(2)}</dd>
              <dt>Combined</dt><dd>{graph.risk.toFixed(2)}</dd>
            </dl>
          </>
        )}
        <div className="actions">
          {canPlay && (
            <button onClick={onPlay} disabled={playing}><Icon name="play" size={14} />{playing ? 'Playing' : 'Play sample'}</button>
          )}
          <button onClick={onReset}><Icon name="refresh" size={14} />Reset</button>
        </div>
      </section>

      <span className="spacer" />
      <button className={view === 'settings' ? 'nav-item on' : 'nav-item'} onClick={() => setView('settings')}
              aria-current={view === 'settings' ? 'page' : undefined}>
        <Icon name="settings" size={16} /><span>Settings</span><kbd>{mod},</kbd>
      </button>
      {!desktop && user && (
        <button className="nav-item" onClick={onSignOut}><Icon name="logout" size={16} /><span>Sign out</span></button>
      )}
    </aside>
  )
}
