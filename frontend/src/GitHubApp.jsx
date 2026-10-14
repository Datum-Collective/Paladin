import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import { useToast } from './toast.jsx'

// Repo and account names come from GitHub: rendered as text only. Links only ever go to github.com.
const githubHref = (url) => (typeof url === 'string' && url.startsWith('https://github.com/') ? url : undefined)

/** Web: repository access through the Paladin GitHub App, per user. Rows in the grouped-list style. */
export default function GitHubApp({ configured }) {
  const toast = useToast()
  const [installs, setInstalls] = useState(null)
  const [busy, setBusy] = useState(false)
  const [confirming, setConfirming] = useState(null)
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    try { setInstalls(await api.githubRepos()); setErr('') } catch (e) { setErr(e.message); setInstalls([]) }
  }, [])
  useEffect(() => { if (configured) load() }, [configured, load])

  const connect = async () => {
    setBusy(true)
    try {
      const { url } = await api.githubInstallUrl()
      if (githubHref(url)) window.location.assign(url)
      else throw new Error('Unexpected install address')
    } catch (e) { setBusy(false); toast(`Could not start connecting GitHub: ${e.message}`, 'bad') }
  }
  const disconnect = async (id) => {
    setConfirming(null)
    try {
      await api.githubDisconnect(id)
      toast('Disconnected. To fully revoke access, uninstall the app on GitHub.', 'ok')
      setInstalls((list) => (list || []).filter((i) => i.installation_id !== id))
    } catch (e) { toast(e.message, 'bad') }
  }

  if (!configured) {
    return (
      <div className="frow"><div className="frow-text"><b>GitHub</b>
        <div className="muted small">Repository access is not configured on this server. Public repositories can still be scanned.</div>
      </div></div>
    )
  }
  return (
    <>
      <div className="frow">
        <div className="frow-text">
          <b>GitHub</b>
          <div className="muted small">
            Choose which repositories Paladin may read, and where it may open pull requests with fixes (always on a
            separate <code>fixes</code> branch). GitHub installs the app on whichever account is signed in on
            github.com, so make sure it is the same account you signed in to Paladin with.
          </div>
          <div className="small status-line">
            <span className={`pill ${installs && installs.length ? 'ok' : 'mute'}`}>
              {installs === null ? 'Checking…' : installs.length ? 'Connected' : 'Not connected'}
            </span>
            {err && <span className="err">{err}</span>}
          </div>
        </div>
        <div className="frow-ctl"><button className="primary" disabled={busy} onClick={connect}>
          {installs && installs.length ? 'Connect Another Account' : 'Connect GitHub'}</button></div>
      </div>
      {(installs || []).map((inst) => (
        <div className="frow" key={inst.installation_id}>
          <div className="frow-text">
            <b>{inst.account}</b>
            {inst.error ? (
              <div className="err small">Can’t reach this installation. It may have been uninstalled on GitHub; disconnect it and connect again.</div>
            ) : inst.repos.length === 0 ? (
              <div className="muted small">No repositories selected. Use Choose Repositories to add some.</div>
            ) : (
              <div className="muted small">
                {inst.repos.map((r, i) => (
                  <span key={r.full_name}>{i ? ', ' : ''}
                    <a href={githubHref(r.html_url)} target="_blank" rel="noopener noreferrer">{r.full_name}</a>
                    {r.private ? ' (private)' : ''}</span>
                ))}
              </div>
            )}
          </div>
          <div className="frow-ctl">
            <button onClick={() => { const u = githubHref(inst.manage_url); if (u) window.open(u, '_blank', 'noopener,noreferrer') }}>
              Choose Repositories</button>
            {confirming === inst.installation_id ? (
              <>
                <button className="danger" onClick={() => disconnect(inst.installation_id)}>Disconnect</button>
                <button onClick={() => setConfirming(null)}>Cancel</button>
              </>
            ) : <button onClick={() => setConfirming(inst.installation_id)}>Disconnect…</button>}
          </div>
        </div>
      ))}
    </>
  )
}
