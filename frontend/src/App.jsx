import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import Graph from './Graph.jsx'
import Insights from './Insights.jsx'

const SEV = { CRITICAL: 'sev-critical', HIGH: 'sev-high', MEDIUM: 'sev-medium', LOW: 'sev-low' }
const KILL_CHAIN = ['reconnaissance', 'initial-access', 'execution', 'persistence', 'privilege-escalation',
  'defense-evasion', 'credential-access', 'discovery', 'lateral-movement', 'collection',
  'command-and-control', 'exfiltration', 'impact']
const RUNNING = ['queued', 'cloning', 'scanning', 'fixing']
const NEXT_ACTION = { proposed: 'approve', approved: 'execute', executed: 'verify' }
const hhmm = (ts) => (ts || '').replace('T', ' ').replace('Z', '').slice(5, 16)

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
      <button className="primary" onClick={() => go(api.demo)}>Use demo account</button>
      <hr />
      <input placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      <input placeholder="password" type="password" value={pw} onChange={(e) => setPw(e.target.value)} />
      <button onClick={() => go(() => (mode === 'login' ? api.login(email, pw) : api.register(email, pw)))}>
        {mode === 'login' ? 'Sign in' : 'Create account'}
      </button>
      <button className="link" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>
        {mode === 'login' ? 'Need an account?' : 'Have an account?'}
      </button>
      {err && <p className="err">{err}</p>}
    </div>
  )
}

function KillChain({ tactics }) {
  return (
    <div className="killchain">
      {KILL_CHAIN.map((t) => (
        <span key={t} className={tactics.includes(t) ? 'kc on' : 'kc'}>{t.replace(/-/g, ' ')}</span>
      ))}
    </div>
  )
}

function PathDetail({ path }) {
  if (!path) return <p className="muted">Select a path to see its story, assets and evidence.</p>
  return (
    <div>
      <h3><span className={`badge ${SEV[path.severity]}`}>{path.severity}</span> risk {path.risk.toFixed(3)}</h3>
      <p>{path.narrative}</p>
      <KillChain tactics={path.tactics} />
      <h4>Affected assets</h4>
      <ul className="assets">
        {path.assets.map((a) => (
          <li key={a.id}><b>{a.label}</b> <span className="muted">{a.kind} · criticality {a.criticality}</span></li>
        ))}
      </ul>
      <h4>Attack progression</h4>
      <ol className="hops">
        {path.hops.map((h) => (
          <li key={h.edge}>
            <b>{h.src}</b> → <b>{h.dst}</b>
            <div className="muted">{h.technique} {h.technique_name} · p={h.p} ·{' '}
              {h.observed ? <span className="obs">confirmed</span> : 'possible (no events yet)'}</div>
            {h.events.map((e) => (
              <div key={e.id} className="ev"><span className="muted">{e.id} · {hhmm(e.ts)} · {e.source}</span>
                <code>{e.raw || `${e.type} ${e.actor} ${e.src_ip}`}</code></div>
            ))}
            {h.mitigation && <div className="muted">fix: {h.mitigation} {h.mitigation_name}</div>}
          </li>
        ))}
      </ol>
    </div>
  )
}

