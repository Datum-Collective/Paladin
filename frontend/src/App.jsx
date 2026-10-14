import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api.js'
import Analysis from './Analysis.jsx'
import CommandPalette from './CommandPalette.jsx'
import Resizer from './Resizer.jsx'
import Insights from './Insights.jsx'
import RepoView from './RepoView.jsx'
import Settings, { PANES } from './Settings.jsx'
import Home from './Home.jsx'
import WorkspacesView from './WorkspacesView.jsx'
import ActivityView from './ActivityView.jsx'
import IntegrationsView from './IntegrationsView.jsx'
import { ConfirmDialog, NewWorkspaceDialog } from './Dialogs.jsx'
import { PrefsProvider, usePrefs } from './prefs.jsx'
import { useWorkspaces } from './useWorkspaces.js'
import Assistant from './Assistant.jsx'
import { classifyInput, pushRecent } from './lib.js'
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
      {config.demo && <button type="button" className="primary" onClick={() => go(api.demo)}>Continue with Demo Account</button>}
      {config.demo && <div className="or">or</div>}
      <input placeholder="Email" aria-label="Email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
      <input placeholder="Password" aria-label="Password" type="password"
             autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={pw}
             onChange={(e) => setPw(e.target.value)} />
      <button type="submit" className={config.demo ? '' : 'primary'}>{mode === 'login' ? 'Sign In' : 'Create Account'}</button>
      <button type="button" className="link" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>
        {mode === 'login' ? 'Create an Account' : 'Sign In Instead'}
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
          <button onClick={onRetry}>Try Again</button>
        </>
      ) : <p className="muted">Starting…</p>}
    </div>
  )
}

const TITLES = { home: 'Home', workspaces: 'Workspaces', analysis: 'Analysis', repo: 'Repository', insights: 'Insights',
  assistant: 'Assistant', activity: 'Activity', integrations: 'Integrations', settings: 'Settings' }

