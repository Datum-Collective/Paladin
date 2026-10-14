import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api.js'
import Analysis from './Analysis.jsx'
import CommandPalette from './CommandPalette.jsx'
import Insights from './Insights.jsx'
import RepoView from './RepoView.jsx'
import Settings, { PANES } from './Settings.jsx'
import Assistant from './Assistant.jsx'
import { pushRecent } from './lib.js'
import { useStored } from './useStored.js'
import Sidebar from './Sidebar.jsx'
import Icon from './Icons.jsx'
import { SEV_TONE } from './parts.jsx'
import { ToastProvider, useToast } from './toast.jsx'
import { useWorkspace } from './useWorkspace.js'

const bridge = typeof window !== 'undefined' ? window.paladin : undefined

function Login({ onDone, config }) {
  const [email, setEmail] = useState('')
  const [pw, setPw] = useState('')
  const [mode, setMode] = useState('login')
  const [err, setErr] = useState('')
  const go = async (fn) => {
    setErr('')
    try { await fn(); onDone() } catch (e) { setErr(e.message) }
  }
  return (
    <form className="login" onSubmit={(e) => { e.preventDefault(); go(() => (mode === 'login' ? api.login(email, pw) : api.register(email, pw))) }}>
      <span className="brand big"><span className="brand-mark" aria-hidden="true" />Paladin</span>
      <p className="muted">Turn scattered security signals into ranked attack paths and the cheapest fix.</p>
      {config.demo && <button type="button" className="primary" onClick={() => go(api.demo)}>Continue with demo account</button>}
      {config.demo && <div className="or">or</div>}
      <input placeholder="Email" aria-label="Email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
      <input placeholder="Password" aria-label="Password" type="password"
             autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={pw}
             onChange={(e) => setPw(e.target.value)} />
      <button type="submit" className={config.demo ? '' : 'primary'}>{mode === 'login' ? 'Sign in' : 'Create account'}</button>
      <button type="button" className="link" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>
        {mode === 'login' ? 'Create an account' : 'I already have an account'}
      </button>
      {err && <p className="err" role="alert">{err}</p>}
    </form>
  )
}

function Splash({ error, onRetry }) {
  return (
    <div className="splash">
      <span className="brand big"><span className="brand-mark" aria-hidden="true" />Paladin</span>
      {error ? (
        <>
          <p className="err" role="alert">{error}</p>
          <button onClick={onRetry}>Try again</button>
        </>
      ) : <p className="muted">Starting…</p>}
    </div>
  )
}

const TITLES = { analysis: 'Analysis', repo: 'Repository', insights: 'Insights', assistant: 'Assistant', settings: 'Settings' }

