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

  return (
    <div className="scrim" role="presentation">
      <div className="dialog onboard" role="dialog" aria-modal="true" aria-labelledby="ob-t" tabIndex={-1} ref={(el) => el && !el.contains(document.activeElement) && el.focus()}>
        <div className="ob-steps" aria-label={`Step ${step + 1} of ${STEPS.length}`}>
          {STEPS.map((s, i) => <span key={s} className={i === step ? 'dot on' : i < step ? 'dot done' : 'dot'} title={s} />)}
        </div>

        {step === 0 && (
          <section>
            <span className="brand big"><span className="brand-mark" aria-hidden="true" />Paladin</span>
            <h2 id="ob-t">{first ? `Welcome, ${first}.` : 'Welcome.'}</h2>
            <p className="muted">Paladin turns logs and repository scans into ranked attack paths, then shows the cheapest
              fix that cuts the most of them. Setup takes a minute and every step is optional.</p>
            <ul className="login-points">
              <li><Icon name="github" size={14} /> Connect GitHub to scan your repositories</li>
              <li><Icon name="chat" size={14} /> Add a model key for the assistant and AI review</li>
              <li><Icon name="play" size={14} /> Start from a sample scenario or your own repository</li>
            </ul>
          </section>
        )}

        {step === 1 && (
          <section>
            <h2 id="ob-t">Connect GitHub</h2>
            {ghMode === 'app' && config.github ? (
              <>
                <p className="muted">Choose which repositories Paladin may read. Pull requests with fixes only ever go to a
                  separate <code>fixes</code> branch. You will return here afterwards.</p>
                <button className="primary" disabled={busy} onClick={connectGithub}><Icon name="github" size={16} /> Install the GitHub App</button>
              </>
            ) : ghMode === 'app' ? (
              <p className="muted">Repository access is not configured on this server. Public repositories can still be
                scanned by pasting a link, so you can skip this.</p>
            ) : canStoreKeys ? (
              <>
                <p className="muted">Paste a personal access token to search your repositories, open private ones, and
                  create pull requests. It is stored in your system keychain.</p>
                <div className="ob-row">
                  <input type="password" autoComplete="off" spellCheck={false} placeholder="GitHub token" value={secret}
                         disabled={busy} onChange={(e) => setSecret(e.target.value.trim())} />
                  <button className="primary" disabled={!secret || busy} onClick={() => saveSecret('githubToken')}>Save</button>
                </div>
                {saved.githubToken && <p className="ok-text small">Token saved.</p>}
              </>
            ) : (
              <p className="muted">Public repositories work with just a link. A token is set on the server for private ones.</p>
            )}
            {err && <p className="err" role="alert">{err}</p>}
          </section>
        )}

        {step === 2 && (
          <section>
            <h2 id="ob-t">Add a model key</h2>
            <p className="muted">Powers the assistant and AI review of findings. Paladin works without it.</p>
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
                  <button className="primary" disabled={!secret || busy} onClick={() => saveSecret(p.field)}>Save</button>
                </div>
                {saved[p.field] && <p className="ok-text small">{p.name} key saved to your keychain.</p>}
              </>
            ) : (
              <p className="small">
                <span className={`pill ${modelReady ? 'ok' : 'mute'}`}>{modelReady ? 'Set on the server' : 'Not set'}</span>{' '}
                <span className="muted">{modelReady
                  ? 'The assistant is ready to use.'
                  : 'On the web version keys are configured by the server administrator. Your own key can be stored in the desktop app.'}</span>
              </p>
            )}
            {err && <p className="err" role="alert">{err}</p>}
          </section>
        )}

        {step === 3 && (
          <section>
            <h2 id="ob-t">Where to start?</h2>
            <p className="muted">You can change any of this later in Settings.</p>
            <div className="ob-choices">
              {canPlay && (
                <button className="ob-choice" onClick={() => onFinish('sample')}>
                  <Icon name="play" size={18} /><span><b>Try the sample scenario</b>
                    <span className="muted small">Replay a realistic attack and see the ranked paths.</span></span>
                </button>
              )}
              <button className="ob-choice" onClick={() => onFinish('repo')}>
                <Icon name="repo" size={18} /><span><b>Open a repository</b>
                  <span className="muted small">Paste a GitHub link{config.desktop ? ' or choose a local folder' : ''}.</span></span>
              </button>
              <button className="ob-choice" onClick={() => onFinish('explore')}>
                <Icon name="home" size={18} /><span><b>Explore on my own</b>
                  <span className="muted small">Go to Home.</span></span>
              </button>
            </div>
          </section>
        )}

        <div className="actions ob-actions">
          {step > 0 ? <button onClick={back}>Back</button> : <button className="link" onClick={() => onFinish('skip')}>Skip setup</button>}
          <span className="spacer" />
          {step < STEPS.length - 1 && (
            <button className="primary" onClick={next}>{step === 0 ? 'Get started' : (step === 1 || step === 2) && !(saved.githubToken || modelReady) ? 'Skip' : 'Continue'}</button>
          )}
        </div>
      </div>
    </div>
  )
}
