import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import { hhmm, pathLabels } from './lib.js'
import { KIND_LABEL } from './kinds.js'
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

const BASIS = { finding: ['Backed by a finding in the code', 'ok'], reference: ['Import at a real line', 'ok'], assumed: ['Assumed, not verified', 'warn'],
  '': ['Prior only, no events yet', 'mute'] }

/** Inspector body for a clicked node or edge: what it is, where it is in the code, and how well supported it is. */
export function ElementDetail({ el, graph, onClear }) {
  if (!el || !graph) return null
  const node = el.type === 'node' ? graph.nodes.find((n) => n.id === el.id) : null
  const edge = el.type === 'edge' ? graph.edges.find((e) => e.id === el.id) : null
  const label = (id) => pathLabels([id], graph.nodes)[0]
  if (!node && !edge) return null
  return (
    <section className="detail" aria-label={node ? 'Selected node' : 'Selected step'}>
      <div className="row-top"><h3 className="first">{node ? KIND_LABEL[node.kind] || node.kind : 'Attack step'}</h3>
        <button className="tool" onClick={onClear} aria-label="Clear selection"><Icon name="x" size={12} /></button></div>
      {node && (
        <>
          <p><b>{node.label}</b></p>
          <dl className="kv wide">
            {node.meta && node.meta.file && <><dt>Location</dt><dd className="mono">{node.meta.file}{node.meta.line ? `:${node.meta.line}` : ''}</dd></>}
            {node.meta && node.meta.cwe && <><dt>Weakness</dt><dd>{node.meta.cwe} · {node.meta.rule}</dd></>}
            {node.meta && node.meta.confidence !== undefined && <><dt>Confidence</dt><dd>{Math.round(node.meta.confidence * 100)}%</dd></>}
            {node.meta && node.meta.severity && <><dt>Severity</dt><dd>{node.meta.severity}</dd></>}
            {node.meta && node.meta.confirmed !== undefined && <><dt>Status</dt><dd>{node.meta.confirmed ? 'Confirmed: the quoted code shows input reaching it' : 'Potential: a match without a proven data flow'}</dd></>}
            {node.meta && node.meta.routed !== undefined && node.kind === 'component' && <><dt>Route handler</dt><dd>{node.meta.routed ? 'Found in this file' : 'None found'}</dd></>}
            <dt>Criticality</dt><dd>{node.criticality} of 10</dd>
          </dl>
          {node.meta && node.meta.snippet && <code className="snippet">{node.meta.snippet}</code>}
          {node.meta && node.meta.reason && <p className="muted">{node.meta.reason}</p>}
          {node.meta && node.meta.impact && <p><b>Impact</b> {node.meta.impact}</p>}
          {node.meta && node.meta.evidence && node.meta.evidence.length > 0 && (
            <ul className="plain small">{node.meta.evidence.map((e, i) => <li key={i}><span className="mono">{e.file}:{e.line}</span> <code>{e.quote}</code></li>)}</ul>
          )}
          {node.meta && node.meta.advisories && node.meta.advisories.length > 0 && <p className="muted small">Advisories: {node.meta.advisories.join(', ')}</p>}
          {node.meta && node.meta.assumed && <p className="muted small">This target is assumed from the weakness category; it was not located in the code.</p>}
        </>
      )}
      {edge && (
        <>
          <p><b>{label(edge.src)}</b> <span className="muted">to</span> <b>{label(edge.dst)}</b></p>
          <dl className="kv wide">
            <dt>Technique</dt><dd>{edge.technique}</dd>
            <dt>Likelihood</dt><dd>{Math.round(edge.p * 100)}%</dd>
            <dt>Support</dt><dd>{edge.observed ? <span className="pill ok">Confirmed by events</span>
              : <span className={`pill ${BASIS[edge.basis || ''][1]}`}>{BASIS[edge.basis || ''][0]}</span>}</dd>
          </dl>
          {edge.note && <p className="muted">{edge.note}</p>}
          {edge.evidence && edge.evidence.length > 0 && <p className="muted small mono">Events {edge.evidence.slice(0, 5).join(', ')}</p>}
        </>
      )}
    </section>
  )
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
  const name = (id) => pathLabels([id], path.assets)[0]
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
            <div><b>{name(h.src)}</b> <span className="muted">to</span> <b>{name(h.dst)}</b></div>
            <div className="muted">
              {h.technique} {h.technique_name} · p {h.p} · {h.observed ? 'confirmed by events'
                : h.basis === 'finding' ? 'backed by a code finding' : h.basis === 'reference' ? 'import at a real line' : h.basis === 'assumed' ? 'assumed, not verified' : 'possible, no events yet'}
            </div>
            {h.note && <div className="muted small">{h.note}</div>}
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
  const [keys, setKeys] = useState([])
  const [label, setLabel] = useState('')
  const loadKeys = useCallback(() => api.keys().then((r) => setKeys(r.keys)).catch(() => {}), [])
  useEffect(() => { loadKeys() }, [loadKeys])
  const makeKey = async () => {
    try { setKey((await api.createKey(label.trim() || 'source')).key); setLabel(''); loadKeys() } catch (e) { toast(e.message, 'bad') }
  }
  const revoke = async (id) => {
    try { await api.revokeKey(id); toast('Key revoked', 'ok'); loadKeys() } catch (e) { toast(e.message, 'bad') }
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
      <div className="actions">
        <input value={label} maxLength={64} onChange={(e) => setLabel(e.target.value)} placeholder="Key name, e.g. web-01 syslog"
               aria-label="API key name" />
        <button onClick={makeKey}>Create API Key</button>
      </div>
      {key && <p className="muted small">Copy this key now. It is shown only once; Paladin stores only a hash of it.</p>}
      {key && <pre className="runbook">{curl}</pre>}
      {keys.length > 0 && (
        <ul className="keylist">
          {keys.map((k) => (
            <li key={k.id}>
              <code>{k.key_prefix}…</code> <span>{k.label}</span>{' '}
              {k.revoked_at ? <span className="muted small">revoked</span>
                : <button className="link" onClick={() => revoke(k.id)} aria-label={`Revoke ${k.label}`}>Revoke</button>}
            </li>
          ))}
        </ul>
      )}
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