function Fixes({ fixes, onPropose }) {
  if (!fixes || (!fixes.cheapest_cut && !fixes.best_single)) return null
  const card = (title, f) => f && (
    <div className="fix">
      <h4>{title}</h4>
      <div>Cut {f.edges.join(', ')} · cost {f.total_cost} · breaks {f.paths_broken} path(s) ·
        removes {f.risk_removed_pct}% of risk</div>
      <div className="muted">{f.mitigations.map((m) => `${m.technique} → ${m.mitigation}`).join('; ')}</div>
      <button onClick={() => onPropose(f.edges, title)}>Propose fix</button>
    </div>
  )
  return (
    <div>
      <h4>Recommended fixes</h4>
      {card('Cheapest cut', fixes.cheapest_cut)}
      {card('Best single fix', fixes.best_single)}
      {fixes.edge_count_cut_cost != null && (
        <p className="muted">A cut minimising edge count would cost {fixes.edge_count_cut_cost}.</p>
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
      <h4>Remediation workflow</h4>
      {err && <p className="err">{err}</p>}
      {items.map((r) => (
        <div key={r.id} className="fix">
          <div onClick={() => show(r.id)} style={{ cursor: 'pointer' }}>
            <b>#{r.id}</b> {r.title} <span className={`state st-${r.state}`}>{r.state}</span>
            <div className="muted">{r.edges.join(', ')}{r.ai_drafted ? ' · AI-drafted runbook' : ''}</div>
          </div>
          {r.note && <div className="err">{r.note}</div>}
          {r.risk_before != null && (
            <div className="muted">risk {r.risk_before} → {r.risk_after} · paths {r.paths_before} → {r.paths_after}</div>
          )}
          {NEXT_ACTION[r.state] && <button onClick={() => step(r.id, NEXT_ACTION[r.state])}>{NEXT_ACTION[r.state]}</button>}
          {['executed', 'verified', 'failed'].includes(r.state) &&
            <button onClick={() => step(r.id, 'rollback')}>rollback</button>}
          {open === r.id && detail && (
            <>
              <pre className="curl">{detail.runbook}</pre>
              <ul className="hops">
                {detail.audit.map((a, i) => <li key={i}>{a.action} · {a.actor}<span className="muted"> {a.detail}</span></li>)}
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
      <p className="muted">{data.total} events (latest {data.events.length})</p>
      <ul className="paths">
        {data.events.map((e) => (
          <li key={e.id}>
            <span className="muted">{e.id} · {hhmm(e.ts)} · {e.source} · {e.type}</span>
            <div><code>{e.raw || `${e.actor} ${e.src_ip}`}</code></div>
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
      setMsg(`accepted ${r.accepted}, rejected ${r.rejected}`)
      onDone()
    } catch (e) { setMsg(e.message) }
  }
  const file = async (e) => { const f = e.target.files[0]; if (f) setText(await f.text()) }
  const curl = `curl -X POST ${location.origin}/api/ingest -H "X-API-Key: ${key}" -H "Content-Type: application/json" \\
  -d '{"format":"${fmt}","lines":["<one log line>"]}'`
  return (
    <div>
      <h4>Upload logs</h4>
      <select value={fmt} onChange={(e) => setFmt(e.target.value)}>
        <option value="linux_auth">Linux auth (syslog)</option>
        <option value="web_access">Web access (combined)</option>
        <option value="snort_alert">IDS alert (Snort format)</option>
      </select>
      <input type="file" onChange={file} />
      <textarea rows={5} value={text} onChange={(e) => setText(e.target.value)} placeholder="paste log lines" />
      <button className="primary" onClick={send} disabled={!text}>Ingest</button> <span className="muted">{msg}</span>
      <h4>Send from your own system</h4>
      <button onClick={async () => setKey((await api.createKey('source')).key)}>Create API key</button>
      {key && <pre className="curl">{curl}</pre>}
    </div>
  )
}

function Repo({ onDone }) {
  const [url, setUrl] = useState('')
  const [job, setJob] = useState(null)
  const [cfg, setCfg] = useState({ github_enabled: false, ai_enabled: false })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.hConfig().then(setCfg).catch(() => {})
    api.hJobs().then((r) => r.jobs[0] && api.hJob(r.jobs[0].id).then(setJob)).catch(() => {})
  }, [])
  useEffect(() => {
    if (!job || !RUNNING.includes(job.state)) return
    const t = setTimeout(async () => {
      const j = await api.hJob(job.id)
      setJob(j)
      if (!RUNNING.includes(j.state)) onDone()
    }, 1200)
    return () => clearTimeout(t)
  }, [job])

  const run = async () => {
    setErr('')
    try { setJob(await api.hStart(url.trim())) } catch (e) { setErr(e.message) }
  }
  const openPr = async () => {
    setErr(''); setBusy(true)
    try { setJob(await api.hPr(job.id)) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <div>
      <h4>Scan a GitHub repository</h4>
      <input style={{ width: '100%' }} placeholder="https://github.com/owner/repo" value={url}
        onChange={(e) => setUrl(e.target.value)} />
      <button className="primary" onClick={run} disabled={!url || (job && RUNNING.includes(job.state))}>
        Scan and fix
      </button>
      <p className="muted">
        Repo code is never executed. AI: {cfg.ai_enabled ? 'on' : 'off (rules only)'} · Pull requests:{' '}
        {cfg.github_enabled ? 'enabled' : 'patch download only'}
      </p>
      {err && <p className="err">{err}</p>}
      {job && (
        <>
          <p><b>{job.repo_url}</b> <span className={`state st-${job.state}`}>{job.state}</span></p>
          {job.error && <p className="err">{job.error}</p>}
          <ul className="hops">{job.log.slice(-6).map((l, i) => <li key={i} className="muted">{l.msg}</li>)}</ul>
          {job.fixes.length > 0 && (
            <>
              <h4>{job.fixes.length} verified fix(es) on {job.branch}</h4>
              <ul className="paths">
                {job.fixes.map((f) => (
                  <li key={f.id}>
                    <b>{f.rule}</b> <span className="muted">{f.cwe} · {f.technique} · {f.method}</span>
                    <div className="muted">{f.file}:{f.line}: {f.explanation}</div>
                  </li>
                ))}
              </ul>
              <pre className="curl">{job.diff.slice(0, 5000)}</pre>
              <a href={`/api/harness/jobs/${job.id}/patch`} target="_blank" rel="noreferrer">Download patch</a>{' '}
              {job.state === 'ready' && (
                <button className="primary" disabled={busy || !cfg.github_enabled} onClick={openPr}>
                  Approve and open PR
                </button>
              )}
              {job.pr_url && <p>PR: <a href={job.pr_url} target="_blank" rel="noreferrer">{job.pr_url}</a></p>}
            </>
          )}
        </>
      )}
    </div>
  )
}

function Empty({ canPlay, onPlay, goTab }) {
  return (
    <div className="empty">
      <h2>Nothing analysed yet</h2>
      <p className="muted">Bring in signals and the attack paths appear here.</p>
      <div className="empty-actions">
        <button className="primary" onClick={() => goTab('repo')}>Scan a GitHub repo</button>
        <button onClick={() => goTab('ingest')}>Upload or send logs</button>
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
  const [view, setView] = useState('dashboard')
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

  if (user === undefined) return null
  if (!user) return <Login onDone={() => api.me().then(setUser)} />

  const selected = paths.find((p) => p.id === sel)
  const empty = !graph || (graph.events === 0 && paths.length === 0)
  const sev = graph ? graph.severity : 'LOW'
  return (
    <div className="app">
      <header>
        <b>Attack Path Compiler</b>
        {!empty && <span className={`badge ${SEV[sev]}`}>{sev}</span>}
        {!empty && <span className="muted">risk {graph.risk.toFixed(3)} · {graph.events} events</span>}
        <span className="spacer" />
        {canPlay && <button className="primary" disabled={playing} onClick={play}>{playing ? 'Playing…' : 'Play'}</button>}
        <button onClick={() => setView(view === 'dashboard' ? 'insights' : 'dashboard')}>
          {view === 'dashboard' ? 'Insights' : 'Dashboard'}
        </button>
        <button onClick={async () => { await api.simReset(); setSel(null); refresh() }}>Reset</button>
        <button onClick={async () => { await api.logout(); setUser(null) }}>Sign out</button>
      </header>
      {view === 'insights' ? <Insights key={graph ? graph.events : 0} rems={rems} /> : (
        <main>
          <aside>
            <div className="tabs">
              {[['paths', 'Paths'], ['events', 'Events'], ['ingest', 'Ingest'], ['repo', 'Repo']].map(([t, l]) => (
                <button key={t} className={tab === t ? 'tab on' : 'tab'} onClick={() => setTab(t)}>{l}</button>
              ))}
            </div>
            {tab === 'paths' && (paths.length === 0 ? <p className="muted">No paths yet.</p> : (
              <ul className="paths">
                {paths.map((p) => (
                  <li key={p.id} className={p.id === sel ? 'on' : ''} onClick={() => setSel(p.id)}>
                    <span className={`badge ${SEV[p.severity]}`}>{p.severity}</span> {p.risk.toFixed(3)}
                    <div className="muted">{p.nodes.join(' → ')}</div>
                  </li>
                ))}
              </ul>
            ))}
            {tab === 'events' && <Events data={events} />}
            {tab === 'ingest' && <Ingest onDone={refresh} />}
            {tab === 'repo' && <Repo onDone={refresh} />}
          </aside>
          <section>
            {empty ? <Empty canPlay={canPlay} onPlay={play} goTab={setTab} /> : <Graph graph={graph} highlight={selected} />}
          </section>
          <aside className="right">
            {!empty && <PathDetail path={selected} />}
            {!empty && <Fixes fixes={fixes} onPropose={async (edges, title) => { await api.propose(edges, title); refresh() }} />}
            <Remediations items={rems} onChange={refresh} />
          </aside>
        </main>
      )}
    </div>
  )
}
