import { useEffect, useState } from 'react'
import { api } from './api.js'

const SRC_COLOR = { linux_auth: '#38bdf8', web_access: '#a78bfa', ids_alert: '#f59e0b', json: '#94a3b8' }
const fmtTime = (ts) => (ts || '').replace('T', ' ').replace('Z', '').slice(11, 16)

function Timeline({ data }) {
  const W = 640, H = 150, P = 28
  const rows = data.buckets
  if (!rows.length) return <p className="muted">No events yet. Press Play or ingest logs.</p>
  const max = Math.max(...rows.map((r) => r.total), 1)
  const bw = (W - P * 2) / Math.max(rows.length, 1)
  const sources = [...new Set(rows.flatMap((r) => Object.keys(r.by_source)))]
  const lo = Date.parse(data.range[0]), hi = Date.parse(data.range[1])
  const xOf = (ts) => P + ((Date.parse(ts) - lo) / Math.max(1, hi - lo)) * (W - P * 2)
  return (
    <svg viewBox={`0 0 ${W} ${H + 24}`} className="chart" role="img" aria-label="Events over time">
      {rows.map((r, i) => {
        let y = H - 6
        return Object.entries(r.by_source).map(([s, c]) => {
          const h = (c / max) * (H - 30)
          y -= h
          return <rect key={`${i}${s}`} x={P + r.index * bw + 1} y={y} width={Math.max(1, bw - 2)} height={h}
                       fill={SRC_COLOR[s] || '#64748b'}><title>{`${s}: ${c}`}</title></rect>
        })
      })}
      {data.confirmed.map((c) => (
        <g key={c.edge}>
          <line x1={xOf(c.first_seen)} x2={xOf(c.first_seen)} y1={6} y2={H - 6} stroke="#ef4444" strokeDasharray="3 3" />
          <circle cx={xOf(c.first_seen)} cy={8} r={4} fill="#ef4444"><title>{`${c.technique} ${c.src} → ${c.dst}`}</title></circle>
        </g>
      ))}
      <line x1={P} x2={W - P} y1={H - 5} y2={H - 5} stroke="currentColor" opacity=".3" />
      <text x={P} y={H + 14} fontSize="10" fill="currentColor">{fmtTime(data.range[0])}</text>
      <text x={W - P} y={H + 14} fontSize="10" textAnchor="end" fill="currentColor">{fmtTime(data.range[1])}</text>
      {sources.map((s, i) => (
        <g key={s}><rect x={P + i * 110} y={H + 4} width="8" height="8" fill={SRC_COLOR[s] || '#64748b'} />
          <text x={P + i * 110 + 12} y={H + 12} fontSize="10" fill="currentColor">{s}</text></g>
      ))}
    </svg>
  )
}

function RiskLine({ series }) {
  const W = 640, H = 130, P = 30
  if (series.length < 2) return <p className="muted">Needs at least two checkpoints.</p>
  const max = Math.max(...series.map((s) => s.risk), 0.05)
  const pts = series.map((s, i) => [P + (i / (series.length - 1)) * (W - P * 2), H - 18 - (s.risk / max) * (H - 36), s])
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Risk over time">
      <polyline fill="none" stroke="#ef4444" strokeWidth="2" points={pts.map((p) => `${p[0]},${p[1]}`).join(' ')} />
      {pts.map((p, i) => (
        <circle key={i} cx={p[0]} cy={p[1]} r="3" fill="#ef4444">
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
  const [b, setB] = useState(null)
  useEffect(() => {
    api.timeline().then(setT).catch(() => {})
    api.metrics().then(setM).catch(() => {})
    api.benchmarks().then(setB).catch(() => {})
  }, [])
  const done = rems.filter((r) => r.risk_before != null)
  return (
    <div className="insights">
      <section className="card">
        <h3>Alert compression</h3>
        {m && (
          <div className="stats">
            <div><b>{m.compression.raw_events}</b><span>raw events</span></div>
            <div><b>{m.compression.confirmed_steps}</b><span>confirmed attack steps</span></div>
            <div><b>{m.compression.ranked_paths}</b><span>ranked paths</span></div>
            <div><b>{m.compression.critical_or_high}</b><span>critical / high</span></div>
          </div>
        )}
        <p className="muted">What the analyst reads shrinks from events to a short ranked list.</p>
      </section>
      <section className="card">
        <h3>Attack timeline</h3>
        {t && <Timeline data={t} />}
        <p className="muted">Bars: events per interval by source. Red markers: first time an attack step was confirmed.</p>
        {t && t.confirmed.length > 0 && (
          <Table cols={[['first_seen', 'first seen'], ['technique', 'technique'], ['src', 'from'], ['dst', 'to'], ['p', 'p']]}
                 rows={t.confirmed.map((c) => ({ ...c, first_seen: fmtTime(c.first_seen) }))} />
        )}
      </section>
      <section className="card">
        <h3>Risk as evidence accumulates</h3>
        {t && <RiskLine series={t.risk_series} />}
      </section>
      <section className="card">
        <h3>Before / after fixes</h3>
        {done.length === 0 ? <p className="muted">Execute a remediation to see risk before and after.</p> : (
          <Table cols={[['id', '#'], ['title', 'fix'], ['risk_before', 'risk before'], ['risk_after', 'risk after'],
                        ['state', 'state']]} rows={done} />
        )}
      </section>
      <section className="card">
        <h3>Live pipeline timings</h3>
        {m && (
          <>
            <Table cols={[['k', 'stage'], ['v', 'ms']]}
                   rows={Object.entries(m.current_analysis_ms).filter(([k]) => k.endsWith('_ms')).map(([k, v]) => ({ k, v }))} />
            <p className="muted">Ingest: {m.ingest_events_per_sec} events/s · p50 {m.ingest_ms_per_event_p50} ms/event ·
              p95 {m.ingest_ms_per_event_p95} ms/event ({m.events_ingested} events this process)</p>
          </>
        )}
      </section>
      <section className="card">
        <h3>Benchmarks (generated by scripts/benchmark.py)</h3>
        {b && b.runs.length > 0 ? (
          <>
            <Table cols={[['events', 'events'], ['parse_eps', 'parse /s'], ['ingest_eps', 'ingest /s'],
                          ['correlate_ms', 'correlate ms'], ['paths_ms', 'paths ms'], ['end_to_end_ms', 'end-to-end ms'],
                          ['end_to_end_eps', 'end-to-end /s']]} rows={b.runs} />
            {b.graph_scale && (
              <Table cols={[['nodes', 'nodes'], ['edges', 'edges'], ['top10_paths_ms', 'top-10 paths ms'],
                            ['min_cut_ms', 'min cut ms']]} rows={b.graph_scale} />
            )}
            <p className="muted">{b.meta.system} {b.meta.machine}, {b.meta.cpus} CPUs, Python {b.meta.python}.
              Synthetic seeded load, in-process (no network).</p>
          </>
        ) : <p className="muted">Run scripts/benchmark.py to generate results.</p>}
      </section>
    </div>
  )
}
