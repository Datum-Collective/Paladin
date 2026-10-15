import { useEffect, useState } from 'react'
import { api } from './api.js'
import { Skeleton } from './ui.jsx'

const SRC_COLOR = { linux_auth: 'var(--info)', web_access: 'var(--text-2)', ids_alert: 'var(--warn)', json: 'var(--bg-3)' }
const fmtTime = (ts) => (ts || '').replace('T', ' ').replace('Z', '').slice(11, 16)

function Timeline({ data }) {
  const W = 640, H = 150, P = 28, NB = 24
  const rows = data.buckets
  if (!rows.length) return <p className="muted">No events yet.</p>
  const max = Math.max(...rows.map((r) => r.total), 1)
  const bw = (W - P * 2) / NB            // width of one time bucket, not of one non-empty bucket
  const sources = [...new Set(rows.flatMap((r) => Object.keys(r.by_source)))]
  const lo = Date.parse(data.range[0]), hi = Date.parse(data.range[1])
  const xOf = (ts) => P + ((Date.parse(ts) - lo) / Math.max(1, hi - lo)) * (W - P * 2)
  return (
    <svg viewBox={`0 0 ${W} ${H + 40}`} className="chart" role="img" aria-label="Events over time">
      {rows.map((r, i) => {
        let y = H - 6
        return Object.entries(r.by_source).map(([s, c]) => {
          const h = (c / max) * (H - 30)
          y -= h
          return <rect key={`${i}${s}`} x={P + r.index * bw + 1} y={y} width={Math.max(1, bw - 2)} height={h} rx={Math.min(3, Math.max(1, bw - 2) / 2)}
                       style={{ fill: SRC_COLOR[s] || 'var(--text-2)' }}><title>{`${s}: ${c}`}</title></rect>
        })
      })}
      {data.confirmed.map((c) => (
        <g key={c.edge}>
          <line x1={xOf(c.first_seen)} x2={xOf(c.first_seen)} y1={6} y2={H - 6} style={{ stroke: 'var(--bad)' }} strokeDasharray="3 3" />
          <circle cx={xOf(c.first_seen)} cy={8} r={4} style={{ fill: 'var(--bad)' }}><title>{`${c.technique} ${c.src} → ${c.dst}`}</title></circle>
        </g>
      ))}
      <line x1={P} x2={W - P} y1={H - 5} y2={H - 5} stroke="currentColor" opacity=".3" />
      <text x={P} y={H + 14} fontSize="10" fill="currentColor">{fmtTime(data.range[0])}</text>
      <text x={W - P} y={H + 14} fontSize="10" textAnchor="end" fill="currentColor">{fmtTime(data.range[1])}</text>
      {sources.map((s, i) => (
        <g key={s}><rect x={P + i * 120} y={H + 26} width="8" height="8" rx="2" style={{ fill: SRC_COLOR[s] || 'var(--text-2)' }} />
          <text x={P + i * 120 + 12} y={H + 34} fontSize="10" fill="currentColor">{s}</text></g>
      ))}
    </svg>
  )
}

/** Horizontal bars of how often each label occurs. Labels are plain text so nothing depends on colour alone. */
function CountBars({ rows, label }) {
  if (!rows.length) return <p className="muted">Nothing to show.</p>
  const W = 640, ROW = 26, L = 220, R = 40
  const max = Math.max(...rows.map((r) => r[1]), 1)
  return (
    <svg viewBox={`0 0 ${W} ${rows.length * ROW + 6}`} className="chart" role="img" aria-label={label}>
      {rows.map(([name, n], i) => {
        const w = Math.max(4, (n / max) * (W - L - R))
        return (
          <g key={name} transform={`translate(0 ${i * ROW + 3})`}>
            <text x={L - 10} y={ROW / 2 + 3} fontSize="12" textAnchor="end" fill="currentColor">{name.length > 30 ? `${name.slice(0, 29)}…` : name}</text>
            <rect x={L} y={4} width={w} height={ROW - 10} rx={(ROW - 10) / 2} style={{ fill: 'var(--accent)' }} />
            <text x={L + w + 8} y={ROW / 2 + 3} fontSize="12" fill="currentColor">{n}</text>
          </g>
        )
      })}
    </svg>
  )
}

