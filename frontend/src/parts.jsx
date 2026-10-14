import { useState } from 'react'
import { api } from './api.js'
import { hhmm } from './lib.js'
import { useToast } from './toast.jsx'
import Icon from './Icons.jsx'

export const SEV_TONE = { CRITICAL: 'bad', HIGH: 'bad', MEDIUM: 'warn', LOW: 'ok' }
const KILL_CHAIN = ['reconnaissance', 'initial-access', 'execution', 'persistence', 'privilege-escalation',
  'defense-evasion', 'credential-access', 'discovery', 'lateral-movement', 'collection',
  'command-and-control', 'exfiltration', 'impact']
const NEXT_ACTION = { proposed: 'Approve', approved: 'Execute', executed: 'Verify' }
const STEP = { Approve: 'approve', Execute: 'execute', Verify: 'verify' }

// a glyph accompanies the colour so severity never depends on colour alone
const SEV_GLYPH = { CRITICAL: '▲', HIGH: '▲', MEDIUM: '◆', LOW: '●' }

export function Severity({ level }) {
  const word = level.charAt(0) + level.slice(1).toLowerCase()
  return <span className={`pill ${SEV_TONE[level]}`}><span aria-hidden="true">{SEV_GLYPH[level]} </span>{word}</span>
}

export function KillChain({ tactics }) {
  return (
    <div className="killchain" aria-label="Kill chain stages">
      {KILL_CHAIN.map((t) => (
        <span key={t} className={tactics.includes(t) ? 'kc on' : 'kc'}>{t.replace(/-/g, ' ')}</span>
      ))}
    </div>
  )
}

