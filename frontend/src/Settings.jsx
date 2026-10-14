import { useEffect, useState } from 'react'
import { api } from './api.js'
import { useToast } from './toast.jsx'

const bridge = typeof window !== 'undefined' ? window.paladin : undefined
const noop = () => {}
export const PANES = [['general', 'General'], ['providers', 'Providers'], ['updates', 'Updates']]

const PROVIDERS = [
  { field: 'anthropicApiKey', id: 'anthropic', label: 'Claude API key', help: 'Powers the assistant and AI review of scan findings.' },
  { field: 'openaiApiKey', id: 'openai', label: 'OpenAI API key', help: 'Powers the assistant with OpenAI models.' },
  { field: 'githubToken', id: 'github', label: 'GitHub token', help: 'Opens pull requests and reads private repositories.' },
]

function KeyRow({ spec, stored, serverConfigured, canEdit, busy, onSave }) {
  const [v, setV] = useState('')
  const [check, setCheck] = useState(null)
  const toast = useToast()
  const set = canEdit ? stored : serverConfigured
  const validate = async () => {
    setCheck({ state: 'checking' })
    try {
      const r = await api.validate(spec.id)
      setCheck(r.ok ? { state: 'ok', models: r.models } : { state: 'bad', error: r.error })
    } catch (e) { setCheck({ state: 'bad', error: { message: e.message } }) }
  }
  const id = `key-${spec.id}`
  return (
    <div className="setting-row">
      <div className="setting-text">
        <label htmlFor={id}><b>{spec.label}</b></label>
        <div className="muted small">{spec.help}</div>
        <div className="small">
          <span className={`pill ${set ? 'ok' : 'mute'}`}>{set ? (canEdit ? 'Stored in keychain' : 'Set on server') : 'Not set'}</span>
          {check && check.state === 'checking' && <span className="muted"> Checking…</span>}
          {check && check.state === 'ok' && <span className="ok-text"> Key accepted{check.models ? ` · ${check.models} models` : ''}</span>}
          {check && check.state === 'bad' && (
            <span className="err"> {check.error.message}{check.error.hint ? ` ${check.error.hint}` : ''}</span>
          )}
        </div>
      </div>
      <div className="setting-control">
        {canEdit && (
          <>
            <input id={id} type="password" autoComplete="off" spellCheck={false} value={v} disabled={busy}
                   placeholder={stored ? 'Replace key' : 'Paste key'} onChange={(e) => setV(e.target.value.trim())} />
            <button className="primary" disabled={!v || busy}
                    onClick={async () => { if (await onSave({ [spec.field]: v })) { setV(''); setCheck(null); toast('Key saved', 'ok') } }}>
              Save
            </button>
            {stored && <button disabled={busy} onClick={async () => { if (await onSave({ [spec.field]: null })) { setCheck(null); toast('Key removed', 'ok') } }}>Remove</button>}
          </>
        )}
        {spec.id !== 'github' && <button disabled={!set || busy} onClick={validate}>Check key</button>}
      </div>
    </div>
  )
}

export default function Settings({ pane, config, user, onReset, onSignOut }) {
  const toast = useToast()
  const [info, setInfo] = useState(null)
  const [stored, setStored] = useState(null)
  const [upd, setUpd] = useState({ phase: 'disabled' })
  const [busy, setBusy] = useState(false)
  const [srv, setSrv] = useState(config.providers || {})

  useEffect(() => {
    api.config().then((c) => setSrv(c.providers || {})).catch(noop)
    if (!bridge) return undefined
    bridge.info().then(setInfo).catch(noop)
    bridge.getSettings().then(setStored).catch(noop)
    return bridge.onUpdate(setUpd)
  }, [])

  const save = async (patch) => {
    if (!bridge) return false
    setBusy(true)
    try {
      setStored(await bridge.setSettings(patch))
      api.config().then((c) => setSrv(c.providers || {})).catch(noop)
      return true
    } catch (e) {
      toast(e.message || 'Could not save the key', 'bad')
      bridge.getSettings().then(setStored).catch(noop) // show what is really stored
      return false
    } finally { setBusy(false) }
  }
  const updText = {
    disabled: 'Updates are off in development builds.', idle: 'Not checked yet.', checking: 'Checking for updates…',
    current: 'Paladin is up to date.', downloading: `Downloading version ${upd.version || ''} (${upd.percent || 0}%)…`,
    ready: `Version ${upd.version} is ready to install.`, error: `Could not check for updates. ${upd.error || ''}`,
  }[upd.phase] || ''

  return (
    <div className="settings">
      <div className="settings-inner">
        {pane === 'general' && (
          <section className="group" aria-labelledby="s-about">
            <h3 id="s-about" className="first">About</h3>
            <dl className="kv wide">
              <dt>Version</dt><dd>{(info && info.version) || config.version}</dd>
              <dt>Mode</dt><dd>{config.desktop ? `Desktop${info ? `, ${info.platform} ${info.arch}` : ''}` : 'Web'}</dd>
              {config.desktop && info && <><dt>Data folder</dt><dd className="mono">{info.dataDir}</dd></>}
              {!config.desktop && user && <><dt>Account</dt><dd>{user.email}</dd></>}
            </dl>
            <div className="actions">
              {config.desktop && <button onClick={() => bridge.openDataFolder()}>Show Data Folder</button>}
              <button className="danger" onClick={onReset}>Reset Workspace…</button>
              {!config.desktop && <button onClick={onSignOut}>Sign Out</button>}
            </div>
          </section>
        )}

        {pane === 'providers' && (
          <section className="group" aria-labelledby="s-prov">
            <h3 id="s-prov" className="first">Model providers</h3>
            {config.desktop && stored && !stored.encryptionAvailable && (
              <p className="notice warn">Secure storage is unavailable on this system, so keys cannot be saved.</p>
            )}
            <p className="muted small">
              Conversations are sent to the provider you choose. Credentials found in the text are masked first, and
              the interface never receives a stored key.
            </p>
            {PROVIDERS.map((s) => (
              <KeyRow key={s.id} spec={s} canEdit={config.desktop && Boolean(stored) && stored.encryptionAvailable}
                      stored={Boolean(stored && stored[s.field])} serverConfigured={Boolean(srv[s.id])}
                      busy={busy} onSave={save} />
            ))}
          </section>
        )}

        {pane === 'updates' && (
          <section className="group" aria-labelledby="s-upd">
            <h3 id="s-upd" className="first">Software update</h3>
            <p>{config.desktop ? updText : 'The web version updates when the server is redeployed.'}</p>
            {config.desktop && (
              <div className="actions">
                <button onClick={() => bridge.checkForUpdates()} disabled={upd.phase === 'disabled' || upd.phase === 'checking'}>
                  Check for Updates
                </button>
                {upd.phase === 'ready' && <button className="primary" onClick={() => bridge.installUpdate()}>Restart and Install</button>}
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  )
}