const tally = (items, key) => Object.entries(items.reduce((a, f) => ({ ...a, [f[key]]: (a[f[key]] || 0) + 1 }), {}))
  .sort((a, b) => b[1] - a[1]).slice(0, 8)

function RiskLine({ series, unit = 'events ingested →' }) {
  const W = 640, H = 130, P = 30
  if (series.length < 2) return <p className="muted">Needs at least two checkpoints of events.</p>
  const max = Math.max(1, ...series.map((s) => s.risk))
  const pts = series.map((s, i) => [P + (i / (series.length - 1)) * (W - P * 2), H - 18 - (s.risk / max) * (H - 36), s])
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Risk over time">
      <polyline fill="none" style={{ stroke: 'var(--bad)' }} strokeWidth="2" points={pts.map((p) => `${p[0]},${p[1]}`).join(' ')} />
      {pts.map((p, i) => (
        <circle key={i} cx={p[0]} cy={p[1]} r="3" style={{ fill: 'var(--bad)' }}>
          <title>{`${p[2].events ? `${p[2].events} events: ` : ''}risk ${p[2].risk}, ${p[2].paths} paths`}</title></circle>
      ))}
      <text x={4} y={14} fontSize="10" fill="currentColor">{max.toFixed(2)}</text>
      <text x={4} y={H - 18} fontSize="10" fill="currentColor">0</text>
      <text x={W / 2} y={H - 2} fontSize="10" textAnchor="middle" fill="currentColor">{unit}</text>
    </svg>
  )
}

function Table({ cols, rows }) {
  return (
    <table className="tbl">
      <thead><tr>{cols.map((c) => <th key={c[0]}>{c[1]}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i}>{cols.map((c) => <td key={c[0]}>{r[c[0]] ?? '-'}</td>)}</tr>)}</tbody>
    </table>
  )
}

const SEV_ORDER = ['critical', 'high', 'medium', 'low']

/** What each remediation did to risk. Code remediations are the only source of a before/after for a repository. */
function remediationSeries(rems) {
  const done = rems.filter((r) => r.risk_before != null && ['verified', 'executed'].includes(r.state)).sort((x, y) => x.id - y.id)
  if (!done.length) return []
  return [{ events: 0, risk: done[0].risk_before, paths: done[0].paths_before }, ...done.map((r) => ({ events: 0, risk: r.risk_after, paths: r.paths_after }))]
}

