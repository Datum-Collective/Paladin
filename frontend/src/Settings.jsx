import { useEffect, useMemo, useState } from 'react'
import { api } from './api.js'
import { ago } from './lib.js'
import { PREF_DEFAULTS, usePrefs } from './prefs.jsx'
import { useToast } from './toast.jsx'
import Icon from './Icons.jsx'
import { ConfirmDialog } from './Dialogs.jsx'
import GitHubApp from './GitHubApp.jsx'

const bridge = typeof window !== 'undefined' ? window.paladin : undefined
const noop = () => {}
const isMac = typeof navigator !== 'undefined' && /Mac/.test(navigator.platform)
const M = isMac ? '⌘' : 'Ctrl+'

export const PANES = [
  { id: 'general', label: 'General', icon: 'settings' },
  { id: 'appearance', label: 'Appearance', icon: 'inspector' },
  { id: 'workspaces', label: 'Workspaces', icon: 'folder' },
  { id: 'github', label: 'GitHub', icon: 'github' },
  { id: 'providers', label: 'Models & Providers', icon: 'chat' },
  { id: 'code', label: 'Code & Diffs', icon: 'file' },
  { id: 'shortcuts', label: 'Keyboard Shortcuts', icon: 'command' },
  { id: 'privacy', label: 'Privacy', icon: 'lock' },
  { id: 'advanced', label: 'Advanced', icon: 'shield' },
]

const SHORTCUTS = [
  ['Navigation', [['Start screen', `${M}⇧H`], ['Analysis', `${M}1`], ['Repository', `${M}2`], ['Insights', `${M}3`], ['Assistant', `${M}4`],
    ['Activity', `${M}5`], ['Workspaces', `${M}6`], ['Integrations', `${M}7`], ['Command palette', `${M}K`], ['Settings', `${M},`]]],
  ['Workspaces', [['New workspace', `${M}N`], ['Open repository', `${M}⇧O`], ['Open folder', `${M}O`], ['Add log data', `${M}⇧L`],
    ['Refresh', `${M}R`]]],
  ['View', [['Show or hide sidebar', `${M}B`], ['Collapse or expand sidebar', isMac ? '⌃⌘S' : 'Ctrl+Shift+B'], ['Show or hide inspector', isMac ? '⌥⌘I' : 'Ctrl+Alt+I']]],
  ['Assistant', [['Send message', 'Return'], ['New line', '⇧Return']]],
]

/* ---- form primitives: grouped rows, not cards ---- */
function Group({ title, footer, children }) {
  return (
    <section className="fgroup">
      {title && <h3>{title}</h3>}
      <div className="frows">{children}</div>
      {footer && <p className="muted small ffooter">{footer}</p>}
    </section>
  )
}
function Row({ label, help, htmlFor, children, stack }) {
  return (
    <div className={stack ? 'frow stack' : 'frow'}>
      <div className="frow-text">
        <label htmlFor={htmlFor}>{label}</label>
        {help && <div className="muted small">{help}</div>}
      </div>
      <div className="frow-ctl">{children}</div>
    </div>
  )
}
function Switch({ id, checked, onChange, label }) {
  return (
    <button id={id} role="switch" aria-checked={checked} aria-label={label} className={checked ? 'switch on' : 'switch'}
            onClick={() => onChange(!checked)}><span /></button>
  )
}
function Segmented({ value, options, onChange, label }) {
  return (
    <div className="seg" role="radiogroup" aria-label={label}>
      {options.map(([v, l]) => (
        <button key={v} role="radio" aria-checked={value === v} className={value === v ? 'on' : ''} onClick={() => onChange(v)}>{l}</button>
      ))}
    </div>
  )
}

