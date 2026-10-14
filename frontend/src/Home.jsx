import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api.js'
import { ago, classifyInput, sortWorkspaces, workspaceStatus } from './lib.js'
import { usePrefs } from './prefs.jsx'
import WorkspaceRow from './WorkspaceRow.jsx'
import Icon from './Icons.jsx'

const ICON = { url: 'github', github: 'github', workspace: 'folder' }

function Suggestion({ s, on, onPick, onHover }) {
  return (
    <div role="option" aria-selected={on} className={on ? 'sugg on' : 'sugg'} onMouseMove={onHover}
         onMouseDown={(e) => e.preventDefault()} onClick={onPick}>
      <Icon name={ICON[s.kind]} size={16} />
      <span className="sugg-main">
        <span className="sugg-title">{s.title}</span>
        {s.subtitle && <span className="muted small sugg-sub">{s.subtitle}</span>}
      </span>
      {s.private && <Icon name="lock" size={13} />}
      <span className="small sugg-act">{s.kind === 'workspace' ? 'Open' : 'Preview'}</span>
    </div>
  )
}

function Preview({ p, busy, onConfirm, onOpenExisting, onCancel }) {
  const info = p.info
  const existing = info.workspace_id
  return (
    <section className="preview" aria-label="Repository details">
      <div className="preview-head">
        <Icon name={p.type === 'github' ? 'github' : 'folder'} size={18} />
        <div className="preview-title">
          <b>{p.type === 'github' ? info.full_name : info.name}</b>
          <span className="muted small mono">{p.type === 'github' ? info.url.replace('https://', '') : info.path}</span>
        </div>
        {p.type === 'github' && <span className="pill mute">{info.private ? 'Private' : 'Public'}</span>}
      </div>
      {p.type === 'github' && info.description && <p className="muted">{info.description}</p>}
      <dl className="kv wide small">
        {p.type === 'github' && <><dt>Default branch</dt><dd>{info.default_branch}</dd></>}
        <dt>What happens</dt>
        <dd>{existing ? 'This is already a workspace. Open it, or scan again.'
          : p.type === 'github' ? 'Clones the default branch (read-only, hooks off), scans it and proposes fixes. Code is never run.'
            : 'Scans the committed code in place. The folder is read, never modified or executed.'}</dd>
      </dl>
      <div className="actions">
        {existing && <button className="primary" onClick={onOpenExisting}>Open Workspace</button>}
        <button className={existing ? '' : 'primary'} onClick={onConfirm} disabled={busy}>
          {busy ? 'Starting…' : existing ? 'Scan Again' : p.type === 'github' ? 'Clone and Scan' : 'Scan Folder'}
        </button>
        <button onClick={onCancel} disabled={busy}>Cancel</button>
      </div>
    </section>
  )
}

function Checklist({ steps, onDismiss }) {
  return (
    <section className="rail-group" aria-labelledby="gs-h">
      <div className="row-top"><h3 id="gs-h" className="first">Get started</h3>
        <button className="link inline small" onClick={onDismiss}>Dismiss</button></div>
      <ol className="steps-list">
        {steps.map((s) => (
          <li key={s.id} className={s.done ? 'done' : ''}>
            <span className="check" aria-hidden="true">{s.done ? <Icon name="check" size={12} /> : null}</span>
            <span className="steps-text"><span>{s.title}</span>
              <span className="muted small">{s.hint}</span></span>
            {!s.done && s.action && <button className="small-btn" onClick={s.action}>{s.cta}</button>}
          </li>
        ))}
      </ol>
    </section>
  )
}

