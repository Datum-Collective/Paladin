import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import Graph from './Graph.jsx'

const SEV = { CRITICAL: 'sev-critical', HIGH: 'sev-high', MEDIUM: 'sev-medium', LOW: 'sev-low' }
const KILL_CHAIN = ['reconnaissance', 'initial-access', 'execution', 'persistence', 'privilege-escalation',
  'defense-evasion', 'credential-access', 'discovery', 'lateral-movement', 'collection',
  'command-and-control', 'exfiltration', 'impact']

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
      <p className="muted">Small alerts in, attack path out, and the one fix that stops it. Synthetic data only.</p>
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
        <span key={t} className={tactics.includes(t) ? 'kc on' : 'kc'} title={t}>{t.replace(/-/g, ' ')}</span>
      ))}
    </div>
  )
}

function PathDetail({ path }) {
  if (!path) return <p className="muted">Select a path to see its story and evidence.</p>
  return (
    <div>
      <h3>
        <span className={`badge ${SEV[path.severity]}`}>{path.severity}</span> risk {path.risk.toFixed(3)}
      </h3>
      <p>{path.narrative}</p>
      <KillChain tactics={path.tactics} />
      <h4>Hops</h4>
      <ul className="hops">
        {path.hops.map((h) => (
          <li key={h.edge}>
            <b>{h.src}</b> → <b>{h.dst}</b> · {h.technique} {h.technique_name} · p={h.p}
            {h.observed ? <span className="obs"> observed</span> : <span className="muted"> prior only</span>}
            <div className="muted">
              {h.evidence.length ? `evidence: ${h.evidence.join(', ')}` : 'no evidence yet'}
              {h.mitigation ? ` · mitigation ${h.mitigation} ${h.mitigation_name}` : ''}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Fixes({ fixes, onApply }) {
  if (!fixes) return null
  const card = (title, f) => (
    <div className="fix">
      <h4>{title}</h4>
      {f ? (
        <>
          <div>Cut {f.edges.join(', ')} · cost {f.total_cost} · breaks {f.paths_broken} path(s) ·
            removes {f.risk_removed_pct}% of risk</div>
          <div className="muted">{f.mitigations.map((m) => `${m.technique} → ${m.mitigation}`).join('; ')}</div>
          <button onClick={() => onApply(f.edges, title)}>Propose fix</button>
        </>
      ) : <div className="muted">No cuttable fix available.</div>}
    </div>
  )
  return (
    <div>
      {card('Cheapest cut (min cost)', fixes.cheapest_cut)}
      {card('Best single fix', fixes.best_single)}
      {fixes.edge_count_cut_cost != null && (
        <p className="muted">A count-minimising cut would cost {fixes.edge_count_cut_cost}.</p>
      )}
      {fixes.applied.length > 0 && <p className="muted">Applied: {fixes.applied.join(', ')}</p>}
    </div>
  )
}

const NEXT_ACTION = { proposed: 'approve', approved: 'execute', executed: 'verify' }

function Remediations({ items, aiEnabled, onChange }) {
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
  if (!items.length) return <p className="muted">No remediations yet. Propose a fix above.</p>
  return (
    <div>
      <h4>Remediations {aiEnabled && <span className="muted">(AI drafting on)</span>}</h4>
      {err && <p className="err">{err}</p>}
      {items.map((r) => (
        <div key={r.id} className="fix">
          <div onClick={() => show(r.id)} style={{ cursor: 'pointer' }}>
            <b>#{r.id}</b> {r.title} <span className={`state st-${r.state}`}>{r.state}</span>
            <div className="muted">{r.edges.join(', ')}{r.ai_drafted ? ' · AI-drafted' : ''}</div>
          </div>
          {r.note && <div className="err">{r.note}</div>}
          {NEXT_ACTION[r.state] && <button onClick={() => step(r.id, NEXT_ACTION[r.state])}>{NEXT_ACTION[r.state]}</button>}
          {['executed', 'verified', 'failed'].includes(r.state) &&
            <button onClick={() => step(r.id, 'rollback')}>rollback</button>}
          {open === r.id && detail && (
            <>
              <pre className="curl">{detail.runbook}</pre>
              <ul className="hops">
                {detail.audit.map((a, i) => <li key={i}>{a.action} by {a.actor}<span className="muted"> {a.detail}</span></li>)}
              </ul>
            </>
          )}
        </div>
      ))}
    </div>
  )
}

function Upload({ onDone }) {
  const [fmt, setFmt] = useState('linux_auth')
  const [text, setText] = useState('')
  const [msg, setMsg] = useState('')
  const send = async () => {
    try {
      const r = await api.ingest(fmt, text.split('\n').filter(Boolean))
      setMsg(`accepted ${r.accepted}, rejected ${r.rejected}`)
      onDone()
    } catch (e) { setMsg(e.message) }
  }
  const file = async (e) => { const f = e.target.files[0]; if (f) setText(await f.text()) }
  return (
    <div>
      <h4>Upload logs</h4>
      <select value={fmt} onChange={(e) => setFmt(e.target.value)}>
        <option value="linux_auth">Linux auth syslog</option>
        <option value="web_access">Web access (combined)</option>
        <option value="snort_alert">Snort/IDS alert</option>
      </select>
      <input type="file" onChange={file} />
      <textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder="paste log lines" />
      <button onClick={send}>Send</button> <span className="muted">{msg}</span>
    </div>
  )
}

const CODE_EXT = /\.(py|js|jsx|ts|tsx|java|go|rb|php|cs|sh|ya?ml)$/i
const SKIP = /(node_modules|\.git|\.venv|venv|__pycache__|dist|build|vendor)\//

function CodeScan({ onDone }) {
  const [rep, setRep] = useState(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  useEffect(() => { api.codeReport().then(setRep).catch(() => {}) }, [])
  const pick = async (e) => {
    const all = Array.from(e.target.files)
    const chosen = all.filter((f) => CODE_EXT.test(f.name) && !SKIP.test(f.webkitRelativePath + '/') && f.size < 200000)
    if (!chosen.length) { setMsg('no source files found'); return }
    setBusy(true); setMsg(`scanning ${chosen.length} files…`)
    try {
      const files = await Promise.all(chosen.slice(0, 300).map(async (f) => ({
        path: f.webkitRelativePath || f.name, content: await f.text() })))
      const root = (chosen[0].webkitRelativePath || 'upload').split('/')[0]
      const r = await api.codeScan(root, files)
      setRep(r); setMsg(''); onDone()
    } catch (err) { setMsg(err.message) } finally { setBusy(false) }
  }
  return (
    <div>
      <h4>Code scan</h4>
      <p className="muted">Choose a project folder. Static rules flag candidates; Claude Haiku (if configured on the
        server) triages them. Files are sent to the server and, when AI is on, snippets to the Claude API.</p>
      <input type="file" webkitdirectory="" directory="" multiple onChange={pick} disabled={busy} />
      <span className="muted"> {msg}</span>
      {rep && rep.scanned && (
        <>
          <p className="muted">{rep.repo}: {rep.files} files, {rep.findings.length} findings
            {rep.ai_used ? ' · AI-triaged' : ' · static only'}</p>
          <ul className="paths">
            {rep.findings.map((f) => (
              <li key={f.id}>
                <b>{f.title}</b> <span className="muted">{f.cwe} · {f.technique}</span>
                <div className="muted">{f.file}:{f.line} {f.exploitable === false ? '· judged not exploitable' : ''}</div>
                <code>{f.snippet}</code>
                {f.reason && <div className="muted">{f.triaged_by}: {f.reason}</div>}
              </li>
            ))}
          </ul>
          <button onClick={async () => { await api.codeClear(); setRep({ scanned: false, findings: [] }); onDone() }}>
            Clear scan
          </button>
        </>
      )}
    </div>
  )
}

function Sources() {
  const [key, setKey] = useState('')
  const make = async () => setKey((await api.createKey('source')).key)
  const curl = `curl -X POST ${location.origin}/api/ingest -H "X-API-Key: ${key}" -H "Content-Type: application/json" \\
  -d '{"format":"linux_auth","lines":["May 14 09:12:03 WEB-BO-01 sshd[912]: Accepted password for www-data from 203.0.113.9 port 51544 ssh2"]}'`
  return (
    <div>
      <h4>Sources</h4>
      <button onClick={make}>Create API key</button>
      {key && <pre className="curl">{curl}</pre>}
    </div>
  )
}

export default function App() {
  const [user, setUser] = useState(undefined)
  const [graph, setGraph] = useState(null)
  const [paths, setPaths] = useState([])
  const [fixes, setFixes] = useState(null)
  const [rems, setRems] = useState({ remediations: [], ai_enabled: false })
  const [sel, setSel] = useState(null)
  const [playing, setPlaying] = useState(false)
  const [tab, setTab] = useState('paths')
  const timer = useRef(null)

  const refresh = useCallback(async () => {
    const [g, p, f, r] = await Promise.all([api.graph(), api.paths(), api.fixes(), api.remediations()])
    setGraph(g); setPaths(p.paths); setFixes(f); setRems(r)
  }, [])

  useEffect(() => {
    api.me().then((u) => setUser(u)).catch(() => setUser(null))
  }, [])

  useEffect(() => {
    if (!user) return
    refresh()
    const es = new EventSource('/api/stream')
    es.onmessage = () => refresh()
    return () => es.close()
  }, [user, refresh])

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
  useEffect(() => () => clearTimeout(timer.current), [])

  if (user === undefined) return null
  if (!user) return <Login onDone={() => api.me().then(setUser)} />

  const selected = paths.find((p) => p.id === sel)
  const sev = graph ? graph.severity : 'LOW'
  return (
    <div className="app">
      <header>
        <b>Attack Path Compiler</b>
        <span className={`badge ${SEV[sev]}`}>{sev}</span>
        <span className="muted">risk {graph ? graph.risk.toFixed(3) : '-'} · {graph ? graph.events : 0} events</span>
        <span className="spacer" />
        <button className="primary" disabled={playing} onClick={play}>{playing ? 'Playing…' : 'Play'}</button>
        <button onClick={async () => { await api.simReset(); setSel(null); refresh() }}>Reset</button>
        <button onClick={async () => { await api.logout(); setUser(null) }}>Sign out</button>
      </header>
      <main>
        <aside>
          <div className="tabs">
            {['paths', 'ingest', 'code', 'sources'].map((t) => (
              <button key={t} className={tab === t ? 'tab on' : 'tab'} onClick={() => setTab(t)}>{t}</button>
            ))}
          </div>
          {tab === 'paths' && (paths.length === 0 ? <p className="muted">No paths yet. Press Play.</p> : (
            <ul className="paths">
              {paths.map((p) => (
                <li key={p.id} className={p.id === sel ? 'on' : ''} onClick={() => setSel(p.id)}>
                  <span className={`badge ${SEV[p.severity]}`}>{p.severity}</span> {p.risk.toFixed(3)}
                  <div className="muted">{p.nodes.join(' → ')}</div>
                </li>
              ))}
            </ul>
          ))}
          {tab === 'ingest' && <Upload onDone={refresh} />}
          {tab === 'code' && <CodeScan onDone={refresh} />}
          {tab === 'sources' && <Sources />}
        </aside>
        <section>
          <Graph graph={graph} highlight={selected} />
        </section>
        <aside className="right">
          <PathDetail path={selected} />
          <Fixes fixes={fixes} onApply={async (edges, title) => { await api.propose(edges, title); refresh() }} />
          <Remediations items={rems.remediations} aiEnabled={rems.ai_enabled} onChange={refresh} />
        </aside>
      </main>
    </div>
  )
}