/* ---- panes ---- */
function General({ config, onReset }) {
  const { prefs, set } = usePrefs()
  const [upd, setUpd] = useState({ phase: 'disabled' })
  useEffect(() => (bridge ? bridge.onUpdate(setUpd) : undefined), [])
  const text = {
    disabled: 'Updates are off in development builds.', idle: 'Not checked yet.', checking: 'Checking for updates…',
    current: 'Paladin is up to date.', downloading: `Downloading version ${upd.version || ''} (${upd.percent || 0}%)…`,
    ready: `Version ${upd.version} is ready to install.`, error: `Could not check for updates. ${upd.error || ''}`,
  }[upd.phase] || ''
  return (
    <>
      <Group title="When Paladin opens">
        <Row label="Start with" help="What you see after launching the app.">
          <Segmented label="Start with" value={prefs['general.startup']} onChange={(v) => set('general.startup', v)}
                     options={[['home', 'Start screen'], ['last', 'Last workspace']]} />
        </Row>
        <Row label="After importing a repository" help="Where to land once the scan starts.">
          <Segmented label="After importing" value={prefs['general.after_import']} onChange={(v) => set('general.after_import', v)}
                     options={[['repository', 'Scan progress'], ['analysis', 'Analysis']]} />
        </Row>
      </Group>
      <Group title="Open workspace">
        <Row label="Reset workspace" help="Deletes this workspace's events, scans, fixes and history. Other workspaces are kept.">
          <button className="danger" onClick={onReset}>Reset…</button>
        </Row>
      </Group>
      {config.desktop && (
        <Group title="Software update">
          <Row label="Paladin" help={text}>
            <button onClick={() => bridge.checkForUpdates()} disabled={upd.phase === 'disabled' || upd.phase === 'checking'}>Check for Updates</button>
            {upd.phase === 'ready' && <button className="primary" onClick={() => bridge.installUpdate()}>Restart and Install</button>}
          </Row>
        </Group>
      )}
    </>
  )
}

function Appearance() {
  const { prefs, set } = usePrefs()
  return (
    <>
      <Group title="Layout" footer="Paladin follows the system appearance. Change Light or Dark in System Settings.">
        <Row label="Density" help="Compact fits more paths and events on screen.">
          <Segmented label="Density" value={prefs['appearance.density']} onChange={(v) => set('appearance.density', v)}
                     options={[['comfortable', 'Comfortable'], ['compact', 'Compact']]} />
        </Row>
        <Row label="Graph labels" help="Show host and account names on graph nodes." htmlFor="s-glabels">
          <Switch id="s-glabels" label="Graph labels" checked={prefs['appearance.graph_labels']} onChange={(v) => set('appearance.graph_labels', v)} />
        </Row>
      </Group>
    </>
  )
}

function Workspaces({ wsl, onCreate }) {
  const toast = useToast()
  const { prefs, set } = usePrefs()
  const [editing, setEditing] = useState(null)
  const [name, setName] = useState('')
  const [del, setDel] = useState(null)
  const commit = async () => {
    const id = editing
    setEditing(null)
    if (id && name.trim()) await wsl.rename(id, name.trim())
  }
  return (
    <>
      <Group title="Browsing">
        <Row label="Default sort" help="How the Workspaces list and Home order your projects." htmlFor="s-sort">
          <select id="s-sort" value={prefs['workspaces.sort']} onChange={(e) => set('workspaces.sort', e.target.value)}>
            <option value="recent">Recently opened</option><option value="name">Name</option><option value="events">Most events</option>
          </select>
        </Row>
      </Group>
      <Group title="Your workspaces" footer="Each workspace keeps its own events, scans, fixes and remediation history.">
        {wsl.workspaces.map((w) => (
          <div className="frow ws-row" key={w.id}>
            <div className="frow-text">
              {editing === w.id ? (
                <input autoFocus value={name} maxLength={60} aria-label="Workspace name" onChange={(e) => setName(e.target.value)}
                       onBlur={commit} onKeyDown={(e) => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEditing(null) }} />
              ) : (
                <div><b>{w.name}</b>{wsl.active === w.id && <span className="pill ok ml">Open</span>}</div>
              )}
              <div className="muted small">
                {w.repo_url ? w.repo_url.replace('https://', '') : 'No repository'} · {w.events} {w.events === 1 ? 'event' : 'events'} · opened {ago(w.opened)}
              </div>
            </div>
            <div className="frow-ctl">
              {wsl.active !== w.id && <button onClick={() => wsl.open(w.id)}>Open</button>}
              <button onClick={() => { setEditing(w.id); setName(w.name) }}>Rename</button>
              <button className="danger" onClick={() => setDel(w)}>Delete…</button>
            </div>
          </div>
        ))}
        <div className="frow"><div className="frow-text" /><div className="frow-ctl">
          <button onClick={onCreate}><Icon name="plus" size={14} />New Workspace…</button>
        </div></div>
      </Group>
      {del && (
        <ConfirmDialog title={`Delete “${del.name}”?`} confirmLabel="Delete Workspace"
                       body="Its events, scans, fixes and remediation history are deleted. You can’t undo this."
                       onCancel={() => setDel(null)} onConfirm={async () => { const d = del; setDel(null); await wsl.remove(d.id) }} />
      )}
    </>
  )
}

