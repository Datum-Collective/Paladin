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
import Onboarding from './Onboarding.jsx'
import { PrefsProvider, usePrefs } from './prefs.jsx'
import { useWorkspaces } from './useWorkspaces.js'
import Assistant from './Assistant.jsx'
import Setup from './Setup.jsx'
import { classifyInput, pathKey, pushRecent } from './lib.js'
import { useStored } from './useStored.js'
import Sidebar from './Sidebar.jsx'
import Icon from './Icons.jsx'
import Brand from './Brand.jsx'
import { SEV_TONE } from './parts.jsx'
import { ToastProvider, useToast } from './toast.jsx'
import { useWorkspace } from './useWorkspace.js'

const bridge = typeof window !== 'undefined' ? window.paladin : undefined
const INSIGHTS_DEMO = typeof location !== 'undefined' && /^(localhost|127\.0\.0\.1)$/.test(location.hostname) &&
  new URLSearchParams(location.search).has('demo')

// What the backend sent us back with after a redirect (sign-in, GitHub App install); read once, then cleaned up
const RETURN = new URLSearchParams(typeof location !== 'undefined' ? location.search : '')
if (typeof history !== 'undefined' && ['login_error', 'github_connected', 'github_error'].some((k) => RETURN.has(k))) {
  history.replaceState(null, '', '/')
}

function Login({ onDone, config }) {
  const [err, setErr] = useState(RETURN.has('login_error') ? 'GitHub sign-in did not finish. Try again.' : '')
  const [waiting, setWaiting] = useState(false)   // desktop: the sign-in is running in the browser

  // desktop: the browser signs in and the engine parks the session; collect it as soon as it is there
  useEffect(() => {
    if (!waiting) return undefined
    let stop = false
    const started = Date.now()
    const tick = async () => {
      if (stop) return
      try {
        if ((await api.claim()).signed_in) { onDone(); return }
      } catch (e) { setErr(e.message); setWaiting(false); return }
      if (Date.now() - started > 10 * 60 * 1000) { setWaiting(false); setErr('Sign-in timed out. Try again.'); return }
      setTimeout(tick, 1500)
    }
    tick()
    return () => { stop = true }
  }, [waiting, onDone])

  const start = async () => {
    setErr('')
    if (!config.desktop) { window.location.assign('/api/auth/login'); return }   // the backend runs the whole flow
    try { await bridge.signIn(); setWaiting(true) } catch { setErr('Could not open your browser to sign in.') }
  }
  return (
    <main className="login-page">
      <form className="login" onSubmit={(e) => { e.preventDefault(); start() }}>
        <Brand big />
        {/* Windows app: the PALADIN card from the brand references; elsewhere the existing introduction */}
        <div className="win-only login-head">
          <h1 className="login-title">Authenticate to PALADIN</h1>
          <p className="login-eyebrow">Attack path intelligence</p>
          <p className="muted">Sign in to access your security workspace.</p>
        </div>
        <div className="not-win">
          <h1 className="login-title">See the shortest path to your crown jewels.</h1>
          <p className="muted login-lede">Paladin turns logs and repository scans into ranked attack paths, then tells you the
            cheapest fix that cuts the most of them.</p>
          <ul className="login-points">
            <li><Icon name="graph" size={14} /> Ranked attack paths from the signals you already have</li>
            <li><Icon name="check" size={14} /> One cheapest fix, with the paths it removes</li>
            <li><Icon name="repo" size={14} /> Remediation tracked from finding to merged pull request</li>
          </ul>
        </div>
        {!config.signin ? (
          <div className="err login-card" role="alert">
            <p>Sign-in is not set up on this server.</p>
            {config.signin_missing && config.signin_missing.length > 0 && (
              <p className="small">Missing: <code>{config.signin_missing.join(', ')}</code>. Copy <code>.env.example</code> to{' '}
                <code>backend/.env</code>, fill them in, restart the server, then run{' '}
                <code>python scripts/check_signin.py</code> to verify.</p>
            )}
          </div>
        ) : waiting ? (
          <div className="login-card">
            <p>Continue in your browser. Paladin opens as soon as you are signed in.</p>
            <button type="button" onClick={start}>Open the Browser Again</button>
            <button type="button" className="link" onClick={() => setWaiting(false)}>Cancel</button>
          </div>
        ) : (
          <button type="submit" className="primary login-cta"><Icon name="github" size={16} /> Continue with GitHub</button>
        )}
        {err && <p className="err" role="alert">{err}</p>}
        <p className="muted small login-fine not-win">GitHub asks which account to use. Signing in shares only your public profile
          and email; repository access is a separate step you choose later.</p>
        <p className="muted small login-fine win-only">Secure authentication powered by GitHub. Repository access is a
          separate step you choose later.</p>
      </form>
    </main>
  )
}

