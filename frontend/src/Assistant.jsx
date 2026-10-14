import { useCallback, useEffect, useRef, useState } from 'react'
import { api, chatStream } from './api.js'
import { usePrefs } from './prefs.jsx'
import { toHistory } from './lib.js'
import Icon from './Icons.jsx'

const SUGGESTIONS = [
  'Which attack path should I fix first, and why?',
  'Explain the worst path step by step.',
  'What evidence confirms each step?',
  'What does the cheapest cut change?',
]
const EFFORT = [['', 'Default'], ['low', 'Low'], ['medium', 'Medium'], ['high', 'High']]
const NOTE = {
  max_tokens: 'The answer was cut off at the length limit.',
  refusal: 'The model declined to answer this.',
  pause_turn: 'The model paused. Send a message to continue.',
  model_context_window_exceeded: 'The conversation no longer fits. Start a new one.',
}

function ErrorNote({ e, onRetry, goSettings }) {
  const auth = e.kind === 'auth' || e.kind === 'permission'
  return (
    <div className="msg-error" role="alert">
      <b>{e.message}</b>
      {e.hint && <span className="muted"> {e.hint}</span>}
      <div className="actions">
        {auth && <button onClick={goSettings}>Open Settings</button>}
        {e.retryable && <button onClick={onRetry}>Try Again</button>}
        {e.request_id && <span className="muted small mono">Request {e.request_id}</span>}
      </div>
    </div>
  )
}