function KeyRow({ spec, stored, serverConfigured, canEdit, busy, onSave, check, onCheck, webKey = false }) {
  const [v, setV] = useState('')
  const toast = useToast()
  const set = canEdit ? stored : serverConfigured
  const id = `key-${spec.id}`
  return (
    <div className="frow stack">
      <div className="frow-text">
        <label htmlFor={id}>{spec.label}</label>
        <div className="muted small">{spec.help}</div>
        <div className="small status-line">
          <span className={`pill ${set ? 'ok' : 'mute'}`}>{set ? (canEdit ? (webKey ? 'Held in server memory' : 'Stored in keychain') : 'Set on server') : 'Not set'}</span>
          {check && check.state === 'checking' && <span className="muted">Checking…</span>}
          {check && check.state === 'ok' && <span className="ok-text">{check.text || 'Key accepted'}</span>}
          {check && check.state === 'bad' && <span className="err">{check.text}</span>}
        </div>
      </div>
      <div className="frow-ctl wide">
        {canEdit && (
          <>
            <input id={id} type="password" autoComplete="off" spellCheck={false} value={v} disabled={busy}
                   placeholder={stored ? 'Replace key' : 'Paste key'} onChange={(e) => setV(e.target.value.trim())} />
            <button className="primary" disabled={!v || busy}
                    onClick={async () => { if (await onSave({ [spec.field]: v })) { setV(''); toast('Key saved', 'ok') } }}>Save</button>
            {stored && <button disabled={busy} onClick={async () => { if (await onSave({ [spec.field]: null })) toast('Key removed', 'ok') }}>Remove</button>}
          </>
        )}
        <button disabled={!set || busy} onClick={onCheck}>Check Key</button>
      </div>
    </div>
  )
}

function useKeys(config) {
  const toast = useToast()
  const [stored, setStored] = useState(null)
  const [busy, setBusy] = useState(false)
  const [srv, setSrv] = useState(config.providers || {})
  useEffect(() => {
    // /api/config is the server-wide view; /api/providers also counts the keys this user pasted
    api.config().then((c) => setSrv(c.providers || {}))
      .then(() => api.providers())
      .then((r) => setSrv(Object.fromEntries(r.providers.map((p) => [p.id, p.configured]))))
      .catch(noop)
    if (bridge) bridge.getSettings().then(setStored).catch(noop)
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
      bridge.getSettings().then(setStored).catch(noop)
      return false
    } finally { setBusy(false) }
  }
  return { stored, srv, setSrv, busy, save, canEdit: config.desktop && Boolean(stored) && stored.encryptionAvailable }
}

function GitHub({ config }) {
  if (config.github_mode === 'app') {
    return (
      <Group title="Repository access" footer="Disconnecting here stops Paladin using the installation. To revoke access completely, uninstall the app on GitHub (Choose Repositories, then Uninstall).">
        <GitHubApp configured={Boolean(config.github)} />
      </Group>
    )
  }
  return <GitHubToken config={config} />
}

function GitHubToken({ config }) {
  const k = useKeys(config)
  const [st, setSt] = useState(null)
  const verify = async () => {
    setSt({ state: 'checking' })
    try {
      const r = await api.githubStatus()
      setSt(!r.configured ? { state: 'bad', text: 'No token is set.' }
        : r.ok ? { state: 'ok', text: `Connected as ${r.login}${r.scopes && r.scopes.length ? ` · scopes: ${r.scopes.join(', ')}` : ''}` }
          : { state: 'bad', text: r.error || 'GitHub rejected the token.' })
    } catch (e) { setSt({ state: 'bad', text: e.message }) }
  }
  useEffect(() => { if (k.srv.github || (k.stored && k.stored.githubToken)) verify() }, [k.srv.github, k.stored && k.stored.githubToken])
  return (
    <>
      {config.desktop && k.stored && !k.stored.encryptionAvailable && <p className="notice warn">Secure storage is unavailable on this system, so tokens cannot be saved.</p>}
      <Group title="Connection" footer="Without a token you can scan public repositories. A token lets you search your repositories, open private ones and send pull requests (repo scope).">
        <KeyRow spec={{ id: 'github', field: 'githubToken', label: 'Personal access token', help: 'Used for repository search, private repositories and pull requests.' }}
                stored={Boolean(k.stored && k.stored.githubToken)} serverConfigured={Boolean(k.srv.github)} canEdit={k.canEdit}
                busy={k.busy} onSave={k.save} check={st} onCheck={verify} />
      </Group>
    </>
  )
}

