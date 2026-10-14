import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import Graph from './Graph.jsx'
import Insights from './Insights.jsx'
import RepoView from './RepoView.jsx'
import Icon from './Icons.jsx'

const SEV_TONE = { CRITICAL: 'bad', HIGH: 'bad', MEDIUM: 'warn', LOW: 'ok' }
const KILL_CHAIN = ['reconnaissance', 'initial-access', 'execution', 'persistence', 'privilege-escalation',
  'defense-evasion', 'credential-access', 'discovery', 'lateral-movement', 'collection',
  'command-and-control', 'exfiltration', 'impact']
const NEXT_ACTION = { proposed: 'Approve', approved: 'Execute', executed: 'Verify' }
const STEP = { Approve: 'approve', Execute: 'execute', Verify: 'verify' }
const hhmm = (ts) => (ts || '').replace('T', ' ').replace('Z', '').slice(5, 16)

function Severity({ level }) {
  return <span className={`pill ${SEV_TONE[level]}`}>{level.toLowerCase()}</span>
}

function Login({ onDone }) {
  const [email, setEmail] = useState('')
  const [pw, setPw] = useState('')
  const [mode, setMode] = useState('login')
  const [err, setErr] = useState('')
  const go = async (fn) => {
    setErr('')
    try { await fn(); onDone() } catch (e) { setErr(e.message) }
  }
  return (
    <div className="login">
      <h1>Attack Path Compiler</h1>
      <p className="muted">Turn scattered security signals into ranked attack paths and the cheapest fix.</p>
      <button className="primary" onClick={() => go(api.demo)}>Continue with demo account</button>
      <div className="or">or</div>
      <input placeholder="Email" aria-label="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
      <input placeholder="Password" aria-label="Password" type="password" value={pw}
             onChange={(e) => setPw(e.target.value)} />
      <button onClick={() => go(() => (mode === 'login' ? api.login(email, pw) : api.register(email, pw)))}>
        {mode === 'login' ? 'Sign in' : 'Create account'}
      </button>
      <button className="link" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>
        {mode === 'login' ? 'Create an account' : 'I already have an account'}
      </button>
      {err && <p className="err">{err}</p>}
    </div>
  )
}

function KillChain({ tactics }) {
  return (
    <div className="killchain" aria-label="Kill chain stages">
      {KILL_CHAIN.map((t) => (
        <span key={t} className={tactics.includes(t) ? 'kc on' : 'kc'}>{t.replace(/-/g, ' ')}</span>
      ))}
    </div>
  )
}

function PathDetail({ path }) {
  if (!path) return <p className="muted">Select a path to see how it works, which assets it touches and the evidence.</p>
  return (
    <div>
      <div className="row-top"><h2>Attack path</h2><Severity level={path.severity} /></div>
      <p className="muted">Risk {path.risk.toFixed(3)}</p>
      <p>{path.narrative}</p>
      <KillChain tactics={path.tactics} />
      <h3>Affected assets</h3>
      <ul className="plain">
        {path.assets.map((a) => (
          <li key={a.id}>{a.label} <span className="muted">{a.kind}, criticality {a.criticality}</span></li>
        ))}
      </ul>
      <h3>Progression</h3>
      <ol className="steps">
        {path.hops.map((h) => (
          <li key={h.edge}>
            <div><b>{h.src}</b> <span className="muted">to</span> <b>{h.dst}</b></div>
            <div className="muted">
              {h.technique} {h.technique_name} · p {h.p} · {h.observed ? 'confirmed by events' : 'possible, no events yet'}
            </div>
            {h.events.map((e) => (
              <div key={e.id} className="ev">
                <span className="muted">{e.id} · {hhmm(e.ts)} · {e.source}</span>
                <code className="snippet">{e.raw || `${e.type} ${e.actor} ${e.src_ip}`}</code>
              </div>
            ))}
            {h.mitigation && <div className="muted">Mitigation {h.mitigation} {h.mitigation_name}</div>}
          </li>
        ))}
      </ol>
    </div>
  )
}

function Fixes({ fixes, onPropose }) {
  if (!fixes || (!fixes.cheapest_cut && !fixes.best_single)) return null
  const card = (title, f) => f && (
    <div className="card">
      <div className="row-top"><b>{title}</b><span className="muted">cost {f.total_cost}</span></div>
      <p className="muted">
        Closes {f.edges.length} step(s) and breaks {f.paths_broken} path(s), removing {f.risk_removed_pct}% of risk.
        {' '}{f.mitigations.map((m) => m.mitigation).filter(Boolean).join(', ')}
      </p>
      <button className="primary" onClick={() => onPropose(f.edges, title)}>Propose fix</button>
    </div>
  )
  return (
    <div>
      <h3>Recommended fixes</h3>
      {card('Cheapest cut', fixes.cheapest_cut)}
      {fixes.best_single && (!fixes.cheapest_cut ||
        fixes.best_single.edges.join() !== fixes.cheapest_cut.edges.join()) && card('Best single fix', fixes.best_single)}
      {fixes.edge_count_cut_cost != null && (
        <p className="muted small">A cut that only minimises step count would cost {fixes.edge_count_cut_cost}.</p>
      )}
    </div>
  )
}

