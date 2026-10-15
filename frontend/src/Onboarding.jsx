import { useCallback, useEffect, useRef, useState } from 'react'
import Icon from './Icons.jsx'
import { api } from './api.js'
import Setup from './Setup.jsx'

const bridge = typeof window !== 'undefined' ? window.paladin : undefined
const FEATURES = [
  { id: 'paths', icon: 'graph', title: 'Ranked attack paths',
    text: 'Logs, scans and your asset map are joined into the routes an attacker could actually take, ordered by real risk.' },
  { id: 'fix', icon: 'check', title: 'The cheapest fix',
    text: 'One change, chosen to cut the most paths for the least effort, with the exact paths it removes shown up front.' },
  { id: 'track', icon: 'repo', title: 'Tracked to a merged PR',
    text: 'Propose, review, open the pull request and verify. Every step is recorded so nothing quietly goes stale.' },
]
// order matters for the dots and the sun: welcome, what it does, github, model, start, done
const ORDER = ['welcome', 'features', 'github', 'model', 'start', 'done']

/** Attack graph that draws itself: an attacker's route lights up, then the cheapest cut severs it. */
function HeroGraph() {
  const N = { i: [46, 150], w: [170, 70], v: [170, 236], a: [320, 150], d: [468, 78], x: [468, 232], c: [596, 150] }
  const E = [['i', 'w'], ['i', 'v'], ['w', 'a'], ['v', 'a'], ['a', 'd'], ['a', 'x'], ['d', 'c'], ['x', 'c']]
  const path = ['i', 'w', 'a', 'd', 'c']
  const pt = (k) => N[k].join(',')
  const label = { i: 'Internet', w: 'Web', v: 'VPN', a: 'App', d: 'Database', x: 'Admin', c: 'Crown jewels' }
  return (
    <svg className="hero-graph" viewBox="0 0 660 300" role="img" aria-label="An attack path from the internet to the crown jewels being cut at one edge">
      {E.map(([a, b]) => <line key={a + b} className="g-edge" x1={N[a][0]} y1={N[a][1]} x2={N[b][0]} y2={N[b][1]} />)}
      <polyline className="g-path" points={path.map(pt).join(' ')} pathLength="1" />
      <g transform={`translate(${(N.a[0] + N.d[0]) / 2} ${(N.a[1] + N.d[1]) / 2})`}>
        <g className="g-cut"><circle r="15" /><path d="M-5 -5L5 5M5 -5L-5 5" /></g>
      </g>
      {Object.entries(N).map(([k, [x, y]], n) => (
        <g key={k} transform={`translate(${x} ${y})`}>
          <g className={`g-node${k === 'c' ? ' crown' : ''}${path.includes(k) ? ' on' : ''}`} style={{ '--n': n }}>
            <circle r={k === 'c' ? 17 : 11} />
            <text y={k === 'c' ? 36 : 28} textAnchor="middle">{label[k]}</text>
          </g>
        </g>
      ))}
    </svg>
  )
}

function FeatureArt({ id }) {
  if (id === 'paths') {
    return (
      <div className="art art-paths" aria-hidden="true">
        {[['Internet → Web → App → Database', 92], ['Phishing → Laptop → AD → File server', 71], ['VPN → Admin panel → Backups', 48]].map(([t, r], i) => (
          <div key={t} className="art-row" style={{ '--i': i }}><span>{t}</span><i style={{ '--w': `${r}%` }} /><b>{(r / 10).toFixed(1)}</b></div>
        ))}
      </div>
    )
  }
  if (id === 'fix') {
    return (
      <div className="art art-fix" aria-hidden="true">
        <div className="art-file">nginx/default.conf</div>
        <div className="art-line del" style={{ '--i': 0 }}>- allow all;</div>
        <div className="art-line add" style={{ '--i': 1 }}>+ allow 10.0.0.0/8;</div>
        <div className="art-line add" style={{ '--i': 2 }}>+ deny all;</div>
        <div className="art-chip">Cuts 6 of 9 paths</div>
      </div>
    )
  }
  return (
    <div className="art art-track" aria-hidden="true">
      {['Proposed', 'Approved', 'PR opened', 'Verified'].map((s, i) => (
        <div key={s} className="art-step" style={{ '--i': i }}><span className="art-dot" /><span>{s}</span></div>
      ))}
    </div>
  )
}

function Sun() { return <div className="ob-sun" aria-hidden="true" /> }