function Providers({ config, onSetup }) {
  const { prefs, set } = usePrefs()
  const k = useKeys(config)
  const [checks, setChecks] = useState({})
  const [models, setModels] = useState([])
  const provider = prefs['assistant.provider']
  const configured = (id) => (k.canEdit && config.desktop ? Boolean(k.stored && k.stored[id === 'anthropic' ? 'anthropicApiKey' : 'openaiApiKey']) : Boolean(k.srv[id]))
  const check = async (id) => {
    setChecks((c) => ({ ...c, [id]: { state: 'checking' } }))
    try {
      const r = await api.validate(id)
      setChecks((c) => ({ ...c, [id]: r.ok ? { state: 'ok', text: `Key accepted · ${r.models} models` }
        : { state: 'bad', text: `${r.error.message} ${r.error.hint || ''}` } }))
    } catch (e) { setChecks((c) => ({ ...c, [id]: { state: 'bad', text: e.message } })) }
  }
  useEffect(() => {
    if (!provider || !configured(provider)) { setModels([]); return undefined }
    let live = true
    api.models(provider).then((r) => live && setModels(r.models)).catch(() => live && setModels([]))
    return () => { live = false }
  }, [provider, k.stored, k.srv])
  const specs = useMemo(() => [
    { id: 'anthropic', field: 'anthropicApiKey', label: 'Claude API key', help: 'Powers the assistant and AI review of scan findings.' },
    { id: 'openai', field: 'openaiApiKey', label: 'OpenAI API key', help: 'Powers the assistant with OpenAI models.' },
  ], [])
  const web = !config.desktop
  const [webBusy, setWebBusy] = useState(false)
  // web: the server checks a pasted key with the provider and holds it in memory for this account only
  const webSave = async (patch) => {
    const [[field, value]] = Object.entries(patch)
    const pid = specs.find((s) => s.field === field).id
    setWebBusy(true)
    try {
      if (value === null) await api.removeKey(pid)
      else {
        const r = await api.setKey(pid, value)
        if (!r.ok) {
          setChecks((c) => ({ ...c, [pid]: { state: 'bad', text: `${r.error.message} ${r.error.hint || ''}` } }))
          return false
        }
        setChecks((c) => ({ ...c, [pid]: { state: 'ok', text: `Key accepted · ${r.models} models` } }))
      }
      const c = await api.config()
      k.setSrv(c.providers || {})
      const pr = await api.providers().catch(() => null)
      if (pr) k.setSrv(Object.fromEntries(pr.providers.map((p) => [p.id, p.configured])))
      return true
    } catch (e) {
      setChecks((c) => ({ ...c, [pid]: { state: 'bad', text: e.message } }))
      return false
    } finally { setWebBusy(false) }
  }
  return (
    <>
      {config.desktop && k.stored && !k.stored.encryptionAvailable && <p className="notice warn">Secure storage is unavailable on this system, so keys cannot be saved.</p>}
      <Group title="Guided setup" footer="Walks through provider, key, model and a live connection test.">
        <Row label="Set up the assistant"><button onClick={onSetup}>Run Setup…</button></Row>
      </Group>
      <Group title="API keys" footer={web ? 'Pasted keys are checked with the provider, held in the server’s memory for your account only, and never shown again. They are cleared when the server restarts.' : 'Keys live in the system keychain and are used only by Paladin’s engine; the interface never receives them.'}>
        {specs.map((s) => (
          <KeyRow key={s.id} spec={s} webKey={web} canEdit={web || k.canEdit}
                  stored={web ? Boolean(k.srv[s.id]) : Boolean(k.stored && k.stored[s.field])}
                  serverConfigured={Boolean(k.srv[s.id])} busy={web ? webBusy : k.busy} onSave={web ? webSave : k.save}
                  check={checks[s.id]} onCheck={() => check(s.id)} />
        ))}
      </Group>
      <Group title="Assistant defaults">
        <Row label="Provider" htmlFor="d-prov">
          <select id="d-prov" value={provider} onChange={(e) => { set('assistant.provider', e.target.value); set('assistant.model', '') }}>
            <option value="">Ask each time</option>
            <option value="anthropic">Claude</option>
            <option value="openai">OpenAI</option>
          </select>
        </Row>
        <Row label="Model" htmlFor="d-model" help={provider && !configured(provider) ? 'Add a key for this provider to choose a model.' : undefined}>
          <select id="d-model" value={prefs['assistant.model']} disabled={!models.length} onChange={(e) => set('assistant.model', e.target.value)}>
            <option value="">First available</option>
            {models.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        </Row>
        <Row label="Reasoning effort" htmlFor="d-eff">
          <select id="d-eff" value={prefs['assistant.effort']} onChange={(e) => set('assistant.effort', e.target.value)}>
            <option value="">Provider default</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
          </select>
        </Row>
        <Row label="Use workspace analysis" help="Ground answers in the paths and fixes Paladin computed." htmlFor="d-ctx">
          <Switch id="d-ctx" label="Use workspace analysis" checked={prefs['assistant.context']} onChange={(v) => set('assistant.context', v)} />
        </Row>
      </Group>
    </>
  )
}

function Code() {
  const { prefs, set } = usePrefs()
  return (
    <Group title="Diff viewer">
      <Row label="Wrap long lines" htmlFor="s-wrap">
        <Switch id="s-wrap" label="Wrap long lines" checked={prefs['diff.wrap']} onChange={(v) => set('diff.wrap', v)} />
      </Row>
      <Row label="Font size" htmlFor="s-fs">
        <select id="s-fs" value={prefs['diff.font_size']} onChange={(e) => set('diff.font_size', Number(e.target.value))}>
          {[10, 11, 12, 13, 14, 15, 16].map((n) => <option key={n} value={n}>{n} pt</option>)}
        </select>
      </Row>
      <div className="frow stack">
        <pre className="diff-preview" aria-label="Preview">{`- cursor.execute("SELECT * FROM users WHERE id = " + uid)\n+ cursor.execute("SELECT * FROM users WHERE id = ?", (uid,))`}</pre>
      </div>
    </Group>
  )
}

function Shortcuts() {
  return (
    <>
      {SHORTCUTS.map(([group, rows]) => (
        <Group key={group} title={group}>
          {rows.map(([name, keys]) => <Row key={name} label={name}><kbd className="kbd-lg">{keys}</kbd></Row>)}
        </Group>
      ))}
      <p className="muted small">Shortcuts follow macOS conventions and are shown for reference; they can’t be changed yet.</p>
    </>
  )
}

function Privacy({ wsl }) {
  const toast = useToast()
  const [confirm, setConfirm] = useState(false)
  const clearAll = async () => {
    setConfirm(false)
    for (const w of [...wsl.workspaces]) await api.deleteWorkspace(w.id).catch(noop)
    await wsl.reload()
    toast('All workspace data was deleted', 'ok')
  }
  return (
    <>
      <Group title="What leaves this computer" footer="Everything else, including your events, scan results and keys, stays on this computer.">
        <Row label="Repository scans" help="GitHub receives the repository link, and your token if you set one. Code is cloned and read, never executed." />
        <Row label="Assistant and AI review" help="Your messages and the computed paths go to the provider you choose. Secrets found in the text are masked first." />
        <Row label="Credential masking" help="API keys, tokens and private keys are masked before anything is sent."><span className="pill ok">Always on</span></Row>
      </Group>
      <Group title="Local data">
        <Row label="Delete all workspace data" help="Removes every workspace’s events, scans, fixes and history. Settings and keys are kept.">
          <button className="danger" onClick={() => setConfirm(true)}>Delete All…</button>
        </Row>
      </Group>
      {confirm && (
        <ConfirmDialog title="Delete all workspace data?" confirmLabel="Delete All Data"
                       body="Every workspace and everything in it is deleted. You can’t undo this."
                       onCancel={() => setConfirm(false)} onConfirm={clearAll} />
      )}
    </>
  )
}

const bytes = (n) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : n >= 1e3 ? `${Math.round(n / 1e3)} KB` : `${n} B`)