export function PathDetail({ path }) {
  if (!path) {
    return (
      <div className="inspector-empty">
        <Icon name="graph" size={22} />
        <p>Select a path</p>
        <p className="muted small">See how it works, which assets it touches and the evidence behind each step.</p>
      </div>
    )
  }
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

export function Fixes({ fixes, onPropose }) {
  const none = !fixes || (!fixes.cheapest_cut && !fixes.best_single)
  if (none) {
    return (
      <div className="inspector-empty">
        <Icon name="shield" size={22} />
        <p>No fixes to suggest</p>
        <p className="muted small">When a dangerous path exists, the cheapest way to break it appears here.</p>
      </div>
    )
  }
  const card = (title, f) => f && (
    <div className="card">
      <div className="row-top"><b>{title}</b><span className="muted">cost {f.total_cost}</span></div>
      <p className="muted">
        Closes {f.edges.length} step(s) and breaks {f.paths_broken} path(s), removing {f.risk_removed_pct}% of risk.
        {' '}{f.mitigations.map((m) => m.mitigation).filter(Boolean).join(', ')}
      </p>
      <button className="primary" onClick={() => onPropose(f.edges, title)}>Propose Fix</button>
    </div>
  )
  return (
    <div>
      <h3 className="first">Recommended fixes</h3>
      {card('Cheapest cut', fixes.cheapest_cut)}
      {fixes.best_single && (!fixes.cheapest_cut ||
        fixes.best_single.edges.join() !== fixes.cheapest_cut.edges.join()) && card('Best single fix', fixes.best_single)}
      {fixes.edge_count_cut_cost != null && (
        <p className="muted small">A cut that only minimises step count would cost {fixes.edge_count_cut_cost}.</p>
      )}
    </div>
  )
}

export function Remediations({ items, onChange }) {
  const [open, setOpen] = useState(null)
  const [detail, setDetail] = useState(null)
  const [busy, setBusy] = useState(null)
  const toast = useToast()
  if (!items.length) {
    return (
      <div className="inspector-empty">
        <Icon name="check" size={22} />
        <p>Nothing in remediation</p>
        <p className="muted small">Proposed fixes move through approve, execute and verify here, with an audit trail.</p>
      </div>
    )
  }
  const show = async (id) => {
    if (open === id) { setOpen(null); return }
    setOpen(id)
    try { setDetail(await api.remediation(id)) } catch (e) { toast(e.message, 'bad') }
  }
  const step = async (id, action) => {
    setBusy(id)
    try { await api.rstep(id, action); if (open === id) setDetail(await api.remediation(id)); onChange() }
    catch (e) { toast(e.message, 'bad') } finally { setBusy(null) }
  }
  return (
    <div>
      <h3 className="first">Remediation</h3>
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
            {NEXT_ACTION[r.state] && (
              <button className="primary" disabled={busy === r.id} onClick={() => step(r.id, STEP[NEXT_ACTION[r.state]])}>
                {NEXT_ACTION[r.state]}
              </button>
            )}
            {['executed', 'verified', 'failed'].includes(r.state) && (
              <button disabled={busy === r.id} onClick={() => step(r.id, 'rollback')}>Roll Back</button>
            )}
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

export function Events({ data }) {
  if (!data || !data.events.length) return <p className="muted">No events yet.</p>
  return (
    <div>
      <p className="muted small">{data.total} events, newest first</p>
      <ul className="rows">
        {data.events.map((e) => (
          <li key={e.id}>
            <div className="muted small">{e.id} · {hhmm(e.ts)} · {e.source} · {e.type}</div>
            <code className="snippet">{e.raw || `${e.actor} ${e.src_ip}`}</code>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function Ingest({ onDone, desktop }) {
  const [fmt, setFmt] = useState('linux_auth')
  const [text, setText] = useState('')
  const [key, setKey] = useState('')
  const toast = useToast()
  const send = async () => {
    try {
      const r = await api.ingest(fmt, text.split('\n').filter(Boolean))
      toast(`${r.accepted} accepted, ${r.rejected} rejected`, r.accepted ? 'ok' : 'warn')
      if (r.accepted) setText('')
      onDone()
    } catch (e) { toast(e.message, 'bad') }
  }
  const file = async (e) => { const f = e.target.files[0]; if (f) setText(await f.text()) }
  const makeKey = async () => {
    try { setKey((await api.createKey('source')).key) } catch (e) { toast(e.message, 'bad') }
  }
  const curl = `curl -X POST ${location.origin}/api/ingest -H "X-API-Key: ${key}" -H "Content-Type: application/json" \\
  -d '{"format":"${fmt}","lines":["<one log line>"]}'`
  return (
    <div>
      <h3 className="first">Add log data</h3>
      <select value={fmt} onChange={(e) => setFmt(e.target.value)} aria-label="Log format">
        <option value="linux_auth">Linux auth (syslog)</option>
        <option value="web_access">Web access (combined)</option>
        <option value="snort_alert">IDS alert (Snort format)</option>
      </select>
      <input type="file" onChange={file} aria-label="Log file" />
      <textarea rows={5} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste log lines" />
      <div className="actions">
        <button className="primary" onClick={send} disabled={!text}>Import Logs</button>
      </div>
      <h3>Send from your own system</h3>
      <button onClick={makeKey}>Create API Key</button>
      {key && <pre className="runbook">{curl}</pre>}
      {key && desktop && (
        <p className="muted small">The desktop engine listens on this machine only, on a port that changes at each launch.</p>
      )}
    </div>
  )
}

export function Empty({ canPlay, onPlay, go }) {
  return (
    <div className="empty">
      <div className="empty-mark"><Icon name="graph" size={28} /></div>
      <h2>Nothing to analyse yet</h2>
      <p className="muted">Scan a repository or add log data, and the attack paths appear here.</p>
      <div className="actions center">
        <button className="primary" onClick={() => go('repo')}>Scan a Repository</button>
        <button onClick={() => go('ingest')}>Add Log Data</button>
        {canPlay && <button onClick={onPlay}>Play Sample Scenario</button>}
      </div>
    </div>
  )
}
