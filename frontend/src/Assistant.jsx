import { useCallback, useEffect, useRef, useState } from 'react'
import { api, chatStream } from './api.js'
import { usePrefs } from './prefs.jsx'
import { ago, fromStored } from './lib.js'
import { useStored } from './useStored.js'
import Icon from './Icons.jsx'
import { Skeleton } from './ui.jsx'

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

export default function Assistant({ goSettings, onSetup, workspaceEmpty, workspaceId }) {
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
  const [convs, setConvs] = useState(null)                   // null while loading
  const [cid, setCid] = useStored(`assistant-conversation-${workspaceId || 0}`, null)
  const cidRef = useRef(null)
  const sentRef = useRef(false)      // the user has sent a message in this view
  cidRef.current = cid
  const [loadErr, setLoadErr] = useState('')
  const [editing, setEditing] = useState(null)               // { id, title } while renaming
  const [confirmDel, setConfirmDel] = useState(null)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const abort = useRef(null)
  const end = useRef(null)
  const skipLoad = useRef(false)     // a conversation created by sending: its messages are already on screen

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

  const loadConvs = useCallback(async () => {
    try { const r = await api.conversations(); setConvs(r.conversations); setLoadErr(''); return r.conversations }
    catch (e) { setConvs((c) => c || []); setLoadErr(e.message); return null }
  }, [])
  useEffect(() => {
    loadConvs().then((list) => {
      if (!list) return
      const now = cidRef.current          // read at answer time: the user may have started a chat meanwhile
      if (now !== null && list.some((c) => c.id === now)) return
      if (now === null && (skipLoad.current || sentRef.current)) return   // a chat is already being started
      setCid(list[0] ? list[0].id : null)
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  // the selected conversation's messages always come from storage, so navigating away and back loses nothing
  useEffect(() => {
    if (skipLoad.current) { skipLoad.current = false; return undefined }
    if (abort.current) abort.current.abort()
    if (!cid) { setMsgs([]); return undefined }
    let live = true
    api.conversationMessages(cid).then((r) => live && setMsgs(r.messages.map(fromStored)))
      .catch((e) => { if (live) { setMsgs([]); if (e.status === 404) setCid(null); else setLoadErr(e.message) } })
    return () => { live = false }
  }, [cid]) // eslint-disable-line react-hooks/exhaustive-deps

  const run = useCallback(async (conv, text, { retry = false } = {}) => {
    const ac = new AbortController()
    abort.current = ac
    setBusy(true)
    setMsgs((m) => [...(retry ? m.filter((x, i) => !(i === m.length - 1 && x.role === 'assistant' && (x.error || x.interrupted))) : [...m, { role: 'user', content: text }]),
      { role: 'assistant', content: '', streaming: true }])
    const patch = (fn) => setMsgs((m) => { const c = [...m]; c[c.length - 1] = fn(c[c.length - 1]); return c })
    const clientId = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`
    await chatStream({ provider, model, effort: effort || null, include_context: ctx, conversation_id: conv, client_id: clientId,
      retry, messages: [{ role: 'user', content: text }] },
    (ev) => {
      if (ev.type === 'text') patch((m) => ({ ...m, content: m.content + ev.delta }))
      else if (ev.type === 'done') patch((m) => ({ ...m, streaming: false, stop: ev.stop_reason, usage: ev.usage }))
      else if (ev.type === 'error') patch((m) => ({ ...m, streaming: false, error: ev }))
    }, ac.signal)
    patch((m) => ({ ...m, streaming: false, stopped: ac.signal.aborted && !m.error && m.stop === undefined }))
    setBusy(false)
    loadConvs()                                   // new title and ordering after the first message
  }, [provider, model, effort, ctx, loadConvs])

  const send = async (text) => {
    const t = (text ?? input).trim()
    if (!t || !ready) return
    setInput('')
    sentRef.current = true
    let conv = cid
    if (!conv) {
      try { conv = (await api.createConversation()).id } catch (e) { setLoadErr(e.message); setInput(t); return }
      skipLoad.current = true
      setCid(conv)
    }
    run(conv, t)
  }
  const stop = () => { if (abort.current) abort.current.abort() }
  const lastUser = [...msgs].reverse().find((m) => m.role === 'user')
  const retry = () => lastUser && run(cid, lastUser.content, { retry: true })
  const newChat = () => { if (busy) stop(); setCid(null); setMsgs([]); setInput('') }
  const saveTitle = async () => {
    const e = editing
    setEditing(null)
    if (!e || !e.title.trim()) return
    try { await api.renameConversation(e.id, e.title); loadConvs() } catch (err) { setLoadErr(err.message) }
  }
  const remove = async (id) => {
    setConfirmDel(null)
    try { await api.deleteConversation(id); if (id === cid) newChat(); loadConvs() } catch (err) { setLoadErr(err.message) }
  }
  const onKey = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }

  if (providers === null) return <div className="assistant"><p className="muted pad">Loading…</p></div>
  const any = providers.some((p) => p.configured)
  return (
    <div className="assistant-shell">
      <aside className="chat-list" aria-label="Conversations in this workspace">
        <div className="chat-list-head">
          <span className="side-label">Chats</span>
          <button className="tool" onClick={newChat} aria-label="New chat" title="New chat"><Icon name="plus" size={14} /></button>
        </div>
        {convs === null && <Skeleton lines={4} />}
        {convs && convs.length === 0 && <p className="muted small chat-list-empty">No saved chats in this workspace yet.</p>}
        <ul role="listbox" aria-label="Chats">
          {(convs || []).map((c) => (
            <li key={c.id} role="option" aria-selected={c.id === cid} className={c.id === cid ? 'chat-item on' : 'chat-item'}>
              {editing && editing.id === c.id ? (
                <input autoFocus value={editing.title} aria-label="Chat title" maxLength={120}
                       onChange={(e) => setEditing({ id: c.id, title: e.target.value })} onBlur={saveTitle}
                       onKeyDown={(e) => { if (e.key === 'Enter') saveTitle(); if (e.key === 'Escape') setEditing(null) }} />
              ) : confirmDel === c.id ? (
                <span className="chat-confirm">Delete this chat?
                  <button className="danger small-btn" onClick={() => remove(c.id)}>Delete</button>
                  <button className="small-btn" onClick={() => setConfirmDel(null)}>Cancel</button></span>
              ) : (
                <>
                  <button className="chat-open" onClick={() => setCid(c.id)} onDoubleClick={() => setEditing({ id: c.id, title: c.title })}>
                    <span className="chat-title">{c.title}</span><span className="muted small">{ago(c.updated)}</span>
                  </button>
                  <span className="chat-actions">
                    <button className="tool" aria-label={`Rename ${c.title}`} title="Rename" onClick={() => setEditing({ id: c.id, title: c.title })}><Icon name="edit" size={12} /></button>
                    <button className="tool" aria-label={`Delete ${c.title}`} title="Delete" onClick={() => setConfirmDel(c.id)}><Icon name="trash" size={12} /></button>
                  </span>
                </>
              )}
            </li>
          ))}
        </ul>
        {loadErr && <p className="err small" role="alert">{loadErr} <button className="link" onClick={loadConvs}>Retry</button></p>}
      </aside>
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
                <div className="actions center"><button className="primary" onClick={onSetup}>Set Up a Provider</button><button onClick={goSettings}>Open Settings</button></div>
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
          <div key={m.id || `local-${i}`} className={`msg ${m.role}`}>
            <div className="msg-role">{m.role === 'user' ? 'You' : (cfg ? cfg.name : 'Assistant')}</div>
            <div className="msg-body">{m.content}{m.streaming && <span className="caret" aria-hidden="true" />}</div>
            {m.error && <ErrorNote e={m.error} onRetry={retry} goSettings={goSettings} />}
            {m.stopped && <p className="muted small">Stopped.</p>}
            {m.interrupted && <p className="muted small">This reply was cut off when Paladin closed. <button className="link" onClick={retry} disabled={!ready}>Ask again</button></p>}
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
    </div>
  )
}
