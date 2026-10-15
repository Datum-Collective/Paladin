import { useEffect, useMemo, useState } from 'react'
import Icon from './Icons.jsx'
import { MitreCode } from './Mitre.jsx'
import { parseDiff, withInline } from './diffParse.js'
import { api } from './api.js'
import { Skeleton } from './ui.jsx'

function Code({ line }) {
  if (!line.mark || line.mark[0] >= line.mark[1]) return <>{line.text || ' '}</>
  const [a, b] = line.mark
  return (
    <>
      {line.text.slice(0, a)}
      <mark>{line.text.slice(a, b)}</mark>
      {line.text.slice(b)}
    </>
  )
}

function Checks({ checks }) {
  if (!checks || !checks.length) return null
  return (
    <ul className="checks">
      {checks.map((c, i) => (
        <li key={i} className={c.passed === false ? 'fail' : c.passed === null ? 'skip' : 'pass'}>
          <span aria-hidden="true">{c.passed === false ? '✕' : c.passed === null ? '–' : '✓'}</span> {c.name}
        </li>
      ))}
    </ul>
  )
}

function FullFile({ jobId, path }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    let live = true
    api.hFile(jobId, path).then((d) => live && setData(d)).catch((e) => live && setErr(e.message))
    return () => { live = false }
  }, [jobId, path])
  if (err) return <p className="err">{err}</p>
  if (!data) return <Skeleton lines={6} />
  const changed = new Set(data.changed_lines)
  return (
    <table className="diff full"><tbody>
      {data.content.split('\n').map((t, i) => (
        <tr key={i} className={changed.has(i + 1) ? 'row-add' : ''}>
          <td className="ln">{i + 1}</td><td className="sign">{changed.has(i + 1) ? '+' : ''}</td>
          <td className="code">{t || ' '}</td>
        </tr>
      ))}
    </tbody></table>
  )
}

function FileDiff({ file, fixes, defaultOpen, jobId }) {
  const [open, setOpen] = useState(defaultOpen)
  const [full, setFull] = useState(false)
  const hunks = useMemo(() => file.hunks.map((h) => ({ ...h, lines: withInline(h.lines) })), [file])
  return (
    <section className="diff-file">
      <button className="diff-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Icon name={open ? 'down' : 'chevron'} size={14} />
        <Icon name="file" size={14} />
        <span className="diff-path">{file.path}</span>
        {file.isNew && <span className="tag">new</span>}
        <span className="diff-stat"><span className="add">+{file.add}</span> <span className="del">−{file.del}</span></span>
      </button>
      {open && fixes.length > 0 && (
        <ul className="diff-notes">
          {fixes.map((f) => (
            <li key={f.id}>
              <span className="tag">{f.method === 'haiku' ? 'AI-drafted' : 'rule'}</span>
              <b>{f.rule}</b> {f.cwe && <MitreCode id={f.cwe} compact />}{f.technique && <> · <MitreCode id={f.technique} compact /></>}
              <div className="muted">{f.explanation}</div>
              <Checks checks={f.checks} />
            </li>
          ))}
        </ul>
      )}
      {open && jobId && (
        <div className="diff-tools">
          <button className="link" onClick={() => setFull(!full)}>{full ? 'Show changes only' : 'Show full file'}</button>
        </div>
      )}
      {open && full && <FullFile jobId={jobId} path={file.path} />}
      {open && !full && hunks.map((h, hi) => (
        <div key={hi} className="hunk">
          <div className="hunk-head">{h.header || `change ${hi + 1}`}</div>
          <table className="diff"><tbody>
            {h.lines.map((l, i) => (
              <tr key={i} className={l.t === '+' ? 'row-add' : l.t === '-' ? 'row-del' : ''}>
                <td className="ln">{l.o ?? ''}</td>
                <td className="ln">{l.n ?? ''}</td>
                <td className="sign">{l.t === ' ' ? '' : l.t}</td>
                <td className="code"><Code line={l} /></td>
              </tr>
            ))}
          </tbody></table>
        </div>
      ))}
    </section>
  )
}

export default function DiffView({ diff, fixes, jobId }) {
  const files = useMemo(() => parseDiff(diff), [diff])
  if (!files.length) return <p className="muted">No code changes.</p>
  const add = files.reduce((s, f) => s + f.add, 0)
  const del = files.reduce((s, f) => s + f.del, 0)
  const byFile = (p) => fixes.filter((f) => f.file === p)
  return (
    <div>
      <p className="muted">{files.length} file{files.length > 1 ? 's' : ''} changed, <span className="add">+{add}</span>{' '}
        <span className="del">−{del}</span></p>
      {files.map((f, i) => <FileDiff key={f.path} file={f} fixes={byFile(f.path)} defaultOpen={i < 4} jobId={jobId} />)}
    </div>
  )
}
