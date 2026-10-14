import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './api.js'
import Analysis from './Analysis.jsx'
import CommandPalette from './CommandPalette.jsx'
import Insights from './Insights.jsx'
import RepoView from './RepoView.jsx'
import Settings from './Settings.jsx'
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

function Shell({ config, user, onSignOut, onExpired }) {
  const toast = useToast()
  const ws = useWorkspace(user, onExpired)
  const [view, setView] = useState('analysis')
  const [tab, setTab] = useState('paths')
  const [selected, setSelected] = useState(null)
  const [palette, setPalette] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)

  const go = useCallback((target) => {
    if (target === 'ingest') { setView('analysis'); setTab('ingest') } else setView(target)
  }, [])
  const openPath = useCallback((id) => { setView('analysis'); setTab('paths'); setSelected(id) }, [])
  const doReset = useCallback(async () => { setConfirmReset(false); setSelected(null); await ws.reset() }, [ws])

  useEffect(() => {
    const onKey = (e) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey) return
      const k = e.key.toLowerCase()
      if (k === 'k') { e.preventDefault(); setPalette((p) => !p) }
      else if (k === '1') { e.preventDefault(); setView('analysis') }
      else if (k === '2') { e.preventDefault(); setView('repo') }
      else if (k === '3') { e.preventDefault(); setView('insights') }
      else if (k === ',') { e.preventDefault(); setView('settings') }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const severity = ws.graph ? { label: ws.graph.severity.toLowerCase(), tone: SEV_TONE[ws.graph.severity] } : { label: '', tone: '' }

  const commands = useMemo(() => {
    const c = [
      { id: 'v-analysis', group: 'Go to', title: 'Analysis', icon: 'graph', hint: 'Graph, paths, fixes', run: () => setView('analysis') },
      { id: 'v-repo', group: 'Go to', title: 'Repository', icon: 'repo', hint: 'Scan a GitHub repo', keywords: 'github scan code', run: () => setView('repo') },
      { id: 'v-insights', group: 'Go to', title: 'Insights', icon: 'chart', hint: 'Timeline and benchmarks', run: () => setView('insights') },
      { id: 'v-settings', group: 'Go to', title: 'Settings', icon: 'settings', keywords: 'keys updates preferences', run: () => setView('settings') },
      { id: 'a-ingest', group: 'Actions', title: 'Add log data', icon: 'upload', keywords: 'ingest upload paste logs', run: () => go('ingest') },
      { id: 'a-events', group: 'Actions', title: 'Show events', icon: 'file', run: () => { setView('analysis'); setTab('events') } },
      { id: 'a-refresh', group: 'Actions', title: 'Refresh data', icon: 'refresh', run: () => ws.refresh() },
      { id: 'a-reset', group: 'Actions', title: 'Reset workspace', icon: 'trash', run: () => setConfirmReset(true) },
    ]
    if (ws.canPlay) c.splice(4, 0, { id: 'a-play', group: 'Actions', title: 'Play sample scenario', icon: 'play', run: () => ws.play() })
    const f = ws.fixes
    if (f && f.cheapest_cut) c.push({ id: 'f-cut', group: 'Fixes', title: 'Propose cheapest cut', icon: 'shield',
      hint: `${f.cheapest_cut.risk_removed_pct}% risk removed`, run: () => ws.propose(f.cheapest_cut.edges, 'Cheapest cut') })
    if (f && f.best_single) c.push({ id: 'f-single', group: 'Fixes', title: 'Propose best single fix', icon: 'shield',
      hint: `${f.best_single.risk_removed_pct}% risk removed`, run: () => ws.propose(f.best_single.edges, 'Best single fix') })
    if (bridge) c.push({ id: 'u-check', group: 'App', title: 'Check for updates', icon: 'refresh',
      run: async () => { const s = await bridge.checkForUpdates(); toast(s.phase === 'disabled' ? 'Updates are off in development builds' : 'Checking for updates…') } })
    for (const p of ws.paths.slice(0, 12)) {
      c.push({ id: `p-${p.id}`, group: 'Paths', title: p.nodes.join(' → '), icon: 'graph', hint: `${p.severity.toLowerCase()} · ${p.risk.toFixed(2)}`,
        run: () => openPath(p.id) })
    }
    return c
  }, [ws, go, openPath, toast])

  if (!ws.loaded) return <Splash />
  return (
    <div className="app">
      <Sidebar view={view} setView={setView} graph={ws.graph} empty={ws.empty} severity={severity} canPlay={ws.canPlay}
               playing={ws.playing} onPlay={ws.play} onReset={() => setConfirmReset(true)} onPalette={() => setPalette(true)}
               rems={ws.rems} desktop={config.desktop} user={user} onSignOut={onSignOut} />
      <div className="content">
        <div className="toolbar drag">
          <h1 className="toolbar-title">{{ analysis: 'Analysis', repo: 'Repository', insights: 'Insights', settings: 'Settings' }[view]}</h1>
          {view === 'analysis' && !ws.empty && (
            <span className="muted small toolbar-sub">
              worst path {ws.graph.worst.toFixed(2)} · combined {ws.graph.risk.toFixed(2)} · {ws.graph.events} {ws.graph.events === 1 ? 'event' : 'events'}
            </span>
          )}
          <span className="spacer" />
          <button className="nodrag" onClick={() => setPalette(true)} aria-label="Command palette"><Icon name="command" size={14} /></button>
        </div>
        {view === 'insights' && <Insights key={ws.graph ? ws.graph.events : 0} rems={ws.rems} />}
        {view === 'repo' && <RepoView onDone={ws.refresh} />}
        {view === 'settings' && <Settings config={config} user={user} onReset={() => setConfirmReset(true)} onSignOut={onSignOut} />}
        {view === 'analysis' && (
          <Analysis state={ws} selected={selected} setSelected={setSelected} tab={tab} setTab={setTab} go={go} desktop={config.desktop} />
        )}
      </div>

      <CommandPalette open={palette} onClose={() => setPalette(false)} commands={commands} />
      {confirmReset && (
        <div className="scrim" onMouseDown={() => setConfirmReset(false)}>
          <div className="dialog" role="alertdialog" aria-modal="true" aria-labelledby="reset-title" onMouseDown={(e) => e.stopPropagation()}>
            <h2 id="reset-title">Reset this workspace?</h2>
            <p className="muted">Events, applied fixes, scan results and remediation history are deleted. This cannot be undone.</p>
            <div className="actions end">
              <button autoFocus onClick={() => setConfirmReset(false)}>Cancel</button>
              <button className="danger" onClick={doReset}>Reset workspace</button>
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