/** First-run experience: welcome, what Paladin does, optional GitHub and model setup, a starting point, then a send-off. */
export default function Onboarding({ config, user, canPlay, onFinish }) {
  const [i, setI] = useState(0)
  const [dir, setDir] = useState('fwd')
  const [feature, setFeature] = useState(0)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [secret, setSecret] = useState('')
  const [saved, setSaved] = useState({})
  const [choice, setChoice] = useState(canPlay ? 'sample' : 'repo')
  const [leaving, setLeaving] = useState(false)
  const [connected, setConnected] = useState(false)   // a provider passed the live test in this session
  const root = useRef(null)
  const step = ORDER[i]
  const providers = config.providers || {}
  const canStoreKeys = Boolean(config.desktop && bridge)
  const first = ((user && (user.name || user.login)) || '').split(' ')[0]
  const modelReady = Boolean(providers.anthropic || providers.openai || saved.anthropicApiKey || saved.openaiApiKey)

  const go = useCallback((n) => {
    setErr(''); setSecret('')
    setI((cur) => { const t = Math.max(0, Math.min(ORDER.length - 1, typeof n === 'function' ? n(cur) : n)); setDir(t >= cur ? 'fwd' : 'back'); return t })
  }, [])
  const next = useCallback(() => go((c) => c + 1), [go])
  const back = useCallback(() => go((c) => c - 1), [go])

  const finish = useCallback((c) => {
    if (leaving) return
    setLeaving(true)
    const reduce = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
    setTimeout(() => onFinish(c), reduce ? 0 : 620)
  }, [leaving, onFinish])

  useEffect(() => { if (root.current) root.current.focus() }, [])
  useEffect(() => {
    const onKey = (e) => {
      const typing = /^(INPUT|TEXTAREA)$/.test((e.target && e.target.tagName) || '')
      if (e.key === 'Escape') finish('skip')
      else if (!typing && e.key === 'ArrowRight' && step !== 'done') next()
      else if (!typing && e.key === 'ArrowLeft') back()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [finish, next, back, step])
  useEffect(() => {      // the feature tour advances itself until the person takes over
    if (step !== 'features') return undefined
    const t = setInterval(() => setFeature((f) => (f + 1) % FEATURES.length), 5200)
    return () => clearInterval(t)
  }, [step, feature])

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
  const startLabel = { sample: 'Replaying the sample scenario', repo: 'Opening the repository launcher', explore: 'Landing on Home' }[choice]
  const primary = step === 'welcome' ? 'Get started'
    : step === 'features' ? 'Continue'
      : step === 'github' ? (saved.githubToken ? 'Continue' : 'Skip for now')
        : step === 'model' ? (connected ? 'Continue' : 'Skip for now')
          : step === 'start' ? 'Continue' : null

  return (
    <div ref={root} className={`ob-screen${leaving ? ' out' : ''}`} role="dialog" aria-modal="true" aria-labelledby="ob-t" tabIndex={-1}
         style={{ '--p': i / (ORDER.length - 1) }}>
      <Sun />
      <header className="ob-top">
        <span className="brand"><span className="brand-mark" aria-hidden="true" />Paladin</span>
        {step !== 'done' && <button className="link ob-skip" onClick={() => finish('skip')}>Skip setup</button>}
      </header>

      <main className="ob-stage" key={step} data-dir={dir} data-step={step}>
        {step === 'welcome' && (
          <>
            <div className="ob-copy">
              <span className="ob-eyebrow">Attack path compiler</span>
              <h1 id="ob-t" className="ob-lead">{first ? <>Hi {first}.<br />Let’s find the shortest way in.</> : <>Hi there.<br />Let’s find the shortest way in.</>}</h1>
              <p className="ob-sub">Paladin reads your logs and repositories, works out how an attacker would get to what matters, and tells you the
                cheapest change that closes the most doors.</p>
            </div>
            <HeroGraph />
          </>
        )}

        {step === 'features' && (
          <>
            <div className="ob-copy">
              <span className="ob-eyebrow">What you get</span>
              <h1 id="ob-t" className="ob-lead">From noise to a short, ordered list.</h1>
              <div className="ob-tabs" role="tablist">
                {FEATURES.map((f, n) => (
                  <button key={f.id} role="tab" aria-selected={feature === n} className={feature === n ? 'ob-tab on' : 'ob-tab'}
                          onClick={() => setFeature(n)}>
                    <span className="ob-ico"><Icon name={f.icon} size={18} /></span>
                    <span><b>{f.title}</b>{feature === n && <small>{f.text}</small>}</span>
                    {feature === n && <i className="ob-timer" key={`t${feature}`} />}
                  </button>
                ))}
              </div>
            </div>
            <div className="ob-visual" key={feature}><FeatureArt id={FEATURES[feature].id} /></div>
          </>
        )}

        {step === 'github' && (
          <>
            <div className="ob-copy">
              <span className="ob-eyebrow">Step 1 of 2 · optional</span>
              <h1 id="ob-t" className="ob-lead">Bring your code.</h1>
              <p className="ob-sub">Connect GitHub so Paladin can read the repositories you choose and open pull requests with fixes.</p>
              <div className="ob-card">
                {ghMode === 'app' && config.github ? (
                  <button className="ob-cta" disabled={busy} onClick={connectGithub}><Icon name="github" size={18} /> Connect GitHub</button>
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
            </div>
            <div className="ob-visual">
              <div className="art art-repos" aria-hidden="true">
                <div className="art-head">You choose the repositories</div>
                {['your-org/api', 'your-org/web', 'your-org/infra'].map((r, n) => (
                  <div key={r} className="art-repo" style={{ '--i': n }}><Icon name="repo" size={15} /><span>{r}</span><i className={n === 2 ? '' : 'on'} /></div>
                ))}
                <div className="art-foot"><Icon name="lock" size={13} /> Fixes only go to a separate <code>fixes</code> branch</div>
              </div>
            </div>
          </>
        )}

        {step === 'model' && (
          <>
            <div className="ob-copy">
              <span className="ob-eyebrow">Step 2 of 2 · optional</span>
              <h1 id="ob-t" className="ob-lead">Give it a brain.</h1>
              <p className="ob-sub">A model key unlocks the assistant and AI review of findings. Paladin works fully without one.</p>
              <div className="ob-card ob-setup">
                {/* the same validated flow as Settings → Run Setup: key in the keychain, real model list, live test */}
                <Setup embedded config={config} onClose={() => {}} onOpenAssistant={() => {}} onComplete={() => setConnected(true)} />
              </div>
            </div>
            <div className="ob-visual">
              <div className="art art-chat" aria-hidden="true">
                <div className="bubble q" style={{ '--i': 0 }}>Which fix removes the most paths?</div>
                <div className="bubble a" style={{ '--i': 1 }}>Restrict SSH to the VPN range. It cuts 6 of 9 paths and is a one-line change.</div>
                <div className="bubble q" style={{ '--i': 2 }}>Open the pull request.</div>
              </div>
            </div>
          </>
        )}

        {step === 'start' && (
          <>
            <div className="ob-copy">
              <span className="ob-eyebrow">Last thing</span>
              <h1 id="ob-t" className="ob-lead">Where would you like to start?</h1>
              <p className="ob-sub">Pick one. You can always do the others from Home.</p>
            </div>
            <div className="ob-choices" role="radiogroup" aria-label="Starting point">
              {[
                canPlay && ['sample', 'play', 'Try the sample scenario', 'Replay a realistic attack and watch the paths rank themselves.'],
                ['repo', 'repo', 'Open a repository', `Paste a GitHub link${config.desktop ? ' or choose a local folder' : ''} and scan it.`],
                ['explore', 'home', 'Look around first', 'Go straight to Home and explore at your own pace.'],
              ].filter(Boolean).map(([id, icon, t, d]) => (
                <button key={id} role="radio" aria-checked={choice === id} className={choice === id ? 'ob-choice on' : 'ob-choice'} onClick={() => setChoice(id)}>
                  <span className="ob-ico"><Icon name={icon} size={18} /></span>
                  <span><b>{t}</b><small>{d}</small></span>
                  <span className="ob-radio" aria-hidden="true" />
                </button>
              ))}
            </div>
          </>
        )}

        {step === 'done' && (
          <div className="ob-done">
            <span className="ob-check" aria-hidden="true"><Icon name="check" size={30} /></span>
            <h1 id="ob-t" className="ob-lead">You’re all set{first ? `, ${first}` : ''}.</h1>
            <p className="ob-sub">{startLabel}. Everything below can be changed any time in Settings.</p>
            <ul className="ob-summary">
              <li className={saved.githubToken ? 'ok' : ''}><span>GitHub</span><em>{saved.githubToken ? 'Token saved' : ghMode === 'app' ? 'Connect from Integrations' : 'Public repositories by link'}</em></li>
              <li className={connected || modelReady ? 'ok' : ''}><span>Model</span><em>{connected ? 'Connected and tested' : modelReady ? 'Key present, not tested yet' : 'Not set, run setup from Settings'}</em></li>
              <li className="ok"><span>Start</span><em>{{ sample: 'Sample scenario', repo: 'Open a repository', explore: 'Home' }[choice]}</em></li>
            </ul>
            <button className="ob-next big" onClick={() => finish(choice)} disabled={leaving}>Enter Paladin</button>
          </div>
        )}
      </main>

      {step !== 'done' && (
        <footer className="ob-bottom">
          <button className="ob-back" onClick={back} disabled={i === 0} aria-label="Back"><Icon name="chevron" size={18} /></button>
          <div className="ob-dots" aria-label={`Step ${i + 1} of ${ORDER.length}`}>
            {ORDER.slice(0, -1).map((s, n) => (
              <button key={s} className={n === i ? 'd on' : n < i ? 'd done' : 'd'} onClick={() => n < i && go(n)} aria-label={`Go to ${s}`} tabIndex={n < i ? 0 : -1} />
            ))}
          </div>
          <button className="ob-next" onClick={next}>{primary}</button>
        </footer>
      )}
    </div>
  )
}
