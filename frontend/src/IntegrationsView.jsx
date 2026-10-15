import { useEffect, useState } from 'react'
import { api } from './api.js'
import { Ingest } from './parts.jsx'
import GitHubApp from './GitHubApp.jsx'

function Row({ name, desc, state, tone, actions }) {
  return (
    <div className="frow">
      <div className="frow-text">
        <b>{name}</b>
        <div className="muted small">{desc}</div>
        <div className="small status-line"><span className={`pill ${tone}`}>{state.label}</span>
          {state.detail && <span className={state.bad ? 'err' : 'muted'}>{state.detail}</span>}</div>
      </div>
      <div className="frow-ctl">{actions}</div>
    </div>
  )
}

export default function IntegrationsView({ config, desktop, goSettings, onIngested }) {
  const [gh, setGh] = useState(null)
  const [checks, setChecks] = useState({})
  const providers = config.providers || {}
  const appMode = config.github_mode === 'app'   // web: per-user GitHub App; desktop: the user's own token
  useEffect(() => { if (config.github && !appMode) api.githubStatus().then(setGh).catch(() => setGh({ ok: false, error: 'Could not reach GitHub.' })) }, [config.github, appMode])
  const check = async (id) => {
    setChecks((c) => ({ ...c, [id]: { label: 'Checking…', tone: 'info' } }))
    try {
      const r = await api.validate(id)
      setChecks((c) => ({ ...c, [id]: r.ok ? { label: 'Connected', tone: 'ok', detail: `${r.models} models available` }
        : { label: 'Rejected', tone: 'bad', bad: true, detail: `${r.error.message} ${r.error.hint || ''}` } }))
    } catch (e) { setChecks((c) => ({ ...c, [id]: { label: 'Error', tone: 'bad', bad: true, detail: e.message } })) }
  }
  const ghState = !config.github ? { label: 'Not connected', tone: 'mute' }
    : !gh ? { label: 'Checking…', tone: 'info' }
      : gh.ok ? { label: 'Connected', tone: 'ok', detail: `${gh.login}${gh.scopes && gh.scopes.length ? ` · ${gh.scopes.join(', ')}` : ''}` }
        : { label: 'Rejected', tone: 'bad', bad: true, detail: gh.error }
  const prov = (id, name, desc) => {
    const set = Boolean(providers[id])
    const s = checks[id] || (set ? { label: 'Key set', tone: 'ok' } : { label: 'No key', tone: 'mute' })
    return (
      <Row name={name} desc={desc} state={s} tone={s.tone} actions={(
        <>
          <button disabled={!set} onClick={() => check(id)}>Check Key</button>
          <button onClick={() => goSettings('providers')}>{set ? 'Manage' : 'Add Key'}</button>
        </>
      )} />
    )
  }
  return (
    <div className="page">
      <div className="page-inner">
        <div className="page-head"><h1>Integrations</h1></div>
        <section className="fgroup">
          <h3>Source control</h3>
          <div className="frows">
            {appMode ? <GitHubApp configured={Boolean(config.github)} /> : <Row name="GitHub" desc="Search your repositories, open private ones and send pull requests." state={ghState} tone={ghState.tone}
                 actions={(
                   <>
                     {config.github && <button onClick={() => { setGh(null); api.githubStatus().then(setGh).catch(() => {}) }}>Verify</button>}
                     <button onClick={() => goSettings('github')}>{config.github ? 'Manage' : 'Connect'}</button>
                   </>
                 )} />}
          </div>
        </section>
        <section className="fgroup">
          <h3>Model providers</h3>
          <div className="frows">
            {prov('anthropic', 'Claude', 'Assistant answers and AI review of scan findings.')}
            {prov('openai', 'OpenAI', 'Assistant answers with OpenAI models.')}
          </div>
        </section>
        <section className="fgroup">
          <h3>Log ingestion</h3>
          <div className="frows"><div className="frow stack"><Ingest onDone={onIngested} desktop={desktop} /></div></div>
        </section>
      </div>
    </div>
  )
}