function Advanced({ config, user }) {
  const toast = useToast()
  const [info, setInfo] = useState(null)
  const [store, setStore] = useState(null)
  const [confirmClones, setConfirmClones] = useState(false)
  const loadStore = () => api.storage().then(setStore).catch(noop)
  useEffect(() => { if (bridge) bridge.info().then(setInfo).catch(noop); loadStore() }, [])
  const diag = [
    `Paladin ${(info && info.version) || config.version}`, `Mode: ${config.desktop ? 'desktop' : 'web'}`,
    info ? `Platform: ${info.platform} ${info.arch}` : null, `Claude key: ${config.providers && config.providers.anthropic ? 'set' : 'not set'}`,
    `OpenAI key: ${config.providers && config.providers.openai ? 'set' : 'not set'}`, `GitHub token: ${config.github ? 'set' : 'not set'}`,
  ].filter(Boolean).join('\n')
  const resetAll = async () => {
    try { await api.setPrefs(PREF_DEFAULTS); window.location.reload() } catch (e) { toast(e.message, 'bad') }
  }
  return (
    <>
      <Group title="Engine">
        <Row label="Version">{(info && info.version) || config.version}</Row>
        <Row label="Mode">{config.desktop ? `Desktop${info ? `, ${info.platform} ${info.arch}` : ''}` : 'Web'}</Row>
        {user && <Row label="Account" help="Signed in with GitHub">{user.login || user.email}</Row>}
        {config.desktop && info && (
          <Row label="Data folder" help={info.dataDir} stack><button onClick={() => bridge.openDataFolder()}>Show in Finder</button></Row>
        )}
      </Group>
      <Group title="Storage">
        <Row label="Database" help="Events, findings, fixes and history are stored in your Paladin account, not on this machine.">
          {store ? (store.database_bytes == null ? 'In your account' : bytes(store.database_bytes)) : '…'}</Row>
        <Row label="Cloned repositories" help={store ? `${store.clones.count} working ${store.clones.count === 1 ? 'copy' : 'copies'} from scans. Findings stay; patched-file previews for cleared scans stop working.` : ''}>
          <span>{store ? bytes(store.clones.bytes) : '…'}</span>
          <button disabled={!store || store.clones.count === 0} onClick={() => setConfirmClones(true)}>Clear…</button>
        </Row>
      </Group>
      {confirmClones && (
        <ConfirmDialog title="Clear cloned repositories?" confirmLabel="Clear Clones" danger={false}
                       body="Working copies of finished scans are deleted. Findings and history are kept, and scans in progress are not touched."
                       onCancel={() => setConfirmClones(false)}
                       onConfirm={async () => { setConfirmClones(false); try { const r = await api.clearClones(); toast(`Removed ${r.removed} ${r.removed === 1 ? 'copy' : 'copies'}`, 'ok'); loadStore() } catch (e) { toast(e.message, 'bad') } }} />
      )}
      <Group title="Support">
        <Row label="Diagnostics" help="Versions and which integrations are configured. No keys or workspace data.">
          <button onClick={async () => {
            try { await navigator.clipboard.writeText(diag); toast('Diagnostics copied', 'ok') } catch { toast('Could not copy. Select and copy it manually.', 'bad') }
          }}>Copy Diagnostics</button>
        </Row>
      </Group>
      <Group title="Reset">
        <Row label="Reset all settings" help="Restores every preference on this page to its default. Workspaces and keys are kept.">
          <button className="danger" onClick={resetAll}>Reset Settings</button>
        </Row>
      </Group>
    </>
  )
}

export default function Settings({ pane, setPane, onSetup, config, user, wsl, onCreate, onReset }) {
  const body = {
    general: <General config={config} onReset={onReset} />, appearance: <Appearance />, workspaces: <Workspaces wsl={wsl} onCreate={onCreate} />,
    github: <GitHub config={config} />, providers: <Providers config={config} onSetup={onSetup} />, code: <Code />, shortcuts: <Shortcuts />,
    privacy: <Privacy wsl={wsl} />, advanced: <Advanced config={config} user={user} />,
  }[pane]
  return (
    <div className="settings">
      <nav className="settings-nav" aria-label="Settings categories">
        {PANES.map((p) => (
          <button key={p.id} className={pane === p.id ? 'nav-item on' : 'nav-item'} aria-current={pane === p.id ? 'page' : undefined}
                  onClick={() => setPane(p.id)}>
            <Icon name={p.icon} size={16} /><span>{p.label}</span>
          </button>
        ))}
      </nav>
      <div className="settings-body">
        <div className="settings-inner">{body}</div>
      </div>
    </div>
  )
}
