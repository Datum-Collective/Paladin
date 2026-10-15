import { useEffect, useRef, useState } from 'react'
import { api, downloadText } from './api.js'
import { looksLikeRepo, scanStages, scanTarget } from './lib.js'
import DiffView from './DiffView.jsx'
import Icon from './Icons.jsx'

const RUNNING = ['queued', 'cloning', 'scanning', 'fixing']

function ScanReport({ r }) {
  if (!r || r.files_total === undefined) return null
  const skipped = Object.entries(r.skipped || {}).sort((a, b) => b[1].count - a[1].count)
  return (
    <section className="block">
      <h3>Scan coverage</h3>
      <p><b>{r.scanned}</b> of {r.files_total} files · {r.lines_scanned.toLocaleString()} lines · {r.rules.length} rules</p>
      <p className="muted">
        {r.candidates} rule hit(s), {r.ai.review_findings} from AI review, {r.judged_not_exploitable} judged not exploitable.
        {r.ai.enabled ? ` AI reviewed ${r.ai.review_files} file(s)` : ' AI is off'}
        {r.ai.claims_rejected ? `; ${r.ai.claims_rejected} claim(s) discarded because they did not match the code` : ''}
        {r.ai.review_truncated && r.ai.review_truncated.length ? `; ${r.ai.review_truncated.length} file(s) too long to review in full` : ''}.
      </p>
      {skipped.length > 0 && (
        <ul className="plain">
          {skipped.map(([why, d]) => (
            <li key={why}><b>{d.count}</b> {why} <span className="muted">{d.examples.join(', ')}</span></li>
          ))}
        </ul>
      )}
      <details><summary>Rules checked</summary>
        <ul className="plain">{r.rules.map((x) => <li key={x.id}>{x.title} <span className="muted">{x.cwe}</span></li>)}</ul>
      </details>
      <details><summary>Files scanned</summary>
        <ul className="plain mono">{r.scanned_files.map((f) => <li key={f}>{f}</li>)}</ul>
      </details>
      {r.map && (
        <details open><summary>Repository map</summary>
          <p className="muted small">{Object.entries(r.map.languages || {}).map(([k, v]) => `${k} ${v}`).join(' · ') || 'No source languages recognised'}
            {r.map.dependencies ? ` · ${r.map.dependencies} pinned dependencies` : ''}</p>
          {r.map.entries && r.map.entries.length > 0 ? (
            <ul className="plain small">{r.map.entries.slice(0, 12).map((e) => (
              <li key={e.file}><span className="mono">{e.file}</span> <span className="muted">{e.routes.length} route(s){e.auth ? ' · auth checks present' : ' · no auth checks found'}</span></li>
            ))}</ul>
          ) : <p className="muted small">No entry points (routes or handlers) were found.</p>}
        </details>
      )}
      {r.crawler && r.crawler.partial && (
        <p className="notice warn">Partial results: the AI review did not finish for every file
          ({Object.entries(r.crawler.failed || {}).map(([k, v]) => `${v} ${k.replace('_', ' ')}`).join(', ') || 'stopped early'}). Rule hits and reviewed files are complete; scan again to finish.</p>
      )}
      {r.crawler && r.crawler.dependency_note && <p className="muted small">{r.crawler.dependency_note}</p>}
      <p className="muted">{r.limits}</p>
    </section>
  )
}

function Verification({ v }) {
  if (!v) return null
  const ok = v.python_files_compiled === v.python_files_changed && v.fixed_rules_still_matching.length === 0
  return (
    <p className={ok ? 'notice' : 'notice warn'}>
      <b>Verified on the patched files:</b> {v.python_files_compiled} of {v.python_files_changed} changed Python
      file(s) compile; {v.changed_files - v.python_files_changed} other file(s) are not syntax-checked; rule hits in
      changed files went from {v.findings_before} to {v.findings_after}
      {v.fixed_rules_still_matching.length ? `; still matching: ${v.fixed_rules_still_matching.join(', ')}` : ''}.
      Tests were not run.
    </p>
  )
}

