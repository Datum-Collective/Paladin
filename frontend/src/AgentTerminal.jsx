import { useEffect, useRef, useState } from 'react'
import { api, agentStream } from './api.js'
import { usePrefs } from './prefs.jsx'

/* The fixing agent as a terminal: every tool call and result as it happens, then a verdict that Paladin computed
   (re-scan, real tests, MITRE citations), shown apart from what the agent claims. */

const VERDICT = {
  verified: ['Verified', 'ok'], fixed_untested: ['Fixed, tests not run', 'warn'], partial: ['Partly fixed', 'warn'],
  ungrounded: ['Fixed, but not grounded in MITRE', 'warn'], incomplete: ['Stopped early', 'warn'],
  no_changes: ['No change made', 'bad'], not_fixed: ['Not fixed', 'bad'], failed_tests: ['Tests fail', 'bad'],
  regressed: ['Introduced new findings', 'bad'],
}
const ICON = { list_files: '≡', read_file: '◇', search_code: '⌕', edit_file: '✎', mitre_lookup: '◈', run_tests: '▶',
  rescan_file: '⟳', finish: '■' }

function argLine(name, input) {
  if (!input) return ''
  if (name === 'edit_file') return `${input.path || ''}`
  if (name === 'mitre_lookup') return input.id || `“${input.query || ''}”`
  if (name === 'search_code') return `/${input.pattern || ''}/`
  if (name === 'read_file') return `${input.path || ''}${input.start ? `:${input.start}` : ''}`
  return input.path || input.dir || ''
}

const mitreUrl = (id) => id.startsWith('CWE-') ? `https://cwe.mitre.org/data/definitions/${id.slice(4)}.html`
  : id.startsWith('CAPEC-') ? `https://capec.mitre.org/data/definitions/${id.slice(6)}.html`
    : id.startsWith('T') ? `https://attack.mitre.org/techniques/${id.replace('.', '/')}/`
      : `https://attack.mitre.org/mitigations/${id}/`

function Line({ l }) {
  if (l.kind === 'text') return <div className="t-text">{l.text}</div>
  if (l.kind === 'tool') {
    return (
      <div className={`t-tool ${l.ok === false ? 'bad' : ''}`}>
        <span className="t-ico" aria-hidden="true">{ICON[l.name] || '●'}</span>
        <b>{l.name}</b> <span className="t-arg">{argLine(l.name, l.input)}</span>
        {l.summary !== undefined && <div className="t-out">⎿ {l.summary.split('\n').slice(0, 6).join('\n')}</div>}
        {l.summary === undefined && <span className="spinner tiny" aria-label="running" />}
      </div>
    )
  }
  if (l.kind === 'tests') {
    return <div className={`t-sys ${l.ran ? (l.passed ? 'ok' : 'bad') : ''}`}>tests {l.phase}: {l.ran ? `${l.passed ? 'PASSED' : 'FAILED'} (${l.runner})` : `not run: ${l.reason}`}</div>
  }
  if (l.kind === 'error') return <div className="t-sys bad">✕ {l.text}</div>
  return <div className="t-sys">{l.text}</div>
}