export default function Home({
  workspaces, current, desktop, config, onOpen, onImportRepo, onImportFolder, onChooseFolder, onNew, onRename, onDelete,
  go, goSettings, focusToken, intent,
}) {
  const { prefs, set } = usePrefs()
  const [q, setQ] = useState('')
  const [items, setItems] = useState([])
  const [itemsFor, setItemsFor] = useState('')      // the query these suggestions were fetched for
  const [ghErr, setGhErr] = useState('')
  const [hi, setHi] = useState(0)
  const [focus, setFocus] = useState(false)
  const [armed, setArmed] = useState(false)       // ↓ opens the list without typing
  const [phase, setPhase] = useState('idle')        // idle | checking | preview | working
  const [preview, setPreview] = useState(null)
  const [err, setErr] = useState(null)
  const [gh, setGh] = useState(null)
  const input = useRef(null)

  useEffect(() => { if (input.current) input.current.focus() }, [focusToken])
  useEffect(() => {
    if (!config.github) { setGh(null); return }
    api.githubStatus().then(setGh).catch(() => setGh({ ok: false, error: 'Could not reach GitHub.' }))
  }, [config.github])

  useEffect(() => {
    if (!focus || phase !== 'idle') return undefined
    const ac = new AbortController()
    const t = setTimeout(() => {
      api.suggestRepos(q, ac.signal).then((r) => { setItems(r.suggestions); setItemsFor(q); setGhErr(r.github_error || ''); setHi(0) }).catch(() => {})
    }, q ? 140 : 0)
    return () => { clearTimeout(t); ac.abort() }
  }, [q, focus, phase])

  const fail = useCallback((e) => {
    const m = e.message || 'That did not work.'
    setErr({ message: m, token: /token|private|rate limit/i.test(m), retry: /reach|network|connection/i.test(m) })
    setPhase('idle')
  }, [])

  const previewRepo = useCallback(async (text) => {
    setErr(null); setPhase('checking')
    try { setPreview({ type: 'github', text, info: await api.resolveRepo(text) }); setPhase('preview') } catch (e) { fail(e) }
  }, [fail])
  const previewFolder = useCallback(async (path) => {
    setErr(null)
    if (!desktop) { setErr({ message: 'Local folders can only be opened in the desktop app.' }); return }
    setPhase('checking')
    try { setPreview({ type: 'local', text: path, info: await api.resolveLocal(path) }); setPhase('preview') } catch (e) { fail(e) }
  }, [desktop, fail])

  const confirm = useCallback(async () => {
    setPhase('working'); setErr(null)
    try {
      if (preview.type === 'github') await onImportRepo(preview.text)
      else await onImportFolder(preview.info.path)
    } catch (e) { fail(e); setPhase('preview') }
  }, [preview, onImportRepo, onImportFolder, fail])

  const cancel = () => { setPreview(null); setPhase('idle'); setErr(null) }
  const chooseFolder = async () => { const p = onChooseFolder && await onChooseFolder(); if (p) { setQ(p); previewFolder(p) } }

  const lastIntent = useRef(null)
  useEffect(() => {
    if (intent && intent.id !== lastIntent.current) { lastIntent.current = intent.id; setQ(intent.path); previewFolder(intent.path) }
  }, [intent, previewFolder])

  const pick = useCallback(async (s) => {
    if (s.kind === 'workspace') await onOpen(s.workspace_id)
    else previewRepo(s.url)
  }, [onOpen, previewRepo])

  const fresh = itemsFor === q                      // never act on suggestions for text that is no longer in the box
  const live = fresh ? items : []
  const submit = () => {
    if (phase !== 'idle') return
    const kind = classifyInput(q)
    if (kind === 'github') previewRepo(q.trim())
    else if (kind === 'path') previewFolder(q.trim())
    else if (live[hi] && (q.trim() || armed)) pick(live[hi])
    else setErr({ message: q.trim() ? `Nothing matches “${q.trim()}”. Paste a GitHub link, owner/name or a folder path.` : 'Paste a GitHub link, owner/name or a folder path.' })
  }
  const onKey = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setArmed(true); setHi((n) => Math.min(live.length - 1, n + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHi((n) => Math.max(0, n - 1)) }
    else if (e.key === 'Enter') { e.preventDefault(); submit() }
    else if (e.key === 'Escape') { setQ(''); setArmed(false); cancel() }
  }

  const resume = current && (current.events > 0 || current.repo_url) ? current : null
  const recents = useMemo(
    () => sortWorkspaces(workspaces.filter((w) => !resume || w.id !== resume.id), 'recent').slice(0, 6), [workspaces, resume])
  const showList = focus && phase === 'idle' && live.length > 0 && (q.trim() !== '' || armed)
  const providers = config.providers || {}
  const anyModel = Boolean(providers.anthropic || providers.openai)
  const steps = [
    { id: 'gh', title: 'Connect GitHub', hint: 'Optional. Search your repositories and open private ones.', done: Boolean(config.github),
      cta: 'Connect', action: () => goSettings('github') },
    { id: 'ai', title: 'Add a model key', hint: 'Optional. Enables the assistant and AI review of findings.', done: anyModel,
      cta: 'Add', action: () => goSettings('providers') },
    { id: 'repo', title: 'Open a repository', hint: 'Paste a link above, or open a local folder.', done: workspaces.some((w) => w.repo_url),
      cta: 'Start', action: () => input.current && input.current.focus() },
  ]
  const showGuide = !prefs['general.onboarding_dismissed'] && steps.some((s) => !s.done)
  const rs = resume ? workspaceStatus(resume) : null

  return (
    <div className="page home">
      <div className="home-grid">
        <div className="home-main">
          {resume && (
            <section className="resume" aria-label="Resume">
              <div className="resume-text">
                <span className="muted small">Resume</span>
                <b>{resume.name}</b>
                <span className="muted small">
                  {resume.repo_url ? resume.repo_url.replace('https://', '') : 'No repository'} · opened {ago(resume.opened)}
                </span>
              </div>
              <span className={`pill ${rs.tone}`}>{rs.label}</span>
              <button className="primary" onClick={() => go('analysis')}>Continue</button>
            </section>
          )}

          <h1 className="home-title">Open a project</h1>
          <div className={`bar-wrap ${focus ? 'focus' : ''}`}>
          <div className={`bar ${focus ? 'focus' : ''} ${err ? 'bad' : ''}`}>
            <Icon name="github" size={20} />
            <input ref={input} value={q} disabled={phase === 'checking' || phase === 'working'} spellCheck={false} autoComplete="off"
                   role="combobox" aria-expanded={showList} aria-controls="home-list" aria-autocomplete="list"
                   aria-label="GitHub repository, folder path, or workspace name"
                   placeholder={desktop ? 'GitHub link, owner/name, folder path, or workspace' : 'GitHub link, owner/name, or workspace'}
                   onChange={(e) => { setQ(e.target.value); setErr(null); if (phase === 'preview') cancel() }}
                   onFocus={() => setFocus(true)} onBlur={() => setTimeout(() => { setFocus(false); setArmed(false) }, 120)} onKeyDown={onKey} />
            {phase === 'checking' ? <span className="spinner" role="status" aria-label="Checking" />
              : <button className="primary bar-go" onClick={submit} disabled={phase !== 'idle' || !q.trim()}>
                {classifyInput(q) === 'github' || classifyInput(q) === 'path' ? 'Preview' : live[hi] && live[hi].kind === 'workspace' ? 'Open' : 'Go'}
                <Icon name="return" size={14} /></button>}
          </div>

          {showList && (
            <div id="home-list" role="listbox" className="sugg-list glass" aria-label="Suggestions">
              {live.map((s, i) => <Suggestion key={`${s.kind}-${s.url || s.workspace_id}`} s={s} on={i === hi}
                                              onHover={() => setHi(i)} onPick={() => pick(s)} />)}
              {ghErr && <div className="sugg-note muted small">GitHub repositories are unavailable: {ghErr}</div>}
            </div>
          )}
          </div>

          <div className="launch-actions">
            <button onClick={chooseFolder} disabled={!desktop} title={desktop ? 'Open a local Git repository' : 'Available in the desktop app'}>
              <Icon name="folder" size={14} />Open Folder…</button>
            <button onClick={onNew}><Icon name="plus" size={14} />New Workspace…</button>
          </div>

          {phase === 'checking' && <p className="progress" role="status"><span className="spinner tiny" aria-hidden="true" />Checking the repository…</p>}
          {err && (
            <div className="inline-error" role="alert">
              <span>{err.message}</span>
              <span className="actions">
                {err.token && <button onClick={() => goSettings('github')}>Open GitHub Settings</button>}
                {err.retry && <button onClick={() => (preview ? confirm() : submit())}>Try Again</button>}
              </span>
            </div>
          )}
          {preview && phase !== 'idle' && (
            <Preview p={preview} busy={phase === 'working'} onConfirm={confirm} onCancel={cancel}
                     onOpenExisting={() => onOpen(preview.info.workspace_id)} />
          )}

          <section className="recents" aria-labelledby="rec-h">
            <div className="row-top">
              <h3 id="rec-h" className="first">Recent workspaces</h3>
              <button className="link inline" onClick={() => go('workspaces')}>All workspaces ({workspaces.length})</button>
            </div>
            {recents.length === 0 ? <p className="muted">No workspaces yet. Open a repository above to create one.</p> : (
              <ul className="wlist">
                {recents.map((w) => <WorkspaceRow key={w.id} w={w} active={current && current.id === w.id}
                                                  onOpen={onOpen} onRename={onRename} onDelete={onDelete} />)}
              </ul>
            )}
          </section>
        </div>

        <aside className="home-rail" aria-label="Status and capabilities">
          {showGuide && <Checklist steps={steps} onDismiss={() => set('general.onboarding_dismissed', true)} />}
          <section className="rail-group" aria-labelledby="cn-h">
            <h3 id="cn-h" className="first">Connections</h3>
            <ul className="conn">
              <li><span className={`dot ${config.github ? (gh && gh.ok === false ? 'bad' : 'ok') : ''}`} />
                <span className="conn-text">GitHub<span className="muted small">
                  {!config.github ? 'Not connected' : gh && gh.ok ? `Connected as ${gh.login}` : gh && gh.error ? gh.error : 'Checking…'}</span></span>
                <button className="small-btn" onClick={() => goSettings('github')}>{config.github ? 'Manage' : 'Connect'}</button></li>
              <li><span className={`dot ${providers.anthropic ? 'ok' : ''}`} />
                <span className="conn-text">Claude<span className="muted small">{providers.anthropic ? 'Key set' : 'No key'}</span></span>
                <button className="small-btn" onClick={() => goSettings('providers')}>{providers.anthropic ? 'Manage' : 'Add key'}</button></li>
              <li><span className={`dot ${providers.openai ? 'ok' : ''}`} />
                <span className="conn-text">OpenAI<span className="muted small">{providers.openai ? 'Key set' : 'No key'}</span></span>
                <button className="small-btn" onClick={() => goSettings('providers')}>{providers.openai ? 'Manage' : 'Add key'}</button></li>
            </ul>
          </section>
        </aside>
      </div>
    </div>
  )
}
