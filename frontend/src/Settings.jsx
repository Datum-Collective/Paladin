import { useEffect, useState } from 'react'
import { useToast } from './toast.jsx'

const bridge = typeof window !== 'undefined' ? window.paladin : undefined
const noop = () => {}

function KeyField({ label, help, field, set, saved, onSave, disabled }) {
  const [v, setV] = useState('')
  return (
    <div className="setting-row">
      <div className="setting-text">
        <div><b>{label}</b> <span className={`pill ${saved ? 'ok' : 'mute'}`}>{saved ? 'stored securely' : 'not set'}</span></div>
        <div className="muted small">{help}</div>
      </div>
      <div className="setting-control">
        <input type="password" autoComplete="off" spellCheck={false} placeholder={saved ? 'Replace key' : 'Paste key'}
               aria-label={label} value={v} onChange={(e) => setV(e.target.value.trim())} disabled={disabled} />
        <button className="primary" disabled={!v || disabled} onClick={async () => { await onSave({ [field]: v }); setV('') }}>Save</button>
        {saved && <button disabled={disabled} onClick={() => onSave({ [field]: null })}>Remove</button>}
      </div>
    </div>
  )
}

export default function Settings({ config, user, onReset, onSignOut }) {
  const toast = useToast()
  const [info, setInfo] = useState(null)
  const [stored, setStored] = useState(null)
  const [upd, setUpd] = useState({ phase: 'disabled' })
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!bridge) return undefined
    bridge.info().then(setInfo).catch(() => {})
    bridge.getSettings().then(setStored).catch(() => {})
    return bridge.onUpdate(setUpd)
  }, [])

  const save = async (patch) => {
    if (!bridge) return
    setSaving(true)
    const removing = Object.values(patch).every((v) => v === null)
    try {
      setStored(await bridge.setSettings(patch))
      toast(removing ? 'Key removed. The analysis engine restarted.' : 'Saved. The analysis engine restarted with the new key.', 'ok')
    } catch (e) {
      toast(e.message || 'Could not save', 'bad')
      bridge.getSettings().then(setStored).catch(noop) // show what is really stored, not what we expected
    } finally { setSaving(false) }
  }
  const updText = {
    disabled: 'Updates are off in development builds.', idle: 'Not checked yet.', checking: 'Checking for updates…',
    current: 'You are on the latest version.', downloading: `Downloading ${upd.version || ''} (${upd.percent || 0}%)…`,
    ready: `Version ${upd.version} is ready to install.`, error: `Update check failed: ${upd.error}`,
  }[upd.phase] || ''

  return (
    <div className="settings">
      <div className="settings-inner">
        <h1>Settings</h1>

        <section className="group">
          <h3>About</h3>
          <dl className="kv wide">
            <dt>Version</dt><dd>{(info && info.version) || config.version}</dd>
            <dt>Mode</dt><dd>{config.desktop ? `Desktop (${info ? `${info.platform} ${info.arch}` : 'local'})` : 'Web'}</dd>
            {config.desktop && info && <><dt>Data</dt><dd className="mono">{info.dataDir}</dd></>}
            {!config.desktop && user && <><dt>Account</dt><dd>{user.email}</dd></>}
            <dt>AI drafting</dt><dd>{config.ai ? 'On' : 'Off'}</dd>
            <dt>Pull requests</dt><dd>{config.github ? 'Enabled' : 'Unavailable, patch download only'}</dd>
          </dl>
          {config.desktop && (
            <div className="actions"><button onClick={() => bridge.openDataFolder()}>Show data folder</button></div>
          )}
        </section>

        {config.desktop && stored && (
          <section className="group">
            <h3>Integrations</h3>
            {!stored.encryptionAvailable && (
              <p className="notice warn">Secure storage is unavailable on this system, so keys cannot be saved.</p>
            )}
            <KeyField label="Anthropic API key" field="anthropicApiKey" saved={stored.anthropicApiKey}
                      help="Optional. Enables AI review of scan findings and patch drafting. Stored in the OS keychain."
                      onSave={save} disabled={saving || !stored.encryptionAvailable} />
            <KeyField label="GitHub token" field="githubToken" saved={stored.githubToken}
                      help="Optional. Needed to open pull requests and to read private repositories."
                      onSave={save} disabled={saving || !stored.encryptionAvailable} />
          </section>
        )}

        {config.desktop && (
          <section className="group">
            <h3>Updates</h3>
            <p>{updText}</p>
            <div className="actions">
              <button onClick={() => bridge.checkForUpdates()} disabled={upd.phase === 'disabled' || upd.phase === 'checking'}>
                Check for updates
              </button>
              {upd.phase === 'ready' && <button className="primary" onClick={() => bridge.installUpdate()}>Restart and install</button>}
            </div>
          </section>
        )}

        <section className="group">
          <h3>Data</h3>
          <p className="muted">Clears events, applied fixes, scan results and remediation history for this workspace.</p>
          <div className="actions"><button className="danger" onClick={onReset}>Reset workspace</button></div>
        </section>

        {!config.desktop && (
          <section className="group">
            <h3>Session</h3>
            <div className="actions"><button onClick={onSignOut}>Sign out</button></div>
          </section>
        )}
      </div>
    </div>
  )
}