function Shell({ config, user, onSignOut, onExpired }) {
  const toast = useToast()
  const ws = useWorkspace(user, onExpired)
  const [view, setView] = useState('analysis')
  const [tab, setTab] = useState('paths')
  const [selected, setSelected] = useState(null)
  const [palette, setPalette] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useStored('sidebar-open', true)
  const [inspectorOpen, setInspectorOpen] = useStored('inspector-open', true)
  const [pane, setPane] = useStored('settings-pane', 'general')
  const [recents, setRecents] = useStored('palette-recents', [])

  const go = useCallback((target) => {
    if (target === 'ingest') { setView('analysis'); setTab('ingest') } else setView(target)
  }, [])
  const openPath = useCallback((id) => { setView('analysis'); setTab('paths'); setSelected(id) }, [])
  const doReset = useCallback(async () => { setConfirmReset(false); setSelected(null); await ws.reset() }, [ws])
  const fx = ws.fixes

  // One command table drives the menu bar, the palette and the keyboard, so they cannot drift apart.
  const run = useCallback((id) => {
    const table = {
      analysis: () => setView('analysis'), repo: () => setView('repo'), insights: () => setView('insights'),
      assistant: () => setView('assistant'), settings: () => setView('settings'), ingest: () => go('ingest'),
      events: () => { setView('analysis'); setTab('events') }, palette: () => setPalette((p) => !p),
      'toggle-sidebar': () => setSidebarOpen((o) => !o), 'toggle-inspector': () => setInspectorOpen((o) => !o),
      play: () => (ws.canPlay ? ws.play() : toast('No sample scenario is installed.', 'warn')),
      refresh: () => ws.refresh(), reset: () => setConfirmReset(true),
      'fix-cheapest': () => (fx && fx.cheapest_cut ? ws.propose(fx.cheapest_cut.edges, 'Cheapest cut') : toast('There is no fix to propose yet.', 'warn')),
      'fix-single': () => (fx && fx.best_single ? ws.propose(fx.best_single.edges, 'Best single fix') : toast('There is no fix to propose yet.', 'warn')),
      'check-updates': async () => {
        if (!bridge) return
        const s = await bridge.checkForUpdates()
        toast(s.phase === 'disabled' ? 'Updates are off in development builds.' : 'Checking for updates…')
      },
    }
    if (table[id]) table[id]()
  }, [ws, fx, go, toast, setSidebarOpen, setInspectorOpen])

  // native menu bar -> same table (desktop)
  const runRef = useRef(run)
  runRef.current = run
  useEffect(() => (bridge && bridge.onCommand ? bridge.onCommand(({ id }) => runRef.current(id)) : undefined), [])

  // keyboard (web has no menu bar; desktop accelerators come from the menu, so only the web needs these)
  useEffect(() => {
    if (config.desktop) return undefined
    const keys = { k: 'palette', 1: 'analysis', 2: 'repo', 3: 'insights', 4: 'assistant', ',': 'settings' }
    const onKey = (e) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey) return
      const id = keys[e.key.toLowerCase()]
      if (id) { e.preventDefault(); runRef.current(id) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [config.desktop])

  const title = view === 'settings' ? (PANES.find(([id]) => id === pane) || PANES[0])[1] : TITLES[view]
  useEffect(() => { document.title = `${title} · Paladin` }, [title])

  const severity = ws.graph ? { label: ws.graph.severity.toLowerCase(), tone: SEV_TONE[ws.graph.severity] } : { label: '', tone: '' }

  const commands = useMemo(() => {
    const c = [
      { id: 'analysis', group: 'Go to', title: 'Analysis', icon: 'graph', hint: 'Graph, paths, fixes' },
      { id: 'repo', group: 'Go to', title: 'Repository', icon: 'repo', hint: 'Scan a GitHub repository', keywords: 'github scan code' },
      { id: 'insights', group: 'Go to', title: 'Insights', icon: 'chart', hint: 'Timeline and benchmarks' },
      { id: 'assistant', group: 'Go to', title: 'Assistant', icon: 'chat', hint: 'Ask about your paths', keywords: 'claude openai chat ask' },
      { id: 'settings', group: 'Go to', title: 'Settings', icon: 'settings', keywords: 'keys providers updates preferences' },
      { id: 'ingest', group: 'Actions', title: 'Add log data…', icon: 'upload', keywords: 'ingest upload paste logs' },
      { id: 'events', group: 'Actions', title: 'Show events', icon: 'file' },
      { id: 'refresh', group: 'Actions', title: 'Refresh', icon: 'refresh' },
      { id: 'toggle-sidebar', group: 'View', title: 'Show or hide sidebar', icon: 'sidebar' },
      { id: 'toggle-inspector', group: 'View', title: 'Show or hide inspector', icon: 'inspector' },
      { id: 'reset', group: 'Actions', title: 'Reset workspace…', icon: 'trash' },
    ]
    if (ws.canPlay) c.splice(5, 0, { id: 'play', group: 'Actions', title: 'Play sample scenario', icon: 'play' })
    if (fx && fx.cheapest_cut) c.push({ id: 'fix-cheapest', group: 'Fixes', title: 'Propose cheapest cut', icon: 'shield', hint: `${fx.cheapest_cut.risk_removed_pct}% of risk removed` })
    if (fx && fx.best_single) c.push({ id: 'fix-single', group: 'Fixes', title: 'Propose best single fix', icon: 'shield', hint: `${fx.best_single.risk_removed_pct}% of risk removed` })
    if (bridge) c.push({ id: 'check-updates', group: 'App', title: 'Check for updates…', icon: 'refresh' })
    const cmds = c.map((x) => ({ ...x, run: () => run(x.id) }))
    for (const p of ws.paths.slice(0, 12)) {
      cmds.push({ id: `path-${p.id}`, group: 'Paths', title: p.nodes.join(' → '), icon: 'graph',
        hint: `${p.severity.toLowerCase()} · ${p.risk.toFixed(2)}`, run: () => openPath(p.id) })
    }
    return cmds
  }, [ws.canPlay, ws.paths, fx, run, openPath])

  if (!ws.loaded) return <Splash />
  const showInspector = view === 'analysis'
  return (
    <div className="app" data-sidebar={sidebarOpen ? 'open' : 'closed'}>
      {sidebarOpen && (
        <Sidebar view={view} setView={setView} graph={ws.graph} empty={ws.empty} severity={severity} canPlay={ws.canPlay}
                 playing={ws.playing} onPlay={ws.play} onReset={() => setConfirmReset(true)} onPalette={() => setPalette(true)}
                 rems={ws.rems} desktop={config.desktop} user={user} onSignOut={onSignOut} />
      )}
      <div className="content">
        <div className="toolbar drag" role="toolbar" aria-label={`${title} toolbar`}>
          <button className="tool nodrag" onClick={() => run('toggle-sidebar')} aria-label={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'}
                  aria-pressed={sidebarOpen} title="Show or hide sidebar"><Icon name="sidebar" size={16} /></button>
          <h1 className="toolbar-title">{title}</h1>
          {view === 'analysis' && !ws.empty && (
            <span className="muted small toolbar-sub">
              Worst path {ws.graph.worst.toFixed(2)} · combined {ws.graph.risk.toFixed(2)} · {ws.graph.events} {ws.graph.events === 1 ? 'event' : 'events'}
            </span>
          )}
          <span className="spacer" />
          {view === 'settings' && (
            <div className="seg nodrag" role="tablist" aria-label="Settings sections">
              {PANES.map(([id, l]) => (
                <button key={id} role="tab" aria-selected={pane === id} className={pane === id ? 'on' : ''} onClick={() => setPane(id)}>{l}</button>
              ))}
            </div>
          )}
          <span className="spacer" />
          {showInspector && (
            <button className="tool nodrag" onClick={() => run('toggle-inspector')} aria-pressed={inspectorOpen}
                    aria-label={inspectorOpen ? 'Hide inspector' : 'Show inspector'} title="Show or hide inspector"><Icon name="inspector" size={16} /></button>
          )}
          <button className="tool nodrag" onClick={() => setPalette(true)} aria-label="Command palette" title="Command palette"><Icon name="search" size={16} /></button>
        </div>
        {view === 'insights' && <Insights key={ws.graph ? ws.graph.events : 0} rems={ws.rems} />}
        {view === 'repo' && <RepoView onDone={ws.refresh} />}
        {view === 'assistant' && <Assistant goSettings={() => { setPane('providers'); setView('settings') }} workspaceEmpty={ws.empty} />}
        {view === 'settings' && <Settings pane={pane} config={config} user={user} onReset={() => setConfirmReset(true)} onSignOut={onSignOut} />}
        {view === 'analysis' && (
          <Analysis state={ws} selected={selected} setSelected={setSelected} tab={tab} setTab={setTab} go={go}
                    desktop={config.desktop} inspectorOpen={inspectorOpen} />
        )}
      </div>

      <CommandPalette open={palette} onClose={() => setPalette(false)} commands={commands} recents={recents}
                      onRun={(id) => { if (!id.startsWith('path-')) setRecents((r) => pushRecent(r, id)) }} />
      {confirmReset && (
        <div className="scrim" onMouseDown={() => setConfirmReset(false)}
             onKeyDown={(e) => { if (e.key === 'Escape') setConfirmReset(false) }}>
          <div className="dialog" role="alertdialog" aria-modal="true" aria-labelledby="reset-title" aria-describedby="reset-desc"
               tabIndex={-1} ref={(el) => el && el.focus()} onMouseDown={(e) => e.stopPropagation()}>
            <h2 id="reset-title">Reset this workspace?</h2>
            <p id="reset-desc" className="muted">Events, applied fixes, scan results and remediation history are deleted. You can’t undo this.</p>
            <div className="actions end">
              <button onClick={() => setConfirmReset(false)}>Cancel</button>
              <button className="danger" onClick={doReset}>Reset Workspace</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function App() {
  const [config, setConfig] = useState(null)
  const [user, setUser] = useState(undefined)
  const [error, setError] = useState('')

  const boot = useCallback(async () => {
    setError('')
    try {
      const cfg = await api.config()
      setConfig(cfg)
      document.documentElement.dataset.desktop = cfg.desktop ? '1' : '0'
      try {
        setUser(await api.me())
      } catch (e) {
        if (e.status !== 401) throw e
        if (cfg.desktop) { await api.local(); setUser(await api.me()) } else setUser(null)
      }
    } catch (e) {
      setError(e.message === 'request failed' ? 'Could not reach the analysis engine.' : e.message)
    }
  }, [])

  useEffect(() => {
    if (bridge) document.documentElement.dataset.platform = bridge.platform
    boot()
  }, [boot])

  const signOut = useCallback(async () => { await api.logout(); setUser(null) }, [])
  // desktop has no account screen: a lapsed session is silently renewed through the local-account endpoint
  const renew = useCallback(async () => {
    try { await api.local(); setUser(await api.me()) } catch (e) { setError(e.message) }
  }, [])

  if (error) return <Splash error={error} onRetry={boot} />
  if (!config || user === undefined) return <Splash />
  return (
    <ToastProvider>
      {user ? <Shell config={config} user={user} onSignOut={signOut} onExpired={config.desktop ? renew : signOut} /> : <Login config={config} onDone={() => api.me().then(setUser)} />}
    </ToastProvider>
  )
}
