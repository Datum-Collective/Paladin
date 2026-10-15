import { useState } from 'react'
import Icon from './Icons.jsx'
import { Severity } from './parts.jsx'
import WorkspaceSwitcher from './WorkspaceSwitcher.jsx'

const mod = typeof navigator !== 'undefined' && /Mac/.test(navigator.platform) ? '⌘' : 'Ctrl+'
const TOP = [['home', 'Home', 'home', '⇧H'], ['workspaces', 'Workspaces', 'folder', '6']]
const WS = [['analysis', 'Analysis', 'graph', '1'], ['repo', 'Repository', 'repo', '2'], ['insights', 'Insights', 'chart', '3'],
  ['assistant', 'Assistant', 'chat', '4'], ['activity', 'Activity', 'activity', '5']]
const FOOT = [['integrations', 'Integrations', 'plug', '7'], ['settings', 'Settings', 'settings', ',']]

function Avatar({ user }) {
  const [bad, setBad] = useState(false)
  const initial = (user.login || user.name || '?').slice(0, 1).toUpperCase()
  return user.avatar_url && !bad
    ? <img className="avatar" src={user.avatar_url} alt="" width="26" height="26" referrerPolicy="no-referrer" onError={() => setBad(true)} />
    : <span className="avatar fallback" aria-hidden="true">{initial}</span>
}

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
      {user && (
        <div className="account">
          <button className={view === 'settings' ? 'account-main on' : 'account-main'} onClick={() => setView('settings')}
                  aria-label={`Account and settings for ${user.login || 'you'}`} title={rail ? `${user.login || 'Account'}  Settings` : undefined}>
            <Avatar user={user} />
            {!rail && <span className="account-text">
              <span className="account-name">{user.name || user.login}</span>
              <span className="account-sub">{user.login ? `@${user.login}` : 'GitHub'}</span>
            </span>}
          </button>
          <button className="account-out" onClick={onSignOut} aria-label={`Sign out ${user.login || ''}`.trim()}
                  title={`Sign Out${user.login ? ` (${user.login})` : ''}`}><Icon name="logout" size={15} /></button>
        </div>
      )}
      <button className="nav-item collapse" onClick={onToggleRail} aria-label={rail ? 'Expand sidebar' : 'Collapse sidebar'}
              title={rail ? 'Expand sidebar' : undefined}>
        <Icon name={rail ? 'chevrons-right' : 'chevrons-left'} size={16} />{!rail && <span>Collapse</span>}
      </button>
    </aside>
  )
}
