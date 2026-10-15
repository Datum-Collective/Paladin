// First-run setup: what Paladin does, then provider -> key -> model -> a real test call. Nothing is marked done
// until that test call succeeds with the saved key and chosen model.
import { useCallback, useEffect, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { AlertCircle, ArrowLeft, ArrowRight, Check, CheckCircle2, Eye, EyeOff, KeyRound, Loader2, X } from 'lucide-react'
import { api } from './api.js'
import { keyProblem, setupAdvice } from './lib.js'
import { usePrefs } from './prefs.jsx'
import { useStored } from './useStored.js'
import { Skeleton } from './ui.jsx'

const getBridge = () => (typeof window !== 'undefined' ? window.paladin : undefined)

export const PROVIDERS = [
  { id: 'anthropic', name: 'Claude', maker: 'Anthropic', field: 'anthropicApiKey', env: 'ANTHROPIC_API_KEY', where: 'console.anthropic.com',
    blurb: 'Strong at explaining attack paths step by step.' },
  { id: 'openai', name: 'OpenAI', maker: 'OpenAI', field: 'openaiApiKey', env: 'OPENAI_API_KEY', where: 'platform.openai.com',
    blurb: 'GPT models, if that is the account you already have.' },
]
const STEPS = [
  { id: 'provider', label: 'Provider' },
  { id: 'key', label: 'API key' }, { id: 'model', label: 'Model' }, { id: 'test', label: 'Test' }, { id: 'done', label: 'Ready' },
]
const IDS = STEPS.map((s) => s.id)

function Reveal({ children, k }) {
  const reduce = useReducedMotion()
  return (
    <motion.div key={k} initial={reduce ? false : { opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.2 }}>
      {children}
    </motion.div>
  )
}

function ErrorBox({ error }) {
  if (!error) return null
  return (
    <div className="setup-error" role="alert">
      <AlertCircle size={16} aria-hidden="true" />
      <div><b>{error.message}</b>{error.hint && <span className="muted"> {error.hint}</span>}
        {error.request_id && <div className="muted small mono">Request {error.request_id}</div>}</div>
    </div>
  )
}

function ProviderStep({ value, onChange, keyState }) {
  return (
    <>
      <h2 id="setup-title" tabIndex={-1}>Choose your model provider</h2>
      <p className="muted">You can switch later in Settings. Only the provider you pick receives your questions.</p>
      <div className="setup-cards" role="radiogroup" aria-label="Model provider">
        {PROVIDERS.map((p) => (
          <button key={p.id} role="radio" aria-checked={value === p.id} className={value === p.id ? 'setup-card on' : 'setup-card'} onClick={() => onChange(p.id)}>
            <span className="setup-card-top"><b>{p.name}</b>{keyState[p.id] && <span className="pill ok">Key saved</span>}</span>
            <span className="muted">{p.blurb}</span>
            <span className="muted small">{p.maker}</span>
          </button>
        ))}
      </div>
    </>
  )
}

function KeyStep({ provider, env, onVerified, back }) {
  const p = PROVIDERS.find((x) => x.id === provider)
  const [v, setV] = useState('')
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [local, setLocal] = useState('')
  const hasKey = env.desktop ? env.stored && env.stored[p.field] : env.server[provider]
  const canEdit = env.desktop && env.stored && env.stored.encryptionAvailable
  const problem = keyProblem(provider, v)

  const verify = useCallback(async () => {
    setBusy(true); setErr(null)
    const r = await api.validate(provider).catch((e) => ({ ok: false, error: { kind: 'network', message: e.message, hint: '' } }))
    setBusy(false)
    if (r.ok) onVerified()
    else setErr(r.error)
    return r.ok
  }, [provider, onVerified])

  const save = async () => {
    setBusy(true); setErr(null); setLocal('')
    try {
      const b = getBridge()
      if (!b || !b.setSettings) throw new Error('Saving keys needs the desktop app.')
      await b.setSettings({ [p.field]: v })
    } catch (e) { setBusy(false); setLocal(e.message || 'Could not save the key.'); return }
    const ok = await verify()
    if (ok) setV('')
    else if (!hasKey) {
      // a brand-new key the provider rejected is not worth keeping; a replacement is left alone, because the
      // previous key is already overwritten and a network blip must not read as "bad key"
      const b = getBridge()
      if (b && b.setSettings) await Promise.resolve(b.setSettings({ [p.field]: null })).catch(() => {})
    }
    await env.refresh()
  }

  return (
    <>
      <h2 id="setup-title" tabIndex={-1}>Add your {p.name} API key</h2>
      {env.desktop && env.stored && !env.stored.encryptionAvailable && (
        <p className="notice warn">Secure storage is unavailable on this system, so a key cannot be saved here.</p>
      )}
      {hasKey && (
        <div className="setup-saved"><CheckCircle2 size={16} aria-hidden="true" /> A {p.name} key is already set.
          <button className="primary" disabled={busy} onClick={verify}>{busy ? 'Checking…' : 'Use this key'}</button></div>
      )}
      {canEdit && (
        <>
          <label className="setup-field" htmlFor="setup-key">{hasKey ? 'Or replace it' : `${p.name} API key`}</label>
          <div className="setup-keyrow">
            <KeyRound size={16} aria-hidden="true" />
            <input id="setup-key" type={show ? 'text' : 'password'} autoComplete="off" spellCheck={false} value={v} disabled={busy}
                   placeholder={provider === 'anthropic' ? 'sk-ant-…' : 'sk-…'} aria-invalid={Boolean(problem)} aria-describedby="setup-key-help"
                   onChange={(e) => setV(e.target.value.trim())}
                   onKeyDown={(e) => { if (e.key === 'Enter' && v && !problem && !busy) save() }} />
            <button className="tool" type="button" onClick={() => setShow((s) => !s)} aria-label={show ? 'Hide key' : 'Show key'} aria-pressed={show}>
              {show ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
          <p id="setup-key-help" className={problem ? 'err small' : 'muted small'}>
            {problem || `Create one at ${p.where}. It is stored in your system keychain and never shown again.`}
          </p>
          <button className="primary" disabled={!v || Boolean(problem) || busy} onClick={save}>
            {busy ? <><Loader2 size={14} className="spin" aria-hidden="true" /> Checking…</> : 'Save and check key'}
          </button>
        </>
      )}
      {!env.desktop && !hasKey && (
        <div className="notice">
          <b>This server has no {p.name} key.</b> Keys on the web version are set by whoever runs the server, as
          <code> {p.env}</code>. Ask them to add it, then check again, or choose the other provider.
          <div className="actions"><button onClick={env.refresh}>Check again</button><button onClick={back}>Choose another provider</button></div>
        </div>
      )}
      {local && <p className="err" role="alert">{local}</p>}
      <ErrorBox error={err} />
    </>
  )
}

function ModelStep({ provider, model, onPick }) {
  const [state, setState] = useState({ phase: 'loading', list: [], error: '' })
  const load = useCallback(() => {
    setState({ phase: 'loading', list: [], error: '' })
    api.models(provider).then((r) => setState({ phase: 'ok', list: r.models, error: '' }))
      .catch((e) => setState({ phase: 'bad', list: [], error: e.message }))
  }, [provider])
  useEffect(load, [load])
  useEffect(() => {
    if (state.phase === 'ok' && state.list.length && !state.list.some((m) => m.id === model)) onPick(state.list[0].id)
  }, [state, model, onPick])
  return (
    <>
      <h2 id="setup-title" tabIndex={-1}>Pick a model</h2>
      <p className="muted">These are the models your key can use right now.</p>
      {state.phase === 'loading' && <Skeleton lines={4} />}
      {state.phase === 'bad' && (
        <div className="setup-error" role="alert"><AlertCircle size={16} aria-hidden="true" /><div>{state.error}
          <div className="actions"><button onClick={load}>Try again</button></div></div></div>
      )}
      {state.phase === 'ok' && state.list.length === 0 && <p className="notice warn">This key has no models available. Check the account on the provider’s site.</p>}
      {state.phase === 'ok' && state.list.length > 0 && (
        <div className="setup-models" role="radiogroup" aria-label="Model">
          {state.list.map((m) => (
            <button key={m.id} role="radio" aria-checked={model === m.id} className={model === m.id ? 'setup-model on' : 'setup-model'} onClick={() => onPick(m.id)}>
              <span>{m.name || m.id}</span>{model === m.id && <Check size={14} aria-hidden="true" />}
            </button>
          ))}
        </div>
      )}
    </>
  )
}

function TestStep({ result, running, run, advice, goto }) {
  return (
    <>
      <h2 id="setup-title" tabIndex={-1}>Testing the connection</h2>
      <p className="muted">Paladin sends one tiny message with your saved key and chosen model, the same way the assistant will.</p>
      <div className="setup-status" role="status" aria-live="polite">
        {running && <><Loader2 size={18} className="spin" aria-hidden="true" /> Contacting the provider…</>}
        {!running && result && result.ok && <><CheckCircle2 size={18} aria-hidden="true" /> Connected. The model answered.</>}
      </div>
      {!running && result && !result.ok && (
        <>
          <ErrorBox error={result.error} />
          <div className="actions">
            {advice.goto === 'key' && <button className="primary" onClick={() => goto('key')}>Replace the key</button>}
            {advice.goto === 'model' && <button className="primary" onClick={() => goto('model')}>Choose another model</button>}
            {advice.retry && <button className="primary" onClick={run}>Try again</button>}
            {!advice.retry && advice.goto !== 'key' && <button onClick={run}>Test again</button>}
          </div>
        </>
      )}
    </>
  )
}

function Done({ provider, model, openAssistant, finish }) {
  const p = PROVIDERS.find((x) => x.id === provider)
  return (
    <>
      <div className="setup-mark ok"><CheckCircle2 size={24} aria-hidden="true" /></div>
      <h2 id="setup-title" tabIndex={-1}>You’re all set</h2>
      <p>Paladin will use <b>{p.name}</b> with <span className="mono">{model}</span>. Change this any time in Settings → Models & Providers.</p>
      <div className="actions">
        <button className="primary" onClick={finish}>Start scanning</button>
        <button onClick={openAssistant}>Open the assistant</button>
      </div>
    </>
  )
}

/** Props: config, onClose(), onOpenAssistant(). Closing before the test passes records "set up later". */
export default function Setup({ config, onClose, onOpenAssistant, embedded = false, onComplete }) {
  const { prefs, set } = usePrefs()
  const reduce = useReducedMotion()
  const [step, setStep] = useStored('setup-step', 'provider')
  const [provider, setProvider] = useStored('setup-provider', prefs['assistant.provider'] || 'anthropic')
  const [model, setModel] = useState(prefs['assistant.model'] || '')
  const [env, setEnv] = useState({ desktop: Boolean(config.desktop && getBridge()), stored: null, server: config.providers || {} })
  const [test, setTest] = useState({ running: false, result: null })
  const [keyOk, setKeyOk] = useState(false)
  const root = useRef(null)
  const idx = Math.max(0, IDS.indexOf(step))
  // an interrupted run resumes at the provider step: the test result and model choice are not remembered
  useEffect(() => { if (step !== 'provider') setStep('provider') }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = useCallback(async () => {
    const [stored, list] = await Promise.all([
      getBridge() && getBridge().getSettings ? getBridge().getSettings().catch(() => null) : null,
      api.providers().catch(() => null),
    ])
    setEnv((e) => ({ ...e, stored, server: list ? Object.fromEntries(list.providers.map((p) => [p.id, p.configured])) : e.server }))
  }, [])
  useEffect(() => { refresh() }, [refresh])

  const configured = (id) => {
    const p = PROVIDERS.find((x) => x.id === id)
    return env.desktop ? Boolean(env.stored && env.stored[p.field]) : Boolean(env.server[id])
  }
  const keyState = Object.fromEntries(PROVIDERS.map((p) => [p.id, configured(p.id)]))

  const go = useCallback((id) => { setStep(id); setKeyOk(false) }, [setStep])
  const next = () => go(IDS[Math.min(idx + 1, IDS.length - 1)])
  const prev = () => go(IDS[Math.max(idx - 1, 0)])

  const close = useCallback(async () => {
    setStep('provider')
    onClose()                                   // always leave, even if recording "later" fails
    if (step !== 'done') { try { await set('general.setup_skipped', true) } catch { /* preference stays unset */ } }
  }, [step, set, setStep, onClose])
  const finish = async () => { setStep('provider'); onClose() }

  useEffect(() => {
    const el = root.current && root.current.querySelector('#setup-title')
    if (el) el.focus()
  }, [step])

  const runTest = useCallback(async () => {
    setTest({ running: true, result: null })
    let result
    try { result = await api.testProvider(provider, model) } catch (e) {
      result = { ok: false, error: { kind: 'network', message: e.message || 'Could not reach Paladin’s engine.', hint: 'Check your connection and try again.' } }
    }
    if (result.ok) {
      // the configuration is only recorded once a real round trip has succeeded
      try {
        for (const [k, v] of [['assistant.provider', provider], ['assistant.model', model], ['general.setup_skipped', false], ['general.setup_done', true]]) await set(k, v)
      } catch (e) {
        setTest({ running: false, result: { ok: false, error: { kind: 'server', message: 'The connection works, but the choice could not be saved.', hint: e.message || 'Try again.' } } })
        return
      }
      setTest({ running: false, result })
      setStep('done')
      if (onComplete) onComplete({ provider, model })
      return
    }
    setTest({ running: false, result })
  }, [provider, model, set, setStep])
  useEffect(() => { if (step === 'test' && !test.running && !test.result && model) runTest() }, [step])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (step !== 'test') setTest({ running: false, result: null }) }, [step])

  // Esc leaves; Enter on a step with a single obvious action continues
  const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); close() } }

  const canNext = { provider: Boolean(provider), key: keyOk || configured(provider), model: Boolean(model) }[step]
  const needsKeyCheck = step === 'key' && configured(provider) && !keyOk
  const advice = setupAdvice(test.result && test.result.error)
  const stepBody = {
    provider: <ProviderStep value={provider} onChange={(p) => { setProvider(p); setModel('') }} keyState={keyState} />,
    key: <KeyStep provider={provider} env={{ ...env, refresh }} onVerified={() => { setKeyOk(true); setStep('model') }} back={() => go('provider')} />,
    model: <ModelStep provider={provider} model={model} onPick={setModel} />,
    test: <TestStep result={test.result} running={test.running} run={runTest} advice={advice} goto={go} />,
    done: <Done provider={provider} model={model} openAssistant={() => { finish(); onOpenAssistant() }} finish={finish} />,
  }[step]

  const body = <Reveal k={step}>{stepBody}</Reveal>
  if (embedded) {
    return (
      <div className="setup-embedded" ref={root}>
        <ol className="setup-progress" aria-label="Model setup progress">
          {STEPS.slice(0, -1).map((s, n) => <li key={s.id} className={n === idx ? 'on' : n < idx ? 'done' : ''}>{s.label}</li>)}
        </ol>
        {step === 'done' ? (
          <div className="setup-status" role="status"><CheckCircle2 size={18} aria-hidden="true" /> Connected to {PROVIDERS.find((x) => x.id === provider).name} · <span className="mono">{model}</span></div>
        ) : body}
        {step !== 'done' && step !== 'key' && (
          <div className="actions">
            {idx > 0 && step !== 'test' && <button onClick={prev}><ArrowLeft size={14} aria-hidden="true" />Back</button>}
            {step === 'test' && !test.running && <button onClick={prev}><ArrowLeft size={14} aria-hidden="true" />Back</button>}
            {step !== 'test' && <button className="primary" disabled={!canNext || needsKeyCheck} onClick={next}>
              {step === 'model' ? 'Test connection' : 'Continue'}<ArrowRight size={14} aria-hidden="true" /></button>}
          </div>
        )}
        {step === 'key' && configured(provider) && !keyOk && null}
      </div>
    )
  }
  return (
    <div className="scrim setup-scrim" onKeyDown={onKey}>
      <div className="setup" role="dialog" aria-modal="true" aria-labelledby="setup-title" ref={root}>
        <aside className="setup-rail" aria-label="Setup progress">
          <span className="brand"><span className="brand-mark" aria-hidden="true" />Paladin</span>
          <ol>
            {STEPS.map((s, i) => (
              <li key={s.id} className={i === idx ? 'on' : i < idx ? 'done' : ''} aria-current={i === idx ? 'step' : undefined}>
                <span className="setup-dot">{i < idx ? <Check size={11} aria-hidden="true" /> : i + 1}</span>{s.label}
              </li>
            ))}
          </ol>
        </aside>
        <section className="setup-main">
          <div className="setup-bar" aria-hidden="true"><motion.span animate={{ width: `${(idx / (STEPS.length - 1)) * 100}%` }} transition={reduce ? { duration: 0 } : { duration: 0.3 }} /></div>
          <button className="tool setup-x" onClick={close} aria-label="Close setup"><X size={16} /></button>
          <div className="setup-body" aria-live="off">
            {body}
          </div>
          {step !== 'done' && step !== 'test' && (
            <footer className="setup-foot">
              <button className="plain-btn" onClick={close}>Set up later</button>
              <span className="spacer" />
              {idx > 0 && <button onClick={prev}><ArrowLeft size={14} aria-hidden="true" />Back</button>}
              {step === 'key' && !keyOk && !configured(provider) ? null : (
                <button className="primary" disabled={!canNext || needsKeyCheck} onClick={next} title={needsKeyCheck ? 'Use or replace the saved key first' : undefined}>
                  {step === 'model' ? 'Test connection' : 'Continue'}<ArrowRight size={14} aria-hidden="true" />
                </button>
              )}
            </footer>
          )}
          {step === 'test' && (
            <footer className="setup-foot"><button className="plain-btn" onClick={close}>Set up later</button><span className="spacer" />
              <button onClick={prev} disabled={test.running}><ArrowLeft size={14} aria-hidden="true" />Back</button></footer>
          )}
        </section>
      </div>
    </div>
  )
}
