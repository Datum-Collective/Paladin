import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import { ago } from './lib.js'
import { Skeleton } from './ui.jsx'
import Icon from './Icons.jsx'

const TONE = { failed: 'bad', cancelled: 'mute', done: 'ok', ready: 'ok', pr_opened: 'ok', queued: 'info', cloning: 'info', scanning: 'info', fixing: 'info' }
const LABEL = { failed: 'Failed', done: 'Scanned', ready: 'Fixes ready', pr_opened: 'Pull request opened', queued: 'Queued',
  cloning: 'Cloning', scanning: 'Scanning', fixing: 'Preparing fixes', cancelled: 'Cancelled' }
const RUNNING = new Set(['queued', 'cloning', 'scanning', 'fixing'])
const ACTION = { proposed: 'Proposed', approved: 'Approved', executed: 'Executed', verified: 'Verified', rolled_back: 'Rolled back' }

export default function ActivityView({ onRetry, goSettings }) {
  const [items, setItems] = useState(null)
  const [err, setErr] = useState('')
  const [filter, setFilter] = useState('all')
  const [retrying, setRetrying] = useState(null)

  const load = useCallback(async () => {
    try { setItems((await api.activity()).items); setErr('') } catch (e) { setErr(e.message) }
  }, [])
  useEffect(() => { load() }, [load])
  const busy = items && items.some((i) => i.kind === 'scan' && RUNNING.has(i.state))
  useEffect(() => {
    if (!busy) return undefined
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [busy, load])

  const retry = async (it) => {
    setRetrying(it.id)
    try { await onRetry(it.retry) } catch (e) { setErr(e.message) } finally { setRetrying(null); load() }
  }
  const cancel = async (it) => {
    setRetrying(it.id)
    try { await api.hCancel(it.id) } catch (e) { setErr(e.message) } finally { setRetrying(null); load() }
  }
  const shown = (items || []).filter((i) => filter === 'all' || (filter === 'scans' ? i.kind === 'scan' : i.kind === 'remediation'))
  return (
    <div className="page">
      <div className="page-inner">
        <div className="page-head">
          <h1>Activity</h1>
          <span className="actions"><button onClick={load}><Icon name="refresh" size={14} />Refresh</button></span>
        </div>
        <div className="filters">
          <div className="seg" role="radiogroup" aria-label="Show">
            {[['all', 'All'], ['scans', 'Scans'], ['remediation', 'Remediation']].map(([v, l]) =>
              <button key={v} role="radio" aria-checked={filter === v} className={filter === v ? 'on' : ''} onClick={() => setFilter(v)}>{l}</button>)}
          </div>
          {busy && <span className="muted small"><span className="spinner tiny" aria-hidden="true" /> A scan is running</span>}
        </div>
        {err && <div className="inline-error" role="alert"><span>{err}</span><button onClick={load}>Try Again</button></div>}
        {items === null && !err && <Skeleton lines={4} />}
        {items && shown.length === 0 && (
          <div className="empty-block"><h2>No activity yet</h2>
            <p className="muted">Scans and remediation steps for this workspace are recorded here.</p></div>
        )}
        <ul className="timeline">
          {shown.map((it) => (
            <li key={`${it.kind}-${it.id}`} className="tl-item">
              <span className="tl-icon"><Icon name={it.kind === 'scan' ? 'repo' : 'shield'} size={16} /></span>
              <div className="tl-main">
                <div className="row-top">
                  <b>{it.title}</b>
                  {it.kind === 'scan'
                    ? <span className={`pill ${TONE[it.state] || 'mute'}`}>{LABEL[it.state] || it.state}</span>
                    : <span className="pill mute">{ACTION[it.action] || it.action}</span>}
                </div>
                {it.detail && <p className={it.state === 'failed' ? 'err small' : 'muted small'}>{it.detail}</p>}
                <div className="muted small">
                  {it.kind === 'remediation' && it.actor ? `${it.actor} · ` : ''}{ago(it.ts)}
                </div>
                {it.retry && (
                  <div className="actions">
                    <button disabled={retrying === it.id} onClick={() => retry(it)}>{retrying === it.id ? 'Retrying…' : 'Retry scan'}</button>
                    {/token|private|not found/i.test(it.detail) && <button onClick={() => goSettings('github')}>Open GitHub Settings</button>}
                  </div>
                )}
                {it.cancel && (
                  <div className="actions">
                    <button disabled={retrying === it.id} onClick={() => cancel(it)}>{retrying === it.id ? 'Cancelling…' : 'Cancel scan'}</button>
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
