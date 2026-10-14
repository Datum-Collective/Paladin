import { useState } from 'react'

/** Modal confirmation. Cancel is never the default; Esc cancels. Used for every destructive action. */
export function ConfirmDialog({ title, body, confirmLabel, danger = true, onConfirm, onCancel }) {
  return (
    <div className="scrim" onMouseDown={onCancel} onKeyDown={(e) => { if (e.key === 'Escape') onCancel() }}>
      <div className="dialog" role="alertdialog" aria-modal="true" aria-labelledby="dlg-t" aria-describedby="dlg-d" tabIndex={-1}
           ref={(el) => el && el.focus()} onMouseDown={(e) => e.stopPropagation()}>
        <h2 id="dlg-t">{title}</h2>
        <p id="dlg-d" className="muted">{body}</p>
        <div className="actions end">
          <button onClick={onCancel}>Cancel</button>
          <button className={danger ? 'danger' : 'primary'} onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  )
}

/** New workspace: a name, and optionally a source to import from. Validates before anything is created. */
export function NewWorkspaceDialog({ desktop, onCreate, onImportRepo, onImportFolder, onChooseFolder, onCancel }) {
  const [name, setName] = useState('')
  const [source, setSource] = useState('empty')
  const [repo, setRepo] = useState('')
  const [folder, setFolder] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    setErr('')
    if (source === 'empty' && !name.trim()) { setErr('Give the workspace a name.'); return }
    if (source === 'github' && !repo.trim()) { setErr('Paste a GitHub link or owner/name.'); return }
    if (source === 'folder' && !folder) { setErr('Choose a folder first.'); return }
    setBusy(true)
    try {
      if (source === 'empty') await onCreate(name.trim())
      else if (source === 'github') await onImportRepo(repo.trim())
      else await onImportFolder(folder)
      onCancel()
    } catch (e) { setErr(e.message || 'That did not work.') } finally { setBusy(false) }
  }
  const pick = async () => { const p = await onChooseFolder(); if (p) setFolder(p) }
  return (
    <div className="scrim" onMouseDown={onCancel} onKeyDown={(e) => { if (e.key === 'Escape') onCancel() }}>
      <form className="dialog wide" role="dialog" aria-modal="true" aria-labelledby="nw-t" onMouseDown={(e) => e.stopPropagation()}
            onSubmit={(e) => { e.preventDefault(); submit() }}>
        <h2 id="nw-t">New workspace</h2>
        <p className="muted small">A workspace keeps its own data, scans and history.</p>
        <div className="seg" role="radiogroup" aria-label="Source">
          {[['empty', 'Empty'], ['github', 'GitHub repository'], ...(desktop ? [['folder', 'Local folder']] : [])].map(([v, l]) => (
            <button type="button" key={v} role="radio" aria-checked={source === v} className={source === v ? 'on' : ''}
                    onClick={() => { setSource(v); setErr('') }}>{l}</button>
          ))}
        </div>
        {source === 'empty' && (
          <label className="field-col">Name
            <input autoFocus value={name} maxLength={60} onChange={(e) => setName(e.target.value)} placeholder="Incident review" />
          </label>
        )}
        {source === 'github' && (
          <label className="field-col">Repository
            <input autoFocus value={repo} spellCheck={false} onChange={(e) => setRepo(e.target.value)} placeholder="github.com/owner/repo" />
            <span className="muted small">The workspace is named after the repository and a scan starts right away.</span>
          </label>
        )}
        {source === 'folder' && (
          <div className="field-col">Folder
            <div className="actions">
              <button type="button" onClick={pick}>Choose Folder…</button>
              <span className="muted small mono">{folder || 'No folder chosen'}</span>
            </div>
            <span className="muted small">Must be a Git repository; committed code is scanned in place.</span>
          </div>
        )}
        {err && <p className="err" role="alert">{err}</p>}
        <div className="actions end">
          <button type="button" onClick={onCancel}>Cancel</button>
          <button type="submit" className="primary" disabled={busy}>{busy ? 'Working…' : source === 'empty' ? 'Create' : 'Import'}</button>
        </div>
      </form>
    </div>
  )
}