function Remediations({ items, onChange }) {
  const [open, setOpen] = useState(null)
  const [detail, setDetail] = useState(null)
  const [err, setErr] = useState('')
  const show = async (id) => {
    if (open === id) { setOpen(null); return }
    setOpen(id); setDetail(await api.remediation(id))
  }
  const step = async (id, action) => {
    setErr('')
    try { await api.rstep(id, action); setDetail(await api.remediation(id)); onChange() } catch (e) { setErr(e.message) }
  }
  if (!items.length) return null
  return (
    <div>
      <h3>Remediation</h3>
      {err && <p className="err">{err}</p>}
      {items.map((r) => (
        <div key={r.id} className="card">
          <button className="row-btn" onClick={() => show(r.id)} aria-expanded={open === r.id}>
            <b>{r.title}</b>
            <span className={`pill ${r.state === 'verified' ? 'ok' : r.state === 'failed' ? 'bad' : 'info'}`}>{r.state.replace('_', ' ')}</span>
          </button>
          {r.note && <p className="err">{r.note}</p>}
          {r.risk_before != null && (
            <p className="muted">Risk {r.risk_before} to {r.risk_after} · dangerous paths {r.paths_before} to {r.paths_after}</p>
          )}
          <div className="actions">
            {NEXT_ACTION[r.state] && <button className="primary" onClick={() => step(r.id, STEP[NEXT_ACTION[r.state]])}>{NEXT_ACTION[r.state]}</button>}
            {['executed', 'verified', 'failed'].includes(r.state) && <button onClick={() => step(r.id, 'rollback')}>Roll back</button>}
          </div>
          {open === r.id && detail && (
            <>
              <pre className="runbook">{detail.runbook}</pre>
              {detail.ai_drafted && <p className="muted small">Runbook drafted by AI from the computed facts.</p>}
              <ul className="plain">
                {detail.audit.map((a, i) => <li key={i}>{a.action} <span className="muted">by {a.actor} {a.detail}</span></li>)}
              </ul>
            </>
          )}
        </div>
      ))}
    </div>
  )
}