function Splash({ error, onRetry }) {
  return (
    <div className="splash">
      <Brand big />
      {!error && <span className="splash-bar" aria-hidden="true" />}
      {error ? (
        <>
          <p className="err" role="alert">{error}</p>
          <button onClick={onRetry}>Try Again</button>
        </>
      ) : <span className="sr-only" role="status">Loading</span>}
    </div>
  )
}

const TITLES = { home: 'Home', workspaces: 'Workspaces', analysis: 'Analysis', repo: 'Repository', insights: 'Insights',
  assistant: 'Assistant', activity: 'Activity', integrations: 'Integrations', settings: 'Settings' }

function Shell({ config, user, onSignOut, onExpired }) {
  const toast = useToast()
  const { prefs, set: setPref, ready: prefsReady } = usePrefs()
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
  const [setupOpen, setSetupOpen] = useState(false)
  const [setupRuns, setSetupRuns] = useState(0)   // bumps when setup closes so Settings re-reads key state
  const [delTarget, setDelTarget] = useState(null)
  const [sidebarOpen, setSidebarOpen] = useStored('sidebar-open', true)
  const [rail, setRail] = useStored('sidebar-rail', false)
  const [sidebarW, setSidebarW] = useStored('sidebar-w', 248)
  const [inspectorOpen, setInspectorOpen] = useStored('inspector-open', true)
  const [pane, setPane] = useStored('settings-pane', 'general')
  const [recents, setRecents] = useStored('palette-recents', [])

  // first screen honours the "Start with" preference, once; coming back from installing the GitHub App lands on
  // Integrations with the result
  useEffect(() => {
    if (view !== null || !prefsReady || !wsl.loaded) return
    if (RETURN.has('github_connected') || RETURN.has('github_error')) {
      setView('integrations')
      if (RETURN.has('github_connected')) toast('GitHub repositories connected', 'ok')
      else toast('Could not connect GitHub. Install the app on the same account you signed in with, on your personal account (not an organization), and try again.', 'bad')
      return
    }
    setView(prefs['general.startup'] === 'last' && wsl.current ? 'analysis' : 'home')
  }, [view, prefsReady, wsl.loaded, wsl.current, prefs, toast])

  // First launch: nothing validated, nothing skipped, and no provider key anywhere. Returning users (including
  // web users whose server already holds a key) go straight in; setup stays reachable from Settings and the palette.
  const checkedSetup = useRef(false)
  useEffect(() => {
    if (checkedSetup.current || !prefsReady || !wsl.loaded) return
    const welcoming = !prefs['general.welcome_seen'] && !wsl.workspaces.some((w) => w.repo_url || w.events > 0)
    if (welcoming) return                      // the welcome tour comes first; this re-runs when it finishes
    checkedSetup.current = true
    if (prefs['general.setup_done'] || prefs['general.setup_skipped']) return
    api.providers().then((r) => {
      if (!r.providers.some((p) => p.configured)) setSetupOpen(true)
    }).catch(() => {})
  }, [prefsReady, wsl.loaded, wsl.workspaces, prefs])

  const go = useCallback((target) => {
    if (target === 'ingest') { setView('analysis'); setTab('ingest') } else setView(target)
  }, [])
  const openPath = useCallback((id) => { setView('analysis'); setTab('paths'); setSelected(id) }, [])
  const doReset = useCallback(async () => { setConfirmReset(false); setSelected(null); await ws.reset() }, [ws])
  const goSettings = useCallback((p) => { if (p) setPane(p); setView('settings') }, [setPane])
  const fx = ws.fixes

  const openWs = useCallback(async (id) => {
    // opening a workspace lands inside it; if you are already in one of its views, stay on that view
    const inside = new Set(['analysis', 'repo', 'insights', 'assistant', 'activity'])
    if (await wsl.open(id)) { setSelected(null); setTab('paths'); setView((v) => (inside.has(v) ? v : 'analysis')) }
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
      assistant: () => setView('assistant'), settings: () => goSettings(), setup: () => setSetupOpen(true), ingest: () => go('ingest'),
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

  // first-run guide: brand-new accounts only (nothing imported yet), once; any way out remembers it was seen
  const isNew = wsl.loaded && !wsl.workspaces.some((w) => w.repo_url || w.events > 0)
  const showWelcome = prefsReady && !prefs['general.welcome_seen'] && isNew
  const finishWelcome = useCallback(async (choice, opts) => {
    checkedSetup.current = true      // the tour already offered provider setup; never open it again straight after
    await setPref('general.welcome_seen', true)
    if (opts && opts.keepOpen) return
    if (choice === 'sample') { setView('analysis'); run('play') }
    else if (choice === 'repo') run('open-repo')
    else setView('home')
  }, [setPref, run])

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
      { id: 'setup', group: 'Actions', title: 'Set up AI provider…', icon: 'shield', hint: 'Provider, key and model', keywords: 'onboarding claude openai api key model connect' },
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
        hint: `${p.severity.toLowerCase()} · ${p.risk.toFixed(2)}`, run: () => openPath(pathKey(p)) })
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
        {view === 'insights' && <Insights key={ws.graph ? `${ws.graph.events}:${ws.graph.nodes.length}:${ws.graph.edges.length}` : 'empty'} graph={ws.graph} paths={ws.paths} fixes={ws.fixes} rems={ws.rems} />}
        {view === 'repo' && <RepoView onDone={ws.refresh} onViewPaths={() => setView('analysis')} />}
        {view === 'assistant' && <Assistant key={wsl.active} goSettings={() => goSettings('providers')} onSetup={() => setSetupOpen(true)} workspaceEmpty={ws.empty} workspaceId={wsl.active} />}
        {view === 'settings' && <Settings key={setupRuns} pane={pane} setPane={setPane} onSetup={() => setSetupOpen(true)} config={config} user={user} wsl={wsl} onCreate={() => setNewDlg(true)} onReset={() => setConfirmReset(true)} />}
        {view === 'analysis' && (
          <Analysis state={ws} selected={selected} setSelected={setSelected} tab={tab} setTab={setTab} go={go}
                    desktop={config.desktop} inspectorOpen={inspectorOpen} />
        )}
      </div>

      {setupOpen && <Setup config={config} onClose={() => { setSetupOpen(false); setSetupRuns((n) => n + 1) }} onOpenAssistant={() => setView('assistant')} />}
      {showWelcome && <Onboarding config={config} user={user} canPlay={ws.canPlay} onFinish={finishWelcome} />}
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
        setUser(null)
      }
    } catch (e) {
      setError(e.message === 'request failed' ? 'Could not reach the analysis engine.' : e.message)
    }
  }, [])

  useEffect(() => {
    if (bridge) document.documentElement.dataset.platform = bridge.platform
    boot()
  }, [boot])

  const signOut = useCallback(async () => { try { await api.logout() } finally { setUser(null) } }, [])
  // a lapsed session (refresh rejected or revoked) goes back to the sign-in screen
  const expired = useCallback(() => setUser(null), [])
  const signedIn = useCallback(() => api.me().then(setUser), [])

  if (error) return <Splash error={error} onRetry={boot} />
  if (!config || user === undefined) return <Splash />
  if (INSIGHTS_DEMO) return <ToastProvider><PrefsProvider key="insights-demo"><Insights demo /></PrefsProvider></ToastProvider>
  return (
    <ToastProvider>
      <PrefsProvider key={user ? 'u' : 'anon'}>
        {user ? <Shell config={config} user={user} onSignOut={signOut} onExpired={expired} /> : <Login config={config} onDone={signedIn} />}
      </PrefsProvider>
    </ToastProvider>
  )
}