export default function Insights({ rems }) {
  const [t, setT] = useState(null)
  const [m, setM] = useState(null)
  const [code, setCode] = useState(null)
  const [err, setErr] = useState('')
  const load = () => {
    setErr('')
    Promise.all([api.timeline().then(setT), api.metrics().then(setM), api.codeReport().then(setCode)])
      .catch((e) => setErr(e.message || 'Could not load insights.'))
  }
  useEffect(load, [rems.length, rems.map((r) => r.state).join()])    // eslint-disable-line react-hooks/exhaustive-deps
  if (err) return <div className="insights"><div className="inline-error" role="alert"><span>{err}</span><button onClick={load}>Try Again</button></div></div>
  if (!m || !t || !code) return <div className="insights"><Skeleton lines={5} /></div>
  const findings = code.scanned ? code.findings : []
  const open = findings.filter((f) => !f.fixed && f.exploitable !== false)
  const hasEvents = m.compression.raw_events > 0
  const done = rems.filter((r) => r.risk_before != null)
  const series = hasEvents && t.risk_series.length >= 2 ? t.risk_series : remediationSeries(rems)
  const sev = SEV_ORDER.map((s) => [s[0].toUpperCase() + s.slice(1), open.filter((f) => (f.severity || 'medium') === s).length]).filter((x) => x[1] > 0)
  const status = [['Confirmed', open.filter((f) => f.status === 'confirmed').length],
    ['Potential', open.filter((f) => f.status !== 'confirmed').length],
    ['Fixed', findings.filter((f) => f.fixed).length],
    ['Judged not exploitable', findings.filter((f) => f.exploitable === false).length]].filter((x) => x[1] > 0)
  const nothing = !hasEvents && !findings.length && !m.compression.ranked_paths
  return (
    <div className="insights">
      <section className="card">
        <h3>From {findings.length && !hasEvents ? 'findings' : 'events'} to action</h3>
        <div className="stats">
          {hasEvents ? (
            <>
              <div><b>{m.compression.raw_events}</b><span>security events</span></div>
              <div><b>{m.compression.confirmed_steps}</b><span>confirmed attack steps</span></div>
            </>
          ) : (
            <>
              <div><b>{open.length}</b><span>open findings</span></div>
              <div><b>{findings.filter((f) => f.fixed).length}</b><span>fixed</span></div>
            </>
          )}
          <div><b>{m.compression.ranked_paths}</b><span>ranked paths</span></div>
          <div><b>{m.compression.critical_or_high}</b><span>critical / high</span></div>
        </div>
        {nothing && <p className="muted">Nothing analysed yet. Paste a repository on Home, or import logs under Analysis, and the results appear here.</p>}
      </section>

      {findings.length > 0 && (
        <section className="card wide-card">
          <h3>Repository findings · {code.repo}</h3>
          <div className="stats">
            <div><b>{findings.length}</b><span>findings</span></div>
            <div><b>{open.filter((f) => f.status === 'confirmed').length}</b><span>confirmed</span></div>
            <div><b>{findings.filter((f) => f.fixed).length}</b><span>fixed</span></div>
            <div><b>{code.files}</b><span>files scanned</span></div>
          </div>
          <div className="two-col">
            <div><h4>By severity (open)</h4><CountBars rows={sev} label="Open findings by severity" /></div>
            <div><h4>By status</h4><CountBars rows={status} label="Findings by status" /></div>
            <div><h4>By rule</h4><CountBars rows={tally(open, 'title')} label="Open findings by rule" /></div>
            <div><h4>By file</h4><CountBars rows={tally(open, 'file')} label="Open findings by file" /></div>
          </div>
        </section>
      )}

      {hasEvents ? (
        <section className="card">
          <h3>Attack timeline</h3>
          <Timeline data={t} />
          <p className="muted">Bars: events by source over time. Red markers: when an attack step was first confirmed.</p>
          {t.confirmed.length > 0 && (
            <Table cols={[['first_seen', 'first seen'], ['technique', 'technique'], ['src', 'from'], ['dst', 'to'], ['p', 'p']]}
                   rows={t.confirmed.map((c) => ({ ...c, first_seen: fmtTime(c.first_seen) }))} />
          )}
        </section>
      ) : findings.length > 0 && (
        <section className="card">
          <h3>Log data</h3>
          <p className="muted">This workspace has no log events, so there is no attack timeline. Import logs under Analysis → Import to see when
            attack steps were first observed.</p>
        </section>
      )}

      <section className="card">
        <h3>Risk over time</h3>
        {series.length >= 2 ? <RiskLine series={series} unit={hasEvents && t.risk_series.length >= 2 ? 'events ingested →' : 'after each verified fix →'} />
          : <p className="muted">{hasEvents ? 'Needs at least two checkpoints of events.'
            : 'Verify an applied fix and the risk before and after it is plotted here.'}</p>}
      </section>

      <section className="card">
        <h3>Before and after remediation</h3>
        {done.length === 0 ? <p className="muted">Apply a fix, then verify it: risk and dangerous paths before and after appear here.</p> : (
          <Table cols={[['id', '#'], ['title', 'fix'], ['risk_before', 'risk before'], ['risk_after', 'risk after'],
                        ['paths_before', 'paths before'], ['paths_after', 'paths after'], ['state', 'state']]}
                 rows={done.map((r) => ({ ...r, state: (r.state || '').replace('_', ' ') }))} />
        )}
      </section>
    </div>
  )
}
