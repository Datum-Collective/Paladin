import { useEffect, useState } from 'react'
import { api } from './api.js'
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
    f.triaged_by === 'haiku-review' ? ['needs review', 'warn'] : ['needs manual fix', 'warn'])
  return (
    <section className="block">
      <h3>Findings <span className="count">{items.length}</span></h3>
      <ul className="rows">
        {items.map((f) => {
          const [label, tone] = verdict(f)
          return (
            <li key={f.id}>
              <div className="row-top"><b>{f.title}</b><span className={`pill ${tone}`}>{label}</span></div>
              <div className="muted">{f.file}:{f.line} · {f.cwe} · {f.technique}</div>
              {f.snippet && <code className="snippet">{f.snippet}</code>}
              {f.reason && <div className="muted">{f.reason}</div>}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

export default function RepoView({ onDone }) {
  const [url, setUrl] = useState('')
  const [job, setJob] = useState(null)
  const [cfg, setCfg] = useState({ github_enabled: false, ai_enabled: false })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)

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
          <input placeholder="https://github.com/owner/repo" value={url} aria-label="GitHub repository URL"
                 onChange={(e) => setUrl(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && url && !running && run()} />
          <button className="primary" onClick={run} disabled={!url || running}>{running ? 'Scanning' : 'Scan'}</button>
        </div>
        <p className="muted small">AI {cfg.ai_enabled ? 'on' : 'off'} · Pull requests {cfg.github_enabled ? 'enabled' : 'unavailable (patch download only)'}</p>
        {err && <p className="err">{err}</p>}
        {job && (
          <>
            <div className="status">
              <b>{job.repo_url}</b>
              <span className={`pill ${job.state === 'failed' ? 'bad' : running ? 'info' : 'ok'}`}>
                {job.state === 'pr_opened' ? 'PR opened' : job.state}
              </span>
            </div>
            {job.error && <p className="err">{job.error}</p>}
            <ul className="log">{job.log.slice(-6).map((l, i) => <li key={i}>{l.msg}</li>)}</ul>
            <ScanReport r={job.report} />
            <Findings items={job.findings} />
          </>
        )}
      </aside>
      <main className="repo-main">
        {!job && <div className="empty"><h2>No repository scanned</h2><p className="muted">Changes appear here as a reviewable diff.</p></div>}
        {job && job.fixes.length === 0 && !running && (
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
                <a className="btn" href={`/api/harness/jobs/${job.id}/patch`} target="_blank" rel="noreferrer">Download</a>
                {job.state === 'ready' && (
                  <button className="primary" disabled={busy || !cfg.github_enabled} onClick={openPr}>
                    {busy ? 'Opening' : 'Open Pull Request'}
                  </button>
                )}
              </div>
            </div>
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
