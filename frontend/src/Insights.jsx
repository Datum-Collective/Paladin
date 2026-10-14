import { useEffect, useState } from 'react'
import { api } from './api.js'

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
          return <rect key={`${i}${s}`} x={P + r.index * bw + 1} y={y} width={Math.max(1, bw - 2)} height={h}
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

function RiskLine({ series }) {
  const W = 640, H = 130, P = 30
  if (series.length < 2) return <p className="muted">Needs at least two checkpoints of events.</p>
  const max = Math.max(1, ...series.map((s) => s.risk))
  const pts = series.map((s, i) => [P + (i / (series.length - 1)) * (W - P * 2), H - 18 - (s.risk / max) * (H - 36), s])
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Risk over time">
      <polyline fill="none" style={{ stroke: 'var(--bad)' }} strokeWidth="2" points={pts.map((p) => `${p[0]},${p[1]}`).join(' ')} />
      {pts.map((p, i) => (
        <circle key={i} cx={p[0]} cy={p[1]} r="3" style={{ fill: 'var(--bad)' }}>
          <title>{`${p[2].events} events: risk ${p[2].risk}, ${p[2].paths} paths`}</title></circle>
      ))}
      <text x={4} y={14} fontSize="10" fill="currentColor">{max.toFixed(2)}</text>
      <text x={4} y={H - 18} fontSize="10" fill="currentColor">0</text>
      <text x={W / 2} y={H - 2} fontSize="10" textAnchor="middle" fill="currentColor">events ingested →</text>
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

export default function Insights({ rems }) {
  const [t, setT] = useState(null)
  const [m, setM] = useState(null)
  useEffect(() => {
    api.timeline().then(setT).catch(() => {})
    api.metrics().then(setM).catch(() => {})
  }, [])
  const done = rems.filter((r) => r.risk_before != null)
  return (
    <div className="insights">
      <section className="card">
        <h3>From events to action</h3>
        {m && (
          <div className="stats">
            <div><b>{m.compression.raw_events}</b><span>security events</span></div>
            <div><b>{m.compression.confirmed_steps}</b><span>confirmed attack steps</span></div>
            <div><b>{m.compression.ranked_paths}</b><span>ranked paths</span></div>
            <div><b>{m.compression.critical_or_high}</b><span>critical / high</span></div>
          </div>
        )}
      </section>
      <section className="card">
        <h3>Attack timeline</h3>
        {t && <Timeline data={t} />}
        <p className="muted">Bars: events by source over time. Red markers: when an attack step was first confirmed.</p>
        {t && t.confirmed.length > 0 && (
          <Table cols={[['first_seen', 'first seen'], ['technique', 'technique'], ['src', 'from'], ['dst', 'to'], ['p', 'p']]}
                 rows={t.confirmed.map((c) => ({ ...c, first_seen: fmtTime(c.first_seen) }))} />
        )}
      </section>
      <section className="card">
        <h3>Risk over time</h3>
        {t && <RiskLine series={t.risk_series} />}
      </section>
      <section className="card">
        <h3>Before and after remediation</h3>
        {done.length === 0 ? <p className="muted">Execute a remediation to compare risk and paths.</p> : (
          <Table cols={[['id', '#'], ['title', 'fix'], ['risk_before', 'risk before'], ['risk_after', 'risk after'],
                        ['paths_before', 'paths before'], ['paths_after', 'paths after'], ['state', 'state']]} rows={done} />
        )}
      </section>
    </div>
  )
}