function Verdict({ v, onOpenDiff }) {
  const [label, tone] = VERDICT[v.verdict] || [v.verdict, 'mute']
  const t = v.tests || {}
  const g = v.grounding || { citations: [] }
  return (
    <section className={`verdict ${tone}`} aria-live="polite">
      <div className="row-top"><h3 className="first">Paladin's verdict</h3><span className={`pill ${tone}`}>{label}</span></div>
      <p>{v.reason}</p>
      <ul className="checks">
        {(v.resolved || []).map((r) => <li key={r.id} className="ok">✓ {r.file}:{r.line} {r.rule}: {r.how}</li>)}
        {(v.unresolved || []).map((r) => <li key={r.id} className="bad">✕ {r.file}:{r.line} {r.rule}: {r.how}</li>)}
        {(v.regressions || []).map((r, i) => <li key={i} className="bad">✕ new finding: {r.rule} in {r.file}</li>)}
        <li className={t.after && t.after.ran ? (t.after.passed ? 'ok' : 'bad') : 'warn'}>
          {t.after && t.after.ran ? `${t.after.passed ? '✓' : '✕'} tests ${t.after.passed ? 'pass' : 'fail'} after the change (${t.after.runner})`
            : `! tests not run${t.after ? `: ${t.after.reason}` : ''}`}
          {t.before && t.before.ran && <span className="muted"> · before: {t.before.passed ? 'passed' : 'failed'}</span>}
        </li>
        <li className={g.ok ? 'ok' : 'warn'}>
          {g.ok ? '✓' : '!'} MITRE grounding:{' '}
          {g.citations.length ? g.citations.map((c) => (
            <a key={c} href={mitreUrl(c)} target="_blank" rel="noopener noreferrer"
               className={g.fabricated.includes(c) ? 'bad' : ''}>{c}</a>)).reduce((a, b) => [a, ' ', b]) : 'no citations'}
          {g.fabricated.length > 0 && <span className="bad"> (not MITRE entries: {g.fabricated.join(', ')})</span>}
          {g.unrelated.length > 0 && <span className="muted"> (not linked to these weaknesses by MITRE: {g.unrelated.join(', ')})</span>}
          {g.related_checked === false && g.citations.length > 0 && <span className="muted"> (custom request: checked that each id is a real MITRE entry)</span>}
        </li>
      </ul>
      {v.changed_files && v.changed_files.length > 0 && (
        <p className="small">Changed {v.changed_files.join(', ')} · {v.committed ? 'committed to the scan’s local branch (nothing pushed)' : 'not committed'}
          {v.committed && <> · <button className="link inline small" onClick={onOpenDiff}>Review the diff</button></>}</p>
      )}
      {v.error && <p className="err small">{v.error.message}</p>}
      {v.agent_claim && <p className="muted small"><b>The agent’s own summary</b> (a claim, not evidence): {v.agent_claim}</p>}
    </section>
  )
}