function Shell({ config, user, onSignOut, onExpired }) {
  const toast = useToast()
  const { prefs, ready: prefsReady } = usePrefs()
  const wsl = useWorkspaces(user)
  const ws = useWorkspace(user, onExpired, wsl.active)
  const [view, setView] = useState(null)               // null until preferences and workspaces are known
  const [tab, setTab] = useState('paths')
  const [selected, setSelected] = useState(null)
  const [palette, setPalette] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)
  const [homeFocus, setHomeFocus] = useState(0)
  const [homeIntent, setHomeIntent] = useState(null)
  const [newDlg, setNewDlg] = useState(false)
  const [delTarget, setDelTarget] = useState(null)
  const [sidebarOpen, setSidebarOpen] = useStored('sidebar-open', true)
  const [rail, setRail] = useStored('sidebar-rail', false)
  const [sidebarW, setSidebarW] = useStored('sidebar-w', 248)
  const [inspectorOpen, setInspectorOpen] = useStored('inspector-open', true)
  const [pane, setPane] = useStored('settings-pane', 'general')
  const [recents, setRecents] = useStored('palette-recents', [])

  // first screen honours the "Start with" preference, once
  useEffect(() => {
    if (view === null && prefsReady && wsl.loaded) setView(prefs['general.startup'] === 'last' && wsl.current ? 'analysis' : 'home')
  }, [view, prefsReady, wsl.loaded, wsl.current, prefs])

  const go = useCallback((target) => {
    if (target === 'ingest') { setView('analysis'); setTab('ingest') } else setView(target)
  }, [])
  const openPath = useCallback((id) => { setView('analysis'); setTab('paths'); setSelected(id) }, [])
  const doReset = useCallback(async () => { setConfirmReset(false); setSelected(null); await ws.reset() }, [ws])
  const goSettings = useCallback((p) => { if (p) setPane(p); setView('settings') }, [setPane])
  const fx = ws.fixes

  const openWs = useCallback(async (id) => {
    if (await wsl.open(id)) { setSelected(null); setTab('paths'); setView((v) => (v === 'home' || v === null ? 'analysis' : v)) }
  }, [wsl])
  const createNamed = useCallback(async (name) => {
    const w = await wsl.create(name)
    if (w) { setSelected(null); setView('analysis'); toast(`Created ${w.name}`, 'ok') }
    else throw new Error('Could not create the workspace.')
    return w
  }, [wsl, toast])
  const importLocal = useCallback(async (path) => {
    const r = await wsl.importLocal(path)
    setSelected(null)
    setView(prefs['general.after_import'] === 'analysis' ? 'analysis' : 'repo')
    toast(r.reopened ? `Scanning ${r.workspace.name} again` : `Scanning ${r.workspace.name}`, 'ok')
  }, [wsl, prefs, toast])
  const chooseFolder = useCallback(() => (bridge && bridge.chooseFolder ? bridge.chooseFolder() : Promise.resolve(null)), [])

  const importRepo = useCallback(async (q) => {
    const r = await wsl.importRepo(q)               // throws to Home, which shows the message inline
    setSelected(null)
    setView(prefs['general.after_import'] === 'analysis' ? 'analysis' : 'repo')
    toast(r.reopened ? `Opened ${r.workspace.name}` : `Scanning ${r.workspace.name}`, 'ok')
  }, [wsl, prefs, toast])
  const retryScan = useCallback(async (target) => {      // stays where it is: the user is looking at Activity
    if (classifyInput(target) === 'path') await api.importLocal(target)
    else await api.importRepo(target)
    await wsl.reload()
    toast('Scan restarted', 'ok')
  }, [wsl, toast])

  // One command table drives the menu bar, the palette and the keyboard, so they cannot drift apart.
  const run = useCallback((id) => {
    const table = {
      home: () => setView('home'), 'open-repo': () => { setView('home'); setHomeFocus((n) => n + 1) },
      'new-workspace': () => setNewDlg(true),
      'open-folder': async () => {
        const p = await chooseFolder()
        if (p) { setView('home'); setHomeIntent({ id: Date.now(), path: p }) }
        else if (!bridge) toast('Opening folders is available in the desktop app.', 'warn')
      },
      workspaces: () => setView('workspaces'), activity: () => setView('activity'), integrations: () => setView('integrations'),
      analysis: () => setView('analysis'), repo: () => setView('repo'), insights: () => setView('insights'),
      assistant: () => setView('assistant'), settings: () => goSettings(), ingest: () => go('ingest'),
      events: () => { setView('analysis'); setTab('events') }, palette: () => setPalette((p) => !p),
      'toggle-sidebar': () => setSidebarOpen((o) => !o), 'collapse-sidebar': () => { setSidebarOpen(true); setRail((r) => !r) }, 'toggle-inspector': () => setInspectorOpen((o) => !o),
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
  }, [ws, fx, go, goSettings, chooseFolder, toast, setSidebarOpen, setInspectorOpen, setRail])

  // native menu bar -> same table (desktop)
  const runRef = useRef(run)
  runRef.current = run
  useEffect(() => (bridge && bridge.onCommand ? bridge.onCommand(({ id }) => runRef.current(id)) : undefined), [])

  // keyboard (web has no menu bar; desktop accelerators come from the menu, so only the web needs these)
  useEffect(() => {
    if (config.desktop) return undefined
    const keys = { k: 'palette', b: 'toggle-sidebar', 1: 'analysis', 2: 'repo', 3: 'insights', 4: 'assistant', 5: 'activity', 6: 'workspaces', 7: 'integrations', ',': 'settings' }
    const onKey = (e) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey) return
      const id = e.shiftKey && e.key.toLowerCase() === 'h' ? 'home' : keys[e.key.toLowerCase()]
      if (id) { e.preventDefault(); runRef.current(id) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [config.desktop])

  const title = view === 'settings' ? (PANES.find((p) => p.id === pane) || PANES[0]).label : (TITLES[view] || 'Paladin')
  useEffect(() => { document.title = `${title} · Paladin` }, [title])

  const severity = ws.graph ? { label: ws.graph.severity.toLowerCase(), tone: SEV_TONE[ws.graph.severity] } : { label: '', tone: '' }

  const commands = useMemo(() => {
    const c = [
      { id: 'home', group: 'Go to', title: 'Start screen', icon: 'home', hint: 'Open a repository', keywords: 'home import github open' },
      { id: 'workspaces', group: 'Go to', title: 'All workspaces', icon: 'folder', keywords: 'browse search projects' },
      { id: 'activity', group: 'Go to', title: 'Activity', icon: 'activity', hint: 'Scan history and remediation', keywords: 'history log scans' },
      { id: 'integrations', group: 'Go to', title: 'Integrations', icon: 'plug', hint: 'GitHub and model providers', keywords: 'github claude openai connect' },
      { id: 'new-workspace', group: 'Workspaces', title: 'New workspace…', icon: 'plus' },
      { id: 'open-folder', group: 'Workspaces', title: 'Open folder…', icon: 'folder', keywords: 'local project git' },
      { id: 'open-repo', group: 'Workspaces', title: 'Open repository…', icon: 'github', keywords: 'import github scan clone' },
      { id: 'analysis', group: 'Go to', title: 'Analysis', icon: 'graph', hint: 'Graph, paths, fixes' },
      { id: 'repo', group: 'Go to', title: 'Repository', icon: 'repo', hint: 'Scan a GitHub repository', keywords: 'github scan code' },
      { id: 'insights', group: 'Go to', title: 'Insights', icon: 'chart', hint: 'Timeline and benchmarks' },
      { id: 'assistant', group: 'Go to', title: 'Assistant', icon: 'chat', hint: 'Ask about your paths', keywords: 'claude openai chat ask' },
      { id: 'settings', group: 'Go to', title: 'Settings', icon: 'settings', keywords: 'keys providers updates preferences' },
      { id: 'ingest', group: 'Actions', title: 'Add log data…', icon: 'upload', keywords: 'ingest upload paste logs' },
      { id: 'events', group: 'Actions', title: 'Show events', icon: 'file' },
      { id: 'refresh', group: 'Actions', title: 'Refresh', icon: 'refresh' },
      { id: 'toggle-sidebar', group: 'View', title: 'Show or hide sidebar', icon: 'sidebar' },
      { id: 'collapse-sidebar', group: 'View', title: 'Collapse or expand sidebar', icon: 'chevrons-left' },
      { id: 'toggle-inspector', group: 'View', title: 'Show or hide inspector', icon: 'inspector' },
      { id: 'reset', group: 'Actions', title: 'Reset workspace…', icon: 'trash' },
    ]
    if (ws.canPlay) c.splice(5, 0, { id: 'play', group: 'Actions', title: 'Play sample scenario', icon: 'play' })
    if (fx && fx.cheapest_cut) c.push({ id: 'fix-cheapest', group: 'Fixes', title: 'Propose cheapest cut', icon: 'shield', hint: `${fx.cheapest_cut.risk_removed_pct}% of risk removed` })
    if (fx && fx.best_single) c.push({ id: 'fix-single', group: 'Fixes', title: 'Propose best single fix', icon: 'shield', hint: `${fx.best_single.risk_removed_pct}% of risk removed` })
    if (bridge) c.push({ id: 'check-updates', group: 'App', title: 'Check for updates…', icon: 'refresh' })
    const cmds = c.map((x) => ({ ...x, run: () => run(x.id) }))
    for (const w of wsl.workspaces.filter((x) => x.id !== wsl.active).slice(0, 8)) {
      cmds.push({ id: `ws-${w.id}`, group: 'Workspaces', title: `Switch to ${w.name}`, icon: w.repo_url ? 'github' : 'folder', run: () => openWs(w.id) })
    }
    for (const p of ws.paths.slice(0, 12)) {
      cmds.push({ id: `path-${p.id}`, group: 'Paths', title: p.nodes.join(' → '), icon: 'graph',
        hint: `${p.severity.toLowerCase()} · ${p.risk.toFixed(2)}`, run: () => openPath(p.id) })
    }
    return cmds
  }, [ws.canPlay, ws.paths, fx, run, openPath, wsl.workspaces, wsl.active, openWs])

  if (view === null || !ws.loaded) return <Splash />
  const showInspector = view === 'analysis'
  return (
    <div className="app" data-sidebar={sidebarOpen ? (rail ? 'rail' : 'open') : 'closed'} key={wsl.active}
         style={sidebarOpen ? { gridTemplateColumns: `${rail ? 52 : sidebarW}px minmax(0, 1fr)` } : undefined}>
      {sidebarOpen && (
        <Sidebar view={view} setView={setView} graph={ws.graph} empty={ws.empty} severity={severity} canPlay={ws.canPlay}
                 playing={ws.playing} onPlay={ws.play} onReset={() => setConfirmReset(true)} onPalette={() => setPalette(true)}
                 rems={ws.rems} desktop={config.desktop} user={user} onSignOut={onSignOut} rail={rail} onToggleRail={() => run('collapse-sidebar')}
                 workspaces={wsl.workspaces} current={wsl.current} onOpenWs={openWs} onCreateWs={() => setNewDlg(true)}
                 onHome={() => run('open-repo')} onManage={() => run('workspaces')} />
      )}
      {sidebarOpen && !rail && (
        <Resizer side="left" value={sidebarW} min={200} max={360} onChange={setSidebarW} label="Resize sidebar" />
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
          {showInspector && (
            <button className="tool nodrag" onClick={() => run('toggle-inspector')} aria-pressed={inspectorOpen}
                    aria-label={inspectorOpen ? 'Hide inspector' : 'Show inspector'} title="Show or hide inspector"><Icon name="inspector" size={16} /></button>
          )}
          <button className="tool nodrag" onClick={() => setPalette(true)} aria-label="Command palette" title="Command palette"><Icon name="search" size={16} /></button>
        </div>
        {view === 'home' && (
          <Home workspaces={wsl.workspaces} current={wsl.current} desktop={config.desktop} config={config} onOpen={openWs}
                onImportRepo={importRepo} onImportFolder={importLocal} onChooseFolder={chooseFolder} onNew={() => setNewDlg(true)}
                onRename={wsl.rename} onDelete={setDelTarget} go={go} goSettings={goSettings} focusToken={homeFocus} intent={homeIntent} />
        )}
        {view === 'workspaces' && (
          <WorkspacesView wsl={wsl} onOpen={openWs} onRename={wsl.rename} onDelete={setDelTarget}
                          onNew={() => setNewDlg(true)} onOpenRepo={() => run('open-repo')} />
        )}
        {view === 'activity' && <ActivityView key={wsl.active} onRetry={retryScan} goSettings={goSettings} />}
        {view === 'integrations' && <IntegrationsView config={config} desktop={config.desktop} goSettings={goSettings} onIngested={ws.refresh} />}
        {view === 'insights' && <Insights key={ws.graph ? ws.graph.events : 0} rems={ws.rems} />}
        {view === 'repo' && <RepoView onDone={ws.refresh} />}
        {view === 'assistant' && <Assistant goSettings={() => goSettings('providers')} workspaceEmpty={ws.empty} />}
        {view === 'settings' && <Settings pane={pane} setPane={setPane} config={config} user={user} wsl={wsl} onCreate={() => setNewDlg(true)} />}
        {view === 'analysis' && (
          <Analysis state={ws} selected={selected} setSelected={setSelected} tab={tab} setTab={setTab} go={go}
                    desktop={config.desktop} inspectorOpen={inspectorOpen} />
        )}
      </div>

      {newDlg && (
        <NewWorkspaceDialog desktop={config.desktop} onCancel={() => setNewDlg(false)} onCreate={createNamed}
                            onImportRepo={importRepo} onImportFolder={importLocal} onChooseFolder={chooseFolder} />
      )}
      {delTarget && (
        <ConfirmDialog title={`Delete “${delTarget.name}”?`} confirmLabel="Delete Workspace"
                       body="Its events, scans, fixes and remediation history are deleted. You can’t undo this."
                       onCancel={() => setDelTarget(null)}
                       onConfirm={async () => { const d = delTarget; setDelTarget(null); if (await wsl.remove(d.id)) toast(`Deleted ${d.name}`, 'ok') }} />
      )}
      <CommandPalette open={palette} onClose={() => setPalette(false)} commands={commands} recents={recents}
                      onRun={(id) => { if (!id.startsWith('path-') && !id.startsWith('ws-')) setRecents((r) => pushRecent(r, id)) }} />
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
      <PrefsProvider key={user ? 'u' : 'anon'}>
        {user ? <Shell config={config} user={user} onSignOut={signOut} onExpired={config.desktop ? renew : signOut} /> : <Login config={config} onDone={() => api.me().then(setUser)} />}
      </PrefsProvider>
    </ToastProvider>
  )
}