function Findings({ items }) {
  if (!items || !items.length) return null
  const verdict = (f) => (f.fixed ? ['fixed', 'ok'] : f.exploitable === false ? ['not exploitable', 'mute'] :
    f.status === 'confirmed' ? ['confirmed', 'bad'] : ['potential', 'warn'])
  const SEV = { critical: 'bad', high: 'bad', medium: 'warn', low: 'mute' }
  return (
    <section className="block">
      <h3>Findings <span className="count">{items.length}</span></h3>
      <ul className="rows">
        {items.map((f) => {
          const [label, tone] = verdict(f)
          return (
            <li key={f.id}>
              <div className="row-top"><b>{f.title}</b>
                <span className="pill-row">{f.severity && <span className={`pill ${SEV[f.severity] || 'mute'}`}>{f.severity}</span>}
                  <span className={`pill ${tone}`}>{label}</span></span></div>
              <div className="muted mono small">{f.file}:{f.line} · {f.cwe} · {f.technique}</div>
              {f.snippet && <code className="snippet">{f.snippet}</code>}
              {f.reason && <div className="muted">{f.reason}</div>}
              {f.impact && <div className="small"><b>Impact</b> {f.impact}</div>}
              {f.evidence && f.evidence.length > 0 && (
                <details className="small"><summary>Evidence across files ({f.evidence.length})</summary>
                  <ul className="plain">{f.evidence.map((e, i) => <li key={i}><span className="mono">{e.file}:{e.line}</span> <code>{e.quote}</code></li>)}</ul>
                </details>
              )}
              {f.reached_via && f.reached_via.length > 0 && (
                <div className="muted small">Reached from <span className="mono">{f.reached_via[0].file}</span>
                  {f.reached_via.map((h) => ` → ${h.target}`).join('')} (imports, not a traced call)</div>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

export default function RepoView({ onDone, onViewPaths, goSettings }) {
  const [url, setUrl] = useState('')
  const [job, setJob] = useState(null)
  const [cfg, setCfg] = useState({ github_enabled: false, ai_enabled: false })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)

  const submitted = useRef('')        // the exact text last handed to the engine, reused by "Try again"
  const userStarted = useRef(false)   // once the user starts a scan, the initial history fetch must not replace it
  const lastLive = useRef({ id: null, state: '' })   // the stage a job was in before it failed

  useEffect(() => {
    api.hConfig().then(setCfg).catch(() => {})
    api.hJobs().then((r) => r.jobs[0] && api.hJob(r.jobs[0].id))
      .then((j) => { if (j && !userStarted.current) setJob(j) }).catch(() => {})
  }, [])
  const seen = useRef(null)
  useEffect(() => {
    if (!job) return undefined
    if (lastLive.current.id !== job.id) lastLive.current = { id: job.id, state: '' }
    if (RUNNING.includes(job.state)) lastLive.current.state = job.state
    // refresh the graph the moment findings are stored (the "fixing" stage) and again when the scan settles
    const key = `${job.id}:${job.state}`
    if (seen.current !== key && (job.state === 'fixing' || !RUNNING.includes(job.state))) { seen.current = key; onDone() }
    if (!RUNNING.includes(job.state)) return undefined
    let live = true
    const t = setTimeout(async () => {
      try {
        const j = await api.hJob(job.id)
        if (live) setJob(j)           // a newer submission replaced this job: its reply must not overwrite it
      } catch (e) { if (live) setErr(e.message) }
    }, 1200)
    return () => { live = false; clearTimeout(t) }
  }, [job])

  const run = async (target = url) => {
    const t = target.trim()
    if (!t || (job && RUNNING.includes(job.state))) return
    submitted.current = t
    userStarted.current = true
    setErr('')
    try { setJob(await api.hStart(t)) } catch (e) { setErr(e.message); submitted.current = '' }
  }
  // Submitting is the whole interaction: pasting a repository link, pressing Enter or leaving the field starts the
  // scan. A pause while typing does not, so "owner/re" is never scanned on the way to "owner/repo".
  const submitIfRepo = (text) => {
    const t = (text || '').trim()
    if (t && t !== submitted.current && looksLikeRepo(t)) run(t)
  }
  // where a failed job had got to: what this view saw it running, else what the stored result shows it finished
  const failedAt = (j) => (lastLive.current.id === j.id && lastLive.current.state) ||
    (j.findings && j.findings.length ? 'fixing' : j.report && j.report.files_total !== undefined ? 'scanning' : 'cloning')
  // the text to scan again: what was submitted here, else a GitHub owner/name from history, else the stored path
  const retryTarget = (j) => submitted.current || scanTarget(j.repo_url)
  const openPr = async () => {
    setErr(''); setBusy(true)
    try { setJob(await api.hPr(job.id)) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const cancel = async () => {
    setErr(''); setBusy(true)
    try { setJob(await api.hCancel(job.id)); onDone() } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(job.diff)
      setCopied(true); setTimeout(() => setCopied(false), 1500)
    } catch { setErr('Could not copy to the clipboard. Use Download instead.') }
  }
  const running = job && RUNNING.includes(job.state)
  return (
    <div className="repo">
      <aside className="repo-side">
        <h2>Repository</h2>
        <p className="muted">Paste a GitHub link. The code is read, never executed, and every change is reviewed before a pull request.</p>
        <div className="field">
          <input placeholder="Paste a GitHub link to scan it" value={url} aria-label="GitHub repository URL" disabled={running}
                 onChange={(e) => setUrl(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && url && !running && run()}
                 onPaste={(e) => { const t = e.clipboardData && e.clipboardData.getData('text'); setTimeout(() => submitIfRepo(t || e.target.value), 0) }}
                 onBlur={(e) => submitIfRepo(e.target.value)} />
          {running && <button onClick={cancel} disabled={busy}>{busy ? 'Cancelling…' : 'Cancel'}</button>}
        </div>
        <p className="muted small">AI {cfg.ai_enabled ? 'on' : 'off'} · Pull requests {cfg.github_enabled ? 'enabled' : 'unavailable (patch download only)'}</p>
        {err && <p className="err">{err}</p>}
        {job && (
          <>
            <div className="status">
              <b>{job.repo_url}</b>
              <span className={`pill ${job.state === 'failed' ? 'bad' : running ? 'info' : job.state === 'cancelled' ? 'mute' : 'ok'}`}>
                {job.state === 'pr_opened' ? 'PR opened' : job.state === 'cancelled' ? 'Cancelled' : job.state}
              </span>
            </div>
            <ol className="scan-stages" aria-label="Scan progress">
              {scanStages(job.state, failedAt(job)).map((st) => (
                <li key={st.id} className={`stage ${st.status}`} aria-current={st.status === 'current' ? 'step' : undefined}>
                  <span className="stage-dot" aria-hidden="true">{st.status === 'done' ? '✓' : st.status === 'failed' ? '!' : ''}</span>{st.label}
                </li>
              ))}
            </ol>
            {job.error && <p className="err" role="alert">{job.error}</p>}
            {(job.state === 'failed' || job.state === 'cancelled') && (
              <div className="actions"><button className="primary" onClick={() => run(retryTarget(job))}>
                {job.state === 'failed' ? 'Try again' : 'Scan again'}</button></div>
            )}
            {!running && job.state !== 'failed' && job.state !== 'cancelled' && onViewPaths && (
              <div className="actions"><button className="primary" onClick={onViewPaths}>
                {job.findings && job.findings.length ? 'View attack paths' : 'Open analysis'}</button></div>
            )}
            <ul className="log">{job.log.slice(-6).map((l, i) => <li key={i}>{l.msg}</li>)}</ul>
            <ScanReport r={job.report} />
            <Findings items={job.findings} />
          </>
        )}
      </aside>
      <main className="repo-main">
        {!job && <div className="empty"><h2>Paste a repository to begin</h2><p className="muted">The scan starts as soon as you paste a GitHub link. Findings become attack paths; fixes appear here as a reviewable diff.</p></div>}
        {running && (
          <div className="empty"><h2>Scanning {job.repo_url}</h2>
            <p className="muted">Attack paths appear in Analysis as soon as weaknesses are found. Proposed fixes appear here when the scan finishes.</p></div>
        )}
        {job && job.fixes.length === 0 && !running && job.state !== 'cancelled' && (
          <div className="empty"><h2>No code changes</h2>
            <p className="muted">{job.findings.length ? 'Nothing could be fixed safely and automatically. See the findings.' : 'Nothing needed changing.'}</p></div>
        )}
        {job && job.fixes.length > 0 && (
          <>
            <div className="diff-bar">
              <div>
                <h2>Proposed changes</h2>
                <p className="muted">{job.fixes.length} verified fix(es) on <code>{job.branch}</code>. Tests were not run.</p>
              </div>
              <div className="actions">
                <button onClick={copy}><Icon name="copy" size={14} /> {copied ? 'Copied' : 'Copy patch'}</button>
                <button onClick={async () => { try { await downloadText(`/api/harness/jobs/${job.id}/patch`, `paladin-fixes-${job.id}.patch`) } catch (e) { setErr(e.message) } }}>
                  Download Patch</button>
                {job.state === 'ready' && (
                  <button className="primary" disabled={busy || !cfg.github_enabled} onClick={openPr}
                          title={cfg.github_enabled ? undefined : 'Pull requests need a GitHub token. Download the patch instead.'}>
                    {busy ? 'Opening' : 'Open Pull Request'}
                  </button>
                )}
              </div>
            </div>
            {job.state === 'ready' && !cfg.github_enabled && (
              <p className="notice" role="note">
                <b>Why you can’t open a pull request:</b> Paladin has no GitHub token, so it cannot push the fixes branch to{' '}
                <b>{job.repo_url}</b>. Add a token in Settings → GitHub (a fine-grained token for this repository with
                Contents and Pull requests set to Read and write). Your account also needs write access to {job.repo_url};
                if it isn’t your repository, ask the owner to add you as a collaborator. Until then, Download Patch gives
                you the same changes.{' '}
                {goSettings && <button className="link inline" onClick={goSettings}>Add a GitHub Token</button>}
              </p>
            )}
            <Verification v={job.report && job.report.verification} />
            {job.pr_url && (
              <p className="notice">Pull request opened: <a href={job.pr_url} target="_blank" rel="noreferrer">{job.pr_url}</a></p>
            )}
            <DiffView diff={job.diff} fixes={job.fixes} jobId={job.id} />
          </>
        )}
      </main>
    </div>
  )
}