export default function AgentTerminal({ goSettings, goRepo, workspaceId }) {
  const { prefs, set: setPref } = usePrefs()
  const [job, setJob] = useState(null)
  const [cfg, setCfg] = useState(null)
  const [models, setModels] = useState([])
  const model = prefs['agent.model'] || 'claude-opus-5-5'
  const [lines, setLines] = useState([])
  const [verdict, setVerdict] = useState(null)
  const [busy, setBusy] = useState(false)
  const [input, setInput] = useState('')
  const abort = useRef(null)
  const end = useRef(null)

  const load = async () => {
    try {
      const r = await api.hJobs()
      const j = r.jobs[0] ? await api.hJob(r.jobs[0].id) : null
      setJob(j)
      const last = j && j.report && j.report.agent_runs && j.report.agent_runs[j.report.agent_runs.length - 1]
      if (last && !busy) setVerdict(last)
    } catch { setJob(null) }
  }
  useEffect(() => {
    load()
    api.providers().then((r) => {
      const c = r.providers.find((p) => p.id === 'anthropic')
      setCfg(c)
      if (c && c.configured) api.models('anthropic').then((m) => setModels(m.models)).catch(() => {})
    }).catch(() => setCfg({ configured: false }))
    return () => abort.current && abort.current.abort()
  }, [workspaceId]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (end.current) end.current.scrollIntoView({ block: 'end' }) }, [lines, verdict])

  const open = job ? job.findings.filter((f) => !f.fixed && f.exploitable !== false) : []
  const run = async () => {
    const instruction = input.trim()
    setInput(''); setVerdict(null); setBusy(true)
    setLines([{ kind: 'sys', text: `$ paladin fix${instruction ? ` "${instruction}"` : ' --open-findings'} --model ${model}` }])
    const ac = new AbortController()
    abort.current = ac
    const add = (l) => setLines((x) => [...x, l])
    const toolDone = (id, patch) => setLines((x) => x.map((l) => (l.kind === 'tool' && l.id === id ? { ...l, ...patch } : l)))
    await agentStream({ instruction, model, job_id: job ? job.id : null }, (e) => {
      if (e.type === 'start') {
        const m = e.mitre || {}
        add({ kind: 'sys', text: `working copy ${e.root}` })
        add({ kind: 'sys', text: `${e.targets.length} finding(s): ${e.targets.map((t) => `${t.file}:${t.line} ${t.cwe || t.rule}`).join(' · ') || 'none (custom request)'}` })
        add({ kind: 'sys', text: `grounding: MITRE ATT&CK ${m.attack ? m.attack.version : '?'} · CWE ${m.cwe ? m.cwe.version : '?'} · CAPEC ${m.capec ? m.capec.version : '?'} (offline)` })
      } else if (e.type === 'text') {
        setLines((x) => {
          const last = x[x.length - 1]
          if (last && last.kind === 'text') return [...x.slice(0, -1), { ...last, text: last.text + e.delta }]
          return [...x, { kind: 'text', text: e.delta }]
        })
      } else if (e.type === 'tool') add({ kind: 'tool', id: e.id, name: e.name, input: e.input })
      else if (e.type === 'tool_result') toolDone(e.id, { ok: e.ok, summary: e.summary })
      else if (e.type === 'tests') add({ kind: 'tests', ...e })
      else if (e.type === 'status') add({ kind: 'sys', text: `· ${e.message}` })
      else if (e.type === 'error') add({ kind: 'error', text: e.message })
      else if (e.type === 'verdict') setVerdict(e)
    }, ac.signal)
    if (ac.signal.aborted) add({ kind: 'error', text: 'Stopped. Nothing is committed unless Paladin verified it.' })
    setBusy(false)
    load()
  }
  const stop = () => abort.current && abort.current.abort()

  if (cfg && !cfg.configured) {
    return <div className="empty"><h2>Add a Claude key</h2><p className="muted">The fixing agent runs on your Claude API key.</p>
      <div className="actions center"><button className="primary" onClick={goSettings}>Open Settings</button></div></div>
  }
  return (
    <div className="agent">
      <div className="assistant-bar">
        <span className="small">{job ? <><b>{job.repo_url}</b> · scan #{job.id} · {open.length} open finding(s)</> : 'No scan in this workspace yet'}</span>
        <label>Model
          <select value={model} onChange={(e) => setPref('agent.model', e.target.value)} disabled={busy}>
            {!models.some((m) => m.id === model) && <option value={model}>{model}</option>}
            {models.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        </label>
      </div>
      <div className="terminal" role="log" aria-live="polite" aria-label="Agent activity">
        {lines.length === 0 && !verdict && (
          <div className="t-sys">
            {job ? (open.length ? `Ready. Paladin's agent will fix the ${open.length} open finding(s) in ${job.repo_url}, grounded in MITRE CWE/CAPEC/ATT&CK. `
              : `No open findings in ${job.repo_url}. Describe a change and the agent will make it, grounded in MITRE CWE/CAPEC/ATT&CK. `) +
              'Every result is re-scanned and tested by Paladin; nothing reaches GitHub until you open a pull request.'
              : 'Scan a repository first (Home → paste a GitHub link). The agent works on that scan’s local copy.'}
          </div>
        )}
        {lines.map((l, i) => <Line key={i} l={l} />)}
        {busy && <div className="t-sys"><span className="spinner tiny" /> working…</div>}
        {verdict && <Verdict v={verdict} onOpenDiff={goRepo} />}
        <div ref={end} />
      </div>
      <div className="composer">
        <textarea rows={2} value={input} onChange={(e) => setInput(e.target.value)} disabled={busy || !job}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (!busy && job) run() } }}
                  placeholder={open.length ? 'Enter to fix all open findings, or describe what to fix' : 'Describe the change you want'}
                  aria-label="Instruction for the agent" />
        {busy ? <button onClick={stop}>Stop</button>
          : <button className="primary" onClick={run} disabled={!job || (!open.length && !input.trim())}>{input.trim() ? 'Run' : 'Fix Findings'}</button>}
      </div>
    </div>
  )
}