function Events({ data }) {
  if (!data || !data.events.length) return <p className="muted">No events yet.</p>
  return (
    <div>
      <p className="muted">{data.total} events, newest first</p>
      <ul className="rows">
        {data.events.map((e) => (
          <li key={e.id}>
            <div className="muted">{e.id} · {hhmm(e.ts)} · {e.source} · {e.type}</div>
            <code className="snippet">{e.raw || `${e.actor} ${e.src_ip}`}</code>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Ingest({ onDone }) {
  const [fmt, setFmt] = useState('linux_auth')
  const [text, setText] = useState('')
  const [msg, setMsg] = useState('')
  const [key, setKey] = useState('')
  const send = async () => {
    try {
      const r = await api.ingest(fmt, text.split('\n').filter(Boolean))
      setMsg(`${r.accepted} accepted, ${r.rejected} rejected`)
      onDone()
    } catch (e) { setMsg(e.message) }
  }
  const file = async (e) => { const f = e.target.files[0]; if (f) setText(await f.text()) }
  const curl = `curl -X POST ${location.origin}/api/ingest -H "X-API-Key: ${key}" -H "Content-Type: application/json" \\
  -d '{"format":"${fmt}","lines":["<one log line>"]}'`
  return (
    <div>
      <h3>Add log data</h3>
      <select value={fmt} onChange={(e) => setFmt(e.target.value)} aria-label="Log format">
        <option value="linux_auth">Linux auth (syslog)</option>
        <option value="web_access">Web access (combined)</option>
        <option value="snort_alert">IDS alert (Snort format)</option>
      </select>
      <input type="file" onChange={file} aria-label="Log file" />
      <textarea rows={5} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste log lines" />
      <div className="actions">
        <button className="primary" onClick={send} disabled={!text}>Ingest</button>
        <span className="muted">{msg}</span>
      </div>
      <h3>Send from your own system</h3>
      <button onClick={async () => setKey((await api.createKey('source')).key)}>Create API key</button>
      {key && <pre className="runbook">{curl}</pre>}
    </div>
  )
}

function Empty({ canPlay, onPlay, go }) {
  return (
    <div className="empty">
      <h2>Nothing to analyse yet</h2>
      <p className="muted">Scan a repository or add log data, and the attack paths appear here.</p>
      <div className="actions center">
        <button className="primary" onClick={() => go('repo')}>Scan a repository</button>
        <button onClick={() => go('ingest')}>Add log data</button>
        {canPlay && <button onClick={onPlay}>Play sample scenario</button>}
      </div>
    </div>
  )
}

export default function App() {
  const [user, setUser] = useState(undefined)
  const [graph, setGraph] = useState(null)
  const [paths, setPaths] = useState([])
  const [fixes, setFixes] = useState(null)
  const [events, setEvents] = useState(null)
  const [rems, setRems] = useState([])
  const [sel, setSel] = useState(null)
  const [playing, setPlaying] = useState(false)
  const [canPlay, setCanPlay] = useState(false)
  const [tab, setTab] = useState('paths')
  const [view, setView] = useState('analysis')
  const timer = useRef(null)

  const refresh = useCallback(async () => {
    const [g, p, f, r, ev] = await Promise.all([api.graph(), api.paths(), api.fixes(), api.remediations(), api.events()])
    setGraph(g); setPaths(p.paths); setFixes(f); setRems(r.remediations); setEvents(ev)
  }, [])

  useEffect(() => { api.me().then(setUser).catch(() => setUser(null)) }, [])
  useEffect(() => {
    if (!user) return
    refresh()
    api.simStatus().then((s) => setCanPlay(s.total > 0)).catch(() => {})
    const es = new EventSource('/api/stream')
    es.onmessage = () => refresh()
    return () => es.close()
  }, [user, refresh])
  useEffect(() => () => clearTimeout(timer.current), [])

  const play = async () => {
    setPlaying(true)
    await api.simStart()
    const tick = async () => {
      const r = await api.simStep(15)
      if (r.done) { setPlaying(false); return }
      timer.current = setTimeout(tick, 700)
    }
    tick()
  }
  const go = (target) => {
    if (target === 'ingest') { setView('analysis'); setTab('ingest') } else setView(target)
  }

  if (user === undefined) return null
  if (!user) return <Login onDone={() => api.me().then(setUser)} />

  const selected = paths.find((p) => p.id === sel)
  const empty = !graph || (graph.events === 0 && paths.length === 0)
  const NAV = [['analysis', 'Analysis', 'graph'], ['repo', 'Repository', 'repo'], ['insights', 'Insights', 'chart']]
  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">Attack Path Compiler</span>
        <nav className="seg" aria-label="Sections">
          {NAV.map(([id, label, icon]) => (
            <button key={id} className={view === id ? 'on' : ''} onClick={() => setView(id)}>
              <Icon name={icon} size={14} /> {label}
            </button>
          ))}
        </nav>
        <span className="spacer" />
        {!empty && graph && (
          <span className="status-inline">
            <Severity level={graph.severity} /> <span className="muted">risk {graph.risk.toFixed(2)} · {graph.events} events</span>
          </span>
        )}
        {canPlay && (
          <button disabled={playing} onClick={play}><Icon name="play" size={14} /> {playing ? 'Playing' : 'Play'}</button>
        )}
        <button onClick={async () => { await api.simReset(); setSel(null); refresh() }}>Reset</button>
        <button className="icon-btn" aria-label="Sign out" title="Sign out"
                onClick={async () => { await api.logout(); setUser(null) }}><Icon name="logout" /></button>
      </header>

      {view === 'insights' && <Insights key={graph ? graph.events : 0} rems={rems} />}
      {view === 'repo' && <RepoView onDone={refresh} />}
      {view === 'analysis' && (
        <main className="analysis">
          <aside className="pane left">
            <div className="seg small" role="tablist">
              {[['paths', 'Paths', 'list'], ['events', 'Events', 'file'], ['ingest', 'Add data', 'upload']].map(([t, l]) => (
                <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>{l}</button>
              ))}
            </div>
            {tab === 'paths' && (paths.length === 0 ? <p className="muted">No paths yet.</p> : (
              <ul className="rows selectable">
                {paths.map((p) => (
                  <li key={p.id} className={p.id === sel ? 'on' : ''} onClick={() => setSel(p.id)}>
                    <div className="row-top"><Severity level={p.severity} /><span className="muted">{p.risk.toFixed(3)}</span></div>
                    <div className="path-line">{p.nodes.join(' → ')}</div>
                  </li>
                ))}
              </ul>
            ))}
            {tab === 'events' && <Events data={events} />}
            {tab === 'ingest' && <Ingest onDone={refresh} />}
          </aside>
          <section className="canvas">
            {empty ? <Empty canPlay={canPlay} onPlay={play} go={go} /> : <Graph graph={graph} highlight={selected} />}
          </section>
          <aside className="pane right">
            {!empty && <PathDetail path={selected} />}
            {!empty && <Fixes fixes={fixes} onPropose={async (edges, title) => { await api.propose(edges, title); refresh() }} />}
            <Remediations items={rems} onChange={refresh} />
          </aside>
        </main>
      )}
    </div>
  )
}
