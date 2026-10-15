import { useEffect, useMemo, useState } from 'react'
import { MitreCode } from './Mitre.jsx'
import { api } from './api.js'

const CATEGORY_COLORS = ['var(--accent)', 'var(--info)', 'var(--ok)', 'var(--text-2)', 'var(--line-strong)', 'var(--accent)']
const CATEGORY_BY_RULE = {
  'hardcoded-secret': 'Secrets exposure', 'code-exec': 'Unsafe execution', 'shell-injection': 'Unsafe execution',
  'unsafe-deserialize': 'Unsafe execution', 'sql-concat': 'Input validation', 'xss-sink': 'Input validation',
  'tls-off': 'Configuration', 'weak-hash': 'Configuration', 'permissive-cors': 'Configuration', 'debug-on': 'Configuration',
  'blank-noopener': 'Client security', 'http-script-src': 'Client security',
}
const titleCase = (value) => String(value || '').replace(/[-_]/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
const fmtTime = (ts) => (ts || '').replace('T', ' ').replace('Z', '').slice(11, 16)
const DEMO = {
  findings: [
    { id: 'demo-1', rule: 'hardcoded-secret', file: 'src/config.ts', title: 'Hard-coded credential', technique: 'T1552.001', status: 'confirmed' },
    { id: 'demo-2', rule: 'hardcoded-secret', file: 'src/config.ts', title: 'Hard-coded credential', technique: 'T1552.001', status: 'potential' },
    { id: 'demo-3', rule: 'sql-concat', file: 'src/routes/users.ts', title: 'SQL built from strings', technique: 'T1190', status: 'confirmed' },
    { id: 'demo-4', rule: 'sql-concat', file: 'src/routes/orders.ts', title: 'SQL built from strings', technique: 'T1190', status: 'potential' },
    { id: 'demo-5', rule: 'permissive-cors', file: 'src/server.ts', title: 'CORS allows every origin', technique: 'T1190', status: 'potential' },
    { id: 'demo-6', rule: 'xss-sink', file: 'src/ui/notice.tsx', title: 'Unescaped HTML sink', technique: 'T1189', status: 'potential' },
    { id: 'demo-7', rule: 'weak-hash', file: 'src/auth/passwords.ts', title: 'Weak hash', technique: 'T1110', status: 'confirmed' },
  ],
  graph: { nodes: [
    { id: 'code:config', kind: 'component', label: 'src/config.ts' }, { id: 'code:users', kind: 'component', label: 'src/routes/users.ts' },
    { id: 'code:orders', kind: 'component', label: 'src/routes/orders.ts' }, { id: 'code:server', kind: 'component', label: 'src/server.ts' },
  ] },
  paths: [
    { nodes: ['code:config'], risk: 0.84 }, { nodes: ['code:config'], risk: 0.62 }, { nodes: ['code:users'], risk: 0.59 },
    { nodes: ['code:users'], risk: 0.43 }, { nodes: ['code:orders'], risk: 0.36 }, { nodes: ['code:server'], risk: 0.28 },
  ],
  rems: [
    { state: 'verified', risk_before: 1.12, risk_after: 0.48 }, { state: 'verified', risk_before: 0.72, risk_after: 0.34 },
    { state: 'executed', risk_before: 0.51, risk_after: 0.29 }, { state: 'approved' }, { state: 'proposed' },
  ],
  timeline: { risk_series: [
    { ts: '2026-10-11T09:00:00Z', events: 12, risk: 0.38, paths: 2 }, { ts: '2026-10-12T09:00:00Z', events: 28, risk: 0.66, paths: 4 },
    { ts: '2026-10-13T09:00:00Z', events: 47, risk: 0.91, paths: 5 }, { ts: '2026-10-14T09:00:00Z', events: 64, risk: 0.57, paths: 3 },
  ] },
}

/** Scanner rule ids are the source of category labels; unfamiliar rules remain visible as Other. */
export function findingCategory(finding) {
  if (CATEGORY_BY_RULE[finding.rule]) return CATEGORY_BY_RULE[finding.rule]
  if (String(finding.rule || '').startsWith('ai-')) return titleCase(String(finding.rule).slice(3))
  return 'Other'
}

export function categoryDistribution(findings = []) {
  const groups = new Map()
  findings.forEach((finding) => {
    const category = findingCategory(finding)
    const row = groups.get(category) || { category, count: 0, findings: [], files: new Set(), rules: new Set() }
    row.count += 1; row.findings.push(finding)
    if (finding.file) row.files.add(finding.file)
    if (finding.title) row.rules.add(finding.title)
    groups.set(category, row)
  })
  return [...groups.values()].sort((a, b) => b.count - a.count || a.category.localeCompare(b.category))
}

export function componentRisk(graph, paths = []) {
  if (!graph) return []
  const components = new Map(graph.nodes.filter((node) => node.kind === 'component').map((node) => [node.id, node]))
  const scores = new Map()
  paths.forEach((path) => {
    new Set(path.nodes || []).forEach((id) => {
      if (!components.has(id)) return
      const row = scores.get(id) || { id, label: components.get(id).label, risk: 0, paths: 0 }
      row.risk += Number(path.risk) || 0; row.paths += 1; scores.set(id, row)
    })
  })
  return [...scores.values()].sort((a, b) => b.risk - a.risk || b.paths - a.paths).slice(0, 6)
}

export function mitreMappings(findings = []) {
  const groups = new Map()
  findings.forEach((finding) => {
    if (!finding.technique) return
    const technique = String(finding.technique)
    const row = groups.get(technique) || { technique, count: 0, confirmed: 0, files: new Set() }
    row.count += 1; if (finding.status === 'confirmed') row.confirmed += 1
    if (finding.file) row.files.add(finding.file)
    groups.set(technique, row)
  })
  return [...groups.values()].sort((a, b) => b.count - a.count || a.technique.localeCompare(b.technique))
}

export function remediationOutcome(rems = []) {
  const states = ['verified', 'executed', 'approved', 'proposed', 'failed', 'rolled_back']
  const rows = states.map((state) => ({ state, count: rems.filter((remediation) => remediation.state === state).length })).filter((row) => row.count)
  const direct = rems.filter((remediation) => remediation.state === 'verified' && remediation.risk_before != null && remediation.risk_after != null)
  return { rows, verified: direct.length, directRiskChange: direct.reduce((sum, remediation) => sum + (remediation.risk_before - remediation.risk_after), 0) }
}

function Donut({ rows, selected, onSelect, ariaLabel, totalLabel = 'findings' }) {
  const total = rows.reduce((sum, row) => sum + row.count, 0)
  if (!total) return <p className="muted">No data is available for this chart yet.</p>
  const radius = 48, circumference = 2 * Math.PI * radius
  let offset = 0
  return <div className="analytics-donut-wrap"><svg className="analytics-donut" viewBox="0 0 140 140" role="img" aria-label={ariaLabel}>
    <circle cx="70" cy="70" r={radius} fill="none" stroke="var(--bg-3)" strokeWidth="20" />
    {rows.map((row, index) => {
      const length = row.count / total * circumference
      const element = <circle key={row.category || row.state} cx="70" cy="70" r={radius} fill="none" stroke={CATEGORY_COLORS[index % CATEGORY_COLORS.length]} strokeWidth="20"
        strokeDasharray={`${length} ${circumference - length}`} strokeDashoffset={-offset} transform="rotate(-90 70 70)" className={selected && selected !== (row.category || row.state) ? 'dim' : ''}
        onClick={() => onSelect(selected === (row.category || row.state) ? null : (row.category || row.state))}><title>{`${row.category || titleCase(row.state)}: ${row.count}`}</title></circle>
      offset += length
      return element
    })}
    <text x="70" y="67" textAnchor="middle" className="donut-number">{total}</text><text x="70" y="82" textAnchor="middle" className="donut-label">{totalLabel}</text>
  </svg><div className="analytics-legend">{rows.map((row, index) => <button type="button" key={row.category || row.state} className={selected === (row.category || row.state) ? 'active' : ''} onClick={() => onSelect(selected === (row.category || row.state) ? null : (row.category || row.state))}><i style={{ background: CATEGORY_COLORS[index % CATEGORY_COLORS.length] }} /><span>{row.category || titleCase(row.state)}</span><b>{row.count}</b></button>)}</div></div>
}

function HorizontalBars({ rows, selected, onSelect, label, value = (row) => row.count }) {
  if (!rows.length) return <p className="muted">No data is available for this chart yet.</p>
  const max = Math.max(...rows.map(value), 1)
  return <div className="analytics-bars" aria-label={label}>{rows.map((row) => <button type="button" key={row.id || row.technique} className={selected === (row.id || row.technique) ? 'active' : ''} onClick={() => onSelect(selected === (row.id || row.technique) ? null : (row.id || row.technique))}>
    <span className="analytics-bar-label">{row.label || row.technique}</span><span className="analytics-bar-track"><i style={{ width: `${value(row) / max * 100}%` }} /></span><b>{Number.isInteger(value(row)) ? value(row) : value(row).toFixed(2)}</b>
  </button>)}</div>
}

function RiskLine({ series = [] }) {
  const W = 640, H = 130, P = 30
  if (series.length < 2) return <p className="muted">More than one event checkpoint is needed to show exposure movement.</p>
  const max = Math.max(1, ...series.map((point) => point.risk))
  const points = series.map((point, index) => [P + index / (series.length - 1) * (W - P * 2), H - 18 - point.risk / max * (H - 36), point])
  return <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Exposure across event checkpoints"><polyline fill="none" stroke="var(--accent)" strokeWidth="2" points={points.map((point) => `${point[0]},${point[1]}`).join(' ')} />
    {points.map((point, index) => <circle key={index} cx={point[0]} cy={point[1]} r="3" fill="var(--accent)"><title>{`${point[2].events} events: risk ${point[2].risk}, ${point[2].paths} paths`}</title></circle>)}
    <text x={P} y={H - 2} fontSize="10" fill="currentColor">{fmtTime(points[0][2].ts)}</text><text x={W - P} y={H - 2} fontSize="10" textAnchor="end" fill="currentColor">{fmtTime(points.at(-1)[2].ts)}</text>
  </svg>
}

function Insight({ title, explanation, action, children, wide = false }) {
  return <section className={`card analytics-card${wide ? ' wide-card' : ''}`}><h3>{title}</h3><p className="muted">{explanation}</p>{children}<p className="analytics-action"><b>Next:</b> {action}</p></section>
}

export default function Insights({ graph, paths = [], rems = [], demo = false }) {
  const [timeline, setTimeline] = useState(null)
  const [code, setCode] = useState(null)
  const [category, setCategory] = useState(null)
  const [component, setComponent] = useState(null)
  const [technique, setTechnique] = useState(null)
  const [outcome, setOutcome] = useState(null)
  useEffect(() => {
    if (demo) { setTimeline(DEMO.timeline); setCode({ scanned: true, findings: DEMO.findings }); return undefined }
    let live = true; Promise.all([api.timeline(), api.codeReport()]).then(([nextTimeline, nextCode]) => { if (live) { setTimeline(nextTimeline); setCode(nextCode) } }).catch(() => {})
    return () => { live = false }
  }, [demo])
  const findings = demo ? DEMO.findings : code && code.scanned ? code.findings : []
  const activeGraph = demo ? DEMO.graph : graph
  const activePaths = demo ? DEMO.paths : paths
  const activeRems = demo ? DEMO.rems : rems
  const categories = useMemo(() => categoryDistribution(findings), [findings])
  const components = useMemo(() => componentRisk(activeGraph, activePaths), [activeGraph, activePaths])
  const mappings = useMemo(() => mitreMappings(findings), [findings])
  const outcomes = useMemo(() => remediationOutcome(activeRems), [activeRems])
  const selectedCategory = categories.find((row) => row.category === category)
  const selectedComponent = components.find((row) => row.id === component)
  const selectedTechnique = mappings.find((row) => row.technique === technique)
  const selectedOutcome = outcomes.rows.find((row) => row.state === outcome)
  return <main className="insights analytics">
    <header className="analytics-header wide-card"><div><p className="eyebrow">Analytics {demo && <span className="tag">Demo sample data</span>}</p><h1>Insights</h1><p>Understand where security risk originates, how exposure changes, and which improvements matter most.</p></div></header>
    <Insight title="Finding categories" explanation={categories.length ? `${categories[0].category} accounts for the largest share of recorded findings.` : 'Categories appear after a repository scan records findings.'} action={selectedCategory ? `Review ${selectedCategory.category.toLowerCase()} controls across ${selectedCategory.files.size} affected component${selectedCategory.files.size === 1 ? '' : 's'}.` : 'Select a category to understand the underlying rules and affected components.'}>
      <Donut rows={categories} selected={category} onSelect={setCategory} ariaLabel="Finding distribution by category" />
      {selectedCategory && <p className="analytics-detail"><b>{selectedCategory.category}</b> appears in {selectedCategory.files.size} component{selectedCategory.files.size === 1 ? '' : 's'} through {selectedCategory.rules.size} scanner rule{selectedCategory.rules.size === 1 ? '' : 's'}: {[...selectedCategory.rules].slice(0, 3).join(', ')}.</p>}
    </Insight>
    <Insight title="Risk concentration" explanation={components.length ? `${components[0].label} contributes the largest share of current ranked-path risk.` : 'Risk concentration appears once code components occur in ranked paths.'} action={selectedComponent ? `Prioritize remediation work in ${selectedComponent.label}; it appears on ${selectedComponent.paths} ranked path${selectedComponent.paths === 1 ? '' : 's'}.` : 'Select a component to see how often it occurs in the current ranked paths.'}>
      <HorizontalBars rows={components} selected={component} onSelect={setComponent} label="Risk concentration by component" value={(row) => row.risk} />
    </Insight>
    <Insight title="MITRE ATT&amp;CK distribution" explanation={mappings.length ? `${mappings[0].technique} is the most frequently mapped technique in current repository findings.` : 'Technique mappings appear after findings are available.'} action={selectedTechnique ? `Review controls related to ${selectedTechnique.technique} in ${selectedTechnique.files.size} affected component${selectedTechnique.files.size === 1 ? '' : 's'}.` : 'Select a technique to see its evidence footprint.'}>
      <HorizontalBars rows={mappings.slice(0, 6)} selected={technique} onSelect={setTechnique} label="Mapped ATT&CK techniques" />
      {selectedTechnique && <p className="analytics-detail"><MitreCode id={selectedTechnique.technique} /></p>}
      {selectedTechnique && <p className="analytics-detail"><b>{selectedTechnique.technique}</b> is mapped by {selectedTechnique.count} finding{selectedTechnique.count === 1 ? '' : 's'}; {selectedTechnique.confirmed} {selectedTechnique.confirmed === 1 ? 'is' : 'are'} confirmed. Other mappings remain findings, not confirmed attack observations.</p>}
    </Insight>
    <Insight title="Remediation effectiveness" explanation={outcomes.rows.length ? `${outcomes.verified} remediation action${outcomes.verified === 1 ? ' is' : 's are'} verified against the current workspace.` : 'Outcome analysis begins when remediation actions are proposed.'} action={selectedOutcome ? `Review ${titleCase(selectedOutcome.state)} remediation actions to keep the workflow moving.` : 'Select an outcome to focus the next remediation step.'}>
      <Donut rows={outcomes.rows} selected={outcome} onSelect={setOutcome} ariaLabel="Remediation outcomes" totalLabel="actions" />
      {outcomes.verified > 0 && <p className="analytics-detail">Verified actions have recorded a combined direct model-risk change of {outcomes.directRiskChange.toFixed(2)}. This is not extrapolated beyond those recorded actions.</p>}
    </Insight>
    <Insight wide title="Event exposure checkpoints" explanation="Exposure is recomputed as events arrive, showing how the current attack-path model developed over this event stream." action="Use this movement with the active path analysis; scan-to-scan new, resolved, and reopened finding trends appear only when comparable scan history is stored.">
      {timeline && <RiskLine series={timeline.risk_series} />}
    </Insight>
  </main>
}
