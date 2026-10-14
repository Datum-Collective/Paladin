import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { ago, looksLikeRepo } from './lib.js'
import Icon from './Icons.jsx'

const STEP = { checking: 'Checking the repository…', creating: 'Creating the workspace and starting the scan…' }
const ICON = { url: 'github', github: 'github', workspace: 'folder' }

function Suggestion({ s, on, onPick, onHover }) {
  return (
    <div role="option" aria-selected={on} className={on ? 'sugg on' : 'sugg'} onMouseMove={onHover} onMouseDown={(e) => e.preventDefault()}
         onClick={onPick}>
      <Icon name={ICON[s.kind]} size={16} />
      <span className="sugg-main">
        <span className="sugg-title">{s.title}</span>
        {s.subtitle && <span className="muted small sugg-sub">{s.subtitle}</span>}
      </span>
      {s.private && <Icon name="lock" size={13} className="muted" />}
      <span className="muted small">{{ url: 'Import', github: 'Import', workspace: 'Open' }[s.kind]}</span>
    </div>
  )
}

export default function Home({ workspaces, current, onOpen, onImport, onCreate, goSettings, go, githubConfigured, focusToken, onBack }) {
  const [q, setQ] = useState('')
  const [items, setItems] = useState([])
  const [ghErr, setGhErr] = useState('')
  const [hi, setHi] = useState(0)
  const [focus, setFocus] = useState(false)
  const [step, setStep] = useState(null)
  const [err, setErr] = useState(null)
  const input = useRef(null)

  useEffect(() => { if (input.current) input.current.focus() }, [focusToken])

  // autocomplete: debounced, cancellable, never blocks typing
  useEffect(() => {
    if (!focus) return undefined
    const ac = new AbortController()
    const t = setTimeout(() => {
      api.suggestRepos(q, ac.signal).then((r) => { setItems(r.suggestions); setGhErr(r.github_error || ''); setHi(0) }).catch(() => {})
    }, q ? 140 : 0)
    return () => { clearTimeout(t); ac.abort() }
  }, [q, focus])

  const importUrl = useCallback(async (text) => {
    setErr(null)
    setStep('checking')
    try {
      await api.resolveRepo(text)               // fast, specific feedback before anything is created
      setStep('creating')
      await onImport(text)
    } catch (e) {
      const m = e.message || 'Could not open that repository.'
      setErr({ message: m, token: /token/i.test(m) })
    } finally { setStep(null) }
  }, [onImport])

  const pick = useCallback(async (s) => {
    if (s.kind === 'workspace') { setErr(null); await onOpen(s.workspace_id) } else await importUrl(s.url)
  }, [onOpen, importUrl])

  const submit = () => {
    if (step) return
    if (looksLikeRepo(q)) { importUrl(q.trim()); return }       // a typed link always wins over a highlighted row
    if (items[hi]) { pick(items[hi]); return }
    setErr({ message: 'Enter a GitHub link such as https://github.com/owner/repo, or owner/name.' })
  }
  const onKey = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setHi((n) => Math.min(items.length - 1, n + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHi((n) => Math.max(0, n - 1)) }
    else if (e.key === 'Enter') { e.preventDefault(); submit() }
    else if (e.key === 'Escape') { setQ(''); setErr(null) }
  }
  const showList = focus && items.length > 0 && !step
  const recents = workspaces.slice(0, 6)

  return (
    <main className="home">
      <div className="home-drag drag">
        {onBack && <button className="link inline nodrag" onClick={onBack}>Continue in {current ? current.name : 'workspace'}</button>}
      </div>
      <div className="home-col">
        <div className="home-head">
          <span className="brand-mark" aria-hidden="true" />
          <h1>Open a repository</h1>
          <p className="muted">Paste a GitHub link to scan it, or jump back into a workspace.</p>
        </div>

        <div className={`bar ${focus ? 'focus' : ''} ${err ? 'bad' : ''}`}>
          <Icon name="github" size={20} />
          <input ref={input} value={q} disabled={Boolean(step)} spellCheck={false} autoComplete="off" autoCapitalize="off"
                 role="combobox" aria-expanded={showList} aria-controls="home-list" aria-autocomplete="list"
                 aria-label="GitHub repository link or workspace" placeholder="github.com/owner/repo, or search workspaces"
                 onChange={(e) => { setQ(e.target.value); setErr(null) }} onFocus={() => setFocus(true)}
                 onBlur={() => setTimeout(() => setFocus(false), 120)} onKeyDown={onKey} />
          {step ? <span className="spinner" role="status" aria-label="Working" />
            : <button className="primary bar-go" onClick={submit} disabled={!q.trim() && !items.length}>
              {looksLikeRepo(q) ? 'Import' : items[hi] && items[hi].kind === 'workspace' ? 'Open' : 'Go'}<Icon name="return" size={14} />
            </button>}
        </div>

        {showList && (
          <div id="home-list" role="listbox" className="sugg-list" aria-label="Suggestions">
            {items.map((s, i) => <Suggestion key={`${s.kind}-${s.url || s.workspace_id}`} s={s} on={i === hi} onHover={() => setHi(i)} onPick={() => pick(s)} />)}
            {ghErr && <div className="sugg-note muted small">GitHub repositories are unavailable: {ghErr}</div>}
          </div>
        )}
        {focus && !step && q.trim() && items.length === 0 && !looksLikeRepo(q) && (
          <p className="muted small hint">No workspace matches “{q.trim()}”. Enter a GitHub link or owner/name to import a repository.</p>
        )}
        {!githubConfigured && focus && !step && (
          <p className="muted small hint">Add a GitHub token in <button className="link inline" onClick={() => goSettings('github')}>Settings</button> to
            search your repositories and open private ones.</p>
        )}

        {step && <p className="progress" role="status"><span className="spinner small-s" aria-hidden="true" />{STEP[step]}</p>}
        {err && (
          <div className="inline-error" role="alert">
            <span>{err.message}</span>
            {err.token && <button onClick={() => goSettings('github')}>Open GitHub Settings</button>}
          </div>
        )}

        <section className="recents" aria-labelledby="rec-h">
          <div className="row-top"><h3 id="rec-h" className="first">Recent workspaces</h3>
            <button className="link inline" onClick={onCreate}><Icon name="plus" size={12} /> New workspace</button></div>
          {recents.length === 0 && <p className="muted">No workspaces yet.</p>}
          <ul className="recent-list">
            {recents.map((w) => (
              <li key={w.id}>
                <button className="recent" onClick={() => onOpen(w.id)}>
                  <Icon name={w.repo_url ? 'github' : 'folder'} size={16} />
                  <span className="recent-main">
                    <span className="recent-name">{w.name}{current && current.id === w.id && <span className="pill mute">Open</span>}</span>
                    <span className="muted small">{w.repo_url ? w.repo_url.replace('https://', '') : 'No repository'}</span>
                  </span>
                  <span className="muted small">{w.events ? `${w.events} ${w.events === 1 ? 'event' : 'events'} · ` : ''}{ago(w.opened)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <div className="home-foot">
          <button className="link inline" onClick={() => go('ingest')}>Add log data</button>
          <span className="muted">·</span>
          <button className="link inline" onClick={() => go('assistant')}>Ask the assistant</button>
          <span className="muted">·</span>
          <button className="link inline" onClick={() => goSettings('general')}>Settings</button>
        </div>
      </div>
    </main>
  )
}