export default function Assistant({ goSettings, workspaceEmpty }) {
  const [providers, setProviders] = useState(null)
  const { prefs, set: setPref } = usePrefs()
  const provider = prefs['assistant.provider'] || 'anthropic'
  const setProvider = (v) => setPref('assistant.provider', v)
  const [models, setModels] = useState({ state: 'idle', list: [], error: '' })
  const model = prefs['assistant.model']
  const setModel = (v) => setPref('assistant.model', v)
  const effort = prefs['assistant.effort']
  const setEffort = (v) => setPref('assistant.effort', v)
  const ctx = prefs['assistant.context']
  const setCtx = (v) => setPref('assistant.context', v)
  const [msgs, setMsgs] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const abort = useRef(null)
  const end = useRef(null)

  useEffect(() => { api.providers().then((r) => setProviders(r.providers)).catch(() => setProviders([])) }, [])
  const cfg = providers && providers.find((p) => p.id === provider)

  useEffect(() => {
    if (!cfg || !cfg.configured) { setModels({ state: 'idle', list: [], error: '' }); return undefined }
    let live = true
    setModels((m) => ({ ...m, state: 'loading', error: '' }))
    api.models(provider).then((r) => {
      if (!live) return
      setModels({ state: 'ready', list: r.models, error: '' })
      if (!r.models.some((m) => m.id === model) && r.models[0]) setPref('assistant.model', r.models[0].id)
    }).catch((e) => live && setModels({ state: 'error', list: [], error: e.message }))
    return () => { live = false }
  }, [provider, cfg && cfg.configured]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { if (end.current) end.current.scrollIntoView({ block: 'end' }) }, [msgs])
  useEffect(() => () => abort.current && abort.current.abort(), [])

  const picked = models.list.find((m) => m.id === model)
  const ready = cfg && cfg.configured && model && !busy

  const run = useCallback(async (history) => {
    const ac = new AbortController()
    abort.current = ac
    setBusy(true)
    setMsgs([...history, { role: 'assistant', content: '', streaming: true }])
    const patch = (fn) => setMsgs((m) => { const c = [...m]; c[c.length - 1] = fn(c[c.length - 1]); return c })
    await chatStream({ provider, model, effort: effort || null, include_context: ctx, messages: toHistory(history) },
    (ev) => {
      if (ev.type === 'text') patch((m) => ({ ...m, content: m.content + ev.delta }))
      else if (ev.type === 'done') patch((m) => ({ ...m, streaming: false, stop: ev.stop_reason, usage: ev.usage }))
      else if (ev.type === 'error') patch((m) => ({ ...m, streaming: false, error: ev }))
    }, ac.signal)
    patch((m) => ({ ...m, streaming: false, stopped: ac.signal.aborted }))
    setBusy(false)
  }, [provider, model, effort, ctx])

  const send = (text) => {
    const t = (text ?? input).trim()
    if (!t || !ready) return
    setInput('')
    run([...msgs, { role: 'user', content: t }])
  }
  const stop = () => { if (abort.current) abort.current.abort() }
  const retry = () => run(msgs.slice(0, -1))
  const onKey = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }

  if (providers === null) return <div className="assistant"><p className="muted pad">Loading…</p></div>
  const any = providers.some((p) => p.configured)
  return (
    <div className="assistant">
      <div className="assistant-bar">
        <label>Provider
          <select value={provider} onChange={(e) => { setProvider(e.target.value); setModel('') }} disabled={busy}>
            {providers.map((p) => <option key={p.id} value={p.id}>{p.name}{p.configured ? '' : ' (no key)'}</option>)}
          </select>
        </label>
        <label>Model
          <select value={model} onChange={(e) => setModel(e.target.value)} disabled={busy || !models.list.length}>
            {models.list.length === 0 && <option value="">{models.state === 'loading' ? 'Loading…' : 'No models'}</option>}
            {models.list.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        </label>
        {(!picked || picked.effort) && (
          <label>Effort
            <select value={effort} onChange={(e) => setEffort(e.target.value)} disabled={busy}>
              {EFFORT.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
        )}
        <label className="check"><input type="checkbox" checked={ctx} onChange={(e) => setCtx(e.target.checked)} disabled={busy} />
          Use workspace analysis</label>
      </div>

      <div className="thread" role="log" aria-live="polite" aria-label="Conversation">
        {msgs.length === 0 && (
          <div className="empty">
            <div className="empty-mark"><Icon name="chat" size={26} /></div>
            {!any ? (
              <>
                <h2>Connect a model provider</h2>
                <p className="muted">Add a Claude or OpenAI API key to ask questions about your attack paths. Keys are stored in the system keychain.</p>
                <div className="actions center"><button className="primary" onClick={goSettings}>Open Settings</button></div>
              </>
            ) : !cfg.configured ? (
              <>
                <h2>No {cfg.name} key</h2>
                <p className="muted">Add a key for {cfg.name}, or choose another provider above.</p>
                <div className="actions center"><button onClick={goSettings}>Open Settings</button></div>
              </>
            ) : models.state === 'error' ? (
              <>
                <h2>Could not load models</h2>
                <p className="muted">{models.error}</p>
              </>
            ) : (
              <>
                <h2>Ask about your attack paths</h2>
                <p className="muted">
                  {workspaceEmpty && ctx ? 'The workspace is empty, so answers will not have findings to draw on yet.'
                    : 'Answers are grounded in the paths and fixes Paladin computed. Credentials are masked before anything is sent.'}
                </p>
                <div className="suggestions">
                  {SUGGESTIONS.map((s) => <button key={s} onClick={() => send(s)} disabled={!ready}>{s}</button>)}
                </div>
              </>
            )}
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div className="msg-role">{m.role === 'user' ? 'You' : (cfg ? cfg.name : 'Assistant')}</div>
            <div className="msg-body">{m.content}{m.streaming && <span className="caret" aria-hidden="true" />}</div>
            {m.error && <ErrorNote e={m.error} onRetry={retry} goSettings={goSettings} />}
            {m.stopped && <p className="muted small">Stopped.</p>}
            {m.stop && NOTE[m.stop] && <p className="muted small">{NOTE[m.stop]}</p>}
            {m.usage && m.usage.output > 0 && <p className="muted small">{m.usage.input} in · {m.usage.output} out tokens</p>}
          </div>
        ))}
        <div ref={end} />
      </div>

      <div className="composer">
        <textarea rows={2} value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={onKey}
                  placeholder={ready || busy ? 'Ask a question' : 'Choose a provider and model to begin'}
                  aria-label="Message" disabled={!cfg || !cfg.configured} />
        {busy
          ? <button onClick={stop}><Icon name="stop" size={14} />Stop</button>
          : <button className="primary" onClick={() => send()} disabled={!ready || !input.trim()}>Send</button>}
      </div>
    </div>
  )
}
