import { useEffect, useState } from 'react'
import Icon from './Icons.jsx'
import { api } from './api.js'

const bridge = typeof window !== 'undefined' ? window.paladin : undefined
const STEPS = ['Welcome', 'GitHub', 'Model', 'Start']
const PROVIDERS = [
  { id: 'anthropic', name: 'Claude', field: 'anthropicApiKey', hint: 'Anthropic API key' },
  { id: 'openai', name: 'OpenAI', field: 'openaiApiKey', hint: 'OpenAI API key' },
]

/** First-run guide: what Paladin does, optional GitHub and model keys, then a way in. Every step can be skipped. */
export default function Onboarding({ config, user, canPlay, onFinish }) {
  const [step, setStep] = useState(0)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [provider, setProvider] = useState('anthropic')
  const [secret, setSecret] = useState('')
  const [saved, setSaved] = useState({})
  const providers = config.providers || {}
  const canStoreKeys = Boolean(config.desktop && bridge)
  const first = (user && (user.name || user.login) || '').split(' ')[0]

  useEffect(() => { setErr(''); setSecret('') }, [step, provider])
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onFinish('skip') }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onFinish])

  const next = () => setStep((n) => Math.min(STEPS.length - 1, n + 1))
  const back = () => setStep((n) => Math.max(0, n - 1))

  const connectGithub = async () => {
    setBusy(true); setErr('')
    try {
      const { url } = await api.githubInstallUrl()
      if (typeof url !== 'string' || !url.startsWith('https://github.com/')) throw new Error('Unexpected install address')
      await onFinish('github', { keepOpen: true })       // remember the guide was seen before leaving the page
      window.location.assign(url)
    } catch (e) { setBusy(false); setErr(e.message || 'Could not start connecting GitHub.') }
  }
  const saveSecret = async (field) => {
    if (!secret || !bridge) return
    setBusy(true); setErr('')
    try { await bridge.setSettings({ [field]: secret }); setSaved((s) => ({ ...s, [field]: true })); setSecret('') }
    catch (e) { setErr(e.message || 'Could not save the key.') } finally { setBusy(false) }
  }

  const ghMode = config.github_mode
  const p = PROVIDERS.find((x) => x.id === provider)
  const modelReady = providers.anthropic || providers.openai || saved.anthropicApiKey || saved.openaiApiKey

  const lead = step === 0 ? (first ? `Hi ${first}.` : 'Hi there.') : step === 1 ? 'Bring your code.' : step === 2 ? 'Give it a brain.' : 'Pick a starting point.'
  const sub = step === 0
    ? 'Paladin turns your logs and repositories into ranked attack paths, then shows the cheapest fix. Let’s get you set up in a minute.'
    : step === 1 ? 'Connect GitHub so Paladin can read the repositories you choose.'
      : step === 2 ? 'Add a model key to unlock the assistant and AI review. Paladin works without one.'
        : 'You can change all of this later in Settings.'
  const primary = step === 0 ? 'Get started'
    : step < 3 ? ((step === 1 ? saved.githubToken : modelReady) ? 'Continue' : 'Skip for now') : null

  return (
    <div className="ob-screen" role="dialog" aria-modal="true" aria-labelledby="ob-t" tabIndex={-1}
         ref={(el) => el && !el.contains(document.activeElement) && el.focus()}>
      <header className="ob-top">
        <span className="brand"><span className="brand-mark" aria-hidden="true" />Paladin</span>
        <button className="link ob-skip" onClick={() => onFinish('skip')}>Skip setup</button>
      </header>

      <main className="ob-stage" key={step}>
        <h1 id="ob-t" className="ob-lead">{lead}</h1>
        <p className="ob-sub">{sub}</p>

        <div className="ob-body">
          {step === 0 && (
            <ul className="ob-tiles">
              <li><span className="ob-ico"><Icon name="graph" size={18} /></span><span><b>Ranked attack paths</b><small>From the signals you already have.</small></span></li>
              <li><span className="ob-ico"><Icon name="check" size={18} /></span><span><b>The cheapest fix</b><small>And exactly which paths it removes.</small></span></li>
              <li><span className="ob-ico"><Icon name="repo" size={18} /></span><span><b>Tracked to a merged PR</b><small>Remediation from finding to fix.</small></span></li>
            </ul>
          )}

          {step === 1 && (
            <div className="ob-card">
              {ghMode === 'app' && config.github ? (
                <>
                  <button className="ob-cta" disabled={busy} onClick={connectGithub}><Icon name="github" size={18} /> Connect GitHub</button>
                  <p className="ob-note">You choose the repositories. Fixes only ever go to a separate <code>fixes</code> branch.</p>
                </>
              ) : ghMode === 'app' ? (
                <p className="ob-note">Repository access isn’t configured on this server. Public repositories still work by pasting a link.</p>
              ) : canStoreKeys ? (
                <>
                  <div className="ob-row">
                    <input type="password" autoComplete="off" spellCheck={false} placeholder="GitHub personal access token" value={secret}
                           disabled={busy} onChange={(e) => setSecret(e.target.value.trim())} />
                    <button className="ob-pill" disabled={!secret || busy} onClick={() => saveSecret('githubToken')}>Save</button>
                  </div>
                  <p className="ob-note">{saved.githubToken ? 'Saved to your system keychain.' : 'Stored in your system keychain, never on a server.'}</p>
                </>
              ) : (
                <p className="ob-note">Public repositories work with just a link. A token is configured on the server for private ones.</p>
              )}
              {err && <p className="ob-err" role="alert">{err}</p>}
            </div>
          )}

          {step === 2 && (
            <div className="ob-card">
              {canStoreKeys ? (
                <>
                  <div className="ob-seg" role="radiogroup" aria-label="Provider">
                    {PROVIDERS.map((x) => (
                      <button key={x.id} role="radio" aria-checked={provider === x.id} className={provider === x.id ? 'on' : ''}
                              onClick={() => setProvider(x.id)}>{x.name}</button>
                    ))}
                  </div>
                  <div className="ob-row">
                    <input type="password" autoComplete="off" spellCheck={false} placeholder={p.hint} value={secret}
                           disabled={busy} onChange={(e) => setSecret(e.target.value.trim())} />
                    <button className="ob-pill" disabled={!secret || busy} onClick={() => saveSecret(p.field)}>Save</button>
                  </div>
                  <p className="ob-note">{saved[p.field] ? `${p.name} key saved to your keychain.` : 'Stored in your system keychain, never on a server.'}</p>
                </>
              ) : (
                <p className="ob-note">
                  <span className={`ob-status ${modelReady ? 'on' : ''}`}>{modelReady ? 'Ready' : 'Not set'}</span>{' '}
                  {modelReady ? 'This server already has a model key, so the assistant works.'
                    : 'On the web, model keys are set by the server administrator. Store your own in the desktop app.'}
                </p>
              )}
              {err && <p className="ob-err" role="alert">{err}</p>}
            </div>
          )}

          {step === 3 && (
            <div className="ob-choices">
              {canPlay && (
                <button className="ob-choice" onClick={() => onFinish('sample')}>
                  <span className="ob-ico"><Icon name="play" size={18} /></span>
                  <span><b>Try the sample scenario</b><small>Replay a realistic attack and watch the paths rank.</small></span>
                </button>
              )}
              <button className="ob-choice" onClick={() => onFinish('repo')}>
                <span className="ob-ico"><Icon name="repo" size={18} /></span>
                <span><b>Open a repository</b><small>Paste a GitHub link{config.desktop ? ' or choose a local folder' : ''}.</small></span>
              </button>
              <button className="ob-choice" onClick={() => onFinish('explore')}>
                <span className="ob-ico"><Icon name="home" size={18} /></span>
                <span><b>Look around first</b><small>Go to Home and explore.</small></span>
              </button>
            </div>
          )}
        </div>
      </main>

      <footer className="ob-bottom">
        <button className="ob-back" onClick={back} disabled={step === 0} aria-label="Back"><Icon name="chevron" size={18} /></button>
        <div className="ob-dots" aria-label={`Step ${step + 1} of ${STEPS.length}`}>
          {STEPS.map((s, i) => <span key={s} className={i === step ? 'd on' : i < step ? 'd done' : 'd'} />)}
        </div>
        {primary ? <button className="ob-next" onClick={next}>{primary}</button> : <span className="ob-next ghost" aria-hidden="true" />}
      </footer>
    </div>
  )
}
